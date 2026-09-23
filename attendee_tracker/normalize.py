"""Turn CFBD JSON (camelCase or snake_case) into a stable internal shape.

Missing attendance stays None. This module never substitutes zero.
"""

from __future__ import annotations

from datetime import datetime


def pick(row: dict, *keys: str):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    for key in keys:
        if key in row:
            return row[key]
    return None


def as_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
    return None


def as_str(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    text = str(value).strip()
    return text or None


def as_bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def as_iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return as_str(value)


def _record_block(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {
        "games": as_int(pick(value, "games")),
        "wins": as_int(pick(value, "wins")),
        "losses": as_int(pick(value, "losses")),
        "ties": as_int(pick(value, "ties")),
    }


def normalize_venue(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    venue_id = as_int(pick(row, "id", "venue_id", "venueId"))
    name = as_str(pick(row, "name"))
    if venue_id is None and not name:
        return None
    return {
        "id": venue_id,
        "name": name,
        "city": as_str(pick(row, "city")),
        "state": as_str(pick(row, "state")),
        "capacity": as_int(pick(row, "capacity")),
        "dome": as_bool(pick(row, "dome")),
    }


def normalize_team(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    school = as_str(pick(row, "school"))
    team_id = as_int(pick(row, "id", "team_id", "teamId"))
    if not school or team_id is None:
        return None
    location = pick(row, "location")
    venue = normalize_venue(location) if isinstance(location, dict) else None
    logos = pick(row, "logos") or []
    if not isinstance(logos, list):
        logos = []
    logo = next((as_str(item) for item in logos if as_str(item)), None)
    color = as_str(pick(row, "color"))
    alternate = as_str(pick(row, "alternate_color", "alternateColor", "alt_color"))
    return {
        "id": team_id,
        "school": school,
        "mascot": as_str(pick(row, "mascot")),
        "abbreviation": as_str(pick(row, "abbreviation")),
        "conference": as_str(pick(row, "conference")),
        "classification": as_str(pick(row, "classification")),
        "color": _hex_color(color),
        "alternate_color": _hex_color(alternate),
        "logo": logo,
        "venue_id": venue["id"] if venue else None,
        "stadium": venue["name"] if venue else None,
        "city": venue["city"] if venue else None,
        "state": venue["state"] if venue else None,
        "capacity": venue["capacity"] if venue else None,
    }


def normalize_game(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    game_id = as_int(pick(row, "id"))
    home_team = as_str(pick(row, "home_team", "homeTeam"))
    away_team = as_str(pick(row, "away_team", "awayTeam"))
    if game_id is None or not home_team or not away_team:
        return None
    # Key absent and JSON null both mean "not reported". Never coerce that to 0.
    if "attendance" in row:
        attendance = as_int(row.get("attendance"))
    else:
        attendance = None
    return {
        "id": game_id,
        "season": as_int(pick(row, "season")),
        "week": as_int(pick(row, "week")),
        "season_type": (as_str(pick(row, "season_type", "seasonType")) or "regular").casefold(),
        "start_date": as_iso(pick(row, "start_date", "startDate")),
        "completed": bool(as_bool(pick(row, "completed"))),
        "neutral_site": bool(as_bool(pick(row, "neutral_site", "neutralSite"))),
        "conference_game": bool(as_bool(pick(row, "conference_game", "conferenceGame"))),
        "attendance": attendance,
        "venue_id": as_int(pick(row, "venue_id", "venueId")),
        "venue": as_str(pick(row, "venue")),
        "home_id": as_int(pick(row, "home_id", "homeId")),
        "home_team": home_team,
        "home_conference": as_str(pick(row, "home_conference", "homeConference")),
        "home_points": as_int(pick(row, "home_points", "homePoints")),
        "away_id": as_int(pick(row, "away_id", "awayId")),
        "away_team": away_team,
        "away_conference": as_str(pick(row, "away_conference", "awayConference")),
        "away_points": as_int(pick(row, "away_points", "awayPoints")),
    }


def normalize_record(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    team = as_str(pick(row, "team"))
    team_id = as_int(pick(row, "team_id", "teamId"))
    total = _record_block(pick(row, "total"))
    if not team or total is None:
        return None
    if total["wins"] is None or total["losses"] is None:
        return None
    return {
        "year": as_int(pick(row, "year")),
        "team_id": team_id,
        "team": team,
        "conference": as_str(pick(row, "conference")),
        "wins": total["wins"],
        "losses": total["losses"],
        "ties": total["ties"] if total["ties"] is not None else 0,
        "games": total["games"],
    }


def normalize_rankings(weeks: list) -> list[dict]:
    """Keep AP Top 25 only. CFBD's poll query param does not accept AP."""
    normalized = []
    for week in weeks or []:
        if not isinstance(week, dict):
            continue
        polls = pick(week, "polls") or []
        ap_ranks = None
        for poll in polls:
            if not isinstance(poll, dict):
                continue
            name = as_str(pick(poll, "poll")) or ""
            if name.casefold() != "ap top 25":
                continue
            ap_ranks = []
            for rank_row in pick(poll, "ranks") or []:
                if not isinstance(rank_row, dict):
                    continue
                school = as_str(pick(rank_row, "school"))
                rank = as_int(pick(rank_row, "rank"))
                if not school or rank is None:
                    continue
                ap_ranks.append(
                    {
                        "rank": rank,
                        "team_id": as_int(pick(rank_row, "team_id", "teamId")),
                        "school": school,
                        "conference": as_str(pick(rank_row, "conference")),
                    }
                )
            break
        if not ap_ranks:
            continue
        normalized.append(
            {
                "season": as_int(pick(week, "season")),
                "season_type": (as_str(pick(week, "season_type", "seasonType")) or "regular").casefold(),
                "week": as_int(pick(week, "week")),
                "poll": "AP Top 25",
                "ranks": ap_ranks,
            }
        )
    return normalized


def latest_ap_week(rankings: list[dict]) -> dict | None:
    """Postseason polls sort after regular-season polls, then by week number."""
    usable = [week for week in rankings if week.get("week") is not None and week.get("ranks")]
    if not usable:
        return None

    def sort_key(week: dict) -> tuple[int, int]:
        phase = 1 if week.get("season_type") == "postseason" else 0
        return (phase, int(week["week"]))

    return max(usable, key=sort_key)


def _hex_color(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if not text.startswith("#"):
        text = f"#{text}"
    return text
