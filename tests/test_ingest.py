import json

import pytest

from attendee_tracker.cfbd_client import CfbdError
from attendee_tracker.ingest import main, resolve_years, run_ingest, run_ingest_years


class FakeClient:
    def fetch_games(self, year):
        return [
            {
                "id": 1,
                "season": year,
                "week": 1,
                "seasonType": "regular",
                "startDate": "2026-09-05T23:30:00Z",
                "completed": True,
                "neutralSite": False,
                "attendance": None,
                "venueId": 5,
                "venue": "Demo Stadium",
                "homeId": 10,
                "homeTeam": "Demo State",
                "homeConference": "SEC",
                "homePoints": 21,
                "awayId": 11,
                "awayTeam": "Other",
                "awayPoints": 14,
            }
        ]

    def fetch_records(self, year):
        return [
            {
                "year": year,
                "teamId": 10,
                "team": "Demo State",
                "conference": "SEC",
                "total": {"games": 1, "wins": 1, "losses": 0, "ties": 0},
            }
        ]

    def fetch_rankings(self, year):
        return [
            {
                "season": year,
                "seasonType": "regular",
                "week": 1,
                "polls": [
                    {"poll": "Coaches Poll", "ranks": [{"rank": 1, "school": "Elsewhere", "teamId": 3}]},
                    {"poll": "AP Top 25", "ranks": [{"rank": 8, "school": "Demo State", "teamId": 10}]},
                ],
            }
        ]

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
                "location": {
                    "id": 5,
                    "name": "Demo Stadium",
                    "city": "Town",
                    "state": "AL",
                    "capacity": 55000,
                },
            }
        ]

    def fetch_venues(self):
        return [{"id": 5, "name": "Demo Stadium", "city": "Town", "state": "AL", "capacity": 55000}]


class ExplodingClient:
    def fetch_games(self, year):
        raise AssertionError("games should not be fetched")

    def fetch_records(self, year):
        raise AssertionError("records should not be fetched")

    def fetch_rankings(self, year):
        raise AssertionError("rankings should not be fetched")

    def fetch_teams(self, year):
        raise AssertionError("teams should not be fetched")

    def fetch_venues(self):
        raise AssertionError("venues should not be fetched")


def test_missing_key_exits_without_writing_attendance(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    monkeypatch.setattr("attendee_tracker.ingest.load_dotenv", lambda: None)
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2
    error = capsys.readouterr().err
    assert "CFBD_API_KEY" in error
    assert "will not invent" in error
    assert not (tmp_path / "live").exists()


def test_ingest_keeps_null_attendance_and_skips_a_fresh_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    calls = run_ingest(year=2026, force=True, min_interval_hours=18, client=FakeClient())
    assert calls == 5
    live = json.loads((tmp_path / "live" / "2026.json").read_text(encoding="utf-8"))
    assert live["source"] == "cfbd"
    assert live["synthetic"] is False
    assert live["games"][0]["attendance"] is None
    assert live["teams"][0]["capacity"] == 55000
    assert live["rankings"][0]["poll"] == "AP Top 25"
    assert live["rankings"][0]["ranks"][0]["rank"] == 8

    assert run_ingest(year=2026, force=False, min_interval_hours=18, client=ExplodingClient()) == 0


class CountingClient(FakeClient):
    def __init__(self):
        self.venue_calls = 0
        self.game_years = []

    def fetch_venues(self):
        self.venue_calls += 1
        return super().fetch_venues()

    def fetch_games(self, year):
        self.game_years.append(year)
        return super().fetch_games(year)


def test_year_helpers_cover_a_range_and_repeated_years():
    assert resolve_years(None, None, 2026) == [2026]
    assert resolve_years([2024, 2022, 2024], None, 2026) == [2022, 2024]
    assert resolve_years(None, "2016-2025", 2026) == list(range(2016, 2026))
    assert resolve_years([2016], "2018-2019", 2026) == [2016, 2018, 2019]
    with pytest.raises(SystemExit):
        resolve_years(None, "2025-2016", 2026)
    with pytest.raises(SystemExit):
        resolve_years(None, "not-a-range", 2026)
    with pytest.raises(SystemExit):
        resolve_years(None, "1990-2026", 2026)


def test_year_range_reuses_venues_and_keeps_null_attendance(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    client = CountingClient()
    calls = run_ingest_years(years=[2024, 2025], force=True, min_interval_hours=18, client=client)
    assert calls == 9  # games, records, rankings, teams for each year, venues once
    assert client.venue_calls == 1
    assert client.game_years == [2024, 2025]
    for year in (2024, 2025):
        live = json.loads((tmp_path / "live" / f"{year}.json").read_text(encoding="utf-8"))
        assert live["season"] == year
        assert live["synthetic"] is False
        assert live["games"][0]["attendance"] is None
        assert live["venues"][0]["capacity"] == 55000

    quiet = CountingClient()
    assert run_ingest_years(years=[2024, 2025], force=False, min_interval_hours=18, client=quiet) == 0
    assert quiet.game_years == []
    assert quiet.venue_calls == 0


def test_a_failed_year_in_a_range_leaves_the_other_snapshots(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    live = tmp_path / "live"
    live.mkdir()
    (live / "2025.json").write_text('{"keep": true}\n', encoding="utf-8")

    class Boom(FakeClient):
        def fetch_games(self, year):
            if year == 2025:
                raise CfbdError("CFBD unavailable", status=503)
            return super().fetch_games(year)

    with pytest.raises(CfbdError):
        run_ingest_years(years=[2024, 2025], force=True, min_interval_hours=18, client=Boom())

    written = json.loads((live / "2024.json").read_text(encoding="utf-8"))
    assert written["games"][0]["attendance"] is None
    assert json.loads((live / "2025.json").read_text(encoding="utf-8")) == {"keep": True}


def test_main_passes_a_shared_venue_cache_for_a_range(monkeypatch):
    monkeypatch.setenv("CFBD_API_KEY", "test-key")
    monkeypatch.delenv("SEASON_YEAR", raising=False)
    monkeypatch.setattr("attendee_tracker.ingest.load_dotenv", lambda: None)
    seen = []

    def fake_run(**kwargs):
        seen.append(kwargs)
        return 3

    monkeypatch.setattr("attendee_tracker.ingest.run_ingest", fake_run)
    main(["--years", "2022-2024"])
    assert [row["year"] for row in seen] == [2022, 2023, 2024]
    assert all(row["venue_cache"] is seen[0]["venue_cache"] for row in seen)
    assert seen[0]["venue_cache"] is not None

    seen.clear()
    main(["--year", "2019", "--year", "2021"])
    assert [row["year"] for row in seen] == [2019, 2021]

    seen.clear()
    main(["--year", "2020"])
    assert seen[0]["year"] == 2020
    assert seen[0]["venue_cache"] is None


def test_failed_fetch_does_not_create_a_live_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))

    class Down:
        def fetch_games(self, year):
            raise CfbdError("CFBD unavailable", status=503)

    with pytest.raises(CfbdError):
        run_ingest(year=2026, force=True, min_interval_hours=18, client=Down())
    assert not (tmp_path / "live" / "2026.json").exists()
