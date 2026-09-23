"""Athletics-business headlines for one school.

Google News search is merged with a few publisher RSS feeds. The module keeps
the headline, publisher, date, and link. It does not copy article text or
invent stories.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from attendee_tracker.store import iso, read_json, utc_now, write_json
from attendee_tracker.config import data_dir

NEWS_TTL = timedelta(hours=12)
NEWS_LIMIT = 10
FETCH_TIMEOUT_SECONDS = 8.0
EASTERN = ZoneInfo("America/New_York")

ATTRIBUTION = (
    "Headlines, publisher, and date only, with a link to the original story. "
    "This portfolio app aggregates public feeds and does not copy article text. "
    "Google News RSS is a prototype source, not a commercial redistribution license."
)

# A browser user agent is what returns the RSS document. A bare client gets an empty body.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

BUSINESS_SITES = (
    "frontofficesports.com",
    "on3.com",
    "sportico.com",
    "collegead.com",
    "sportsbusinessjournal.com",
)

# General publisher feeds. Items are kept only when they match the open school.
PUBLISHER_FEEDS = (
    ("https://frontofficesports.com/feed/", "Front Office Sports"),
    ("https://frontofficesports.com/tag/college-sports/feed/", "Front Office Sports"),
    ("https://www.sportico.com/feed/", "Sportico"),
    ("https://www.nytimes.com/athletic/rss/college-football/", "The Athletic"),
    ("https://sports.yahoo.com/college-sports/news/rss/", "Yahoo Sports"),
    ("https://footballstadiumdigest.com/feed/", "Football Stadium Digest"),
)

KEYWORD_CLAUSE = (
    '(NIL OR collective OR "revenue share" OR budget OR financing OR bond OR debt '
    'OR "media rights" OR broadcast OR "TV deal" OR streaming OR sponsorship '
    'OR "jersey patch" OR "naming rights" OR stadium OR renovation OR construction '
    'OR "ticket revenue" OR "premium seating" OR "athletic director" OR buyout '
    'OR "contract extension" OR salary OR realignment OR "grant of rights" OR "exit fee")'
)

# Single-token names that also belong to other programs or leagues.
AMBIGUOUS_NAMES = frozenset({"miami", "georgia", "washington", "usc", "state"})

# A longer school name sitting after a shorter one: "Georgia Tech", "Washington State".
_TRAILING_SCHOOL = re.compile(r"\s+(?:state|tech|southern|a\s*&\s*m)\b", re.IGNORECASE)

_POSITIVE_PATTERNS = (
    ("nil", r"\bnil\b"),
    ("collective", r"collectives?"),
    ("revenue share", r"revenue[\s-]shar\w*"),
    ("budget", r"\bbudgets?\b"),
    ("financing", r"\bfinancing\b"),
    ("bond", r"\bbonds?\b"),
    ("debt", r"\bdebt\b"),
    ("media rights", r"media rights"),
    ("broadcast", r"\bbroadcast\b"),
    ("tv deal", r"tv deal"),
    ("streaming", r"\bstreaming\b"),
    ("sponsorship", r"sponsor(?:ship|ed|s)?"),
    ("jersey patch", r"jersey patch"),
    ("naming rights", r"naming rights?"),
    ("stadium", r"\bstadiums?\b"),
    ("renovation", r"renovat\w*"),
    ("construction", r"\bconstruction\b"),
    ("ticket revenue", r"ticket revenue"),
    ("premium seating", r"premium seating"),
    ("athletic director", r"athletic directors?|\bad\b"),
    ("buyout", r"\bbuyouts?\b"),
    ("contract extension", r"contract extension"),
    ("salary", r"\bsalar(?:y|ies)\b"),
    ("realignment", r"realignment"),
    ("grant of rights", r"grant of rights"),
    ("exit fee", r"exit fee"),
)

# Game copy that mentions a stadium only because the game is played there.
_GAME_TRIP = re.compile(
    r"\b(?:vs\.?|versus|travels to|beats?|defeats?|win over|kickoff)\b",
    re.IGNORECASE,
)

# Sorted after a clean business headline. They stay in the list when a
# positive term is also present.
_DEMOTE = re.compile(
    r"("
    r"box score"
    r"|\brecaps?\b"
    r"|\brecapping\b"
    r"|final score"
    r"|\bpreviews?\b"
    r"|game time"
    r"|injury report"
    r"|depth chart"
    r"|\brankings\b"
    r"|\bhighlights\b"
    r"|\bpredictions?\b"
    r"|keys to the game"
    r"|how to watch"
    r"|where to watch"
    r"|ways to watch"
    r"|watch guide"
    r"|what channel"
    r"|\bodds\b"
    r"|\bbetting\b"
    r"|\bsportsbooks?\b"
    r"|\bmoneyline\b"
    r"|\bpoint spread\b"
    r")",
    re.IGNORECASE,
)

_HIGH_SCHOOL = re.compile(r"\bhigh[\s-]school\b|\bprep school\b", re.IGNORECASE)
_TICKETS = re.compile(r"\btickets?\b", re.IGNORECASE)
_TICKET_REVENUE = re.compile(r"ticket revenue", re.IGNORECASE)


def news_path(slug: str):
    return data_dir() / "news" / f"{safe_slug(slug)}.json"


def safe_slug(slug: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "", (slug or "").casefold()).strip("-")
    if not cleaned:
        raise ValueError("School slug is empty.")
    return cleaned


def build_queries(school: str, abbreviation: str | None = None) -> list[str]:
    """Search strings for one program. School name stays in every query."""
    name = " ".join((school or "").split())
    if not name:
        return []
    quoted = f'"{name}"'
    abbr = (abbreviation or "").strip()
    lead = quoted
    if abbr and abbr.casefold() not in name.casefold() and 2 <= len(abbr) <= 8:
        lead = f"{quoted} {abbr}"
    general = f"{lead} football {KEYWORD_CLAUSE}"
    sites = [f'site:{site} {quoted} football' for site in BUSINESS_SITES]
    return [general, *sites]


def fetch_rss(url: str, timeout: float = FETCH_TIMEOUT_SECONDS) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(2_000_000)
    return payload.decode("utf-8", "replace")


def rss_url(query: str) -> str:
    return "https://news.google.com/rss/search?" + urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )


def parse_rss(xml_text: str, default_source: str = "Google News") -> list[dict]:
    """Pull title, publisher, date, and link out of one feed. Bad XML yields nothing."""
    if not xml_text or "<item" not in xml_text.casefold():
        return []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    items = []
    for node in root.iter():
        if not str(node.tag).endswith("item"):
            continue
        title = _text(node, "title")
        link = _text(node, "link")
        if not title or not link:
            continue
        source_node = _child(node, "source")
        source = ""
        if source_node is not None:
            source = (source_node.text or "").strip()
            if not source:
                source = (source_node.attrib.get("url") or "").strip()
        source = source or default_source or "Google News"
        items.append(
            {
                "title": clean_title(title, source),
                "source": source,
                "published_at": _published(node),
                "url": link.strip(),
            }
        )
    return items


def clean_title(title: str, source: str | None) -> str:
    text = re.sub(r"\s+", " ", title or "").strip()
    if source and " - " in text:
        head, _, tail = text.rpartition(" - ")
        source_key = source.casefold()
        tail_key = tail.casefold()
        if head and (source_key in tail_key or tail_key in source_key):
            return head.strip()
    return text


def school_is_ambiguous(school: str) -> bool:
    return _norm(school) in AMBIGUOUS_NAMES


def matches_school(
    title: str,
    school: str,
    abbreviation: str | None = None,
    mascot: str | None = None,
    city: str | None = None,
) -> bool:
    """True when the headline is about this program, not a neighbor with a similar name.

    Ambiguous names (Miami, Georgia, Washington, USC, State) need the school
    name plus mascot or city, or any two aliases. A single weak token is not enough.
    """
    hits = _alias_hits(title, school, abbreviation, mascot, city)
    if not hits:
        return False
    if school_is_ambiguous(school):
        if "name" in hits and hits & {"mascot", "city"}:
            return True
        return len(hits) >= 2
    if "name" in hits:
        return True
    if hits == {"abbr"} and _norm(abbreviation or "") not in AMBIGUOUS_NAMES:
        return True
    return len(hits) >= 2


def business_terms(title: str) -> set[str]:
    """Positive business topics in a headline. A game trip to a stadium does not count."""
    found = {name for name, pattern in _POSITIVE_PATTERNS if re.search(pattern, title or "", re.IGNORECASE)}
    if found == {"stadium"} and _GAME_TRIP.search(title or ""):
        found.discard("stadium")
    return found


def is_demoted(title: str) -> bool:
    """Game packaging and bare ticket pitches sort after a clean business headline."""
    if _DEMOTE.search(title or ""):
        return True
    if _TICKETS.search(title or "") and not _TICKET_REVENUE.search(title or ""):
        return True
    return False


def is_business_headline(
    title: str,
    school: str,
    abbreviation: str | None = None,
    mascot: str | None = None,
    city: str | None = None,
) -> bool:
    """True when the headline is about this program's athletics business."""
    if _HIGH_SCHOOL.search(title or ""):
        return False
    if not matches_school(title, school, abbreviation, mascot, city):
        return False
    return bool(business_terms(title))


def dedupe_items(items: list[dict]) -> list[dict]:
    """One row per headline. A later copy replaces an older one."""
    order: list[str] = []
    by_key: dict[str, dict] = {}
    for item in items:
        key = title_key(item.get("title") or "")
        url = (item.get("url") or "").strip()
        if not key or not url:
            continue
        current = by_key.get(key)
        if current is None:
            by_key[key] = item
            order.append(key)
            continue
        if (item.get("published_at") or "") > (current.get("published_at") or ""):
            by_key[key] = item
    return [by_key[key] for key in order]


def title_key(title: str) -> str:
    text = title.casefold().replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def select_headlines(
    items: list[dict],
    school: str,
    abbreviation: str | None = None,
    mascot: str | None = None,
    city: str | None = None,
    limit: int = NEWS_LIMIT,
) -> list[dict]:
    matched = [
        item
        for item in items
        if is_business_headline(item.get("title") or "", school, abbreviation, mascot, city)
    ]
    unique = dedupe_items(matched)
    clean = [item for item in unique if not is_demoted(item.get("title") or "")]
    demoted = [item for item in unique if is_demoted(item.get("title") or "")]
    return (_by_date(clean) + _by_date(demoted))[:limit]


def _by_date(items: list[dict]) -> list[dict]:
    dated = [item for item in items if item.get("published_at")]
    undated = [item for item in items if not item.get("published_at")]
    dated.sort(key=lambda item: item["published_at"], reverse=True)
    return dated + undated


def load_business_news(
    slug: str,
    school: str,
    abbreviation: str | None = None,
    mascot: str | None = None,
    city: str | None = None,
) -> dict:
    """Return cached headlines when they are fresh. Otherwise search and store them."""
    try:
        safe_slug(slug)
    except ValueError:
        return _payload(slug, school, [], note="That school slug is not valid.")

    now = utc_now()
    cached = _read_cache(slug)
    if cached and _is_fresh(cached, now):
        return _public(cached, cached_hit=True)

    queries = build_queries(school, abbreviation)
    items, fetched_ok = _search(queries)
    if fetched_ok == 0:
        if cached:
            stale = _public(cached, cached_hit=True)
            stale["stale"] = True
            return stale
        return _public(
            _payload(
                slug,
                school,
                [],
                note="Business headlines could not be loaded just now.",
            ),
            cached_hit=False,
        )

    selected = select_headlines(items, school, abbreviation, mascot, city)
    payload = _payload(slug, school, selected, fetched_at=iso(now), queries=queries)
    try:
        write_json(news_path(slug), payload)
    except (ValueError, OSError):
        return _public(payload, cached_hit=False)
    return _public(payload, cached_hit=False)


def _search(queries: list[str]) -> tuple[list[dict], int]:
    jobs = [(rss_url(query), "Google News") for query in queries]
    jobs.extend(PUBLISHER_FEEDS)
    if not jobs:
        return [], 0
    items: list[dict] = []
    ok = 0
    workers = min(8, len(jobs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch_feed, url, source) for url, source in jobs]
        for future in futures:
            parsed = future.result()
            if parsed is None:
                continue
            ok += 1
            items.extend(parsed)
    return items, ok


def _fetch_feed(url: str, default_source: str) -> list[dict] | None:
    try:
        xml_text = fetch_rss(url)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    return parse_rss(xml_text, default_source=default_source)


def _read_cache(slug: str) -> dict | None:
    try:
        path = news_path(slug)
    except ValueError:
        return None
    payload = read_json(path)
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("items"), list):
        return None
    return payload


def _is_fresh(payload: dict, now: datetime) -> bool:
    fetched = _parse_iso(payload.get("fetched_at"))
    if fetched is None:
        return False
    return now - fetched <= NEWS_TTL


def _public(payload: dict, cached_hit: bool) -> dict:
    items = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        url = item.get("url")
        if not title or not url:
            continue
        items.append(
            {
                "title": title,
                "source": item.get("source") or "Google News",
                "published_at": item.get("published_at"),
                "url": url,
            }
        )
    return {
        "slug": payload.get("slug"),
        "school": payload.get("school"),
        "fetched_at": payload.get("fetched_at"),
        "cached": cached_hit,
        "stale": False,
        "items": items,
        "attribution": ATTRIBUTION,
        "note": payload.get("note"),
    }


def _payload(
    slug: str,
    school: str,
    items: list[dict],
    fetched_at: str | None = None,
    queries: list[str] | None = None,
    note: str | None = None,
) -> dict:
    return {
        "slug": slug,
        "school": school,
        "fetched_at": fetched_at,
        "queries": queries or [],
        "items": items,
        "attribution": ATTRIBUTION,
        "note": note,
    }


def _child(node: ElementTree.Element, name: str) -> ElementTree.Element | None:
    direct = node.find(name)
    if direct is not None:
        return direct
    for child in list(node):
        if str(child.tag).endswith(name):
            return child
    return None


def _text(node: ElementTree.Element, name: str) -> str:
    child = _child(node, name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _published(node: ElementTree.Element) -> str | None:
    raw = _text(node, "pubDate")
    if not raw:
        return None
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(EASTERN).date().isoformat()


def _norm(value: str | None) -> str:
    text = (value or "").casefold().replace("’", "'").replace("`", "'")
    return " ".join(text.split())


def _alias_hits(
    title: str,
    school: str,
    abbreviation: str | None,
    mascot: str | None,
    city: str | None,
) -> set[str]:
    text = _norm(title)
    hits: set[str] = set()
    if _alias_present(text, school):
        hits.add("name")
    # The abbreviation is not a second alias when it is the same token as the school name.
    if _norm(abbreviation) != _norm(school) and _alias_present(text, abbreviation):
        hits.add("abbr")
    if _alias_present(text, mascot):
        hits.add("mascot")
    if _alias_present(text, city):
        hits.add("city")
    return hits


def _alias_present(text: str, alias: str | None) -> bool:
    needle = _norm(alias)
    if len(needle) < 3 or not text:
        return False
    pattern = re.compile(rf"\b{re.escape(needle)}\b")
    for match in pattern.finditer(text):
        rest = text[match.end() :]
        trailing = _TRAILING_SCHOOL.match(rest)
        if trailing:
            # "Georgia" must not claim "Georgia Tech". "Ohio State" already includes State.
            tail = trailing.group(0).strip()
            if needle.endswith(tail):
                return True
            continue
        return True
    return False


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
