"""Build the season view the site renders from a normalized cache."""

from __future__ import annotations

import re
from collections import defaultdict

from attendee_tracker.analysis import analyze, recent_form, win_pct
from attendee_tracker.excluded_years import attendance_year_omitted
from attendee_tracker.pro_stadiums import pro_stadium_note
from attendee_tracker.conferences import (
    conference_sort_index,
    display_conference,
    tier_for,
)
from attendee_tracker.normalize import latest_ap_week

SAMPLE_BANNER = (
    "Sample / demo data only. Synthetic attendance, not from the College Football Data API."
)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return slug or "school"


def record_label(wins: int | None, losses: int | None, ties: int | None) -> str | None:
    if wins is None or losses is None:
        return None
    if ties:
        return f"{wins}-{losses}-{ties}"
    return f"{wins}-{losses}"


def assemble(raw: dict) -> dict:
    teams = list(raw.get("teams") or [])
    games = list(raw.get("games") or [])
    records = list(raw.get("records") or [])
    rankings = list(raw.get("rankings") or [])
    venues = list(raw.get("venues") or [])

    venues_by_id = {venue["id"]: venue for venue in venues if venue.get("id") is not None}
    records_by_id = {row["team_id"]: row for row in records if row.get("team_id") is not None}
    records_by_name = {row["team"].casefold(): row for row in records if row.get("team")}
    ap_week = latest_ap_week(rankings)
    ap_by_id, ap_by_name = _ap_indexes(ap_week)

    season_omitted = attendance_year_omitted(raw.get("season"))
    slugs: dict[str, int] = {}
    schools = []
    for team in teams:
        slug = slugify(team["school"])
        if slug in slugs:
            slug = f"{slug}-{team['id']}"
        slugs[slug] = team["id"]
        record = records_by_id.get(team["id"]) or records_by_name.get(team["school"].casefold())
        wins = record["wins"] if record else None
        losses = record["losses"] if record else None
        ties = record["ties"] if record else None
        decided = None
        if wins is not None and losses is not None:
            decided = wins + losses + (ties or 0)
        rank = ap_by_id.get(team["id"])
        if rank is None:
            rank = ap_by_name.get(team["school"].casefold())
        team_games = [_perspective(game, team) for game in games]
        team_games = [game for game in team_games if game is not None]
        team_games.sort(key=_game_sort)
        home_games = [_home_payload(game, team, venues_by_id) for game in team_games if _is_home_chart_game(game)]
        home_games = [_with_entered_record(game, team_games) for game in home_games]
        reported = [game for game in home_games if game["attendance_status"] == "reported"]
        missing = [game for game in home_games if game["attendance_status"] == "not_reported"]
        capacities = [game["capacity_pct"] for game in reported if game["capacity_pct"] is not None]
        crowds = [game["attendance"] for game in reported]
        results = [game["result"] for game in team_games if game["result"]]
        form = recent_form(results)
        conference = display_conference(team.get("conference"))
        last_home = _last_home_game(home_games)
        pro_note = pro_stadium_note(team.get("stadium"), team.get("venue_id"))
        schools.append(
            {
                "id": team["id"],
                "slug": slug,
                "school": team["school"],
                "mascot": team.get("mascot"),
                "abbreviation": team.get("abbreviation"),
                "conference": conference,
                "tier": tier_for(conference),
                "color": team.get("color") or "#1e3a5f",
                "alternate_color": team.get("alternate_color"),
                "logo": team.get("logo"),
                "stadium": team.get("stadium"),
                "city": team.get("city"),
                "state": team.get("state"),
                "capacity": team.get("capacity"),
                "venue_id": team.get("venue_id"),
                "pro_shared_stadium": pro_note is not None,
                "pro_stadium_note": pro_note,
                "wins": wins,
                "losses": losses,
                "ties": ties or 0,
                "decided_games": decided,
                "win_pct": win_pct(wins, losses, ties),
                "record": record_label(wins, losses, ties),
                "record_source": "cfbd_records" if record else None,
                "ap_rank": rank,
                "ap_week": ap_week["week"] if ap_week else None,
                "ap_season_type": ap_week["season_type"] if ap_week else None,
                "home_games": home_games,
                "reported_home_games": len(reported),
                "missing_attendance_games": len(missing),
                "attendance_omitted": season_omitted,
                "avg_home_attendance": None if season_omitted else ((sum(crowds) / len(crowds)) if crowds else None),
                "avg_capacity_pct": None if season_omitted else ((sum(capacities) / len(capacities)) if capacities else None),
                "last_home_attendance": last_home["attendance"],
                "last_home_attendance_status": last_home["status"],
                "last_home_opponent": last_home["opponent"],
                "last_home_date": last_home["start_date"],
                "last_home_week": last_home["week"],
                "recent_form": form,
                "recent_record": record_label(form["wins"], form["losses"], form["ties"]) if form["games"] else None,
            }
        )

    orders = {
        "ap": _grouped(schools, "ap"),
        "record": _grouped(schools, "record"),
    }
    season_partial = any(
        game.get("attendance_status") == "not_played"
        for school in schools
        for game in school.get("home_games") or []
    )
    analysis_rows = [_analysis_row(school) for school in schools]
    synthetic = bool(raw.get("synthetic") or raw.get("source") != "cfbd")
    notice = raw.get("notice")
    if synthetic and not notice:
        notice = SAMPLE_BANNER
    return {
        "meta": {
            "source": "sample" if synthetic else "cfbd",
            "synthetic": synthetic,
            "notice": notice if synthetic else None,
            "banner": SAMPLE_BANNER if synthetic else None,
            "season": raw.get("season"),
            "attendance_omitted": season_omitted,
            "fetched_at": raw.get("fetched_at"),
            "warnings": list(raw.get("warnings") or []),
            "ap_week": ap_week["week"] if ap_week else None,
            "ap_season_type": ap_week["season_type"] if ap_week else None,
            "ap_poll": "AP Top 25" if ap_week else None,
            "team_count": len(schools),
            "game_count": len(games),
            "season_partial": season_partial,
            "logo_note": (
                "Logos are the URLs CFBD publishes on each team. "
                "CFBD's terms do not grant the right to display school marks."
            ),
        },
        "orders": orders,
        "schools": schools,
        "analysis": analyze(analysis_rows),
    }


def game_capacity(game: dict, team: dict, venues_by_id: dict) -> tuple[int | None, str | None]:
    """Resolve capacity without borrowing another stadium's number."""
    venue = venues_by_id.get(game.get("venue_id"))
    if venue and venue.get("capacity") is not None:
        return venue["capacity"], "game_venue"
    home_capacity = team.get("capacity")
    if home_capacity is None:
        return None, None
    venue_id = game.get("venue_id")
    if venue_id is None or venue_id == team.get("venue_id"):
        return home_capacity, "home_stadium"
    return None, None


def _home_payload(game: dict, team: dict, venues_by_id: dict) -> dict:
    capacity, capacity_source = game_capacity(game, team, venues_by_id)
    attendance = game["attendance"]
    if not game["completed"]:
        status = "not_played"
        attendance_out = None
    elif attendance is None:
        status = "not_reported"
        attendance_out = None
    else:
        status = "reported"
        attendance_out = attendance
    capacity_pct = None
    if status == "reported" and capacity:
        capacity_pct = attendance_out / capacity
    week = game.get("week")
    opponent = game["opponent"]
    label = f"Wk {week} · {opponent}" if week is not None else opponent
    return {
        "id": game["id"],
        "week": week,
        "season_type": game["season_type"],
        "start_date": game["start_date"],
        "opponent": opponent,
        "attendance": attendance_out,
        "attendance_status": status,
        "attendance_source": game.get("attendance_source") if status == "reported" else None,
        "capacity": capacity if status == "reported" or capacity_source else capacity,
        "capacity_source": capacity_source,
        "capacity_pct": capacity_pct,
        "home_points": game["points_for"] if game["completed"] else None,
        "away_points": game["points_against"] if game["completed"] else None,
        "result": game["result"],
        "venue": game.get("venue") or team.get("stadium"),
        "label": label,
    }


def _with_entered_record(home_game: dict, team_games: list[dict]) -> dict:
    prior = [
        game["result"]
        for game in team_games
        if game["result"] and _game_sort(game) < _game_sort(home_game)
    ]
    form = recent_form(prior, window=max(len(prior), 1) if prior else 1)
    if not prior:
        entered = None
    else:
        entered = record_label(form["wins"], form["losses"], form["ties"])
    home_game["entered_record"] = entered
    home_game["entering_win_pct"] = form["win_pct"] if prior else None
    return home_game


def _analysis_row(school: dict) -> dict:
    pregame_points = []
    for game in school["home_games"]:
        if game["attendance_status"] != "reported":
            continue
        if game["capacity_pct"] is None or game["entering_win_pct"] is None:
            continue
        pregame_points.append(
            {
                "entering_win_pct": game["entering_win_pct"],
                "capacity_pct": game["capacity_pct"],
            }
        )
    form = school["recent_form"]
    return {
        "slug": school["slug"],
        "school": school["school"],
        "conference": school["conference"],
        "tier": school["tier"],
        "logo": school.get("logo"),
        "color": school.get("color"),
        "abbreviation": school.get("abbreviation"),
        "record": school["record"],
        "win_pct": school["win_pct"],
        "decided_games": school["decided_games"] or 0,
        "reported_home_games": school["reported_home_games"],
        "attendance_omitted": school.get("attendance_omitted"),
        "avg_home_attendance": school["avg_home_attendance"],
        "avg_capacity_pct": school["avg_capacity_pct"],
        "capacity": school.get("capacity"),
        "stadium": school.get("stadium"),
        "pro_shared_stadium": bool(school.get("pro_shared_stadium")),
        "pro_stadium_note": school.get("pro_stadium_note"),
        "recent_win_pct": form["win_pct"],
        "recent_record": school["recent_record"],
        "pregame_points": pregame_points,
    }


def _grouped(schools: list[dict], mode: str) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for school in schools:
        buckets[school["conference"]].append(school)
    sections = []
    for conference, members in buckets.items():
        ordered = sorted(members, key=lambda school: _sort_key(school, mode))
        sections.append(
            {
                "conference": conference,
                "tier": tier_for(conference),
                "slugs": [school["slug"] for school in ordered],
            }
        )
    sections.sort(key=lambda section: conference_sort_index(section["conference"]))
    return sections


def _sort_key(school: dict, mode: str) -> tuple:
    name = school["school"].casefold()
    unranked = school["ap_rank"] is None
    rank = school["ap_rank"] if school["ap_rank"] is not None else 10_000
    no_record = school["win_pct"] is None
    win_value = school["win_pct"] if school["win_pct"] is not None else -1
    wins = school["wins"] if school["wins"] is not None else -1
    losses = school["losses"] if school["losses"] is not None else 10_000
    if mode == "record":
        return (no_record, -win_value, -wins, losses, unranked, rank, name)
    return (unranked, rank, no_record, -win_value, -wins, losses, name)


def _ap_indexes(ap_week: dict | None) -> tuple[dict, dict]:
    by_id: dict[int, int] = {}
    by_name: dict[str, int] = {}
    if not ap_week:
        return by_id, by_name
    for row in ap_week["ranks"]:
        by_name[row["school"].casefold()] = row["rank"]
        if row.get("team_id") is not None:
            by_id[row["team_id"]] = row["rank"]
    return by_id, by_name


def _perspective(game: dict, team: dict) -> dict | None:
    home_id = game.get("home_id")
    away_id = game.get("away_id")
    if home_id == team["id"]:
        is_home = True
    elif away_id == team["id"]:
        is_home = False
    elif game.get("home_team") == team["school"]:
        is_home = True
    elif game.get("away_team") == team["school"]:
        is_home = False
    else:
        return None
    points_for = game.get("home_points") if is_home else game.get("away_points")
    points_against = game.get("away_points") if is_home else game.get("home_points")
    result = None
    if game.get("completed") and points_for is not None and points_against is not None:
        if points_for > points_against:
            result = "W"
        elif points_for < points_against:
            result = "L"
        else:
            result = "T"
    return {
        "id": game["id"],
        "week": game.get("week"),
        "season_type": game.get("season_type") or "regular",
        "start_date": game.get("start_date"),
        "completed": bool(game.get("completed")),
        "neutral_site": bool(game.get("neutral_site")),
        "attendance": game.get("attendance"),
        "attendance_source": game.get("attendance_source"),
        "venue_id": game.get("venue_id"),
        "venue": game.get("venue"),
        "is_home": is_home,
        "opponent": game["away_team"] if is_home else game["home_team"],
        "points_for": points_for,
        "points_against": points_against,
        "result": result,
    }


def _is_home_chart_game(game: dict) -> bool:
    return bool(game["is_home"]) and not game["neutral_site"]


def _last_home_game(home_games: list[dict]) -> dict:
    """Most recent completed on-campus home game.

    If that game has no attendance, the pin stays empty. An earlier
    reported crowd is not copied forward.
    """
    completed = [game for game in home_games if game.get("attendance_status") != "not_played"]
    if not completed:
        return {
            "attendance": None,
            "status": "none",
            "opponent": None,
            "start_date": None,
            "week": None,
        }
    game = max(completed, key=_game_sort)
    reported = game.get("attendance_status") == "reported" and game.get("attendance") is not None
    return {
        "attendance": game.get("attendance") if reported else None,
        "status": "reported" if reported else "not_reported",
        "opponent": game.get("opponent"),
        "start_date": game.get("start_date"),
        "week": game.get("week"),
    }


def _game_sort(game: dict) -> tuple:
    phase = 1 if game.get("season_type") == "postseason" else 0
    week = game.get("week") if game.get("week") is not None else 99
    return (phase, week, game.get("start_date") or "", game.get("id") or 0)
