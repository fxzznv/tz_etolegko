from __future__ import annotations

import os
import threading
from typing import Optional

import httpx
from fastapi import HTTPException


class KeitaroError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class KeitaroClient:
    """Тонкая обёртка над Keitaro Admin API v1."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def call(self, method: str, path: str, json: Optional[dict] = None):
        url = f"{self.base_url}/admin_api/v1/{path.lstrip('/')}"
        try:
            resp = httpx.request(
                method, url,
                headers={"Api-Key": self.api_key, "Accept": "application/json"},
                json=json, timeout=20,
            )
        except httpx.RequestError as exc:
            raise KeitaroError(502, f"Keitaro недоступен: {exc}") from exc
        if resp.status_code >= 400:
            raise KeitaroError(resp.status_code, f"Keitaro: {method} {path} → HTTP {resp.status_code}")
        return resp.json() if resp.content else None


class MockKeitaro:
    """Встроенный демо-трекер: то же API, но состояние в памяти.

    Включается переменной KEITARO_MOCK=1 — удобно показать интерфейс
    и логику без реального трекера.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.offers = [
            {"id": 101, "name": "NordVPN CPS", "url": "https://offer.example/1"},
            {"id": 102, "name": "Admitad товарка", "url": "https://offer.example/2"},
            {"id": 103, "name": "Namecheap домены", "url": "https://offer.example/3"},
            {"id": 104, "name": "Альфа-банк карта", "url": "https://offer.example/4"},
            {"id": 105, "name": "Яндекс.Практикум", "url": "https://offer.example/5"},
        ]
        self.domains = [
            {"id": 1, "domain": "track.example.com"},
            {"id": 2, "domain": "go.example.net"},
            {"id": 3, "domain": "links.example.org"},
        ]
        self.groups = [{"id": 1, "name": "Основная"}, {"id": 2, "name": "Тесты"}]
        self.sources = [
            {"id": 1, "name": "Facebook Ads"},
            {"id": 2, "name": "Google Ads"},
            {"id": 3, "name": "TikTok"},
        ]
        self.campaigns: dict[int, dict] = {}
        self.streams: dict[int, dict] = {}
        self._next_campaign = 500
        self._next_stream = 900
        self._seed()

    def _seed(self):
        camp = self._create_campaign({"name": "Демо-кампания", "alias": "demo"})
        self._create_stream({
            "campaign_id": camp["id"], "name": "ГЕО-фильтр", "position": 1,
            "type": "regular", "state": "active", "schema": "redirect",
            "action_type": "http", "action_payload": "https://www.google.com/",
            "filters": [{"name": "country", "mode": "accept", "payload": ["US"]}],
        })
        self._create_stream({
            "campaign_id": camp["id"], "name": "Офферы", "position": 2,
            "type": "default", "state": "active", "action_type": "http",
            "schema": "landings",
            "offers": [
                {"offer_id": 101, "share": 60, "state": "active"},
                {"offer_id": 102, "share": 40, "state": "active"},
            ],
        })

    # --- внутренние помощники ---

    def _create_campaign(self, data: dict) -> dict:
        cid = self._next_campaign
        self._next_campaign += 1
        camp = {"id": cid, "name": data["name"], "alias": data.get("alias", ""),
                "state": data.get("state", "active"),
                "domain_id": data.get("domain_id"),
                "group_id": data.get("group_id"),
                "traffic_source_id": data.get("traffic_source_id")}
        self.campaigns[cid] = camp
        return camp

    def _create_stream(self, data: dict) -> dict:
        sid = self._next_stream
        self._next_stream += 1
        stream = {**data, "id": sid}
        stream.setdefault("offers", [])
        self.streams[sid] = stream
        return stream

    @staticmethod
    def _public_stream(s: dict) -> dict:
        return {k: v for k, v in s.items() if k != "campaign_id" or True}

    # --- API ---

    def call(self, method: str, path: str, json: Optional[dict] = None):
        path = path.lstrip("/")
        parts = [p for p in path.split("?")]
        route, _, query = parts[0], "", parts[1] if len(parts) > 1 else ""
        seg = route.split("/")
        with self._lock:
            handler = getattr(self, f"_{method.lower()}", None)
            if handler is None:
                raise KeitaroError(405, f"Mock: метод {method} не поддержан")
            return handler(seg, query, json or {})

    def _delete(self, seg, query, body):
        if len(seg) == 2 and seg[0] == "campaigns" and seg[1].isdigit():
            cid = int(seg[1])
            if cid not in self.campaigns:
                raise KeitaroError(404, "Кампания не найдена")
            del self.campaigns[cid]
            for sid in [s for s, st in self.streams.items() if st["campaign_id"] == cid]:
                del self.streams[sid]
            return {"id": cid, "state": "removed"}
        if len(seg) == 2 and seg[0] == "streams" and seg[1].isdigit():
            sid = int(seg[1])
            if sid not in self.streams:
                raise KeitaroError(404, "Поток не найден")
            del self.streams[sid]
            return {"id": sid, "state": "removed"}
        raise KeitaroError(404, f"Mock: DELETE {seg} не реализован")

    def _get(self, seg, query, body):
        if seg == ["domains"]:
            return [dict(d) for d in self.domains]
        if seg == ["groups"]:
            return [dict(g) for g in self.groups]
        if seg == ["traffic_sources"]:
            return [dict(s) for s in self.sources]
        if seg == ["offers"]:
            return [{"id": o["id"], "name": o["name"]} for o in self.offers]
        if len(seg) == 2 and seg[0] == "offers":
            offer = next((o for o in self.offers if o["id"] == int(seg[1])), None)
            if offer is None:
                raise KeitaroError(404, "Оффер не найден")
            return dict(offer)
        if seg == ["campaigns"]:
            return [{"id": c["id"], "name": c["name"], "state": c["state"]}
                    for c in self.campaigns.values()]
        if len(seg) == 2 and seg[0] == "campaigns" and seg[1].isdigit():
            camp = self.campaigns.get(int(seg[1]))
            if camp is None:
                raise KeitaroError(404, "Кампания не найдена")
            return dict(camp)
        if len(seg) == 3 and seg[0] == "campaigns" and seg[1].isdigit() and seg[2] == "streams":
            cid = int(seg[1])
            if cid not in self.campaigns:
                raise KeitaroError(404, "Кампания не найдена")
            return [self._public_stream(s) for s in self.streams.values() if s["campaign_id"] == cid]
        if seg and seg[0] == "streams" and len(seg) == 2 and seg[1].isdigit():
            stream = self.streams.get(int(seg[1]))
            if stream is None:
                raise KeitaroError(404, "Поток не найден")
            return self._public_stream(dict(stream))
        raise KeitaroError(404, f"Mock: GET {path} не реализован")

    def _post(self, seg, query, body):
        if seg == ["campaigns"]:
            camp = self._create_campaign(body)
            return {"id": camp["id"], "name": camp["name"]}
        if len(seg) == 3 and seg[0] == "campaigns" and seg[1].isdigit() and seg[2] == "enable":
            cid = int(seg[1])
            if cid not in self.campaigns:
                raise KeitaroError(404, "Кампания не найдена")
            self.campaigns[cid]["state"] = "active"
            return {"id": cid, "state": "active"}
        if seg == ["streams"]:
            return self._create_stream(body)
        raise KeitaroError(404, f"Mock: POST {seg} не реализован")

    def _put(self, seg, query, body):
        if seg and seg[0] == "streams" and len(seg) == 2 and seg[1].isdigit():
            sid = int(seg[1])
            stream = self.streams.get(sid)
            if stream is None:
                raise KeitaroError(404, "Поток не найден")
            if "offers" in body:
                stream["offers"] = [dict(o) for o in body["offers"]]
            for key in ("name", "state", "position", "schema", "action_type", "action_payload", "filters"):
                if key in body:
                    stream[key] = body[key]
            return self._public_stream(dict(stream))
        raise KeitaroError(404, f"Mock: PUT {seg} не реализован")


_client = None
_client_lock = threading.Lock()


def get_client():
    global _client
    with _client_lock:
        if _client is None:
            if os.getenv("KEITARO_MOCK", "").lower() in ("1", "true", "yes"):
                _client = MockKeitaro()
            else:
                base = os.getenv("KEITARO_URL", "").rstrip("/")
                key = os.getenv("KEITARO_API_KEY")
                if not base or not key:
                    raise HTTPException(
                        503,
                        "Задайте KEITARO_URL и KEITARO_API_KEY в .env "
                        "или включите демо-режим KEITARO_MOCK=1",
                    )
                _client = KeitaroClient(base, key)
        return _client


def api_call(method: str, path: str, json: Optional[dict] = None):
    try:
        return get_client().call(method, path, json=json)
    except KeitaroError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
