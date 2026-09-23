import pytest

from attendee_tracker.analysis import analyze
from attendee_tracker.assemble import assemble
from attendee_tracker.pro_stadiums import PRO_VENUES, ProVenue, matching_venue, pro_stadium_note
from attendee_tracker.sample_data import build_sample_raw


def test_registry_matches_seeded_names_and_other_nfl_houses():
    seeded = {
        "Allegiant Stadium": "UNLV",
        "Raymond James Stadium": "South Florida",
        "Hard Rock Stadium": "Miami",
        "Lincoln Financial Field": "Temple",
        "Acrisure Stadium": "Pittsburgh",
        "Heinz Field": "Pittsburgh",
    }
    for name, school in seeded.items():
        venue = matching_venue(name)
        assert venue is not None, name
        assert school in venue.schools
        assert pro_stadium_note(name)
        assert pro_stadium_note(name.casefold()) == venue.note

    for name in (
        "Mercedes-Benz Stadium",
        "SoFi Stadium",
        "Levi's Stadium",
        "Gillette Stadium",
        "Caesars Superdome",
        "NRG Stadium",
        "Lucas Oil Stadium",
        "MetLife Stadium",
    ):
        assert pro_stadium_note(name)

    assert "Falcons" in pro_stadium_note("Mercedes-Benz Stadium")
    assert "Saints" in pro_stadium_note("Mercedes-Benz Superdome")
    assert pro_stadium_note("Neyland Stadium") is None
    assert pro_stadium_note("Sam Boyd Stadium") is None
    assert pro_stadium_note("Center Parc Stadium") is None
    assert any(venue.schools == ("Temple",) for venue in PRO_VENUES)


def test_registry_matches_venue_id_even_when_the_name_differs(monkeypatch):
    venue = ProVenue(
        names=("lincoln financial field",),
        note="NFL stadium (Eagles / Lincoln Financial)",
        schools=("Temple",),
        venue_ids=(8675309,),
    )
    monkeypatch.setattr("attendee_tracker.pro_stadiums.PRO_VENUES", (venue,))
    assert pro_stadium_note("Lincoln Financial Field", None) == venue.note
    assert pro_stadium_note("Renamed Bowl", 8675309) == venue.note
    assert pro_stadium_note("Neyland Stadium", 1) is None
    assert matching_venue(None, 8675309) is venue


def test_temple_like_nfl_home_is_excluded_from_soft_support_and_listed_by_crowd():
    raw = _season()
    view = assemble(raw)
    by_name = {school["school"]: school for school in view["schools"]}
    temple = by_name["Temple"]
    assert temple["pro_shared_stadium"] is True
    assert "Eagles" in temple["pro_stadium_note"]
    assert temple["capacity"] == 69796
    assert temple["avg_capacity_pct"] == pytest.approx(17400 / 69796)
    assert temple["avg_home_attendance"] == 17400

    unlv = by_name["UNLV"]
    assert unlv["pro_shared_stadium"] is True
    assert unlv["stadium"] == "Allegiant Stadium"
    assert by_name["UNLV Alumni"]["pro_shared_stadium"] is False
    assert by_name["UNLV Alumni"]["stadium"] == "Sam Boyd Stadium"

    analysis = view["analysis"]
    soft_names = [row["school"] for row in analysis["loyalty"]["softest_support"]]
    loyal_names = [row["school"] for row in analysis["loyalty"]["most_loyal"]]
    fit_names = [row["school"] for row in analysis["points"]]
    assert "Temple" not in soft_names
    assert "Temple" not in loyal_names
    assert "UNLV" not in soft_names
    assert "Temple" not in fit_names
    assert "Campus" in soft_names
    assert analysis["outliers"] == [] or all(row["school"] != "Temple" for row in analysis["outliers"])

    pro_names = [row["school"] for row in analysis["pro_stadiums"]]
    assert pro_names == ["UNLV", "Temple", "Quiet"]
    quiet = analysis["pro_stadiums"][-1]
    assert quiet["school"] == "Quiet"
    assert quiet["avg_home_attendance"] is None
    assert quiet["avg_capacity_pct"] is None
    assert quiet["capacity"] == 70000
    assert "SoFi" in quiet["pro_stadium_note"]
    dumped = str(analysis["pro_stadiums"])
    assert "17400" in dumped or "17400.0" in dumped
    assert "'avg_home_attendance': 0" not in dumped and '"avg_home_attendance": 0' not in str(analysis).replace(" ", "")


def test_sample_schools_are_not_flagged_as_pro_stadiums():
    view = assemble(build_sample_raw())
    assert all(school["pro_shared_stadium"] is False for school in view["schools"])
    assert view["analysis"]["pro_stadiums"] == []


def test_analyze_drops_a_flagged_low_fill_team_from_the_fit():
    rows = [
        _metric("Campus", 0.0, 0.30, 12000),
        _metric("Temple", 0.0, 0.25, 17400, pro=True, capacity=69796, stadium="Lincoln Financial Field"),
        _metric("Champion", 1.0, 0.90, 50000),
    ]
    result = analyze(rows)
    assert [row["school"] for row in result["loyalty"]["softest_support"]] == ["Campus"]
    assert all(row["school"] != "Temple" for row in result["points"])
    assert result["pro_stadiums"][0]["school"] == "Temple"
    assert result["pro_stadiums"][0]["capacity"] == 69796
    assert result["pro_stadiums"][0]["avg_capacity_pct"] == pytest.approx(0.25)


def _metric(name, win_value, fill, crowd, pro=False, capacity=40000, stadium="Campus Field"):
    return {
        "slug": name.casefold().replace(" ", "-"),
        "school": name,
        "conference": "AAC",
        "tier": "Group of 5",
        "record": "0-4" if win_value == 0 else "4-0",
        "win_pct": win_value,
        "decided_games": 4,
        "reported_home_games": 2,
        "avg_home_attendance": crowd,
        "avg_capacity_pct": fill,
        "capacity": capacity,
        "stadium": stadium,
        "pro_shared_stadium": pro,
        "pro_stadium_note": "NFL stadium (Eagles / Lincoln Financial)" if pro else None,
        "recent_win_pct": win_value,
        "recent_record": "0-2",
        "pregame_points": [],
    }


def _season():
    teams = [
        _team(1, "Temple", "Lincoln Financial Field", 69796, "AAC"),
        _team(2, "UNLV", "Allegiant Stadium", 65000, "Mountain West"),
        _team(3, "UNLV Alumni", "Sam Boyd Stadium", 40000, "Mountain West"),
        _team(4, "Campus", "Campus Field", 40000, "AAC"),
        _team(5, "Quiet", "SoFi Stadium", 70000, "Pac-12"),
        _team(6, "Champion", "Champion Field", 80000, "Big Ten"),
    ]
    records = [
        _record(1, "Temple", 1, 3),
        _record(2, "UNLV", 2, 2),
        _record(3, "UNLV Alumni", 2, 2),
        _record(4, "Campus", 0, 4),
        _record(5, "Quiet", 1, 3),
        _record(6, "Champion", 4, 0),
    ]
    games = []
    game_id = 1
    plan = [
        (1, "Temple", 17400),
        (2, "UNLV", 32000),
        (3, "UNLV Alumni", 20000),
        (4, "Campus", 12000),
        (5, "Quiet", None),
        (6, "Champion", 72000),
    ]
    for team_id, school, attendance in plan:
        for week in (1, 2):
            games.append(_game(game_id, team_id, school, attendance, week))
            game_id += 1
    return {
        "source": "cfbd",
        "synthetic": False,
        "season": 2025,
        "teams": teams,
        "venues": [
            {"id": team["venue_id"], "name": team["stadium"], "capacity": team["capacity"]}
            for team in teams
        ],
        "games": games,
        "records": records,
        "rankings": [],
    }


def _team(team_id, school, stadium, capacity, conference):
    return {
        "id": team_id,
        "school": school,
        "conference": conference,
        "color": "#123456",
        "abbreviation": "PRO",
        "venue_id": 5000 + team_id,
        "stadium": stadium,
        "capacity": capacity,
        "city": "City",
        "state": "PA",
    }


def _record(team_id, school, wins, losses):
    return {
        "year": 2025,
        "team_id": team_id,
        "team": school,
        "conference": "AAC",
        "wins": wins,
        "losses": losses,
        "ties": 0,
        "games": wins + losses,
    }


def _game(game_id, home_id, home, attendance, week):
    return {
        "id": game_id,
        "season": 2025,
        "week": week,
        "season_type": "regular",
        "start_date": f"2025-09-{week:02d}T23:30:00Z",
        "completed": True,
        "neutral_site": False,
        "attendance": attendance,
        "venue_id": 5000 + home_id,
        "venue": home,
        "home_id": home_id,
        "home_team": home,
        "home_points": 21,
        "away_id": 8000 + game_id,
        "away_team": "Visitor",
        "away_points": 14,
    }
