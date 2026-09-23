import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from attendee_tracker.app import app
from attendee_tracker.business_news import (
    BUSINESS_SITES,
    PUBLISHER_FEEDS,
    build_queries,
    dedupe_items,
    is_business_headline,
    load_business_news,
    matches_school,
    parse_rss,
    safe_slug,
    select_headlines,
)


PUB = "Tue, 16 Sep 2026 15:04:00 GMT"
OLDER = "Mon, 01 Sep 2026 15:04:00 GMT"


def test_queries_include_school_abbreviation_keywords_and_sites():
    queries = build_queries("South Florida", "USF")
    general = queries[0]
    assert '"South Florida"' in general
    assert "USF" in general
    assert "football" in general
    assert "NIL" in general
    assert "revenue share" in general
    assert "athletic director" in general
    assert len(queries) == 1 + len(BUSINESS_SITES)
    for site in BUSINESS_SITES:
        assert any(f"site:{site}" in query and '"South Florida"' in query for query in queries)


def test_abbreviation_already_inside_the_school_name_is_not_repeated():
    queries = build_queries("USC", "USC")
    assert queries[0].startswith('"USC" football')
    assert queries[0].count("USC") == 1


def test_filter_keeps_business_headlines_and_drops_noise():
    school = "Iron Range"
    assert is_business_headline("Iron Range sells a jersey patch", school)
    assert is_business_headline("Iron Range athletic director fired after review", school)
    assert is_business_headline("Iron Range NIL collective announces revenue share", school)
    assert not is_business_headline("How to watch Iron Range football this week", school)
    assert not is_business_headline("Iron Range odds and point spread", school)
    assert not is_business_headline("Iron Range high school prospect commits", school)
    assert not is_business_headline("Buy Iron Range tickets", school)
    assert not is_business_headline("Iron Range beats Canal in a thriller recap", school)
    assert is_business_headline("Iron Range NIL recap of the Saturday game", school)
    assert not is_business_headline("Canal collective signs a sponsorship", school)
    assert is_business_headline("Iron Range ticket revenue climbs", school)
    assert not is_business_headline("Buy Iron Range tickets", school)
    assert not is_business_headline(
        "Kent State travels to Ohio Stadium against Ohio State",
        "Ohio State",
    )
    assert is_business_headline("Ohio State stadium renovation bond", "Ohio State")


def test_ambiguous_names_need_a_second_alias():
    assert not matches_school("Miami NIL collective expands", "Miami", "MIA", "Hurricanes", "Coral Gables")
    assert matches_school("Miami Hurricanes NIL collective expands", "Miami", "MIA", "Hurricanes", "Coral Gables")
    assert matches_school("Miami stadium financing in Coral Gables", "Miami", "MIA", "Hurricanes", "Coral Gables")
    assert not matches_school("Georgia Tech media rights deal", "Georgia", "UGA", "Bulldogs", "Athens")
    assert matches_school("Georgia Bulldogs media rights deal", "Georgia", "UGA", "Bulldogs", "Athens")
    assert not matches_school("Washington State realignment exit fee", "Washington", "UW", "Huskies", "Seattle")
    assert matches_school("Washington Huskies grant of rights", "Washington", "UW", "Huskies", "Seattle")
    assert not matches_school("USC jersey patch talks", "USC", "USC", "Trojans", "Los Angeles")
    assert matches_school("USC Trojans jersey patch talks", "USC", "USC", "Trojans", "Los Angeles")
    assert matches_school("Ohio State revenue share plan", "Ohio State", "OSU", "Buckeyes", "Columbus")
    assert not matches_school("State budget hearing", "Ohio State", "OSU", "Buckeyes", "Columbus")


def test_demoted_game_copy_sorts_after_a_clean_business_headline():
    rows = [
        _item("Iron Range NIL recap of the Saturday game", "2026-09-20", "https://news.google.com/recap"),
        _item("Iron Range media rights deal", "2026-09-01", "https://news.google.com/rights"),
    ]
    selected = select_headlines(rows, "Iron Range")
    assert [item["title"] for item in selected] == [
        "Iron Range media rights deal",
        "Iron Range NIL recap of the Saturday game",
    ]
    assert is_business_headline("Streaming expert on the best ways to watch Ohio State", "Ohio State")
    watch = select_headlines(
        [
            _item("Streaming expert on the best ways to watch Ohio State", "2026-09-20", "https://news.google.com/watch"),
            _item("Ohio State jersey patch sponsor", "2026-07-28", "https://news.google.com/patch"),
        ],
        "Ohio State",
        "OSU",
        "Buckeyes",
        "Columbus",
    )
    assert [item["title"] for item in watch][0] == "Ohio State jersey patch sponsor"


def test_dedupe_collapses_the_same_headline_and_keeps_the_newer_copy():
    items = [
        _item("Iron Range naming rights deal", "2026-09-01", "https://news.google.com/a"),
        _item("Iron Range naming rights deal", "2026-09-16", "https://news.google.com/b"),
        _item("Iron Range NIL collective", "2026-09-10", "https://news.google.com/c"),
    ]
    kept = dedupe_items(items)
    assert [item["url"] for item in kept] == [
        "https://news.google.com/b",
        "https://news.google.com/c",
    ]


def test_select_sorts_by_date_and_caps_the_list():
    rows = [
        _item(f"Iron Range NIL note {index}", f"2026-08-{index:02d}", f"https://news.google.com/{index}")
        for index in range(1, 16)
    ]
    rows.append(_item("Iron Range ticket offer NIL", "2026-09-20", "https://news.google.com/ticket"))
    selected = select_headlines(rows, "Iron Range", limit=10)
    assert len(selected) == 10
    assert selected[0]["title"] == "Iron Range NIL note 15"
    assert all("ticket" not in item["title"].casefold() for item in selected)


def test_parse_rss_reads_publisher_date_and_strips_the_source_suffix():
    xml = _rss([
        (
            "Iron Range coach contract extension - Sportico",
            "Sportico",
            "https://news.google.com/rss/articles/abc",
            PUB,
        )
    ])
    parsed = parse_rss(xml)
    assert parsed == [
        {
            "title": "Iron Range coach contract extension",
            "source": "Sportico",
            "published_at": "2026-09-16",
            "url": "https://news.google.com/rss/articles/abc",
        }
    ]
    assert parse_rss("<not rss") == []


def test_cache_is_reused_inside_twelve_hours_and_refetched_after(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    moment = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("attendee_tracker.business_news.utc_now", lambda: moment)
    calls = {"n": 0}

    def fetch(url, timeout=8):
        calls["n"] += 1
        return _rss([
            ("Iron Range sponsorship deal - Sportico", "Sportico", "https://news.google.com/rss/articles/one", PUB)
        ])

    monkeypatch.setattr("attendee_tracker.business_news.fetch_rss", fetch)
    first = load_business_news("iron-range", "Iron Range", "IR")
    assert first["cached"] is False
    assert first["items"][0]["title"] == "Iron Range sponsorship deal"
    assert calls["n"] == _fetch_count()
    cached_file = tmp_path / "news" / "iron-range.json"
    assert cached_file.is_file()
    assert json.loads(cached_file.read_text())["items"][0]["url"].startswith("https://")

    calls["n"] = 0
    monkeypatch.setattr(
        "attendee_tracker.business_news.utc_now",
        lambda: moment + timedelta(hours=6),
    )
    second = load_business_news("iron-range", "Iron Range", "IR")
    assert calls["n"] == 0
    assert second["cached"] is True
    assert second["items"] == first["items"]

    monkeypatch.setattr(
        "attendee_tracker.business_news.utc_now",
        lambda: moment + timedelta(hours=13),
    )

    def refetch(url, timeout=8):
        calls["n"] += 1
        return _rss([
            ("Iron Range media rights bid - Front Office Sports", "Front Office Sports", "https://news.google.com/rss/articles/two", PUB)
        ])

    monkeypatch.setattr("attendee_tracker.business_news.fetch_rss", refetch)
    third = load_business_news("iron-range", "Iron Range", "IR")
    assert calls["n"] == _fetch_count()
    assert third["cached"] is False
    assert third["items"][0]["title"] == "Iron Range media rights bid"


def test_failed_fetch_returns_stale_cache_or_an_empty_list(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))
    moment = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("attendee_tracker.business_news.utc_now", lambda: moment)

    def fetch(url, timeout=8):
        return _rss([
            ("Iron Range media rights pledge - CollegeAD", "CollegeAD", "https://news.google.com/rss/articles/donor", OLDER)
        ])

    monkeypatch.setattr("attendee_tracker.business_news.fetch_rss", fetch)
    load_business_news("iron-range", "Iron Range", "IR")

    monkeypatch.setattr(
        "attendee_tracker.business_news.utc_now",
        lambda: moment + timedelta(hours=30),
    )

    def fail(url, timeout=8):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr("attendee_tracker.business_news.fetch_rss", fail)
    stale = load_business_news("iron-range", "Iron Range", "IR")
    assert stale["stale"] is True
    assert stale["items"][0]["title"] == "Iron Range media rights pledge"

    empty = load_business_news("canal", "Canal", "CN")
    assert empty["items"] == []
    assert empty["stale"] is False
    assert "could not be loaded" in empty["note"]
    assert not (tmp_path / "news" / "canal.json").exists()


def test_api_returns_filtered_links_and_unknown_schools_404(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))

    def fetch(url, timeout=8):
        return _rss([
            ("Iron Range jersey patch sponsor - Sportico", "Sportico", "https://news.google.com/rss/articles/patch", PUB),
            ("How to watch Iron Range vs Canal - ESPN", "ESPN", "https://news.google.com/rss/articles/watch", PUB),
            ("Iron Range odds before kickoff - Action", "Action Network", "https://news.google.com/rss/articles/odds", PUB),
            ("Iron Range high school camp - MaxPreps", "MaxPreps", "https://news.google.com/rss/articles/hs", PUB),
            ("Iron Range beats Canal - Local", "Local Paper", "https://news.google.com/rss/articles/recap", PUB),
            ("Iron Range jersey patch sponsor - Yahoo", "Yahoo", "https://news.google.com/rss/articles/dup", PUB),
        ])

    monkeypatch.setattr("attendee_tracker.business_news.fetch_rss", fetch)
    client = TestClient(app)
    response = client.get("/api/school/iron-range/business-news")
    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["items"]] == ["Iron Range jersey patch sponsor"]
    assert body["items"][0]["source"] == "Sportico"
    assert body["items"][0]["url"] == "https://news.google.com/rss/articles/patch"
    assert "portfolio app" in body["attribution"]
    assert "not a commercial redistribution license" in body["attribution"]
    assert "attendance" not in body

    missing = client.get("/api/school/not-a-school/business-news")
    assert missing.status_code == 404
    assert "not invented" in missing.json()["message"]

    season = client.get("/api/season")
    assert season.status_code == 200
    iron = next(row for row in season.json()["schools"] if row["slug"] == "iron-range")
    assert iron["avg_home_attendance"]
    assert "pro_shared_stadium" in iron


def test_publisher_feeds_merge_with_the_school_search(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDEE_DATA_DIR", str(tmp_path))

    def fetch(url, timeout=8):
        if "footballstadiumdigest.com" in url:
            return _rss([
                (
                    "Iron Range stadium renovation financing - Football Stadium Digest",
                    "Football Stadium Digest",
                    "https://footballstadiumdigest.com/iron-range",
                    PUB,
                ),
                (
                    "Alabama NIL collective - Football Stadium Digest",
                    "Football Stadium Digest",
                    "https://footballstadiumdigest.com/alabama",
                    PUB,
                ),
            ])
        if "news.google.com" in url:
            return _rss([
                ("Iron Range NIL collective - Sportico", "Sportico", "https://news.google.com/rss/articles/nil", OLDER)
            ])
        return "<rss><channel></channel></rss>"

    monkeypatch.setattr("attendee_tracker.business_news.fetch_rss", fetch)
    payload = load_business_news("iron-range", "Iron Range", "IR", "Rangers", "Iron Range")
    assert [item["title"] for item in payload["items"]] == [
        "Iron Range stadium renovation financing",
        "Iron Range NIL collective",
    ]
    assert payload["items"][0]["source"] == "Football Stadium Digest"
    assert "Alabama" not in str(payload["items"])


def test_slug_cannot_escape_the_news_directory():
    with pytest.raises(ValueError):
        safe_slug("../")
    assert safe_slug("Iron Range") == "ironrange"
    assert "/" not in safe_slug("a/../../b")


def _fetch_count(school="Iron Range", abbreviation="IR"):
    return len(build_queries(school, abbreviation)) + len(PUBLISHER_FEEDS)


def _item(title, published, url):
    return {"title": title, "source": "Sportico", "published_at": published, "url": url}


def _rss(rows):
    items = []
    for title, source, link, published in rows:
        items.append(
            "<item>"
            f"<title>{title}</title>"
            f"<link>{link}</link>"
            f"<pubDate>{published}</pubDate>"
            f"<source url='https://example.com'>{source}</source>"
            "</item>"
        )
    return "<rss><channel>" + "".join(items) + "</channel></rss>"
