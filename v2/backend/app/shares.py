from __future__ import annotations

from typing import Optional


def redistribute(rows: list) -> None:
    """Раскидывает доли активных офферов так, чтобы сумма была ровно 100.

    Закреплённые (pin) офферы сохраняют свою долю, остаток поровну
    делится между остальными активными. Изменяет rows на месте,
    при невозможной раскладке бросает ValueError.
    """
    active = [r for r in rows if r["state"] == "active"]
    if not active:
        raise ValueError("В потоке нет активных офферов")
    pinned = sum(r["share"] for r in active if r["pin"])
    free = [r for r in active if not r["pin"]]
    rest = 100 - pinned
    if rest < 0:
        raise ValueError("Доли закреплённых офферов превышают 100%")
    if free:
        share, extra = divmod(rest, len(free))
        for i, row in enumerate(free):
            row["share"] = share + (1 if i < extra else 0)
    elif rest:
        raise ValueError("Все доли закреплены, но их сумма не равна 100%")


def api_payload(rows: list) -> list:
    """Формат offers для Keitaro API: только связи, без локальных полей."""
    return sorted(
        (
            {"offer_id": r["id"], "share": r["share"], "state": r["state"]}
            for r in rows
            if r["state"] != "removed"
        ),
        key=lambda x: x["offer_id"],
    )


def merge_snapshot(remote_offers: list, previous: list, names: dict) -> list:
    """Строит локальное состояние потока из ответа Keitaro.

    Офферы, исчезнувшие из трекера, попадают в архив (state="removed"),
    чтобы их можно было вернуть. Флаг pin сохраняется из предыдущего
    локального состояния.
    """
    old = {r["id"]: r for r in previous}
    result = []
    for item in remote_offers:
        oid = item["offer_id"]
        before = old.pop(oid, {})
        result.append({
            "id": oid,
            "name": names.get(oid) or str(oid),
            "share": item["share"],
            "state": item.get("state", "active"),
            "pin": bool(before.get("pin", False)),
        })
    result.extend(
        {**r, "state": "removed", "share": 0, "pin": False}
        for r in old.values()
    )
    return result
