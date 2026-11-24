from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from secrets import token_hex
from threading import RLock
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .db import Base, SessionLocal, engine
from .keitaro import MockKeitaro, api_call, get_client
from .models import Campaign, Stream
from .shares import api_payload, merge_snapshot, redistribute

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Adrobot — редактор кампаний Keitaro")
lock = RLock()


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- схемы ----------

class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    offer_id: int = Field(gt=0)
    domain_id: int = Field(gt=0)
    group_id: int = Field(gt=0)
    traffic_source_id: int = Field(gt=0)


class OfferChange(BaseModel):
    offer_id: int = Field(gt=0)
    # для действия pin: явная доля в %
    percent: Optional[int] = Field(default=None, ge=0, le=100)


# ---------- помощники ----------

def get_campaign(db: OrmSession, cid: int) -> Campaign:
    camp = db.get(Campaign, cid)
    if camp is None:
        raise HTTPException(404, "Кампания не найдена в локальной базе")
    return camp


def get_stream(db: OrmSession, sid: int) -> Stream:
    stream = db.get(Stream, sid)
    if stream is None:
        raise HTTPException(404, "Поток не найден в локальной базе")
    return stream


def campaign_view(db: OrmSession, cid: int) -> dict:
    camp = get_campaign(db, cid)
    rows = db.scalars(
        select(Stream).where(Stream.campaign_id == cid).order_by(Stream.id)
    ).all()
    return {
        "id": camp.id,
        "name": camp.name,
        "streams": [
            {
                "id": s.id,
                "name": s.name,
                "offers": s.draft,
                "published": s.published,
                "dirty": s.draft != s.published,
            }
            for s in rows
        ],
    }


def choices(path: str) -> list:
    rows = api_call("GET", path) or []
    return [
        {"id": r["id"], "name": r.get("name") or r.get("domain") or str(r["id"])}
        for r in rows
    ]


def find_offer(oid: int) -> dict:
    return api_call("GET", f"offers/{oid}")


def offer_names() -> dict:
    return {r["id"]: r.get("name", str(r["id"])) for r in (api_call("GET", "offers") or [])}


# ---------- API ----------

@app.get("/api/meta")
def meta():
    return {"demo": isinstance(get_client(), MockKeitaro)}


@app.get("/api/options")
def options():
    return {
        "domains": choices("domains"),
        "groups": choices("groups?type=campaigns"),
        "sources": choices("traffic_sources"),
    }


@app.get("/api/offers")
def offers(q: str = ""):
    q = q.strip()
    rows = choices("offers")
    if q.isdigit():
        rows = [r for r in rows if r["id"] == int(q)]
    elif q:
        ql = q.casefold()
        rows = [r for r in rows if ql in r["name"].casefold()]
    return rows[:30]


@app.get("/api/campaigns")
def list_campaigns(db: OrmSession = Depends(get_db)):
    return [
        {"id": c.id, "name": c.name}
        for c in db.scalars(select(Campaign).order_by(Campaign.id))
    ]


@app.get("/api/campaigns/{cid}")
def get_campaign_view(cid: int, db: OrmSession = Depends(get_db)):
    return campaign_view(db, cid)


@app.post("/api/campaigns")
def create_campaign(data: CampaignCreate, db: OrmSession = Depends(get_db)):
    """Создаёт кампанию в Keitaro: поток GEO → Google, поток офферов → оффер."""
    find_offer(data.offer_id)  # проверяем, что оффер существует
    # alias — часть URL кампании в трекере: допустимы a-z, 0-9, '-' и '_',
    # принято ~6–10 символов. Генерируем короткий hex, uuid слишком длинный.
    alias = token_hex(5)
    try:
        created = api_call("POST", "campaigns", json={
            "name": data.name,
            "alias": alias,
            "domain_id": data.domain_id,
            "group_id": data.group_id,
            "traffic_source_id": data.traffic_source_id,
            "type": "position",
            "state": "disabled",
        })
    except HTTPException as exc:
        raise HTTPException(
            exc.status_code,
            f"Создание не подтверждено. Проверьте в Keitaro кампанию "
            f"«{data.name}» с alias {alias}. {exc.detail}",
        ) from exc

    cid = created["id"]
    progress = "создание потока страны"
    try:
        api_call("POST", "streams", json={
            "campaign_id": cid,
            "name": data.country,
            "position": 1,
            "type": "regular",
            "state": "active",
            "schema": "redirect",
            "action_type": "http",
            "action_payload": "https://www.google.com/",
            "filters": [{
                "name": "country",
                "mode": "accept",
                "payload": [data.country],
            }],
        })
        progress = "создание потока офферов"
        api_call("POST", "streams", json={
            "campaign_id": cid,
            "name": "Офферы",
            "position": 2,
            "type": "default",
            "state": "active",
            "action_type": "http",
            "schema": "landings",
            "offers": [{"offer_id": data.offer_id, "share": 100, "state": "active"}],
        })
        progress = "включение кампании"
        api_call("POST", f"campaigns/{cid}/enable")
        progress = "кампания включена."
    except HTTPException as exc:
        # Откатываем недособранную кампанию через DELETE /campaigns/{id}.
        # По документации Keitaro это архивация (кампания восстанавливается
        # через /restore); на учебном стенде-эмуляторе удаление
        # безвозвратно и /restore недоступен. Если DELETE не удался —
        # сообщаем alias для ручной проверки.
        deleted = True
        try:
            api_call("DELETE", f"campaigns/{cid}")
        except HTTPException:
            deleted = False
        if deleted:
            raise HTTPException(
                exc.status_code,
                f"Ошибка на шаге «{progress}» — недособранная кампания #{cid} "
                f"удалена из Keitaro (DELETE /campaigns/{cid}). "
                f"Исходная ошибка: {exc.detail}",
            ) from exc
        raise HTTPException(
            exc.status_code,
            f"Ошибка на шаге «{progress}». Не удалось заархивировать кампанию "
            f"#{cid} (alias {alias}) — проверьте её в Keitaro вручную. "
            f"Исходная ошибка: {exc.detail}",
        ) from exc

    return fetch_campaign(cid, db)


@app.post("/api/campaigns/{cid}/fetch")
def fetch_campaign(cid: int, db: OrmSession = Depends(get_db)):
    """Подтягивает потоки кампании из Keitaro в локальную базу."""
    with lock:
        for s in db.scalars(select(Stream).where(Stream.campaign_id == cid)):
            if s.draft != s.published:
                raise HTTPException(
                    409, "Есть несохранённые изменения: сначала Push или Cancel"
                )
        remote_camp = api_call("GET", f"campaigns/{cid}")
        remote_streams = api_call("GET", f"campaigns/{cid}/streams") or []
        names = offer_names()

        db.merge(Campaign(id=cid, name=remote_camp.get("name") or str(cid)))
        seen = set()
        for rs in remote_streams:
            sid = rs["id"]
            seen.add(sid)
            local = db.get(Stream, sid)
            rows = merge_snapshot(rs.get("offers") or [], local.published if local else [], names)
            if local is None:
                local = Stream(id=sid, campaign_id=cid, name=rs.get("name", f"Stream {sid}"))
                db.add(local)
            local.name = rs.get("name", local.name)
            local.published = rows
            local.draft = deepcopy(rows)
        for s in db.scalars(select(Stream).where(Stream.campaign_id == cid)):
            if s.id not in seen:
                db.delete(s)
        db.commit()
        return campaign_view(db, cid)


@app.post("/api/streams/{sid}/offers/{action}")
def edit_offers(sid: int, action: str, data: OfferChange, db: OrmSession = Depends(get_db)):
    """Локальные правки черновика потока: add/remove/restore/pin/unpin."""
    with lock:
        stream = get_stream(db, sid)
        rows = deepcopy(stream.draft)
        row = next((r for r in rows if r["id"] == data.offer_id), None)

        if action == "add":
            if row is not None:
                raise HTTPException(422, "Этот оффер уже есть в потоке")
            offer = find_offer(data.offer_id)
            rows.append({
                "id": data.offer_id,
                "name": offer.get("name", str(data.offer_id)),
                "share": 0,
                "state": "active",
                "pin": False,
            })
        elif row is None:
            raise HTTPException(404, "Оффер не найден в потоке")
        elif action == "remove" and row["state"] != "removed":
            row.update(state="removed", share=0, pin=False)
        elif action == "restore" and row["state"] == "removed":
            row.update(state="active", pin=False)
        elif action in ("pin", "unpin") and row["state"] == "active":
            pinned = action == "pin"
            row["pin"] = pinned
            if pinned and data.percent is not None:
                row["share"] = data.percent
        else:
            raise HTTPException(422, f"Действие {action} недоступно для этого оффера")

        try:
            redistribute(rows)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        stream.draft = rows
        db.commit()
        return campaign_view(db, stream.campaign_id)


@app.post("/api/streams/{sid}/cancel")
def cancel_stream(sid: int, db: OrmSession = Depends(get_db)):
    with lock:
        stream = get_stream(db, sid)
        stream.draft = deepcopy(stream.published)
        db.commit()
        return campaign_view(db, stream.campaign_id)


@app.post("/api/streams/{sid}/push")
def push_stream(sid: int, db: OrmSession = Depends(get_db)):
    """Публикует черновик потока в Keitaro."""
    with lock:
        stream = get_stream(db, sid)
        try:
            redistribute(deepcopy(stream.draft))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        remote = api_call("GET", f"streams/{sid}") or {}
        actual = api_payload(merge_snapshot(remote.get("offers") or [], [], {}))
        target = api_payload(stream.draft)
        if actual != target:
            if actual != api_payload(stream.published):
                raise HTTPException(
                    409,
                    "Поток изменился в Keitaro. Нажмите Cancel, затем загрузите потоки заново.",
                )
            api_call("PUT", f"streams/{sid}", json={"offers": target})
        stream.published = deepcopy(stream.draft)
        db.commit()
        return campaign_view(db, stream.campaign_id)


# ---------- фронт ----------

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
