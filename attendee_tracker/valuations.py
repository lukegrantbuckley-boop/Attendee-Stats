"""Power football valuations and NIL estimates from a committed file.

Dollars, ranks, and rank changes are the published figures in
``data/valuations/power_2026.json``. This module sorts that file.
It does not invent a value, fill a gap, or compute an in-season estimate.
"""

from __future__ import annotations

import json
from pathlib import Path

from attendee_tracker.config import ROOT

VALUATIONS_PATH = ROOT / "data" / "valuations" / "power_2026.json"
SORTS = ("valuation", "nil")


class ValuationsError(Exception):
    def __init__(self, code: str, message: str, status: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def list_valuations(sort: str = "valuation", path: Path | None = None) -> dict:
    key = (sort or "valuation").strip().casefold()
    if key not in SORTS:
        raise ValuationsError(
            "bad_sort",
            "Sort must be valuation or nil.",
            400,
        )
    raw = _load(path or VALUATIONS_PATH)
    schools = [dict(row) for row in raw["schools"]]
    schools.sort(key=_nil_sort_key if key == "nil" else _valuation_sort_key)
    return {
        "sort": key,
        "count": len(schools),
        "scope": raw.get("scope"),
        "valuation_metric": raw.get("valuation_metric"),
        "nil_metric": raw.get("nil_metric_recommendation"),
        "sources": _sources(schools),
        "schools": schools,
    }


def _load(path: Path) -> dict:
    if not path.is_file():
        raise ValuationsError(
            "no_valuations",
            "No committed valuations file. Values were not fabricated.",
            404,
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValuationsError(
            "bad_valuations",
            "The valuations file could not be read. Values were not fabricated.",
            500,
        ) from exc
    schools = payload.get("schools") if isinstance(payload, dict) else None
    if not isinstance(schools, list) or not schools or not all(isinstance(row, dict) for row in schools):
        raise ValuationsError(
            "bad_valuations",
            "The valuations file has no school list. Values were not fabricated.",
            500,
        )
    return payload


def _sources(schools: list[dict]) -> dict:
    first = schools[0]
    valuation = first.get("valuation_source") if isinstance(first.get("valuation_source"), dict) else {}
    prior = first.get("prior_valuation_source") if isinstance(first.get("prior_valuation_source"), dict) else {}
    nil = first.get("nil_source") if isinstance(first.get("nil_source"), dict) else {}
    return {
        "valuation": {
            "publisher": valuation.get("publisher"),
            "url": valuation.get("url"),
            "date": valuation.get("date"),
        },
        "prior_valuation": {
            "publisher": prior.get("publisher"),
            "url": prior.get("url"),
            "date": prior.get("date"),
        },
        "nil": {
            "publisher": nil.get("publisher"),
            "url": nil.get("url"),
            "methodology_url": nil.get("methodology_url"),
            "year": first.get("nil_year"),
        },
    }


def _school_name(row: dict) -> str:
    return str(row.get("school") or "").casefold()


def _number(value) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _valuation_sort_key(row: dict) -> tuple:
    rank = _number(row.get("valuation_rank"))
    value = _number(row.get("valuation_usd"))
    # Published rank first. A missing rank stays last; the dollar figure is not invented.
    return (
        rank if rank is not None else 10**9,
        -(value if value is not None else -1),
        _school_name(row),
    )


def _nil_sort_key(row: dict) -> tuple:
    value = _number(row.get("nil_budget_usd"))
    missing = value is None
    return (
        1 if missing else 0,
        -(value if value is not None else 0),
        _school_name(row),
    )
