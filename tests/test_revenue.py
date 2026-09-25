"""EADA football revenue endpoint. Figures are the committed file, not estimates."""

import hashlib
import json

from fastapi.testclient import TestClient

from attendee_tracker.app import app
from attendee_tracker.revenue import REVENUE_PATH

FINGERPRINT = "292b88ad45322b829e0fbe6be5bff7261ec084d8f0aa3e1f514987f3fb9bb9fb"


def _client():
    return TestClient(app)


def test_revenue_file_matches_the_published_fingerprint():
    digest = hashlib.sha256(REVENUE_PATH.read_bytes()).hexdigest()
    assert digest == FINGERPRINT
    payload = json.loads(REVENUE_PATH.read_text(encoding="utf-8"))
    assert payload["years"] == list(range(2013, 2025))
    assert payload["covid_year"] == 2020
    assert len(payload["schools"]) == 135
    power = [row for row in payload["schools"].values() if row["power"]]
    assert len(power) == 68
    for row in power:
        for year in payload["years"]:
            assert row["revenue_usd"][str(year)] is not None


def test_texas_latest_revenue_and_yoy():
    response = _client().get("/api/revenue/texas")
    assert response.status_code == 200
    body = response.json()
    assert body["school"] == "Texas"
    assert body["slug"] == "texas"
    assert body["source"].startswith("U.S. Department of Education")
    latest = body["latest"]
    assert latest["year"] == 2024
    assert latest["revenue_usd"] == 171_892_714
    assert latest["yoy_base_year"] == 2023
    assert latest["yoy_usd"] == -28_843_750
    assert latest["yoy_pct"] == round((-28_843_750 / 200_736_464) * 100, 2)
    assert round(latest["yoy_pct"], 2) == -14.37
    prior = next(row for row in body["years"] if row["year"] == 2023)
    assert prior["revenue_usd"] == 200_736_464
    growth = body["growth_10y"]
    assert growth["from_year"] == 2014
    assert growth["to_year"] == 2024
    assert growth["from_usd"] == 112_508_162
    assert growth["to_usd"] == 171_892_714
    assert growth["delta_usd"] == 171_892_714 - 112_508_162


def test_covid_yoy_skips_2020_and_compares_2021_with_2019():
    body = _client().get("/api/revenue/texas").json()
    y2020 = next(row for row in body["years"] if row["year"] == 2020)
    y2021 = next(row for row in body["years"] if row["year"] == 2021)
    assert y2020["covid"] is True
    assert y2020["revenue_usd"] == 97_223_872
    assert y2020["yoy_usd"] is None
    assert y2020["yoy_pct"] is None
    assert y2020["yoy_base_year"] is None
    assert y2021["yoy_base_year"] == 2019
    assert y2021["yoy_usd"] == 161_532_860 - 156_147_208
    assert y2021["covid"] is False


def test_unknown_school_is_404():
    for slug in ("air-force", "not-a-school"):
        response = _client().get(f"/api/revenue/{slug}")
        assert response.status_code == 404
        assert response.json()["error"] == "unknown_school"


def test_auburn_2014_carries_the_footnote():
    raw = json.loads(REVENUE_PATH.read_text(encoding="utf-8"))
    body = _client().get("/api/revenue/auburn").json()
    y2014 = next(row for row in body["years"] if row["year"] == 2014)
    assert y2014["revenue_usd"] == 49_639_256
    assert y2014["footnote"] == raw["footnotes"]["*"]
    assert y2014["footnote"] == raw["schools"]["auburn"]["footnotes"]["2014"]
    assert "113,322,921" in y2014["footnote"]
    others = [row for row in body["years"] if row["year"] != 2014]
    assert all(row["footnote"] is None for row in others)


def test_missing_years_stay_null():
    international = _client().get("/api/revenue/florida-international").json()
    assert international["latest"]["year"] == 2023
    assert international["latest"]["revenue_usd"] == 11_012_712
    missing_2024 = next(row for row in international["years"] if row["year"] == 2024)
    assert missing_2024["revenue_usd"] is None
    assert missing_2024["yoy_usd"] is None
    assert international["growth_10y"]["to_year"] == 2023
    assert international["growth_10y"]["from_year"] == 2014

    uab = _client().get("/api/revenue/uab").json()
    for year in range(2013, 2019):
        row = next(item for item in uab["years"] if item["year"] == year)
        assert row["revenue_usd"] is None
    assert uab["latest"]["year"] == 2024
    assert uab["latest"]["revenue_usd"] == 14_442_335
    y2019 = next(row for row in uab["years"] if row["year"] == 2019)
    assert y2019["revenue_usd"] == 11_921_225
    assert y2019["yoy_usd"] is None
    assert uab["growth_10y"] is None
