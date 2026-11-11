"""CFP publication rules, the 12-team bracket, and sourced bowl figures."""

from datetime import date

from fastapi.testclient import TestClient

from attendee_tracker.app import app
from attendee_tracker.assemble import assemble
from attendee_tracker.bowls import business_numbers_without_sources, public_bowls
from attendee_tracker.bracket import SITE_CHOICE, project_bracket
from attendee_tracker.cfp import cfp_is_available, first_release_date, public_poll, snapshot_from_cfbd_weeks
from attendee_tracker.store import load_live


def _team(rank, school, conference, record="10-0"):
    return {
        "rank": rank,
        "school": school,
        "conference": conference,
        "record": record,
        "team_id": rank,
    }


def _field():
    """Power champ and Group of 6 leader both sit outside the top 12. No other ACC team is ranked."""
    return [
        _team(1, "Alpha", "SEC"),
        _team(2, "Beta", "Big Ten"),
        _team(3, "Gamma", "Big 12"),
        _team(4, "At Large One", "SEC"),
        _team(5, "Notre Dame", "FBS Independents"),
        _team(6, "At Large Two", "Big Ten"),
        _team(7, "At Large Three", "Big 12"),
        _team(8, "At Large Four", "SEC"),
        _team(9, "At Large Five", "Big Ten"),
        _team(10, "At Large Six", "SEC"),
        _team(11, "First Out", "Big 12"),
        _team(12, "Second Out", "Big Ten"),
        _team(13, "Third Out", "SEC"),
        _team(14, "Fourth Out", "Big 12"),
        _team(16, "Delta", "ACC"),
        _team(20, "Group Leader", "Sun Belt"),
    ]


def test_first_release_is_the_first_tuesday_in_november():
    assert first_release_date(2026) == date(2026, 11, 3)
    assert first_release_date(2025) == date(2025, 11, 4)


def test_cfp_before_the_first_release_stays_on_the_ap_poll():
    early = {
        "season": 2026,
        "poll_type": "cfp",
        "released_at": "2026-10-20T08:00:00Z",
        "teams": [{"rank": 1, "school": "Georgia"}],
    }
    assert cfp_is_available(early, 2026) is False
    assert public_poll(early, 2026) == "AP"
    ready = dict(early, released_at="2026-11-10T08:00:00Z")
    assert cfp_is_available(ready, 2026) is True
    assert public_poll(ready, 2026) == "CFP"


def test_cfbd_backup_ignores_the_ap_poll():
    weeks = [
        {
            "season": 2026,
            "week": 11,
            "date": "2026-11-10T08:00:00Z",
            "polls": [
                {"poll": "AP Top 25", "ranks": [{"rank": 1, "school": "Wrong", "teamId": 1}]},
                {
                    "poll": "Playoff Committee Rankings",
                    "ranks": [{"rank": 1, "school": "Georgia", "teamId": 61, "conference": "SEC", "record": "8-1"}],
                },
            ],
        }
    ]
    snapshot = snapshot_from_cfbd_weeks(weeks, 2026)
    assert snapshot["teams"][0]["school"] == "Georgia"
    assert snapshot["teams"][0]["team_id"] == 61


def test_notre_dame_in_the_top_12_takes_an_automatic_bid_and_six_at_large_spots():
    bracket = project_bracket(_field(), today=date(2026, 11, 11))
    assert bracket["notre_dame_auto"] is True
    assert bracket["at_large_spots"] == 6
    assert bracket["label"] == "Projected"
    bids = {seed["school"]: seed["bid"] for seed in bracket["seeds"]}
    assert bids["Notre Dame"] == "Notre Dame auto"
    assert "First Out" not in bids
    assert [seed["school"] for seed in bracket["seeds"] if seed["bye"]] == ["Alpha", "Beta", "Gamma", "At Large One"]
    assert bids["At Large One"] == "at-large"


def test_notre_dame_outside_the_top_12_is_not_automatic():
    teams = [team for team in _field() if team["school"] != "Notre Dame"]
    teams.append(_team(18, "Notre Dame", "FBS Independents"))
    bracket = project_bracket(teams, today=date(2026, 11, 11))
    assert bracket["notre_dame_auto"] is False
    assert bracket["at_large_spots"] == 7
    bids = {seed["school"]: seed["bid"] for seed in bracket["seeds"]}
    assert "Notre Dame" not in bids


def test_group_of_six_team_outside_the_top_12_is_seeded_at_the_bottom():
    bracket = project_bracket(_field(), today=date(2026, 11, 11))
    by_seed = {seed["seed"]: seed for seed in bracket["seeds"]}
    assert by_seed[11]["school"] == "Delta"
    assert by_seed[11]["bid"] == "ACC auto"
    assert by_seed[12]["school"] == "Group Leader"
    assert by_seed[12]["bid"] == "Group of 6 auto"
    assert by_seed[12]["rank"] == 20
    assert by_seed[12]["bye"] is False
    pairs = [(game["higher_seed"], game["lower_seed"]) for game in bracket["first_round"]]
    assert pairs == [(5, 12), (6, 11), (7, 10), (8, 9)]
    quarterfinals = [(game["bye_seed"], tuple(game["first_round_seeds"])) for game in bracket["quarterfinals"]]
    assert quarterfinals == [(1, (8, 9)), (4, (5, 12)), (2, (7, 10)), (3, (6, 11))]
    assert all(game["site"] == SITE_CHOICE for game in bracket["quarterfinals"])
    assert all(game["site"] == SITE_CHOICE for game in bracket["semifinals"])


def test_live_season_publishes_cfp_and_keeps_ap_on_the_school():
    raw = load_live(2026)
    view = assemble(raw)
    assert view["meta"]["public_poll"] == "CFP"
    ranked = [school for school in view["schools"] if school.get("cfp_rank") == 1]
    assert ranked
    assert ranked[0]["public_rank"] == 1
    assert ranked[0]["public_poll"] == "CFP"
    assert "ap_rank" in ranked[0]
    prior = assemble(load_live(2025))
    assert prior["meta"]["public_poll"] == "CFP"
    assert prior["meta"]["rank_note"] is None


def test_bowl_business_numbers_have_source_urls_and_the_nav_order():
    payload = public_bowls(2026, today=date(2026, 11, 11))
    assert business_numbers_without_sources({"games": payload["games"]}) == []
    assert payload["label"] == "Projected"
    assert payload["bracket"]["quarterfinals"][0]["site"] == SITE_CHOICE
    broken = {
        "games": [
            {"business": {"payout": {"per_team": 1000000, "source_urls": []}}},
        ]
    }
    assert business_numbers_without_sources(broken)
    html = TestClient(app).get("/").text
    nav = html.split("<nav", 1)[1].split("</nav>", 1)[0]
    assert nav.index(">Marketing Approaches<") < nav.index(">Bowl Games<")
    assert 'href="#/bowls"' in nav
