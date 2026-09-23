import json

import pytest
from fastapi.testclient import TestClient

from attendee_tracker.analysis import ols
from attendee_tracker.app import app
from attendee_tracker.attendance_growth import MIN_SEASONS, rank_attendance_growth


def test_cagr_uses_reported_averages_and_skips_null_years():
    gap = _school("Gap", [
        (2015, 10000),
        (2016, None),
        (2017, 12000),
        (2018, 14000),
        (2019, 16000),
        (2021, 18000),
    ])
    result = rank_attendance_growth([gap])
    row = result["fastest_growing"][0]
    assert row["seasons_with_average"] == 5
    assert row["start_year"] == 2015
    assert row["end_year"] == 2021
    assert row["start_avg"] == 10000
    assert row["end_avg"] == 18000
    expected = ols([2015, 2017, 2018, 2019, 2021], [10000, 12000, 14000, 16000, 18000])[1]
    with_zero = ols([2015, 2016, 2017, 2018, 2019, 2021], [10000, 0, 12000, 14000, 16000, 18000])[1]
    assert row["slope_per_year"] == pytest.approx(expected, abs=0.1)
    assert row["slope_per_year"] != pytest.approx(with_zero, abs=0.1)
    assert result["softest_growth"] == []
    assert result["basis"] == "none"


def test_ten_percent_compound_growth_and_name_tie_break():
    anchor = _school("Anchor", _compound(5000, 0.10))
    middling = _school("Middling", _compound(50000, 0.10))
    result = rank_attendance_growth([middling, anchor])
    names = [row["school"] for row in result["fastest_growing"]]
    assert names == ["Anchor", "Middling"]
    assert result["fastest_growing"][0]["cagr"] == pytest.approx(0.10, abs=1e-4)
    assert result["fastest_growing"][0]["end_avg"] < result["fastest_growing"][1]["end_avg"]
    assert result["fastest_growing"][0]["pct_change"] == pytest.approx(1.1 ** 4 - 1, abs=1e-3)


def test_declines_are_the_falling_list_and_pro_homes_are_left_out():
    grower = _school("Redwood", _compound(20000, 0.08))
    mild = _school("Amber", _compound(10000, -0.05))
    steep = _school("Zebra", _compound(80000, -0.05))
    worse = _school("Canal", _compound(30000, -0.12))
    pro = _school("Temple", _compound(15000, 0.40), stadium="Lincoln Financial Field", pro=True)
    short = _school("Brief", _compound(12000, 0.20)[:4])
    result = rank_attendance_growth([grower, mild, steep, worse, pro, short])
    assert [row["school"] for row in result["fastest_growing"]] == ["Redwood"]
    assert [row["school"] for row in result["softest_growth"]] == ["Canal", "Amber", "Zebra"]
    assert result["basis"] == "decline"
    assert result["softest_growth"][1]["end_avg"] < result["softest_growth"][2]["end_avg"]
    assert "Temple" in result["excluded_pro_shared"]
    assert "Brief" not in [row["school"] for row in result["fastest_growing"] + result["softest_growth"]]
    assert short_seasons(short) < MIN_SEASONS


def test_without_a_decline_the_second_list_is_the_weakest_growth():
    schools = [_school(f"School {index:02d}", _compound(10000, 0.01 * (index + 1))) for index in range(12)]
    result = rank_attendance_growth(schools)
    assert result["basis"] == "weakest_growth"
    assert result["n_declining"] == 0
    growing = [row["school"] for row in result["fastest_growing"]]
    falling = [row["school"] for row in result["softest_growth"]]
    assert growing[0] == "School 11"
    assert len(growing) == 10
    assert falling == ["School 00", "School 01"]
    assert not set(growing) & set(falling)


def test_2020_crowds_do_not_change_growth():
    points = [
        (2016, 10000),
        (2017, 11000),
        (2018, 12100),
        (2019, 13310),
        (2021, 16105),
    ]
    clean = rank_attendance_growth([_school("Plain", points)])["fastest_growing"][0]
    collapse = rank_attendance_growth([_school("Plain", points + [(2020, 100)])])
    spike = rank_attendance_growth([_school("Plain", points + [(2020, 90000)])])["fastest_growing"][0]
    warped = collapse["fastest_growing"][0]
    assert warped["cagr"] == clean["cagr"]
    assert spike["cagr"] == clean["cagr"]
    assert warped["slope_per_year"] == clean["slope_per_year"]
    assert spike["slope_per_year"] == clean["slope_per_year"]
    assert warped["pct_change"] == clean["pct_change"]
    assert warped["seasons_with_average"] == 5
    assert warped["start_year"] == 2016
    assert warped["end_year"] == 2021
    assert warped["start_avg"] == 10000
    assert warped["end_avg"] == 16105
    assert "2020" in collapse["methodology"]
    assert "COVID" in collapse["methodology"]


def test_2020_does_not_qualify_a_four_season_history():
    short = _school("Short", [
        (2017, 10000),
        (2018, 11000),
        (2019, 12000),
        (2020, 500),
        (2021, 13000),
    ])
    result = rank_attendance_growth([short])
    assert result["n_qualifying"] == 0
    assert result["fastest_growing"] == []
    assert result["softest_growth"] == []


def test_a_pro_stadium_only_in_2020_does_not_eject_the_school():
    school = _school("Campus", _compound(20000, 0.04))
    school["seasons"].append({
        "year": 2020,
        "avg_home_attendance": 1000,
        "stadium": "Lincoln Financial Field",
        "pro_shared_stadium": True,
    })
    result = rank_attendance_growth([school])
    assert result["excluded_pro_shared"] == []
    assert result["fastest_growing"][0]["school"] == "Campus"
    assert result["fastest_growing"][0]["seasons_with_average"] == 5
    assert result["fastest_growing"][0]["end_year"] == 2019


def test_history_api_returns_growth_from_cached_seasons(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    live = tmp_path / "live"
    live.mkdir()
    for offset, year in enumerate(range(2015, 2020)):
        raw = _raw(year, [
            _team(1, "Grow U", "Campus Field"),
            _team(2, "Fade U", "Campus Field"),
        ], [
            _game(year * 10 + 1, year, 1, "Grow U", 10000 + offset * 1000),
            _game(year * 10 + 2, year, 2, "Fade U", 20000 - offset * 1000),
        ])
        (live / f"{year}.json").write_text(json.dumps(raw), encoding="utf-8")
    client = TestClient(app)
    response = client.get("/api/history?from=2015&to=2019")
    assert response.status_code == 200
    growth = response.json()["attendance_growth"]
    assert [row["school"] for row in growth["fastest_growing"]] == ["Grow U"]
    assert [row["school"] for row in growth["softest_growth"]] == ["Fade U"]
    assert growth["basis"] == "decline"
    assert growth["fastest_growing"][0]["cagr"] > 0
    assert growth["softest_growth"][0]["cagr"] < 0
    assert "social" not in json.dumps(growth).casefold()


def _compound(start, rate):
    # 2015–2019, so a normal five-season series never lands on the omitted COVID year.
    return [(2015 + index, start * ((1 + rate) ** index)) for index in range(5)]


def _school(name, points, stadium="Campus Field", pro=False):
    return {
        "slug": name.casefold().replace(" ", "-"),
        "school": name,
        "conference": "AAC",
        "color": "#123456",
        "abbreviation": "XX",
        "stadium": stadium,
        "pro_shared_stadium": pro,
        "seasons": [
            {
                "year": year,
                "avg_home_attendance": average,
                "stadium": stadium,
                "pro_shared_stadium": pro,
            }
            for year, average in points
        ],
    }


def short_seasons(school):
    return sum(1 for season in school["seasons"] if season["avg_home_attendance"] is not None)


def _raw(year, teams, games):
    return {
        "source": "cfbd",
        "synthetic": False,
        "season": year,
        "teams": teams,
        "venues": [{"id": 1, "name": "Campus Field", "capacity": 40000}],
        "games": games,
        "records": [],
        "rankings": [],
    }


def _team(team_id, school, stadium):
    return {
        "id": team_id,
        "school": school,
        "conference": "AAC",
        "color": "#123456",
        "abbreviation": "GU",
        "capacity": 40000,
        "venue_id": 1,
        "stadium": stadium,
    }


def _game(game_id, year, home_id, home, attendance):
    return {
        "id": game_id,
        "season": year,
        "week": 1,
        "season_type": "regular",
        "start_date": f"{year}-09-05T23:30:00Z",
        "completed": True,
        "neutral_site": False,
        "attendance": attendance,
        "venue_id": 1,
        "venue": "Campus Field",
        "home_id": home_id,
        "home_team": home,
        "home_points": 21,
        "away_id": 8000 + game_id,
        "away_team": "Visitor",
        "away_points": 14,
    }
