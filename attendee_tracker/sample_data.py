"""Synthetic season used only when no CFBD cache exists.

Every attendance figure in this module is made up so the interface can be
reviewed without an API key. Do not cite it as 2026 attendance.
"""

from __future__ import annotations

import json
from pathlib import Path

from attendee_tracker.config import sample_path

NOTICE = (
    "SAMPLE / DEMO DATA ONLY. These schools, scores, and attendance figures are "
    "synthetic. They are not College Football Data API results and must not be "
    "cited as real 2026 attendance."
)

# school, conference, capacity, color, abbreviation, mascot, city, state,
# ap rank or None, wins, losses, target fill of capacity.
# Capacity None means the stadium figure is unreported on purpose.
TEAMS = [
    ("Iron Range", "SEC", 102000, "#6b2d3c", "IR", "Rangers", "Iron Range", "AL", 2, 4, 0, 0.91),
    ("Redwood", "SEC", 85000, "#9f2d2d", "RW", "Elks", "Redwood", "AL", None, 1, 3, 0.96),
    ("Cumberland", "SEC", 74000, "#1f4d3a", "CUMB", "Forge", "Cumberland", "TN", 11, 3, 1, 0.80),
    ("Blackwater", "SEC", 61000, "#243044", "BW", "Wolves", "Blackwater", "MS", None, 2, 2, 0.60),
    ("Lake Mercer", "Big Ten", 107000, "#1e3a8a", "LM", "Loons", "Lake Mercer", "MI", 1, 4, 0, 0.93),
    ("North Glass", "Big Ten", 72000, "#0f766e", "NG", "Pines", "North Glass", "WI", 6, 4, 0, 0.40),
    ("Pine Hollow", "Big Ten", 68000, "#3f6212", "PH", "Owls", "Pine Hollow", "IN", 9, 3, 1, 0.76),
    ("Quarry", "Big Ten", 50000, "#57534e", "QY", "Stone", "Quarry", "IA", None, 2, 2, 0.62),
    ("Harbor State", "ACC", 81000, "#1d4e89", "HS", "Gulls", "Harbor", "NC", 4, 4, 0, 0.88),
    ("Cinder Ridge", "ACC", 55000, "#9a3412", "CR", "Ash", "Cinder Ridge", "VA", None, 1, 3, 0.47),
    ("East Vale", "ACC", 64000, "#4c1d95", "EV", "Violets", "East Vale", "SC", 18, 2, 2, 0.63),
    ("Marlow", "ACC", 48000, "#3f3f46", "MAR", "Bells", "Marlow", "GA", None, 0, 4, 0.36),
    ("Mesa Union", "Big 12", 90000, "#b45309", "MU", "Suns", "Mesa Union", "TX", 7, 3, 1, 0.79),
    ("Copper Flat", "Big 12", 58000, "#a16207", "CF", "Claims", "Copper Flat", "OK", None, 2, 2, 0.58),
    ("West Marrow", "Big 12", 52000, "#7c2d12", "WM", "Antlers", "West Marrow", "KS", None, 1, 3, 0.50),
    ("Sandhill", "Big 12", 42000, "#854d0e", "SH", "Cranes", "Sandhill", "TX", None, 0, 4, 0.34),
    ("Bayou Tech", "American Athletic", 65000, "#155e75", "BT", "Herons", "Bayou", "LA", 22, 3, 1, 0.77),
    ("River Parish", "American Athletic", 40000, "#0e7490", "RP", "Current", "River Parish", "LA", None, 1, 3, 0.46),
    ("Palmetto Shore", "Sun Belt", 36000, "#4d7c0f", "PS", "Palms", "Palmetto Shore", "FL", None, 2, 2, 0.64),
    ("Gulf Line", "Sun Belt", 30000, "#0369a1", "GL", "Keel", "Gulf Line", "AL", None, 0, 4, 0.39),
    ("High Desert", "Mountain West", 45000, "#c2410c", "HD", "Hawks", "High Desert", "NM", None, 3, 1, 0.74),
    ("Rimrock", "Mountain West", None, "#44403c", "RR", "Rims", "Rimrock", "UT", None, 3, 1, None),
    ("Mill City", "Mid-American", 24000, "#365314", "MC", "Millers", "Mill City", "OH", None, 2, 2, 0.61),
    ("Canal", "Mid-American", 20000, "#1e40af", "CAN", "Locks", "Canal", "OH", None, 0, 4, 0.33),
    ("Foundry", "Conference USA", 38000, "#7f1d1d", "FDY", "Irons", "Foundry", "KY", None, 2, 2, 0.62),
    ("Switchyard", "Conference USA", 31000, "#334155", "SW", "Signals", "Switchyard", "TX", None, 1, 3, 0.48),
]

# Schools whose completed home crowds are intentionally blank.
ALL_NULL_ATTENDANCE = {"Quarry"}
# One completed home game left blank so the missing-attendance badge has a real case.
PARTIAL_NULL_HOME_INDEX = {"Cumberland": 1}
# Reported crowds with no stadium capacity, so percent-full stays blank.
NO_CAPACITY_CROWDS = {
    "Rimrock": (22100, 21850, 23040),
}
NEUTRAL_INSTEAD_OF_AWAY = {"Iron Range"}

# Visitors are not FBS schools in this fixture. Using another demo school's name
# would attach the game to that school's record and home log.
VISITORS = (
    "State College",
    "Polytechnic",
    "River College",
    "Central Academy",
    "North Tech",
    "South Tech",
    "Prairie College",
    "Harbor College",
)

WEEK_DATES = {
    1: "2026-08-29T23:30:00Z",
    2: "2026-09-05T23:30:00Z",
    3: "2026-09-12T23:30:00Z",
    4: "2026-09-19T23:30:00Z",
    5: "2026-09-26T23:30:00Z",
}
HOME_FACTORS = (0.98, 1.0, 1.03)


def build_sample_raw() -> dict:
    teams = []
    venues = []
    records = []
    games = []
    next_game_id = 1001

    for index, row in enumerate(TEAMS, start=1):
        school, conference, capacity, color, abbr, mascot, city, state, _ap, wins, losses, _fill = row
        teams.append(
            {
                "id": index,
                "school": school,
                "mascot": mascot,
                "abbreviation": abbr,
                "conference": conference,
                "classification": "fbs",
                "color": color,
                "alternate_color": "#f4f0e6",
                "logo": None,
                "venue_id": index,
                "stadium": f"{school} Stadium",
                "city": city,
                "state": state,
                "capacity": capacity,
            }
        )
        venues.append(
            {
                "id": index,
                "name": f"{school} Stadium",
                "city": city,
                "state": state,
                "capacity": capacity,
                "dome": False,
            }
        )
        records.append(
            {
                "year": 2026,
                "team_id": index,
                "team": school,
                "conference": conference,
                "wins": wins,
                "losses": losses,
                "ties": 0,
                "games": wins + losses,
            }
        )

    for index, row in enumerate(TEAMS):
        team_id = index + 1
        school, conference, capacity, _color, _abbr, _mascot, _city, _state, _ap, wins, losses, fill = row
        results = (["W"] * wins) + (["L"] * losses)
        opponents = _opponents(index)
        home_crowds = _home_crowds(school, capacity, fill)
        # Three completed home games, then either an away game or a neutral-site game.
        for home_index in range(3):
            opponent = opponents[home_index]
            result = results[home_index]
            points_for, points_against = _score(result, team_id + home_index)
            games.append(
                _game(
                    game_id=next_game_id,
                    week=home_index + 1,
                    start_date=WEEK_DATES[home_index + 1],
                    completed=True,
                    neutral=False,
                    attendance=home_crowds[home_index],
                    venue_id=team_id,
                    venue=f"{school} Stadium",
                    home_id=team_id,
                    home_team=school,
                    home_conference=conference,
                    home_points=points_for,
                    away_id=8000 + team_id * 10 + home_index,
                    away_team=opponent,
                    away_conference=None,
                    away_points=points_against,
                )
            )
            next_game_id += 1

        fourth = results[3]
        points_for, points_against = _score(fourth, team_id + 3)
        opponent = opponents[3]
        visitor_id = 8000 + team_id * 10 + 3
        if school in NEUTRAL_INSTEAD_OF_AWAY:
            games.append(
                _game(
                    game_id=next_game_id,
                    week=4,
                    start_date=WEEK_DATES[4],
                    completed=True,
                    neutral=True,
                    attendance=70000,
                    venue_id=9000,
                    venue="Demo Neutral Field",
                    home_id=team_id,
                    home_team=school,
                    home_conference=conference,
                    home_points=points_for,
                    away_id=visitor_id,
                    away_team=opponent,
                    away_conference=None,
                    away_points=points_against,
                )
            )
        else:
            games.append(
                _game(
                    game_id=next_game_id,
                    week=4,
                    start_date=WEEK_DATES[4],
                    completed=True,
                    neutral=False,
                    attendance=None,
                    venue_id=visitor_id,
                    venue=f"{opponent} Field",
                    home_id=visitor_id,
                    home_team=opponent,
                    home_conference=None,
                    home_points=points_against,
                    away_id=team_id,
                    away_team=school,
                    away_conference=conference,
                    away_points=points_for,
                )
            )
        next_game_id += 1

        games.append(
            _game(
                game_id=next_game_id,
                week=5,
                start_date=WEEK_DATES[5],
                completed=False,
                neutral=False,
                attendance=None,
                venue_id=team_id,
                venue=f"{school} Stadium",
                home_id=team_id,
                home_team=school,
                home_conference=conference,
                home_points=None,
                away_id=8000 + team_id * 10 + 4,
                away_team=opponents[4],
                away_conference=None,
                away_points=None,
            )
        )
        next_game_id += 1

    ranks = []
    for index, row in enumerate(TEAMS, start=1):
        ap_rank = row[8]
        if ap_rank is None:
            continue
        ranks.append(
            {
                "rank": ap_rank,
                "team_id": index,
                "school": row[0],
                "conference": row[1],
            }
        )
    ranks.sort(key=lambda item: item["rank"])

    return {
        "source": "sample",
        "synthetic": True,
        "notice": NOTICE,
        "season": 2026,
        "fetched_at": None,
        "warnings": [
            "Sample/demo data only. Attendance numbers are synthetic and exist for UI wiring."
        ],
        "teams": teams,
        "venues": venues,
        "games": games,
        "records": records,
        "rankings": [
            {
                "season": 2026,
                "season_type": "regular",
                "week": 4,
                "poll": "AP Top 25",
                "ranks": ranks,
            }
        ],
    }


def write_sample(path: Path | None = None) -> Path:
    destination = path or sample_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_sample_raw()
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return destination


def _opponents(index: int) -> list[str]:
    count = len(VISITORS)
    return [VISITORS[(index + step) % count] for step in range(5)]


def _home_crowds(school: str, capacity: int | None, fill: float | None) -> list[int | None]:
    if school in ALL_NULL_ATTENDANCE:
        return [None, None, None]
    if school in NO_CAPACITY_CROWDS:
        return list(NO_CAPACITY_CROWDS[school])
    crowds: list[int | None] = []
    for factor in HOME_FACTORS:
        crowds.append(int(round(capacity * fill * factor)))
    null_index = PARTIAL_NULL_HOME_INDEX.get(school)
    if null_index is not None:
        crowds[null_index] = None
    return crowds


def _score(result: str, seed: int) -> tuple[int, int]:
    if result == "W":
        return 28 + (seed % 11), 13 + (seed % 8)
    return 14 + (seed % 7), 27 + (seed % 10)


def _game(
    *,
    game_id: int,
    week: int,
    start_date: str,
    completed: bool,
    neutral: bool,
    attendance: int | None,
    venue_id: int,
    venue: str,
    home_id: int,
    home_team: str,
    home_conference: str,
    home_points: int | None,
    away_id: int,
    away_team: str,
    away_conference: str,
    away_points: int | None,
) -> dict:
    return {
        "id": game_id,
        "season": 2026,
        "week": week,
        "season_type": "regular",
        "start_date": start_date,
        "completed": completed,
        "neutral_site": neutral,
        "conference_game": home_conference == away_conference and not neutral,
        "attendance": attendance,
        "venue_id": venue_id,
        "venue": venue,
        "home_id": home_id,
        "home_team": home_team,
        "home_conference": home_conference,
        "home_points": home_points,
        "away_id": away_id,
        "away_team": away_team,
        "away_conference": away_conference,
        "away_points": away_points,
    }


if __name__ == "__main__":
    written = write_sample()
    print(f"Wrote {written}")
