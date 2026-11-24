"""Тесты логики распределения долей офферов."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.shares import api_payload, redistribute  # noqa: E402


def row(oid, share=0, state="active", pin=False, name=None):
    return {"id": oid, "name": name or f"Offer {oid}", "share": share,
            "state": state, "pin": pin}


def shares(rows):
    return {r["id"]: r["share"] for r in rows if r["state"] == "active"}


def test_single_offer_gets_100():
    rows = [row(1)]
    redistribute(rows)
    assert shares(rows) == {1: 100}


def test_three_offers_split_evenly_with_remainder():
    rows = [row(1), row(2), row(3)]
    redistribute(rows)
    # 100 / 3 = 33 + остаток 1 → первые по id получают +1
    assert sorted(shares(rows).values()) == [33, 33, 34]
    assert sum(shares(rows).values()) == 100


def test_removed_offers_are_ignored():
    rows = [row(1), row(2, state="removed", share=50), row(3)]
    redistribute(rows)
    assert shares(rows) == {1: 50, 3: 50}


def test_pin_keeps_share_rest_is_split():
    rows = [row(1, pin=True, share=30), row(2), row(3)]
    redistribute(rows)
    assert shares(rows) == {1: 30, 2: 35, 3: 35}


def test_pin_sum_over_100_fails():
    rows = [row(1, pin=True, share=70), row(2, pin=True, share=50), row(3)]
    with pytest.raises(ValueError, match="100"):
        redistribute(rows)


def test_all_pinned_must_sum_100():
    rows = [row(1, pin=True, share=60), row(2, pin=True, share=40)]
    redistribute(rows)  # сумма ровно 100 — ок
    assert shares(rows) == {1: 60, 2: 40}

    rows[1]["share"] = 30
    with pytest.raises(ValueError, match="100"):
        redistribute(rows)


def test_no_active_offers_fails():
    rows = [row(1, state="removed")]
    with pytest.raises(ValueError):
        redistribute(rows)


def test_api_payload_excludes_removed_and_local_fields():
    rows = [row(1, share=100), row(2, state="removed"), row(3, pin=True, share=0)]
    payload = api_payload(rows)
    assert {"offer_id": 1, "share": 100, "state": "active"} in payload
    assert all(o["offer_id"] != 2 for o in payload)
    assert all(set(o) == {"offer_id", "share", "state"} for o in payload)
