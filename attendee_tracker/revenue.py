"""Football revenue from committed EADA filings.

Dollars are the reported figures in ``data/revenue/football_revenue_eada.json``.
Missing years stay null. This module does not interpolate, zero-fill, or estimate.

Year-over-year change skips the COVID season: fiscal 2020 has no YoY, and
fiscal 2021 is compared with 2019. Any other year whose comparison value is
missing also has no YoY.
"""

from __future__ import annotations

import json
from pathlib import Path

from attendee_tracker.business_news import safe_slug
from attendee_tracker.config import ROOT

REVENUE_PATH = ROOT / "data" / "revenue" / "football_revenue_eada.json"
GROWTH_FROM_YEAR = 2014

_cache: dict[str, dict] = {}


class UnknownSchool(LookupError):
    """The slug is not in the committed revenue file."""


def school_revenue(slug: str, path: Path | None = None) -> dict:
    cleaned = safe_slug(slug)
    payload = _load(path or REVENUE_PATH)
    schools = payload.get("schools") if isinstance(payload, dict) else None
    row = schools.get(cleaned) if isinstance(schools, dict) else None
    if not isinstance(row, dict):
        raise UnknownSchool(cleaned)
    body = _present(cleaned, row, payload)
    if body["latest"] is None:
        raise UnknownSchool(cleaned)
    return body


def _load(path: Path) -> dict:
    key = str(path.resolve())
    cached = _cache.get(key)
    if cached is not None:
        return cached
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Revenue file is not an object.")
    _cache[key] = payload
    return payload


def _present(slug: str, row: dict, payload: dict) -> dict:
    years = [int(year) for year in payload.get("years") or []]
    covid_year = int(payload.get("covid_year") or 2020)
    values = _revenue_map(row)
    footnotes = row.get("footnotes") if isinstance(row.get("footnotes"), dict) else {}
    year_rows = [
        _year_row(year, values, footnotes, years, covid_year)
        for year in years
    ]
    latest = _latest(year_rows)
    return {
        "school": row.get("school"),
        "slug": slug,
        "team_id": row.get("team_id"),
        "institution": row.get("institution"),
        "years": year_rows,
        "latest": latest,
        "growth_10y": _growth(values, latest),
        "source": payload.get("source"),
        "fiscal_year_note": payload.get("fiscal_year_note"),
        "display_footnote": payload.get("display_footnote"),
    }


def _revenue_map(row: dict) -> dict[int, int | None]:
    raw = row.get("revenue_usd") if isinstance(row.get("revenue_usd"), dict) else {}
    values: dict[int, int | None] = {}
    for key, value in raw.items():
        year = int(key)
        values[year] = None if value is None else int(value)
    return values


def _year_row(
    year: int,
    values: dict[int, int | None],
    footnotes: dict,
    years: list[int],
    covid_year: int,
) -> dict:
    revenue = values.get(year)
    footnote = footnotes.get(str(year))
    if footnote is None:
        footnote = footnotes.get(year)
    yoy = _yoy(year, values, years, covid_year)
    return {
        "year": year,
        "revenue_usd": revenue,
        "footnote": footnote if footnote else None,
        "covid": year == covid_year,
        "yoy_usd": yoy["yoy_usd"],
        "yoy_pct": yoy["yoy_pct"],
        "yoy_base_year": yoy["yoy_base_year"],
    }


def _yoy(
    year: int,
    values: dict[int, int | None],
    years: list[int],
    covid_year: int,
) -> dict:
    """2020 has no YoY. 2021 compares with 2019. Otherwise compare with the prior year."""
    empty = {"yoy_usd": None, "yoy_pct": None, "yoy_base_year": None}
    if year == covid_year:
        return empty
    base = (covid_year - 1) if year == covid_year + 1 else year - 1
    if base not in values and base not in years:
        return empty
    current = values.get(year)
    prior = values.get(base)
    if current is None or prior is None:
        return {"yoy_usd": None, "yoy_pct": None, "yoy_base_year": base}
    return {
        "yoy_usd": current - prior,
        "yoy_pct": _pct(current - prior, prior),
        "yoy_base_year": base,
    }


def _latest(year_rows: list[dict]) -> dict | None:
    present = [row for row in year_rows if row["revenue_usd"] is not None]
    if not present:
        return None
    row = present[-1]
    return {
        "year": row["year"],
        "revenue_usd": row["revenue_usd"],
        "yoy_usd": row["yoy_usd"],
        "yoy_pct": row["yoy_pct"],
        "yoy_base_year": row["yoy_base_year"],
    }


def _growth(values: dict[int, int | None], latest: dict | None) -> dict | None:
    """Change from fiscal 2014 to the latest reported year, when both exist."""
    if not latest:
        return None
    base = values.get(GROWTH_FROM_YEAR)
    latest_year = latest["year"]
    latest_value = latest["revenue_usd"]
    if base is None or latest_value is None or latest_year <= GROWTH_FROM_YEAR:
        return None
    delta = latest_value - base
    return {
        "from_year": GROWTH_FROM_YEAR,
        "to_year": latest_year,
        "from_usd": base,
        "to_usd": latest_value,
        "delta_usd": delta,
        "pct": _pct(delta, base),
    }


def _pct(delta: int, base: int) -> float | None:
    if base == 0:
        return None
    return round((delta / base) * 100, 2)
