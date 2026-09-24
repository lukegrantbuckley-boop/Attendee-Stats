import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from attendee_tracker.app import app
from attendee_tracker.excluded_years import COVID_OMISSION, attendance_year_omitted
from attendee_tracker.refresh_current import (
    CFBD_SOURCE,
    ESPN_SOURCE,
    apply_attendance_sources,
    espn_attendance_value,
    main,
    match_espn_event,
    refresh_season,
)


class SplitClient:
    """One reported CFBD crowd, one null home game, one neutral, one not yet played."""

    def fetch_games(self, year):
        return [
            _game(1, True, False, 88000, home_id=10, away_id=11, home="Demo State", away="Other"),
            _game(2, True, False, None, home_id=10, away_id=12, home="Demo State", away="Visitor"),
            _game(3, True, True, None, home_id=10, away_id=13, home="Demo State", away="Neutral Foe"),
            _game(4, False, False, None, home_id=10, away_id=14, home="Demo State", away="Future"),
        ]

    def fetch_records(self, year):
        return [
            {
                "year": year,
                "teamId": 10,
                "team": "Demo State",
                "conference": "SEC",
                "total": {"games": 2, "wins": 2, "losses": 0, "ties": 0},
            }
        ]

    def fetch_rankings(self, year):
        return []

    def fetch_teams(self, year):
        return [
            {
                "id": 10,
                "school": "Demo State",
                "mascot": "Tests",
                "abbreviation": "DEM",
                "conference": "SEC",
                "classification": "fbs",
                "color": "123456",
                "logos": ["https://example.com/demo.png"],
                "location": {"id": 5, "name": "Demo Stadium", "city": "Town", "state": "AL", "capacity": 55000},
            }
        ]

    def fetch_venues(self):
        return [{"id": 5, "name": "Demo Stadium", "city": "Town", "state": "AL", "capacity": 55000}]


def _game(game_id, completed, neutral, attendance, *, home_id, away_id, home, away):
    return {
        "id": game_id,
        "season": 2026,
        "week": 1,
        "seasonType": "regular",
        "startDate": f"2026-09-0{game_id}T16:00:00.000Z",
        "completed": completed,
        "neutralSite": neutral,
        "attendance": attendance,
        "venueId": 5,
        "venue": "Demo Stadium",
        "homeId": home_id,
        "homeTeam": home,
        "homeConference": "SEC",
        "homePoints": 21 if completed else None,
        "awayId": away_id,
        "awayTeam": away,
        "awayPoints": 14 if completed else None,
    }


def _espn_getter(attendance):
    def get_json(url):
        if "scoreboard" in url and "seasontype=2" in url and "week=1&" in url:
            return {
                "events": [
                    {
                        "id": "9002",
                        "date": "2026-09-02T16:00Z",
                        "status": {"type": {"completed": True}},
                        "competitions": [
                            {
                                "neutralSite": False,
                                "competitors": [
                                    {"homeAway": "home", "team": {"id": "10"}},
                                    {"homeAway": "away", "team": {"id": "12"}},
                                ],
                            }
                        ],
                    }
                ]
            }
        if "scoreboard" in url:
            return {"events": []}
        if "summary?event=9002" in url:
            return {"gameInfo": {"attendance": attendance}}
        raise AssertionError(url)

    return get_json


def test_espn_attendance_value_keeps_reported_numbers_and_rejects_guesses():
    assert espn_attendance_value(51144) == 51144
    assert espn_attendance_value("100,077") == 100077
    assert espn_attendance_value(40000.0) == 40000
    assert espn_attendance_value(0) == 0
    assert espn_attendance_value(None) is None
    assert espn_attendance_value(True) is None
    assert espn_attendance_value(False) is None
    assert espn_attendance_value(-5) is None
    assert espn_attendance_value("n/a") is None
    assert espn_attendance_value(12.5) is None


def test_match_requires_team_ids_and_a_close_start():
    game = {"home_id": 10, "away_id": 12, "start_date": "2026-09-02T19:30:00.000Z"}
    near = {"home_id": "10", "away_id": "12", "date": "2026-09-02T16:00Z", "espn_id": "1"}
    far = {"home_id": 10, "away_id": 12, "date": "2026-09-05T16:00Z", "espn_id": "2"}
    swapped = {"home_id": 12, "away_id": 10, "date": "2026-09-02T16:00Z", "espn_id": "3"}
    assert match_espn_event(game, [far, swapped, near])["espn_id"] == "1"
    assert match_espn_event(game, [far, swapped]) is None


def test_refresh_keeps_cfbd_attendance_and_fills_only_null_home_games(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    calls = refresh_season(
        year=2026,
        force=True,
        min_interval_hours=18,
        client=SplitClient(),
        get_json=_espn_getter(45123),
        sleep=lambda _seconds: None,
    )
    assert calls == 5
    live = json.loads((tmp_path / "live" / "2026.json").read_text(encoding="utf-8"))
    by_id = {game["id"]: game for game in live["games"]}
    assert by_id[1]["attendance"] == 88000
    assert by_id[1]["attendance_source"] == CFBD_SOURCE
    assert by_id[2]["attendance"] == 45123
    assert by_id[2]["attendance_source"] == ESPN_SOURCE
    assert by_id[3]["attendance"] is None
    assert "attendance_source" not in by_id[3]
    assert by_id[4]["attendance"] is None
    assert "attendance_source" not in by_id[4]
    assert "No attendance was invented." in " ".join(live["warnings"])
    printed = capsys.readouterr().out
    assert "From ESPN summaries: 1" in printed
    assert "Still null: 0" in printed


def test_refresh_leaves_null_when_espn_has_no_crowd(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    refresh_season(
        year=2026,
        force=True,
        min_interval_hours=18,
        client=SplitClient(),
        get_json=_espn_getter(None),
        sleep=lambda _seconds: None,
    )
    live = json.loads((tmp_path / "live" / "2026.json").read_text(encoding="utf-8"))
    missing = next(game for game in live["games"] if game["id"] == 2)
    assert missing["attendance"] is None
    assert "attendance_source" not in missing
    assert all(game["attendance"] != 0 for game in live["games"])


def test_refresh_keeps_an_espn_zero_instead_of_inventing_a_crowd(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    refresh_season(
        year=2026,
        force=True,
        min_interval_hours=18,
        client=SplitClient(),
        get_json=_espn_getter(0),
        sleep=lambda _seconds: None,
    )
    live = json.loads((tmp_path / "live" / "2026.json").read_text(encoding="utf-8"))
    reported = next(game for game in live["games"] if game["id"] == 2)
    assert reported["attendance"] == 0
    assert reported["attendance_source"] == ESPN_SOURCE
    assert next(game for game in live["games"] if game["id"] == 1)["attendance"] == 88000


def test_refresh_restores_a_prior_espn_crowd_when_the_scoreboard_is_down(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    refresh_season(
        year=2026,
        force=True,
        min_interval_hours=18,
        client=SplitClient(),
        get_json=_espn_getter(45123),
        sleep=lambda _seconds: None,
    )

    from attendee_tracker.refresh_current import EspnUnavailable

    def unavailable(_url):
        raise EspnUnavailable("ESPN down")

    refresh_season(
        year=2026,
        force=True,
        min_interval_hours=18,
        client=SplitClient(),
        get_json=unavailable,
        sleep=lambda _seconds: None,
    )
    live = json.loads((tmp_path / "live" / "2026.json").read_text(encoding="utf-8"))
    restored = next(game for game in live["games"] if game["id"] == 2)
    assert restored["attendance"] == 45123
    assert restored["attendance_source"] == ESPN_SOURCE
    assert "Restored 1 previously recorded" in " ".join(live["warnings"])
    assert all(game["attendance"] != 0 for game in live["games"])


def test_apply_does_not_copy_a_neutral_espn_crowd_onto_a_home_game():
    snapshot = {
        "warnings": [],
        "games": [
            {
                "id": 2,
                "completed": True,
                "neutral_site": False,
                "attendance": None,
                "home_id": 10,
                "away_id": 12,
                "start_date": "2026-09-02T16:00:00.000Z",
            }
        ],
    }
    events = [
        {
            "espn_id": "1",
            "home_id": 10,
            "away_id": 12,
            "date": "2026-09-02T16:00Z",
            "completed": True,
            "neutral_site": True,
            "summary_ok": True,
            "attendance": 99999,
        }
    ]
    apply_attendance_sources(snapshot, events, prior={})
    assert snapshot["games"][0]["attendance"] is None
    assert "attendance_source" not in snapshot["games"][0]


def test_missing_key_exits_without_writing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    monkeypatch.setattr("attendee_tracker.refresh_current.load_dotenv", lambda: None)
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2
    error = capsys.readouterr().err
    assert "CFBD_API_KEY" in error
    assert "will not invent" in error
    assert not (tmp_path / "live").exists()


def test_2020_stays_omitted_and_2026_cache_has_real_attendance():
    assert attendance_year_omitted(2020) == COVID_OMISSION
    assert attendance_year_omitted(2026) is None
    assert Path("data/live/2020.json").is_file()

    raw = json.loads(Path("data/live/2026.json").read_text(encoding="utf-8"))
    assert raw["season"] == 2026
    assert raw["source"] == "cfbd"
    assert raw["synthetic"] is False
    completed = [game for game in raw["games"] if game["completed"] and not game["neutral_site"]]
    assert len(completed) == 254
    assert all(isinstance(game["attendance"], int) and game["attendance"] >= 0 for game in completed)
    assert sum(game["attendance"] == 0 for game in completed) == 4
    assert all(game["attendance_source"] == ESPN_SOURCE for game in completed)
    others = [game for game in raw["games"] if not (game["completed"] and not game["neutral_site"])]
    assert others
    assert all(game["attendance"] is None for game in others)
    alabama = next(
        game
        for game in completed
        if game["home_team"] == "Alabama" and game["away_team"] == "East Carolina"
    )
    assert alabama["attendance"] == 100077

    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["season"] == 2026
    assert health.json()["has_live_cache"] is True

    body = client.get("/api/season").json()
    assert body["meta"]["season"] == 2026
    assert body["meta"]["synthetic"] is False
    assert body["meta"]["source"] == "cfbd"
    schools = {row["school"]: row for row in body["schools"]}
    assert len(schools) == 138
    with_crowd = [row for row in schools.values() if row["avg_home_attendance"] is not None]
    assert len(with_crowd) == 137
    assert schools["Western Kentucky"]["avg_home_attendance"] is None
    assert schools["Western Kentucky"]["reported_home_games"] == 0
    assert schools["UL Monroe"]["avg_home_attendance"] == 0
    tide = schools["Alabama"]
    assert tide["avg_home_attendance"] == 100077
    reported = [game for game in tide["home_games"] if game["attendance_status"] == "reported"]
    assert reported
    assert all(game["attendance_source"] == ESPN_SOURCE for game in reported)
    percents = [point["avg_capacity_pct"] * 100 for point in body["analysis"]["points"]]
    assert percents
    assert min(percents) > 20
    assert max(percents) > 100
    assert max(percents) < 110

    covid = client.get("/api/season?year=2020").json()
    assert covid["meta"]["attendance_omitted"] == COVID_OMISSION
    assert covid["meta"]["season"] == 2020
