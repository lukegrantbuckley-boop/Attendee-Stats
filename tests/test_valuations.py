import json
from pathlib import Path

from fastapi.testclient import TestClient

from attendee_tracker.app import app
from attendee_tracker.valuations import VALUATIONS_PATH, list_valuations

ROOT = Path(__file__).resolve().parent.parent
LIVE_2026 = ROOT / "data" / "live" / "2026.json"

VALUE_FIELDS = (
    "school",
    "conference",
    "valuation_usd",
    "valuation_rank",
    "prior_valuation_usd",
    "prior_valuation_rank",
    "rank_change_spots",
    "nil_budget_usd",
    "nil_is_estimate",
)


def _client():
    return TestClient(app)


def _fingerprint(rows):
    return {
        tuple(row.get(field) for field in VALUE_FIELDS)
        for row in rows
    }


def test_default_sort_is_valuation_and_values_match_the_file():
    committed = json.loads(VALUATIONS_PATH.read_text(encoding="utf-8"))
    before = VALUATIONS_PATH.read_bytes()
    response = _client().get("/api/valuations")
    assert response.status_code == 200
    body = response.json()
    assert body["sort"] == "valuation"
    assert body["count"] == 68
    schools = body["schools"]
    assert len(schools) == 68
    assert _fingerprint(schools) == _fingerprint(committed["schools"])
    assert [row["valuation_rank"] for row in schools] == sorted(row["valuation_rank"] for row in schools)
    assert schools[0]["school"] == "Texas"
    assert schools[0]["valuation_usd"] == 2_460_000_000
    assert schools[0]["valuation_rank"] == 1
    assert schools[0]["prior_valuation_rank"] == 1
    assert schools[0]["rank_change_spots"] == 0
    assert schools[0]["nil_budget_usd"] == 46_485_000
    assert schools[0]["nil_is_estimate"] is True
    assert schools[-1]["school"] == "Houston"
    assert schools[-1]["valuation_usd"] == 100_000_000
    tied = [row["school"] for row in schools if row["valuation_rank"] == 7]
    assert tied == ["Oklahoma", "USC"]
    indiana = next(row for row in schools if row["school"] == "Indiana")
    georgia = next(row for row in schools if row["school"] == "Georgia")
    assert indiana["rank_change_spots"] == 16
    assert georgia["rank_change_spots"] == -3
    for row in schools:
        assert row["prior_valuation_rank"] - row["valuation_rank"] == row["rank_change_spots"]
        assert row["nil_is_estimate"] is True
    assert "in_season_estimate" not in response.text
    assert VALUATIONS_PATH.read_bytes() == before


def test_nil_sort_orders_by_budget_without_changing_dollars():
    committed = json.loads(VALUATIONS_PATH.read_text(encoding="utf-8"))
    explicit = _client().get("/api/valuations?sort=valuation").json()
    response = _client().get("/api/valuations?sort=NIL")
    assert response.status_code == 200
    body = response.json()
    assert body["sort"] == "nil"
    schools = body["schools"]
    budgets = [row["nil_budget_usd"] for row in schools]
    assert budgets == sorted(budgets, reverse=True)
    assert [row["school"] for row in schools[:3]] == ["Texas", "Oregon", "LSU"]
    assert schools[-1]["school"] == "Boston College"
    assert schools[-1]["nil_budget_usd"] == 18_797_000
    assert _fingerprint(schools) == _fingerprint(committed["schools"])
    assert _fingerprint(explicit["schools"]) == _fingerprint(schools)
    assert [row["school"] for row in explicit["schools"]] != [row["school"] for row in schools]


def test_bad_sort_is_rejected():
    response = _client().get("/api/valuations?sort=made-up")
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "bad_sort"
    assert "valuation" in body["message"]


def test_sources_are_the_published_pages():
    body = _client().get("/api/valuations").json()
    assert body["sources"]["valuation"]["url"] == (
        "https://www.nytimes.com/athletic/7467869/2026/07/28/"
        "college-football-program-valuations-rankings-2026-texas-notre-dame-osu/"
    )
    assert body["sources"]["valuation"]["date"] == "2026-07-28"
    assert body["sources"]["prior_valuation"]["url"] == (
        "https://www.nytimes.com/athletic/6500596/2025/07/21/"
        "college-football-program-valuations-rankings-2025/"
    )
    assert body["sources"]["nil"]["url"] == "https://nil-ncaa.com/football/"
    assert body["sources"]["nil"]["methodology_url"] == "https://nil-ncaa.com/methodology/"
    assert body["sources"]["nil"]["year"] == "2026-27"
    conferences = {}
    for row in body["schools"]:
        conferences[row["conference"]] = conferences.get(row["conference"], 0) + 1
    assert conferences == {
        "SEC": 16,
        "Big Ten": 18,
        "Big 12": 16,
        "ACC": 17,
        "Independent": 1,
    }


def test_every_school_matches_a_2026_logo():
    live = json.loads(LIVE_2026.read_text(encoding="utf-8"))
    teams = {team["school"]: team for team in live["teams"]}
    missing = []
    for row in _client().get("/api/valuations").json()["schools"]:
        team = teams.get(row["school"])
        if team is None or not team.get("logo"):
            missing.append(row["school"])
    assert missing == []


def test_committed_file_is_used_without_a_key_or_live_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    response = _client().get("/api/valuations")
    assert response.status_code == 200
    assert response.json()["schools"][0]["school"] == "Texas"
    assert response.json()["count"] == 68


def test_missing_file_does_not_invent_values(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "attendee_tracker.valuations.VALUATIONS_PATH",
        tmp_path / "missing.json",
    )
    response = _client().get("/api/valuations")
    assert response.status_code == 404
    assert response.json()["error"] == "no_valuations"
    assert "not fabricated" in response.json()["message"]


def test_sort_tie_break_and_missing_money_stay_blank(tmp_path):
    path = tmp_path / "valuations.json"
    path.write_text(
        json.dumps(
            {
                "schools": [
                    {
                        "school": "Beta",
                        "conference": "SEC",
                        "valuation_usd": 500_000_000,
                        "valuation_rank": 2,
                        "nil_budget_usd": 20_000_000,
                        "rank_change_spots": 0,
                    },
                    {
                        "school": "Alpha",
                        "conference": "SEC",
                        "valuation_usd": 500_000_000,
                        "valuation_rank": 2,
                        "nil_budget_usd": 20_000_000,
                        "rank_change_spots": 1,
                    },
                    {
                        "school": "Gamma",
                        "conference": "ACC",
                        "valuation_usd": 900_000_000,
                        "valuation_rank": 1,
                        "nil_budget_usd": None,
                    },
                    {
                        "school": "Delta",
                        "conference": "Big 12",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    by_value = list_valuations("valuation", path)
    assert [row["school"] for row in by_value["schools"]] == ["Gamma", "Alpha", "Beta", "Delta"]
    assert by_value["schools"][-1].get("valuation_usd") is None
    by_nil = list_valuations("nil", path)
    assert [row["school"] for row in by_nil["schools"]] == ["Alpha", "Beta", "Delta", "Gamma"]
    assert by_nil["schools"][2].get("nil_budget_usd") is None
    assert by_nil["schools"][3]["nil_budget_usd"] is None


def test_index_has_the_valuations_tab():
    html = _client().get("/").text
    assert 'href="#/valuations"' in html
    assert ">Valuations<" in html
    assert 'href="#/"' in html
    assert 'href="#/analysis"' in html
