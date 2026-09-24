"""Home-attendance series across cached seasons.

Teams stay together by CFBD team id, so a conference move does not split
the series. School name is only a fallback when an older file uses a
different id for the same name. Each season keeps the conference from
that year's teams list.

Years with no cache file are listed and left blank. Averages use reported
home games only. Nothing here fills a missing crowd.
"""

from __future__ import annotations

from attendee_tracker.assemble import assemble, slugify
from attendee_tracker.excluded_years import COVID_OMISSION, COVID_WINDOW_NOTE, attendance_year_omitted

MAX_HISTORY_YEARS = 20


class HistoryWindowError(ValueError):
    """The requested from/to window cannot be served."""


def validate_window(year_from: int | None, year_to: int | None, default_year: int) -> tuple[int, int]:
    start = default_year if year_from is None else year_from
    end = default_year if year_to is None else year_to
    if start < 1869 or end < 1869 or start > 2100 or end > 2100:
        raise HistoryWindowError("Season years must be between 1869 and 2100.")
    if end < start:
        raise HistoryWindowError("The from year must be the same as or earlier than the to year.")
    span = end - start + 1
    if span > MAX_HISTORY_YEARS:
        raise HistoryWindowError(
            f"A history window can cover at most {MAX_HISTORY_YEARS} seasons."
        )
    return start, end


def assemble_history(
    raw_by_year: dict[int, dict],
    year_from: int,
    year_to: int,
    *,
    include_games: bool = False,
) -> dict:
    """Build per-school season averages for the inclusive window.

    ``raw_by_year`` holds only seasons that actually have a cache. Missing
    years stay in ``missing_years`` and are not given attendance.
    """
    requested = list(range(year_from, year_to + 1))
    missing = [year for year in requested if year not in raw_by_year]
    present = [year for year in requested if year in raw_by_year]
    sample_years = [
        year
        for year in present
        if raw_by_year[year].get("synthetic") or raw_by_year[year].get("source") != "cfbd"
    ]

    entries: list[dict] = []
    by_id: dict[int, dict] = {}
    by_name: dict[str, dict] = {}

    # Newest season first so the slug, name, and colors match the latest
    # cached year in the window (the year the school cards use).
    for year in reversed(present):
        schools = assemble(raw_by_year[year])["schools"]
        ids_this_year = {school["id"] for school in schools}
        for school in schools:
            entry = by_id.get(school["id"])
            if entry is None:
                named = _unique_name_match(entries, by_name, school, ids_this_year)
                # Same display name, different id, and the newer id is not
                # also in this file: treat it as one program. If both ids
                # are in this year, they are different teams.
                if named is not None:
                    entry = named
                    if school["id"] not in entry["alias_ids"]:
                        entry["alias_ids"].append(school["id"])
                    by_id[school["id"]] = entry
                else:
                    entry = _blank_entry(school)
                    entries.append(entry)
                    by_id[school["id"]] = entry
            by_name.setdefault(school["school"].casefold(), entry)
            entry["slugs"].add(school["slug"])
            entry["seasons"].append(_season_row(year, school))

    schools_out = [_public_entry(entry, include_games=include_games) for entry in entries]
    schools_out.sort(key=lambda school: school["school"].casefold())
    omitted_years = [year for year in requested if attendance_year_omitted(year)]
    return {
        "from": year_from,
        "to": year_to,
        "missing_years": missing,
        "years_present": present,
        "sample_years": sample_years,
        "omitted_years": omitted_years,
        "attendance_note": COVID_WINDOW_NOTE if omitted_years else None,
        "schools": schools_out,
    }


def find_school(history: dict, slug: str) -> dict | None:
    """Resolve a card slug to one history row.

    Canonical slug wins. A historical slug or the current school name is
    used only when that match is unique, so two programs are never folded
    together by accident.
    """
    wanted = (slug or "").strip().casefold()
    if not wanted:
        return None
    schools = list(history.get("schools") or [])
    for school in schools:
        if school.get("slug") == wanted:
            return school
    by_name = [school for school in schools if slugify(school.get("school") or "") == wanted]
    if len(by_name) == 1:
        return by_name[0]
    by_history = [school for school in schools if wanted in (school.get("slugs") or [])]
    if len(by_history) == 1:
        return by_history[0]
    return None


def _unique_name_match(entries: list[dict], by_name: dict[str, dict], school: dict, ids_this_year: set[int]) -> dict | None:
    folded = school["school"].casefold()
    named = by_name.get(folded)
    if named is None or named["id"] in ids_this_year:
        return None
    twins = [entry for entry in entries if entry["school"].casefold() == folded]
    if len(twins) != 1:
        return None
    return named


def _blank_entry(school: dict) -> dict:
    return {
        "id": school["id"],
        "slug": school["slug"],
        "school": school["school"],
        "mascot": school.get("mascot"),
        "abbreviation": school.get("abbreviation"),
        "conference": school.get("conference"),
        "tier": school.get("tier"),
        "color": school.get("color"),
        "alternate_color": school.get("alternate_color"),
        "logo": school.get("logo"),
        "stadium": school.get("stadium"),
        "city": school.get("city"),
        "state": school.get("state"),
        "capacity": school.get("capacity"),
        "slugs": set(),
        "alias_ids": [],
        "seasons": [],
    }


def _public_entry(entry: dict, *, include_games: bool) -> dict:
    seasons = sorted(entry["seasons"], key=lambda row: row["year"])
    if not include_games:
        seasons = [{key: value for key, value in row.items() if key != "home_games"} for row in seasons]
    return {
        "id": entry["id"],
        "slug": entry["slug"],
        "slugs": sorted(entry["slugs"]),
        "school": entry["school"],
        "mascot": entry["mascot"],
        "abbreviation": entry["abbreviation"],
        "conference": entry["conference"],
        "tier": entry["tier"],
        "color": entry["color"],
        "alternate_color": entry["alternate_color"],
        "logo": entry["logo"],
        "stadium": entry["stadium"],
        "city": entry["city"],
        "state": entry["state"],
        "capacity": entry["capacity"],
        "seasons": seasons,
    }


def _season_row(year: int, school: dict) -> dict:
    omitted = attendance_year_omitted(year) or school.get("attendance_omitted")
    # Keep the year in the series so the table can show the gap. The crowd
    # itself stays in the raw cache and is not copied onto this row.
    return {
        "year": year,
        "conference": school.get("conference"),
        "tier": school.get("tier"),
        "record": school.get("record"),
        "ap_rank": school.get("ap_rank"),
        "attendance_omitted": omitted if omitted == COVID_OMISSION else None,
        "avg_home_attendance": None if omitted else school.get("avg_home_attendance"),
        "stadium": school.get("stadium"),
        "pro_shared_stadium": bool(school.get("pro_shared_stadium")),
        "reported_home_games": school.get("reported_home_games"),
        "missing_attendance_games": school.get("missing_attendance_games"),
        "home_games_scheduled": len(school.get("home_games") or []),
        "last_home_attendance": None if omitted else school.get("last_home_attendance"),
        "last_home_attendance_status": None if omitted else school.get("last_home_attendance_status"),
        "last_home_opponent": None if omitted else school.get("last_home_opponent"),
        "last_home_date": None if omitted else school.get("last_home_date"),
        "home_games": [] if omitted else [_lean_game(game) for game in school.get("home_games") or []],
    }


def _lean_game(game: dict) -> dict:
    return {
        "id": game.get("id"),
        "week": game.get("week"),
        "season_type": game.get("season_type"),
        "start_date": game.get("start_date"),
        "opponent": game.get("opponent"),
        "attendance": game.get("attendance"),
        "attendance_status": game.get("attendance_status"),
        "attendance_source": game.get("attendance_source"),
        "result": game.get("result"),
        "label": game.get("label"),
    }
