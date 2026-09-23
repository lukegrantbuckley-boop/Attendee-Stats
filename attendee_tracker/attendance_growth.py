"""Rank multi-year change in average reported home attendance.

The rate is a compound annual change from the earliest reported season
average to the latest. Missing crowds are left out. They are not stored
as zero. Raw crowd size does not decide the order.
"""

from __future__ import annotations

from attendee_tracker.analysis import ols
from attendee_tracker.excluded_years import COVID_WINDOW_NOTE, attendance_year_omitted
from attendee_tracker.pro_stadiums import pro_stadium_note

MIN_SEASONS = 5
GROWTH_LIST_SIZE = 10

METHODOLOGY = (
    "Growth is the compound annual change in average reported home attendance "
    "from the earliest season with a crowd to the latest, inside this window. "
    "A season counts only when a non-neutral home game has a non-null attendance. "
    "Blank crowds are skipped, not filled with zero. "
    f"A school needs at least {MIN_SEASONS} such seasons. "
    "The sort is that rate, not how many people came. "
    "Ties break by school name. "
    "A school is left out when its latest home, or any cached season other than 2020, "
    "lists an NFL stadium, so a move into a pro building does not look like a fanbase collapse or boom. "
    f"{COVID_WINDOW_NOTE}"
)


def rank_attendance_growth(schools: list[dict], limit: int = GROWTH_LIST_SIZE) -> dict:
    """Build the growing and falling lists from history rows."""
    qualifying = []
    excluded_pro = []
    for school in schools:
        if _is_pro_home(school):
            excluded_pro.append(school.get("school") or school.get("slug") or "")
            continue
        metric = _metric(school)
        if metric is None:
            continue
        qualifying.append(metric)

    qualifying.sort(key=lambda row: (-row["cagr"], row["school"].casefold(), row["slug"]))
    growing = [row for row in qualifying if row["cagr"] > 0][:limit]
    growing_slugs = {row["slug"] for row in growing}
    declines = [row for row in qualifying if row["cagr"] < 0 and row["slug"] not in growing_slugs]
    declines.sort(key=lambda row: (row["cagr"], row["school"].casefold(), row["slug"]))
    if declines:
        falling = declines[:limit]
        basis = "decline"
    else:
        weakest = [row for row in qualifying if row["slug"] not in growing_slugs]
        weakest.sort(key=lambda row: (row["cagr"], row["school"].casefold(), row["slug"]))
        falling = weakest[:limit]
        basis = "weakest_growth" if falling else "none"

    return {
        "min_seasons": MIN_SEASONS,
        "list_size": limit,
        "primary_metric": "cagr",
        "methodology": METHODOLOGY,
        "n_qualifying": len(qualifying),
        "n_growing": sum(1 for row in qualifying if row["cagr"] > 0),
        "n_declining": sum(1 for row in qualifying if row["cagr"] < 0),
        "excluded_pro_shared": sorted(name for name in excluded_pro if name),
        "basis": basis,
        "fastest_growing": [_public(row, index) for index, row in enumerate(growing, start=1)],
        "softest_growth": [_public(row, index) for index, row in enumerate(falling, start=1)],
    }


def _metric(school: dict) -> dict | None:
    points = []
    for season in school.get("seasons") or []:
        year = season.get("year")
        if season.get("attendance_omitted") or attendance_year_omitted(year):
            continue
        average = season.get("avg_home_attendance")
        if year is None or average is None:
            continue
        try:
            year = int(year)
            average = float(average)
        except (TypeError, ValueError):
            continue
        if average <= 0:
            continue
        points.append((year, average))
    # One year can appear twice if history ever double-counts. Keep the first.
    seen = set()
    unique = []
    for year, average in sorted(points):
        if year in seen:
            continue
        seen.add(year)
        unique.append((year, average))
    if len(unique) < MIN_SEASONS:
        return None
    start_year, start_avg = unique[0]
    end_year, end_avg = unique[-1]
    cagr = _cagr(start_avg, end_avg, start_year, end_year)
    if cagr is None:
        return None
    slope = ols([float(year) for year, _ in unique], [average for _, average in unique])
    per_year = slope[1] if slope else None
    return {
        "slug": school.get("slug"),
        "school": school.get("school") or "",
        "conference": school.get("conference"),
        "color": school.get("color"),
        "abbreviation": school.get("abbreviation"),
        "logo": school.get("logo"),
        "cagr": cagr,
        "pct_change": (end_avg - start_avg) / start_avg,
        "slope_per_year": per_year,
        "start_year": start_year,
        "end_year": end_year,
        "start_avg": start_avg,
        "end_avg": end_avg,
        "seasons_with_average": len(unique),
    }


def _cagr(start_avg: float, end_avg: float, start_year: int, end_year: int) -> float | None:
    span = end_year - start_year
    if span <= 0 or start_avg <= 0 or end_avg <= 0:
        return None
    return (end_avg / start_avg) ** (1 / span) - 1


def _is_pro_home(school: dict) -> bool:
    if school.get("pro_shared_stadium") or pro_stadium_note(school.get("stadium")):
        return True
    for season in school.get("seasons") or []:
        if season.get("attendance_omitted") or attendance_year_omitted(season.get("year")):
            continue
        if season.get("pro_shared_stadium") or pro_stadium_note(season.get("stadium")):
            return True
    return False


def _public(row: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "slug": row["slug"],
        "school": row["school"],
        "conference": row.get("conference"),
        "color": row.get("color") or "#1e3a5f",
        "abbreviation": row.get("abbreviation"),
        "logo": row.get("logo"),
        "cagr": _round(row["cagr"], 4),
        "pct_change": _round(row["pct_change"], 4),
        "slope_per_year": _round(row.get("slope_per_year"), 1),
        "start_year": row["start_year"],
        "end_year": row["end_year"],
        "start_avg": _round(row["start_avg"], 1),
        "end_avg": _round(row["end_avg"], 1),
        "seasons_with_average": row["seasons_with_average"],
    }


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)
