import json

from fastapi.testclient import TestClient

from attendee_tracker.app import app
from attendee_tracker.sample_data import build_sample_raw


def test_health_and_sample_season_when_live_cache_is_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["has_live_cache"] is False
    assert health.json()["season"] == 2026

    response = client.get("/api/season")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["synthetic"] is True
    assert "SAMPLE / DEMO DATA ONLY" in body["meta"]["notice"]
    assert body["meta"]["banner"]
    dumped = json.dumps(body)
    assert "ticket" not in dumped.casefold()
    assert '"attendance": 0' not in dumped


def test_other_year_is_not_filled_with_the_sample(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    response = client.get("/api/season?year=2025")
    assert response.status_code == 404
    assert "not fabricated" in response.json()["message"]


def test_live_cache_wins_until_demo_is_requested(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    raw = build_sample_raw()
    raw["source"] = "cfbd"
    raw["synthetic"] = False
    raw["notice"] = None
    raw["warnings"] = []
    live = tmp_path / "live"
    live.mkdir()
    (live / "2026.json").write_text(json.dumps(raw), encoding="utf-8")

    client = TestClient(app)
    live_body = client.get("/api/season").json()
    assert live_body["meta"]["source"] == "cfbd"
    assert live_body["meta"]["synthetic"] is False
    assert live_body["meta"]["banner"] is None

    demo = client.get("/api/season?demo=1").json()
    assert demo["meta"]["synthetic"] is True
    assert demo["meta"]["banner"]


def test_season_cards_include_last_home_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    school = next(row for row in client.get("/api/season").json()["schools"] if row["school"] == "Quarry")
    assert school["avg_home_attendance"] is None
    assert school["last_home_attendance"] is None
    assert school["last_home_attendance_status"] == "not_reported"
    assert school["last_home_opponent"]
    iron = next(row for row in client.get("/api/season").json()["schools"] if row["school"] == "Iron Range")
    assert iron["last_home_attendance_status"] == "reported"
    assert iron["last_home_attendance"] > 0


def test_school_history_degrades_when_only_the_sample_year_is_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    response = client.get("/api/school/iron-range?from=2022&to=2026")
    assert response.status_code == 200
    body = response.json()
    assert body["missing_years"] == [2022, 2023, 2024, 2025]
    assert body["years_present"] == [2026]
    assert body["sample_years"] == [2026]
    season = body["school"]["seasons"][0]
    assert season["year"] == 2026
    assert season["avg_home_attendance"] is not None
    assert any(game["attendance"] is None for game in season["home_games"])
    assert '"attendance": 0' not in response.text

    missing = client.get("/api/history?from=2010&to=2012")
    assert missing.status_code == 404
    assert "not fabricated" in missing.json()["message"]

    bad = client.get("/api/school/iron-range?from=2026&to=2020")
    assert bad.status_code == 400
    unknown = client.get("/api/school/not-a-school?from=2026&to=2026")
    assert unknown.status_code == 404


def test_history_reads_each_live_year_without_inventing_the_gap(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    live = tmp_path / "live"
    live.mkdir()
    for year, conference, attendance in ((2021, "Big 12", 41000), (2025, "SEC", None)):
        raw = build_sample_raw()
        raw["source"] = "cfbd"
        raw["synthetic"] = False
        raw["notice"] = None
        raw["season"] = year
        for team in raw["teams"]:
            if team["school"] == "Iron Range":
                team["conference"] = conference
        for game in raw["games"]:
            game["season"] = year
            if game["home_team"] == "Iron Range" and game["attendance"] is not None and attendance is not None:
                game["attendance"] = attendance
            if year == 2025 and game["home_team"] == "Iron Range":
                game["attendance"] = None
        (live / f"{year}.json").write_text(json.dumps(raw), encoding="utf-8")

    client = TestClient(app)
    response = client.get("/api/school/iron-range?from=2021&to=2025")
    assert response.status_code == 200
    body = response.json()
    assert body["missing_years"] == [2022, 2023, 2024]
    assert body["years_present"] == [2021, 2025]
    seasons = {row["year"]: row for row in body["school"]["seasons"]}
    assert seasons[2021]["conference"] == "Big 12"
    assert seasons[2021]["avg_home_attendance"] == 41000
    assert seasons[2025]["conference"] == "SEC"
    assert seasons[2025]["avg_home_attendance"] is None
    assert seasons[2025]["last_home_attendance"] is None
    assert all(game["attendance"] is None for game in seasons[2025]["home_games"])
    assert '"attendance": 0' not in response.text

    listing = client.get("/api/history?from=2021&to=2025").json()
    listed = next(row for row in listing["schools"] if row["slug"] == "iron-range")
    assert "home_games" not in listed["seasons"][0]
    assert listed["seasons"][0]["avg_home_attendance"] == 41000


def test_2020_stays_in_the_cache_and_is_left_out_of_averages(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    live = tmp_path / "live"
    live.mkdir()
    raw = build_sample_raw()
    raw["source"] = "cfbd"
    raw["synthetic"] = False
    raw["notice"] = None
    raw["season"] = 2020
    for game in raw["games"]:
        game["season"] = 2020
        if game["home_team"] == "Iron Range" and game["attendance"] is not None:
            game["attendance"] = 12345
    path = live / "2020.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    client = TestClient(app)
    season = client.get("/api/season?year=2020")
    assert season.status_code == 200
    body = season.json()
    assert body["meta"]["attendance_omitted"] == "covid"
    iron = next(school for school in body["schools"] if school["school"] == "Iron Range")
    assert iron["avg_home_attendance"] is None
    assert iron["avg_capacity_pct"] is None
    assert iron["attendance_omitted"] == "covid"
    assert any(game["attendance"] == 12345 for game in iron["home_games"])
    assert "COVID" in json.dumps(body["analysis"]["methodology"])
    reasons = next(row["reasons"] for row in body["analysis"]["omitted"] if row["school"] == "Iron Range")
    assert reasons == ["2020 is omitted as the COVID season"]
    assert body["analysis"]["loyalty"]["most_loyal"] == []
    assert body["analysis"]["n_teams"] == 0

    history = client.get("/api/school/iron-range?from=2020&to=2020").json()
    row = history["school"]["seasons"][0]
    assert row["year"] == 2020
    assert row["avg_home_attendance"] is None
    assert row["attendance_omitted"] == "covid"
    assert row["last_home_attendance"] is None
    assert row["home_games"] == []
    assert history["omitted_years"] == [2020]
    assert "2020 is omitted as the COVID season" in history["attendance_note"]

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["season"] == 2020
    assert any(game["attendance"] == 12345 for game in on_disk["games"])


def test_analysis_lists_rank_capacity_fill_for_below_median_records(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    analysis = client.get("/api/season").json()["analysis"]
    loyalty = analysis["loyalty"]
    assert loyalty["n_qualifying"] == analysis["n_teams"]
    assert loyalty["win_pct_median"] is not None
    assert 1 <= len(loyalty["most_loyal"]) <= 10
    assert 1 <= len(loyalty["softest_support"]) <= 10
    loyal_fills = [row["avg_capacity_pct"] for row in loyalty["most_loyal"]]
    soft_fills = [row["avg_capacity_pct"] for row in loyalty["softest_support"]]
    assert loyal_fills == sorted(loyal_fills, reverse=True)
    assert soft_fills == sorted(soft_fills)
    listed = loyalty["most_loyal"] + loyalty["softest_support"]
    assert all(row["win_pct"] <= loyalty["win_pct_median"] for row in listed)
    assert all(row["avg_capacity_pct"] is not None for row in listed)
    names = {row["school"] for row in listed}
    assert "Quarry" not in names
    assert "Rimrock" not in names
    assert "North Glass" not in names
    assert loyalty["most_loyal"][0]["school"] == "Redwood"
    assert loyalty["softest_support"][0]["school"] == "Canal"
    assert "logo" in loyalty["most_loyal"][0]
    assert loyalty["most_loyal"][0]["reported_home_games"] >= 2


def test_index_html():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Attendee Tracker" in response.text
    assert "/assets/app.js" in response.text
