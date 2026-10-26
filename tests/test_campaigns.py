"""Football campaign files, the school API, and the refresh rules."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from attendee_tracker.app import app
from attendee_tracker.assemble import slugify
from attendee_tracker.campaigns import (
    CAMPAIGN_YEARS,
    append_items,
    classify_campaign,
    compose_item,
    date_in_window,
    empty_message,
    extract_themes,
    parse_since,
    season_for,
    season_window,
    story_from_html,
    validate_year_file,
)
from attendee_tracker.config import ROOT
from attendee_tracker.store import read_json


def _nuxt_page(url_year: int, published: str, title: str, body: str) -> str:
    """A tiny Nuxt payload. The URL year is not the publish date."""
    data = [
        0,
        {
            "contentTitle": 2,
            "title": 2,
            "contentDate": 3,
            "date": 3,
            "content": 4,
            "sportShortname": 5,
            "url": 6,
        },
        title,
        published,
        body,
        "football",
        f"/news/{url_year}/1/1/stale-slug",
    ]
    return f'<script id="__NUXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def test_page_date_wins_over_a_stale_url_year():
    html = _nuxt_page(
        2024,
        "2026-06-02T10:30:00",
        "Themes Announced for 2026 Tiger Home Games",
        "<p>Football home game themes for the 2026 season.</p>",
    )
    story = story_from_html(html, "stale-slug")
    assert story["date"] == "2026-06-02"
    assert "2024" not in story["date"]


def test_a_url_with_no_page_date_is_not_used():
    html = "<html><link rel=\"canonical\" href=\"https://goduke.com/news/2024/8/1/football-themes\"></html>"
    assert story_from_html(html, "football-themes") is None


def test_meta_published_time_is_a_page_date():
    html = """
    <meta property="og:title" content="Football themes announced | School">
    <meta property="article:published_time" content="2026-04-03T11:00:00-04:00">
    <meta property="og:description" content="Football home game themes for 2026.">
    """
    story = story_from_html(html)
    assert story["date"] == "2026-04-03"
    assert story["title"].startswith("Football themes")


def test_json_ld_date_published_is_a_page_date():
    html = """
    <script type="application/ld+json">
    {"headline":"2026 App State Football Home Game Themes Announced","datePublished":"2026-04-03T11:04:00","description":"<p>Football themes for 2026.</p>"}
    </script>
    """
    story = story_from_html(html)
    assert story["date"] == "2026-04-03"
    assert "Themes" in story["title"]


def test_season_window_is_january_through_the_following_january():
    start, end = season_window(2026)
    assert start == date(2026, 1, 1)
    assert end == date(2027, 1, 31)
    assert date_in_window(date(2026, 1, 30), 2026)
    assert date_in_window(date(2026, 6, 2), 2026)
    assert not date_in_window(date(2025, 12, 31), 2026)
    assert not date_in_window(date(2027, 2, 1), 2026)


def test_parse_since_accepts_a_day_count_or_a_date():
    assert parse_since("7d", date(2026, 10, 26)) == date(2026, 10, 19)
    assert parse_since("2025-01-01") == date(2025, 1, 1)
    with pytest.raises(Exception):
        parse_since("last week")


def test_empty_states():
    assert empty_message(2026, None) == "Not yet reviewed"
    assert empty_message(2025, {"checked_at": "2026-10-26", "items": []}) == (
        "No football campaigns found for 2025 (last checked 2026-10-26)"
    )
    assert empty_message(2026, {"checked_at": "2026-10-26", "items": [{"id": "x"}]}) is None


def test_preview_and_facility_news_are_not_campaigns():
    assert classify_campaign("Football hosts Ohio State on Saturday", "A game preview.", "https://example.com/preview", "football") is None
    assert classify_campaign(
        "Kickoff time set for noon on ESPN",
        "Homecoming kickoff time.",
        "https://example.com/news/kickoff",
        "football",
    ) is None
    assert classify_campaign(
        "James Madison Athletics Announces its Full Promotional Schedule for the 2025 Football Season",
        "The promotional schedule lists themed home games.",
        "https://jmusports.com/news/promo",
        "football",
    ) == "theme_night"


def test_compose_item_does_not_copy_the_article_sentence():
    article = (
        "MEMPHIS, Tenn. – The University of Memphis football team has announced its themes "
        "for the program's six home games during the 2026 season, the program announced Tuesday. "
        "Sept. 5 vs. Arkansas State (6 p.m. Kickoff) – 901 Game A salute to the city."
    )
    item = compose_item(
        school="Memphis",
        source_url="https://gotigersgo.com/news/2026/6/2/football-themes-announced-for-2026-tiger-home-games",
        source_name="University of Memphis Athletics",
        source_type="official",
        title="Themes Announced for 2026 Tiger Home Games",
        text=article,
        published="2026-06-02T10:30:00",
        sport="football",
    )
    assert item is not None
    assert item["type"] == "theme_night"
    assert item["announced"] is True
    assert item["date"] == "2026-06-02"
    assert item["season"] == 2026
    assert "The University of Memphis football team has announced its themes" not in item["description"]
    assert item["description"].endswith(".")


def test_append_bumps_checked_at_and_skips_duplicate_sources():
    record = append_items(
        {"checked_at": "2026-10-01", "items": []},
        [
            {
                "id": "abc",
                "title": "2026 football home-game themes",
                "date": "2026-06-02",
                "source_url": "https://gotigersgo.com/news/2026/6/2/football-themes",
            }
        ],
        "2026-10-26",
    )
    again = append_items(
        record,
        [
            {
                "id": "abc",
                "title": "2026 football home-game themes",
                "date": "2026-06-02",
                "source_url": "https://gotigersgo.com/news/2026/6/2/football-themes.aspx",
            }
        ],
        "2026-10-27",
    )
    assert again["checked_at"] == "2026-10-27"
    assert len(again["items"]) == 1


def test_committed_campaign_files_stay_valid_without_a_fixed_count():
    """Reviewed schools are validated. A missing slug has not been reviewed yet."""
    live = read_json(ROOT / "data" / "live" / "2026.json")
    slugs = {slugify(team["school"]) for team in live["teams"]}
    assert slugs
    for year in CAMPAIGN_YEARS:
        payload = json.loads((ROOT / "data" / "campaigns" / f"{year}.json").read_text(encoding="utf-8"))
        problems = validate_year_file(payload, year)
        assert problems == []
        assert set(payload) <= slugs
        assert payload
        for record in payload.values():
            assert isinstance(record["items"], list)


def test_campaign_api_reports_review_state(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    live = tmp_path / "live"
    live.mkdir()
    raw = read_json(ROOT / "data" / "live" / "2026.json")
    # Keep the request small: the endpoint only needs the school to exist.
    (live / "2026.json").write_text(json.dumps(raw), encoding="utf-8")
    campaigns = tmp_path / "campaigns"
    campaigns.mkdir()
    (campaigns / "2026.json").write_text(
        json.dumps(
            {
                "james-madison": {
                    "checked_at": "2026-10-26",
                    "items": [],
                }
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    empty = client.get("/api/campaigns/james-madison?year=2026")
    assert empty.status_code == 200
    assert empty.json()["empty_message"] == "No football campaigns found for 2026 (last checked 2026-10-26)"
    missing = client.get("/api/campaigns/ohio-state?year=2026")
    assert missing.status_code == 200
    assert missing.json()["empty_message"] == "Not yet reviewed"
    refused = client.get("/api/campaigns/james-madison?year=2020")
    assert refused.status_code == 400
    assert refused.json()["error"] == "bad_year"


def test_theme_names_stop_before_the_sentence_that_follows_the_colon():
    text = (
        "Game-By-Game Themes: Sept. 5 vs. Ball State: Honoring Coach Jim Tressel: The day honors a coach. "
        "Sept. 19 vs. Kent State: Helmet Stripe Game: All fans are encouraged to wear helmet stripes. "
        "Sept. 26 vs. Illinois: The weekend of Sept. 26 features alumni events. "
        "Oct. 10 vs. Maryland: This game will serve as the centerpiece of the weekend. "
        "Nov. 28 vs. Michigan: The Rivalry Game."
    )
    themes = extract_themes(text)
    names = [theme for _, theme in themes]
    assert "This game will serve as the centerpiece of" not in names
    assert all("weekend" not in name.casefold() for name in names)
    assert all("will" not in name.casefold().split() for name in names)
    assert "Helmet Stripe Game" in names
    assert "The Rivalry Game" in names


def test_schedule_lines_keep_the_theme_name_and_drop_the_following_sentence():
    text = (
        "Sept. 5 vs. Arkansas State (6 p.m. Kickoff) – 901 Game A salute to everything Memphis. "
        "Sept. 19 vs. UT Martin (6 p.m. Kickoff) – Youth Day & UofM Student Appreciation Calling all youth in Memphis. "
        "Oct. 10 vs. UAB (Kickoff TBA) – Battle for the Bones / BBQ & Blues Celebrate the tradition. "
        "Oct. 22 vs. East Carolina (6:30 p.m. Kickoff) – The DeAngelo Williams Foundation (Breast Cancer Awareness) For the third year."
    )
    themes = dict(extract_themes(text))
    assert themes["Arkansas State"] == "901 Game"
    assert themes["UT Martin"] == "Youth Day & UofM Student Appreciation"
    assert "Celebrate" not in themes["UAB"]
    assert themes["East Carolina"] == "The DeAngelo Williams Foundation"
    assert all("will" not in theme.casefold().split() for theme in themes.values())


def test_marvel_super_hero_day_is_a_theme_and_a_home_game():
    title = "James Madison Football to Host First Ever Collegiate Marvel Super Hero Day"
    text = (
        "James Madison University's football team will host the first ever collegiate Marvel Super Hero Day "
        "on November 22 against Washington State at Bridgeforth Stadium. Fans will be given away a poster."
    )
    assert classify_campaign(title, text, "https://jmusports.com/news/marvel", "football") == "theme_night"
    item = compose_item(
        school="James Madison",
        source_url="https://jmusports.com/news/2025/8/22/james-madison-football-to-host-first-ever-collegiate-marvel-super-hero-day",
        source_name="James Madison University Athletics",
        source_type="official",
        title=title,
        text=text,
        published="2025-08-22T12:00:00",
        sport="football",
    )
    assert item is not None
    assert item["game"]["opponent"] == "Washington State"
    assert item["game"]["home"] is True
    assert item["title"] == "Marvel Super Hero Day"
    assert "Marvel Super Hero Day" in item["description"]


def test_a_senior_day_game_guide_is_not_a_campaign():
    assert classify_campaign(
        "It's Senior Day vs. Air Force",
        "GAME DAY DETAILS Colorado State vs. Air Force Saturday at Canvas Stadium. GAME DAY TIMELINE parking opens.",
        "https://csurams.com/news/2025/11/28/football-its-senior-day-vs-air-force",
        "football",
    ) is None


def test_another_sports_promotion_is_not_a_football_campaign():
    assert classify_campaign(
        "Florida Volleyball Announces 2026 Promotional Schedule",
        "Volleyball promotional schedule. Football is mentioned in the site menu.",
        "https://floridagators.com/news/2026/8/28/florida-volleyball-announces-2026-promotional-schedule",
        "volleyball",
    ) is None


def test_a_result_headline_is_not_a_campaign():
    assert classify_campaign(
        "Rams drop season finale on Senior Day",
        "Football senior day. The Rams drop the finale in front of a home crowd.",
        "https://csurams.com/news/2025/11/28/football-rams-drop-season-finale-on-senior-day",
        "football",
    ) is None


def test_january_overlap_follows_the_season_named_in_the_title():
    assert season_for(date(2026, 1, 30), "2026 football season tickets", "Tickets for 2026.") == 2026
    assert season_for(date(2026, 1, 15), "Bowl week fan event", "A 2025 football promotion.") == 2025
