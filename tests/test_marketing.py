"""Outlier selection for Marketing Approaches, and the two data files."""

import json

import pytest
from fastapi.testclient import TestClient

from attendee_tracker.analysis import RESIDUAL_Z, analyze
from attendee_tracker.app import app
from attendee_tracker.assemble import assemble
from attendee_tracker.marketing import (
    APPROACHES_PATH,
    COMPLETE_SEASON,
    NO_PROMOTION,
    PLACEHOLDER,
    WORKED_PATH,
    groups_from_rows,
    load_promotions,
    load_strategies,
    marketing_report,
    select_marketing_groups,
)
from attendee_tracker.store import load_live

# 2025 is the last complete season. These slugs are the teams that clear
# the documented 1.25 residual-standard-deviation rule on that cache.
APPROACHES_2025 = [
    "memphis",
    "central-michigan",
    "arkansas-state",
    "california",
    "duke",
    "new-mexico",
]
WORKED_2025 = ["app-state", "charlotte"]


def _row(name, win_value, capacity, *, tier="Power 4", pro=False, omitted=None):
    return {
        "slug": name.casefold().replace(" ", "-"),
        "school": name,
        "conference": "Sun Belt" if tier != "Power 4" else "SEC",
        "tier": tier,
        "record": "1-0",
        "win_pct": win_value,
        "decided_games": 2,
        "reported_home_games": 2,
        "avg_home_attendance": capacity * 10000,
        "avg_capacity_pct": capacity,
        "recent_win_pct": win_value,
        "recent_record": "1-0",
        "pregame_points": [],
        "pro_shared_stadium": pro,
        "attendance_omitted": omitted,
    }


def _spread():
    """A line with enough teams that residuals can be labeled.

    Fill rises with win percentage, then a few teams break that pattern.
    """
    rows = []
    for index, win_value in enumerate((0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0)):
        rows.append(_row(f"Fit {index}", win_value, 0.40 + win_value * 0.45))
    rows.append(_row("Soft Winner", 0.85, 0.30))
    rows.append(_row("On The Line", 0.85, 0.78))
    rows.append(_row("Barely Soft", 0.7, 0.62))
    rows.append(_row("Even Steven", 0.5, 0.20, tier="Group of 5"))
    rows.append(_row("G5 Draw", 0.25, 0.98, tier="Group of 5"))
    rows.append(_row("Power Draw", 0.2, 0.99, tier="Power 4"))
    rows.append(_row("Pro Home", 0.9, 0.10, pro=True))
    rows.append(_row("Covid", 0.9, 0.10, omitted="covid"))
    return rows


def test_threshold_matches_the_analysis_scatter():
    assert RESIDUAL_Z == pytest.approx(1.25)
    report = marketing_report(COMPLETE_SEASON)
    assert report["threshold"]["residual_z"] == RESIDUAL_Z
    assert report["threshold"]["winning_win_pct_above"] == 0.5
    assert report["threshold"]["poor_win_pct_at_or_below"] == 0.5
    assert "1.25" in report["threshold"]["summary"]
    assert "2020" in report["threshold"]["summary"]


def test_selects_winning_teams_below_the_line_and_g5_poor_teams_above_it():
    groups = groups_from_rows(_spread())
    approaches = {row["school"]: row for row in groups["approaches"]}
    worked = {row["school"]: row for row in groups["what_has_worked"]}
    assert "Soft Winner" in approaches
    assert approaches["Soft Winner"]["residual_z"] <= -RESIDUAL_Z
    assert approaches["Soft Winner"]["win_pct"] > 0.5
    assert "On The Line" not in approaches
    assert "Barely Soft" not in approaches
    assert "Even Steven" not in approaches
    assert "G5 Draw" in worked
    assert worked["G5 Draw"]["tier"] != "Power 4"
    assert worked["G5 Draw"]["win_pct"] <= 0.5
    assert worked["G5 Draw"]["residual_z"] >= RESIDUAL_Z
    assert "Power Draw" not in worked
    assert "Pro Home" not in approaches
    assert "Pro Home" not in worked
    assert "Covid" not in approaches
    assert "Covid" not in worked
    analysis = analyze(_spread())
    omitted = {row["school"] for row in analysis["omitted"]}
    assert "Pro Home" in omitted
    assert "Covid" in omitted


def test_a_winning_record_is_strictly_above_five_hundred():
    rows = _spread()
    rows.append(_row("Coin Flip", 0.5, 0.15))
    groups = groups_from_rows(rows)
    names = {row["school"] for row in groups["approaches"]}
    assert "Coin Flip" not in names


def test_too_few_teams_labels_nobody():
    rows = [
        _row("Alpha", 1.0, 0.2),
        _row("Beta", 0.0, 0.9, tier="Group of 5"),
        _row("Gamma", 0.5, 0.5),
    ]
    assert select_marketing_groups(analyze(rows)["points"]) == {
        "approaches": [],
        "what_has_worked": [],
    }


def test_2025_complete_season_lists_the_documented_teams():
    view = assemble(load_live(2025))
    assert view["meta"]["season_partial"] is False
    groups = select_marketing_groups(view["analysis"]["points"])
    approaches = groups["approaches"]
    worked = groups["what_has_worked"]
    assert [row["slug"] for row in approaches] == APPROACHES_2025
    assert [row["slug"] for row in worked] == WORKED_2025
    assert all(row["win_pct"] > 0.5 and row["residual_z"] <= -RESIDUAL_Z for row in approaches)
    assert all(row["residual"] < 0 for row in approaches)
    assert all(
        row["tier"] != "Power 4" and row["win_pct"] <= 0.5 and row["residual_z"] >= RESIDUAL_Z
        for row in worked
    )
    slugs = {row["slug"] for row in approaches + worked}
    assert "coastal-carolina" not in slugs
    omitted = {row["slug"] for row in view["analysis"]["omitted"]}
    assert slugs.isdisjoint(omitted)


def test_2025_file_records_match_the_selector_and_strategies_are_blank():
    view = assemble(load_live(2025))
    points = {row["slug"]: row for row in view["analysis"]["points"]}
    strategies = load_strategies(APPROACHES_PATH)
    assert set(APPROACHES_2025).issubset(strategies)
    assert all(isinstance(text, str) and text.strip() == "" for text in strategies.values())
    stored = json.loads(WORKED_PATH.read_text(encoding="utf-8"))
    season_rows = [row for row in stored["schools"] if row["season"] == 2025]
    assert [row["slug"] for row in season_rows] == WORKED_2025
    assert "coastal-carolina" not in {row["slug"] for row in stored["schools"]}
    for row in season_rows:
        point = points[row["slug"]]
        assert row["record"] == point["record"]
        assert row["fill_pct"] == pytest.approx(point["avg_capacity_pct"])
        assert row["win_pct"] == pytest.approx(point["win_pct"])
        assert row["residual"] == pytest.approx(point["residual"])
        assert row["promotions"], row["slug"]
    promotions = load_promotions(WORKED_PATH)
    for slug in WORKED_2025:
        for item in promotions[slug]:
            assert item["summary"]
            assert item["source_url"].startswith("https://")
            assert len(item["date"]) == 10
    coastal = " ".join(
        item["summary"] + item["source_url"] for items in promotions.values() for item in items
    ).casefold()
    assert "goccusports.com" not in coastal


def test_api_returns_placeholder_takes_and_sourced_promotions():
    client = TestClient(app)
    response = client.get("/api/marketing")
    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2025
    assert body["season_partial"] is False
    assert body["placeholder"] == PLACEHOLDER
    assert body["no_promotion"] == NO_PROMOTION
    assert [row["slug"] for row in body["approaches"]] == APPROACHES_2025
    memphis = body["approaches"][0]
    assert memphis["record"] == "8-5"
    assert memphis["fill_pct"] == pytest.approx(0.516)
    assert memphis["residual"] < 0
    assert memphis["strategy"] == ""
    assert memphis["strategy_is_empty"] is True
    worked = {row["slug"]: row for row in body["what_has_worked"]}
    assert set(worked) == set(WORKED_2025)
    assert worked["app-state"]["record"] == "5-8"
    assert worked["app-state"]["fill_pct"] > 1
    assert any("Yosef" in item["summary"] for item in worked["app-state"]["promotions"])
    assert any(item["source_url"].startswith("https://") for item in worked["charlotte"]["promotions"])
    assert all(item["date"] for row in worked.values() for item in row["promotions"])


def test_api_refuses_2020_and_serves_the_in_progress_season():
    client = TestClient(app)
    refused = client.get("/api/marketing?year=2020")
    assert refused.status_code == 400
    assert refused.json()["error"] == "covid_year"
    assert "2020" in refused.json()["message"]
    current = client.get("/api/marketing?year=2026")
    assert current.status_code == 200
    body = current.json()
    assert body["year"] == 2026
    assert body["season_partial"] is True
    assert body["approaches"]
    assert body["what_has_worked"]
    assert all(row["win_pct"] > 0.5 and row["residual_z"] <= -RESIDUAL_Z for row in body["approaches"])
    assert all(
        row["tier"] != "Power 4" and row["win_pct"] <= 0.5 and row["residual_z"] >= RESIDUAL_Z
        for row in body["what_has_worked"]
    )
    for row in body["what_has_worked"]:
        if row["promotions"]:
            assert all(item["source_url"].startswith("https://") and item["date"] for item in row["promotions"])
        else:
            assert row["promotions"] == []


def test_index_puts_marketing_approaches_after_valuations():
    html = TestClient(app).get("/").text
    nav = html.split("<nav", 1)[1].split("</nav>", 1)[0]
    assert nav.index(">Valuations<") < nav.index(">Marketing Approaches<")
    assert 'href="#/marketing"' in nav
    assert 'data-nav="marketing"' in nav
    assert nav.index('href="#/valuations"') < nav.index('href="#/marketing"')
