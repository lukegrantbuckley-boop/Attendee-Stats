import json

from attendee_tracker.analysis import MIN_TEAMS_FOR_OUTLIERS
from attendee_tracker.assemble import assemble, game_capacity
from attendee_tracker.normalize import latest_ap_week, normalize_game, normalize_rankings
from attendee_tracker.sample_data import NOTICE, build_sample_raw
from attendee_tracker.store import load_sample


def test_committed_fixture_matches_generator():
    assert load_sample() == build_sample_raw()


def test_sample_is_labeled_and_keeps_null_attendance():
    raw = load_sample()
    assert raw["synthetic"] is True
    assert raw["source"] == "sample"
    assert "SAMPLE / DEMO DATA ONLY" in raw["notice"]
    assert NOTICE in raw["notice"]
    assert any(game["attendance"] is None and game["completed"] for game in raw["games"])

    view = assemble(raw)
    assert view["meta"]["synthetic"] is True
    assert view["meta"]["banner"]
    assert view["meta"]["source"] == "sample"

    by_name = {school["school"]: school for school in view["schools"]}
    cumberland = by_name["Cumberland"]
    missing = [game for game in cumberland["home_games"] if game["attendance_status"] == "not_reported"]
    assert missing
    assert all(game["attendance"] is None and game["capacity_pct"] is None for game in missing)

    quarry = by_name["Quarry"]
    assert quarry["reported_home_games"] == 0
    assert all(
        game["attendance"] is None
        for game in quarry["home_games"]
        if game["attendance_status"] != "not_played"
    )

    rimrock = by_name["Rimrock"]
    assert rimrock["capacity"] is None
    assert rimrock["avg_capacity_pct"] is None
    assert rimrock["avg_home_attendance"] is not None

    iron = by_name["Iron Range"]
    assert all(game["venue"] != "Demo Neutral Field" for game in iron["home_games"])
    assert any(game["attendance_status"] == "not_played" for game in iron["home_games"])
    assert view["meta"]["season_partial"] is True


def test_a_finished_season_is_not_partial():
    raw = build_sample_raw()
    for game in raw["games"]:
        game["completed"] = True
    view = assemble(raw)
    assert view["meta"]["season_partial"] is False
    listed = view["analysis"]["loyalty"]["most_loyal"] + view["analysis"]["loyalty"]["softest_support"]
    assert listed
    assert all(row["games_played"] >= 2 for row in listed)


def test_ap_sort_puts_unranked_after_ranked_and_record_sorts_by_wins():
    view = assemble(build_sample_raw())
    schools = {school["slug"]: school for school in view["schools"]}
    sec = next(section for section in view["orders"]["ap"] if section["conference"] == "SEC")
    seen_unranked = False
    for slug in sec["slugs"]:
        rank = schools[slug]["ap_rank"]
        if rank is None:
            seen_unranked = True
        elif seen_unranked:
            raise AssertionError("A ranked school was listed after an unranked school")
    assert seen_unranked

    record_order = next(section for section in view["orders"]["record"] if section["conference"] == "SEC")
    win_pcts = [schools[slug]["win_pct"] for slug in record_order["slugs"]]
    assert win_pcts == sorted(win_pcts, reverse=True)
    assert schools[record_order["slugs"][0]]["record"] == "4-0"
    assert "AP" not in (schools[record_order["slugs"][0]]["record"] or "")


def test_power_4_and_group_of_5_grouping():
    view = assemble(build_sample_raw())
    tiers = {section["conference"]: section["tier"] for section in view["orders"]["ap"]}
    assert tiers["SEC"] == "Power 4"
    assert tiers["Big Ten"] == "Power 4"
    assert tiers["ACC"] == "Power 4"
    assert tiers["Big 12"] == "Power 4"
    assert tiers["Sun Belt"] == "Group of 5"
    assert tiers["Conference USA"] == "Group of 5"
    assert view["orders"]["ap"][0]["tier"] == "Power 4"


def test_sample_outliers_break_the_pattern():
    view = assemble(build_sample_raw())
    analysis = view["analysis"]
    assert analysis["n_teams"] >= MIN_TEAMS_FOR_OUTLIERS
    assert analysis["pearson_r"] > 0.2
    kinds = {point["school"]: point["kind"] for point in analysis["outliers"]}
    assert kinds.get("Redwood") == "draws_above_record"
    assert kinds.get("North Glass") == "soft_crowd_for_record"


def test_capacity_is_not_borrowed_from_a_different_stadium():
    team = {"capacity": 100000, "venue_id": 1, "stadium": "Home"}
    venues = {1: {"id": 1, "capacity": 100000}, 2: {"id": 2, "capacity": None}}
    assert game_capacity({"venue_id": 2}, team, venues) == (None, None)
    assert game_capacity({"venue_id": None}, team, venues) == (100000, "home_stadium")
    assert game_capacity({"venue_id": 1}, team, venues) == (100000, "game_venue")
    assert game_capacity({"venue_id": 9}, team, venues) == (None, None)


def test_normalize_keeps_null_attendance_and_filters_ap():
    game = normalize_game(
        {
            "id": 7,
            "season": 2026,
            "week": 2,
            "seasonType": "regular",
            "completed": True,
            "neutralSite": False,
            "attendance": None,
            "homeId": 1,
            "homeTeam": "Home",
            "awayId": 2,
            "awayTeam": "Away",
        }
    )
    assert game["attendance"] is None
    missing_key = normalize_game(
        {
            "id": 8,
            "homeTeam": "Home",
            "awayTeam": "Away",
            "completed": True,
        }
    )
    assert missing_key["attendance"] is None

    weeks = normalize_rankings(
        [
            {
                "season": 2026,
                "seasonType": "regular",
                "week": 3,
                "polls": [
                    {"poll": "Coaches Poll", "ranks": [{"rank": 1, "school": "Elsewhere", "teamId": 9}]},
                    {"poll": "AP Top 25", "ranks": [{"rank": 5, "school": "Home", "teamId": 1}]},
                ],
            },
            {
                "season": 2026,
                "seasonType": "postseason",
                "week": 1,
                "polls": [
                    {"poll": "AP Top 25", "ranks": [{"rank": 2, "school": "Home", "teamId": 1}]},
                ],
            },
        ]
    )
    latest = latest_ap_week(weeks)
    assert latest["season_type"] == "postseason"
    assert latest["week"] == 1
    assert latest["ranks"][0]["rank"] == 2


def test_card_pins_use_reported_games_and_do_not_backfill_a_null_last_home():
    view = assemble(build_sample_raw())
    by_name = {school["school"]: school for school in view["schools"]}

    iron = by_name["Iron Range"]
    completed = [game for game in iron["home_games"] if game["attendance_status"] != "not_played"]
    assert completed[-1]["attendance"] is not None
    assert iron["last_home_attendance"] == completed[-1]["attendance"]
    assert iron["last_home_attendance_status"] == "reported"
    assert iron["last_home_opponent"] == completed[-1]["opponent"]
    assert iron["avg_home_attendance"] is not None

    quarry = by_name["Quarry"]
    assert quarry["reported_home_games"] == 0
    assert quarry["avg_home_attendance"] is None
    assert quarry["last_home_attendance"] is None
    assert quarry["last_home_attendance_status"] == "not_reported"
    assert quarry["last_home_opponent"]

    raw = {
        "source": "cfbd",
        "synthetic": False,
        "season": 2024,
        "teams": [
            {
                "id": 10,
                "school": "Demo State",
                "conference": "SEC",
                "color": "#123456",
                "capacity": 50000,
                "venue_id": 1,
                "stadium": "Demo Stadium",
            }
        ],
        "venues": [{"id": 1, "name": "Demo Stadium", "capacity": 50000}],
        "records": [],
        "rankings": [],
        "games": [
            _home_game(1, 1, "2024-09-01T23:00:00Z", 50000, "Earlier"),
            _home_game(2, 2, "2024-09-08T23:00:00Z", None, "Later"),
            _home_game(3, 3, "2024-09-15T23:00:00Z", None, "Future", completed=False),
        ],
    }
    school = assemble(raw)["schools"][0]
    assert school["avg_home_attendance"] == 50000
    assert school["last_home_attendance"] is None
    assert school["last_home_attendance_status"] == "not_reported"
    assert school["last_home_opponent"] == "Later"

    waiting = assemble(
        {
            **raw,
            "games": [_home_game(4, 1, "2024-09-01T23:00:00Z", None, "Future", completed=False)],
        }
    )["schools"][0]
    assert waiting["avg_home_attendance"] is None
    assert waiting["last_home_attendance"] is None
    assert waiting["last_home_attendance_status"] == "none"
    assert waiting["reported_home_games"] == 0


def _home_game(game_id, week, start, attendance, opponent, completed=True):
    return {
        "id": game_id,
        "season": 2024,
        "week": week,
        "season_type": "regular",
        "start_date": start,
        "completed": completed,
        "neutral_site": False,
        "attendance": attendance,
        "venue_id": 1,
        "venue": "Demo Stadium",
        "home_id": 10,
        "home_team": "Demo State",
        "home_points": 21 if completed else None,
        "away_id": 80 + game_id,
        "away_team": opponent,
        "away_points": 7 if completed else None,
    }


def test_fixture_json_round_trip_has_no_invented_zero_for_nulls():
    text = json.dumps(build_sample_raw())
    assert '"attendance": null' in text
    assert '"attendance": 0' not in text
