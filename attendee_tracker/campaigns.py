"""Football marketing and fan-engagement campaigns for one school.

Seasons 2025 and 2026 only. Each season file is keyed by school slug.
A slug that is absent has not been reviewed. A slug with an empty item
list was checked and nothing qualifying was found.

Dates come from the article page (CMS timestamp or JSON-LD
``datePublished``). A date that appears only in the URL is not used.
2020 attendance rules are not involved here.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from attendee_tracker.config import data_dir

CAMPAIGN_YEARS = (2025, 2026)
DEFAULT_YEAR = 2026

CAMPAIGN_TYPES = (
    "theme_night",
    "giveaway",
    "ticket_deal",
    "student_promo",
    "community",
    "sponsor_activation",
    "digital",
    "fan_experience",
)
SOURCE_TYPES = ("official", "media", "social")

NOT_REVIEWED = "Not yet reviewed"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ISO_DT = re.compile(r"^(20\d{2}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2}))?")
_YEAR_IN_TEXT = re.compile(r"\b(2025|2026)\b")


class CampaignError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def campaigns_dir() -> Path:
    return data_dir() / "campaigns"


def campaigns_path(year: int) -> Path:
    return campaigns_dir() / f"{year}.json"


def season_window(year: int) -> tuple[date, date]:
    """Roughly February through the following January.

    January of the season year is included so a season-ticket launch in
    January still belongs to that season. The following January is included
    so bowl-season promotions in the first month of the next calendar year
    still belong to the season that just finished.
    """
    if year not in CAMPAIGN_YEARS:
        raise CampaignError(
            "bad_year",
            "Campaigns are available for the 2025 and 2026 seasons.",
            400,
        )
    return date(year, 1, 1), date(year + 1, 1, 31)


def date_in_window(day: date, year: int) -> bool:
    start, end = season_window(year)
    return start <= day <= end


def empty_message(year: int, record: dict | None) -> str | None:
    """Copy for a school with nothing to list. None when items exist."""
    if year not in CAMPAIGN_YEARS:
        raise CampaignError(
            "bad_year",
            "Campaigns are available for the 2025 and 2026 seasons.",
            400,
        )
    if record is None:
        return NOT_REVIEWED
    items = record.get("items") or []
    if items:
        return None
    checked = record.get("checked_at") or ""
    return f"No football campaigns found for {year} (last checked {checked})"


def parse_since(value: str, today: date | None = None) -> date:
    """``7d`` is a day count ending today. Anything else is ``YYYY-MM-DD``."""
    text = (value or "").strip().casefold()
    if not text:
        raise CampaignError("bad_since", "Pass --since as 7d or YYYY-MM-DD.", 400)
    if text.endswith("d") and text[:-1].isdigit():
        days = int(text[:-1])
        if days < 0 or days > 3660:
            raise CampaignError("bad_since", "Day window is out of range.", 400)
        anchor = today or date.today()
        return anchor - timedelta(days=days)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise CampaignError("bad_since", "Pass --since as 7d or YYYY-MM-DD.", 400) from exc


def load_year(year: int) -> dict:
    """Slug to ``{checked_at, items}``. A missing file means nobody is reviewed."""
    if year not in CAMPAIGN_YEARS:
        raise CampaignError(
            "bad_year",
            "Campaigns are available for the 2025 and 2026 seasons.",
            400,
        )
    path = campaigns_path(year)
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CampaignError("bad_campaigns", f"{path.name} is not an object.", 500)
    return payload


def school_campaigns(slug: str, year: int) -> dict:
    """API payload for one school. Unknown slugs are the caller's problem."""
    selected = year if year is not None else DEFAULT_YEAR
    record = None
    payload = load_year(selected)
    if isinstance(payload.get(slug), dict):
        record = payload[slug]
    items = []
    if record is not None:
        items = [item for item in record.get("items") or [] if isinstance(item, dict)]
        items = sorted(items, key=lambda item: (item.get("date") or "", item.get("title") or ""))
    return {
        "slug": slug,
        "year": selected,
        "years": list(CAMPAIGN_YEARS),
        "checked": record is not None,
        "checked_at": record.get("checked_at") if record else None,
        "items": items,
        "empty_message": empty_message(selected, record),
    }


def validate_year_file(payload: dict, year: int) -> list[str]:
    """Return human-readable problems. An empty list means the file is usable."""
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["Campaign file is not an object."]
    for slug, record in payload.items():
        if not isinstance(slug, str) or not slug:
            problems.append("A campaign key is not a school slug.")
            continue
        problems.extend(_validate_record(slug, record, year))
    return problems


def _validate_record(slug: str, record, year: int) -> list[str]:
    problems: list[str] = []
    if not isinstance(record, dict):
        return [f"{slug} is not an object."]
    checked = record.get("checked_at")
    if not isinstance(checked, str) or _parse_day(checked) is None:
        problems.append(f"{slug} needs checked_at as YYYY-MM-DD.")
    items = record.get("items")
    if not isinstance(items, list):
        problems.append(f"{slug} needs an items list.")
        return problems
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, item in enumerate(items, start=1):
        label = f"{slug} item {index}"
        if not isinstance(item, dict):
            problems.append(f"{label} is not an object.")
            continue
        problems.extend(_validate_item(label, item, year))
        item_id = item.get("id")
        if isinstance(item_id, str):
            if item_id in seen_ids:
                problems.append(f"{label} duplicates id {item_id}.")
            seen_ids.add(item_id)
        source = item.get("source_url")
        if isinstance(source, str):
            key = canonical_url(source)
            if key in seen_urls:
                problems.append(f"{label} duplicates source {source}.")
            seen_urls.add(key)
    return problems


def _validate_item(label: str, item: dict, year: int) -> list[str]:
    problems: list[str] = []
    required = (
        "id",
        "title",
        "date",
        "announced",
        "game",
        "type",
        "description",
        "source_url",
        "source_name",
        "source_type",
    )
    for field in required:
        if field not in item:
            problems.append(f"{label} is missing {field}.")
    if not isinstance(item.get("id"), str) or not item.get("id", "").strip():
        problems.append(f"{label} needs an id.")
    if not isinstance(item.get("title"), str) or not item.get("title", "").strip():
        problems.append(f"{label} needs a title.")
    day = _parse_day(item.get("date")) if isinstance(item.get("date"), str) else None
    if day is None:
        problems.append(f"{label} needs a YYYY-MM-DD date.")
    elif not date_in_window(day, year):
        problems.append(f"{label} date {item.get('date')} is outside the {year} season window.")
    if not isinstance(item.get("announced"), bool):
        problems.append(f"{label} needs announced true or false.")
    kind = item.get("type")
    if kind not in CAMPAIGN_TYPES:
        problems.append(f"{label} has an unknown type.")
    elif kind == "theme_night" and item.get("announced") is not True:
        problems.append(f"{label} is a theme night and must be marked announced.")
    game = item.get("game")
    if game is not None:
        if (
            not isinstance(game, dict)
            or not isinstance(game.get("opponent"), str)
            or not game.get("opponent", "").strip()
            or not isinstance(game.get("home"), bool)
        ):
            problems.append(f"{label} game must be null or opponent plus home.")
    description = item.get("description")
    if not isinstance(description, str) or not description.strip():
        problems.append(f"{label} needs a description.")
    elif description.count(".") > 4:
        problems.append(f"{label} description is longer than two sentences.")
    source = item.get("source_url")
    if not isinstance(source, str) or not source.startswith("https://"):
        problems.append(f"{label} needs an https source_url.")
    if not isinstance(item.get("source_name"), str) or not item.get("source_name", "").strip():
        problems.append(f"{label} needs a source_name.")
    if item.get("source_type") not in SOURCE_TYPES:
        problems.append(f"{label} has an unknown source_type.")
    return problems


def canonical_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    path = parts.path.rstrip("/")
    if path.casefold().endswith(".aspx"):
        path = path[:-5]
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, "", ""))


def item_id(url: str) -> str:
    digest = hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()
    return digest[:16]


def append_items(record: dict, new_items: list[dict], checked_at: str) -> dict:
    """Add items whose source URL is not already stored, and bump checked_at."""
    current = record if isinstance(record, dict) else {}
    items = [item for item in current.get("items") or [] if isinstance(item, dict)]
    seen = {canonical_url(item.get("source_url") or "") for item in items}
    seen_ids = {item.get("id") for item in items}
    for item in new_items:
        key = canonical_url(item.get("source_url") or "")
        if not key or key in seen or item.get("id") in seen_ids:
            continue
        items.append(item)
        seen.add(key)
        seen_ids.add(item.get("id"))
    items.sort(key=lambda item: (item.get("date") or "", item.get("title") or ""))
    return {"checked_at": checked_at, "items": items}


def story_from_html(html: str, slug: str | None = None) -> dict | None:
    """Title, publish date, and text from a page. URL dates are ignored."""
    if not html:
        return None
    nuxt = _story_from_nuxt(html, slug)
    if nuxt and nuxt.get("date"):
        return nuxt
    linked = _story_from_jsonld(html)
    if linked and linked.get("date"):
        return linked
    meta = _story_from_meta(html)
    if meta and meta.get("date"):
        return meta
    return None


def _story_from_nuxt(html: str, slug: str | None) -> dict | None:
    match = re.search(
        r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    )
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    candidates = []
    for value in data:
        if isinstance(value, dict) and "contentDate" in value and "contentTitle" in value:
            story = _deref(data, value)
            if isinstance(story, dict) and story.get("date") or isinstance(story, dict) and story.get("contentDate"):
                candidates.append(story)
    if not candidates:
        return None
    chosen = candidates[0]
    if slug:
        for story in candidates:
            url = str(story.get("url") or story.get("contentUrl") or "")
            if slug in url:
                chosen = story
                break
    day = _parse_day(str(chosen.get("contentDate") or chosen.get("date") or ""))
    if day is None:
        return None
    title = str(chosen.get("contentTitle") or chosen.get("title") or "").strip()
    text = _plain(str(chosen.get("content") or ""))
    sport = str(chosen.get("sportShortname") or chosen.get("sportDisplay") or "").casefold()
    return {
        "title": title,
        "date": day.isoformat(),
        "text": text,
        "sport": sport,
        "url": str(chosen.get("url") or chosen.get("contentUrl") or ""),
    }


def _deref(data: list, node, depth: int = 0, seen: set[int] | None = None):
    if depth > 8:
        return None
    if isinstance(node, bool) or node is None:
        return node
    if isinstance(node, int):
        if node < 0 or node >= len(data):
            return node
        seen = set(seen or ())
        if node in seen:
            return None
        seen.add(node)
        return _deref(data, data[node], depth + 1, seen)
    if isinstance(node, list):
        if len(node) == 2 and isinstance(node[0], str) and node[0] in {"Reactive", "ShallowReactive", "Ref"}:
            return _deref(data, node[1], depth + 1, seen)
        return [_deref(data, item, depth + 1, set(seen or ())) for item in node[:40]]
    if isinstance(node, dict):
        resolved = {}
        for key, value in node.items():
            if isinstance(value, int) and not isinstance(value, bool):
                resolved[key] = _deref(data, value, depth + 1, set(seen or ()))
            else:
                resolved[key] = value
        return resolved
    return node


def _story_from_jsonld(html: str) -> dict | None:
    for match in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    ):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            raw_date = node.get("datePublished")
            day = _parse_day(str(raw_date or ""))
            if day is None:
                continue
            title = str(node.get("headline") or node.get("name") or "").strip()
            text = _plain(str(node.get("articleBody") or node.get("description") or ""))
            return {"title": title, "date": day.isoformat(), "text": text, "sport": "", "url": ""}
    return None


def _story_from_meta(html: str) -> dict | None:
    """CMS timestamps in meta tags. A date that exists only in the URL is still ignored."""
    published = _meta_content(html, "article:published_time")
    day = _parse_day(published)
    if day is None:
        return None
    title = _meta_content(html, "og:title") or ""
    description = _meta_content(html, "og:description") or ""
    if not title and not description:
        return None
    return {
        "title": title.split("|")[0].strip(),
        "date": day.isoformat(),
        "text": description,
        "sport": "",
        "url": "",
    }


def _meta_content(html: str, key: str) -> str:
    patterns = (
        rf'(?:property|name)="{re.escape(key)}"\s+content="([^"]*)"',
        rf'content="([^"]*)"\s+(?:property|name)="{re.escape(key)}"',
    )
    for pattern in patterns:
        match = re.search(pattern, html or "", re.I)
        if match and match.group(1).strip():
            return unescape(match.group(1).strip())
    return ""


_OTHER_SPORTS = (
    "basketball",
    "volleyball",
    "baseball",
    "softball",
    "soccer",
    "hockey",
    "lacrosse",
    "tennis",
    "golf",
    "wrestling",
    "rowing",
    "gymnastics",
    "swimming",
)


def _other_sport_page(title: str, url: str, sport: str) -> bool:
    """True when the page is about another sport and not a football story."""
    sport_key = (sport or "").casefold()
    if sport_key and "football" not in sport_key and any(name in sport_key for name in _OTHER_SPORTS):
        return True
    url_key = (url or "").casefold()
    title_key = (title or "").casefold()
    slug = url_key.rstrip("/").split("/")[-1].removesuffix(".aspx")
    if "promoted" in slug or "promoted to" in title_key:
        return True
    if any(name in slug for name in _OTHER_SPORTS) and not slug.startswith("football"):
        return True
    return False


def classify_campaign(title: str, text: str, url: str, sport: str = "") -> str | None:
    """Return a campaign type, or None when the page is not a football campaign."""
    title_key = (title or "").casefold()
    url_key = (url or "").casefold()
    sport_key = (sport or "").casefold()
    if _other_sport_page(title, url, sport):
        return None
    head = f"{title_key} {url_key}"
    body = f"{title_key}\n{(text or '')[:2500]}".casefold()
    if _rejected(title_key, body):
        return None
    if not _is_football(head, body, sport_key):
        return None
    if not _is_campaign(head, body):
        return None
    schedule = any(
        phrase in head or phrase in body[:900]
        for phrase in (
            "promotional schedule",
            "promotional slate",
            "themes announced",
            "home game themes",
            "home-game themes",
            "game themes",
        )
    )
    if schedule or any(
        phrase in head
        for phrase in (
            "theme night",
            "white out",
            "whiteout",
            "blackout",
            "stripe out",
            "pink out",
            "senior day",
            "senior night",
            "super hero",
            "marvel",
        )
    ):
        return "theme_night"
    if any(phrase in head or phrase in body[:700] for phrase in ("giveaway", "free sandwich", "free towel", "bobblehead", "rally towel")):
        return "giveaway"
    if any(phrase in head for phrase in ("student section", "student ticket", "student rush", "student appreciation")):
        return "student_promo"
    if any(phrase in head or phrase in body[:700] for phrase in ("season ticket", "tickets on sale", "ticket renewal", "ticket information", "family pack", "ticket deal")):
        return "ticket_deal"
    if any(phrase in head or phrase in body[:900] for phrase in ("community day", "youth day", "military appreciation", "heroes day", "hero day", "first responder", "hometown heroes")):
        return "community"
    if any(phrase in head or phrase in body[:700] for phrase in ("fan fest", "fan experience", "meet the team", "meet-the-team")):
        return "fan_experience"
    if any(phrase in head for phrase in ("digital campaign", "app exclusive", "social campaign")):
        return "digital"
    if "presented by" in head or "sponsor" in head:
        return "sponsor_activation"
    if any(phrase in body[:900] for phrase in ("white out", "whiteout", "blackout", "theme night", "senior day", "senior night")):
        return "theme_night"
    return None


def _rejected(title_key: str, body: str) -> bool:
    blocked = (
        "recap",
        "notebook",
        "what to watch",
        "how to watch",
        "injury report",
        "press conference",
        "all-american",
        "all-america",
        "scholar-athlete",
        "scholar athlete",
        "dean's list",
        "deans list",
        "dean’s list",
        "president's list",
        "presidents list",
        "president’s list",
        "sell out",
        "sellout",
        "sold out",
        "named head coach",
        "hired as",
        "box score",
        "postgame",
        "post-game",
    )
    if any(phrase in title_key for phrase in blocked):
        return True
    if any(phrase in title_key for phrase in ("defeats", "falls to", "victory", "rolls past", "tops ", "win over", "wins over")):
        return True
    # Result headlines ("Rams drop season finale on Senior Day") are recaps.
    if re.search(r"\b(drops?|dropped|fell|falls|beat|beats|loss|wins|won|defeated|edged|topped|routed)\b", title_key):
        if not any(word in title_key for word in ("giveaway", "promotion", "promotional", "theme", "on sale", "ticket")):
            return True
    if "coaching" in title_key or "assistant coach" in title_key:
        return True
    if re.search(r"\bit['’]?s\s+senior\s+(day|night)\b", title_key):
        return True
    if re.search(r"\bsenior\s+(day|night)\s+(vs\.?|versus|against)\b", title_key):
        return True
    if "game day details" in body[:500] or "game day timeline" in body[:500]:
        if not any(phrase in body[:900] for phrase in ("promotional schedule", "themes announced", "giveaway")):
            return True
    if "set for" in title_key and not any(
        word in title_key for word in ("theme", "giveaway", "festival", "promotion", "promotional")
    ):
        return True
    if re.search(r"\b(preview|kickoff time|game time)\b", title_key):
        return True
    if re.search(r"set for\b.{0,50}(espn|sec network|fox|cbs|noon|p\.m|a\.m|kickoff)", title_key):
        return True
    if "campus operations" in title_key or "parking" in title_key and "giveaway" not in body[:400]:
        return True
    return False


def _is_football(head: str, body: str, sport: str) -> bool:
    if sport:
        sport_names = [part.strip() for part in sport.split(",")]
        if any(part == "football" or part.startswith("football") for part in sport_names):
            return True
        if "football" not in head and "football" not in body[:500]:
            return False
    return "football" in head or "football" in body[:800]


def _is_campaign(head: str, body: str) -> bool:
    phrases = (
        "promotional schedule",
        "promotional slate",
        "promotion",
        "theme night",
        "themes announced",
        "home game themes",
        "game themes",
        "giveaway",
        "white out",
        "whiteout",
        "blackout",
        "stripe out",
        "pink out",
        "senior day",
        "senior night",
        "homecoming",
        "community day",
        "heroes",
        "military appreciation",
        "first responder",
        "student section",
        "student ticket",
        "student rush",
        "student appreciation",
        "youth day",
        "season ticket",
        "tickets on sale",
        "ticket deal",
        "family pack",
        "fan fest",
        "fan experience",
        "free sandwich",
        "free towel",
        "super hero",
        "hero day",
        "game promotion",
        "given away",
    )
    if "homecoming" in head and not any(
        phrase in head or phrase in body[:600]
        for phrase in ("theme", "giveaway", "festival", "parade", "concert", "promotion", "fan")
    ):
        if any(phrase in head for phrase in ("set for", "kickoff", "preview", "hosts")):
            return False
    return any(phrase in head or phrase in body[:900] for phrase in phrases)


_THEME_LINE = re.compile(
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June|July|Aug(?:ust)?|Sept(?:ember)?|Sep\.?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}.{0,80}?(?:vs\.?|versus)\s+"
    r"([A-Z][A-Za-z0-9.&'’\-]+(?:\s+[A-Z][A-Za-z0-9.&'’\-]+){0,3})"
    r"\s*(?:\([^)]{0,40}\))?\s*[:\u2013\u2014\-]\s*"
    r"([A-Z0-9][^:.\n]{1,90})"
)
# A capitalized one of these, after the theme name has started, begins the next sentence.
_SENTENCE_START = {
    "a",
    "an",
    "all",
    "calling",
    "celebrate",
    "celebrating",
    "fans",
    "join",
    "from",
    "wear",
    "don't",
    "don’t",
    "this",
    "invite",
    "more",
    "for",
    "come",
    "embracing",
    "single",
    "enjoy",
    "experience",
    "be",
    "get",
    "make",
    "check",
    "watch",
    "the",
}
_BAD_THEME = re.compile(
    r"\b(will|this|weekend|centerpiece|serve|serves|fans|encouraged|wear|join|celebrate|calling|information|features|featuring)\b",
    re.I,
)


def extract_themes(text: str) -> list[tuple[str, str]]:
    """Opponent and a short theme name from schedule lines. Empty when unclear."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _THEME_LINE.finditer(text or ""):
        opponent = _WS.sub(" ", match.group(1)).strip(" -–—")
        theme = _short_theme(match.group(2))
        if not opponent or not theme or theme.casefold() in seen:
            continue
        seen.add(theme.casefold())
        found.append((opponent, theme))
    return found[:8]


def _short_theme(raw: str) -> str:
    raw = (raw or "").split("(")[0]
    words = _WS.sub(" ", raw).strip(" -–—:").split()
    kept: list[str] = []
    for index, word in enumerate(words):
        bare = word.strip(",:;")
        token = bare.casefold()
        if token in {"/", "&"}:
            kept.append(token)
            continue
        token = token.strip("/&")
        if not token:
            continue
        if index >= 1 and bare[:1].isupper() and token in _SENTENCE_START:
            break
        if token in {"kickoff", "tba", "p.m", "a.m", "pm", "am"}:
            break
        kept.append(bare.strip("/"))
        if len(kept) >= 8:
            break
    while kept and kept[-1].casefold().strip("/&") in {"&", "/", "and", "the", "a", "of", "for"}:
        kept.pop()
    theme = " ".join(kept).strip(" /&-")
    if len(theme) < 3 or len(theme) > 48:
        return ""
    if _BAD_THEME.search(theme):
        return ""
    if any(phrase in theme.casefold() for phrase in ("announced", "kickoff", "information on", "game day")):
        return ""
    return theme


def compose_item(
    *,
    school: str,
    source_url: str,
    source_name: str,
    source_type: str,
    title: str,
    text: str,
    published: str,
    sport: str = "",
) -> dict | None:
    """One campaign item in our own words, or None when the page does not qualify."""
    kind = classify_campaign(title, text, source_url, sport)
    if kind is None:
        return None
    day = _parse_day(published)
    if day is None:
        return None
    season = season_for(day, title, text)
    if season is None:
        return None
    themes = extract_themes(text or "")
    opponent = themes[0][0] if len(themes) == 1 else _single_opponent(title, text)
    game = None
    if opponent and len(themes) <= 1 and "schedule" not in title.casefold() and "themes" not in title.casefold():
        game = {"opponent": opponent, "home": _is_home(title, text)}
    description = _describe(school, season, kind, [theme for _, theme in themes], title)
    if not description or _copies_source(description, text):
        description = _describe(school, season, kind, [], title)
    if _copies_source(description, text):
        return None
    announced = True if kind == "theme_night" else _sounds_announced(title, text)
    return {
        "id": item_id(source_url),
        "title": _item_title(school, season, kind, title, themes),
        "date": day.isoformat(),
        "announced": announced,
        "game": game,
        "type": kind,
        "description": description,
        "source_url": source_url,
        "source_name": source_name,
        "source_type": source_type,
        "season": season,
    }


def season_for(day: date, title: str, text: str) -> int | None:
    """Which season file this dated article belongs in."""
    blob = f"{title} {(text or '')[:500]}"
    named = [int(year) for year in _YEAR_IN_TEXT.findall(blob)]
    named = [year for year in CAMPAIGN_YEARS if year in named]
    fitting = [year for year in CAMPAIGN_YEARS if date_in_window(day, year)]
    if len(named) == 1 and named[0] in fitting:
        return named[0]
    named_fit = [year for year in named if year in fitting]
    if len(named_fit) == 1:
        return named_fit[0]
    if len(fitting) == 1:
        return fitting[0]
    if len(fitting) > 1:
        if named_fit:
            return max(named_fit)
        return max(fitting)
    return None


def _named_from_headline(headline: str) -> str | None:
    """A short name we can use when the headline itself names the promotion."""
    key = (headline or "").casefold()
    if "super hero" in key or "marvel" in key:
        return "Marvel Super Hero Day"
    return None


def _item_title(school: str, season: int, kind: str, headline: str, themes: list[tuple[str, str]]) -> str:
    named = _named_from_headline(headline)
    if named and len(themes) != 1:
        return named
    headline_key = (headline or "").casefold()
    if "promotional schedule" in headline_key or "promotional slate" in headline_key:
        return f"{season} football promotional schedule"
    if "theme" in headline_key and ("announc" in headline_key or "home game" in headline_key):
        return f"{season} football home-game themes"
    if len(themes) == 1:
        return themes[0][1]
    labels = {
        "theme_night": f"{season} football theme",
        "giveaway": f"{season} football giveaway",
        "ticket_deal": f"{season} football ticket offer",
        "student_promo": f"{season} student football promotion",
        "community": f"{season} football community event",
        "sponsor_activation": f"{season} football sponsor event",
        "digital": f"{season} football digital campaign",
        "fan_experience": f"{season} football fan event",
    }
    base = labels.get(kind, f"{season} football campaign")
    if school and school.casefold() not in base.casefold():
        return base
    return base


def _describe(school: str, season: int, kind: str, themes: list[str], headline: str = "") -> str:
    name = school or "The program"
    named = _named_from_headline(headline)
    if named and not themes:
        return f"{name} announced a {named} promotion for a {season} home football game."
    if kind == "theme_night" and themes:
        listed = _join(themes[:4])
        extra = ", among others" if len(themes) > 4 else ""
        return (
            f"{name} announced themed promotions for its {season} home football games. "
            f"The release names {listed}{extra}."
        )
    sentences = {
        "theme_night": f"{name} announced themed promotions for its {season} home football games.",
        "giveaway": f"{name} set a fan giveaway around its {season} football games.",
        "ticket_deal": f"{name} published a ticket offer for the {season} football season.",
        "student_promo": f"{name} aimed a student promotion at its {season} football games.",
        "community": f"{name} scheduled a community event around its {season} football games.",
        "sponsor_activation": f"{name} paired a sponsor activation with its {season} football games.",
        "digital": f"{name} promoted a digital fan campaign for the {season} football season.",
        "fan_experience": f"{name} scheduled an on-site fan event for the {season} football season.",
    }
    return sentences.get(kind, f"{name} published a {season} football fan promotion.")


def _sounds_announced(title: str, text: str) -> bool:
    blob = f"{title} {(text or '')[:300]}".casefold()
    return any(word in blob for word in ("announc", "will host", "set to host", "returns", "on sale", "scheduled"))


def _single_opponent(title: str, text: str) -> str | None:
    matches = re.findall(
        r"\b(?:vs\.?|versus|against)\s+([A-Z][A-Za-z0-9&'’\-]+(?:\s+[A-Z][A-Za-z0-9&'’\-]+){0,3})",
        f"{title}. {(text or '')[:700]}",
    )
    cleaned = []
    for raw in matches:
        opponent = raw.strip(" -")
        if opponent.casefold() in {"the", "its", "home"}:
            continue
        if any(word in opponent.casefold() for word in ("game", "kickoff", "ticket", "stadium")):
            continue
        cleaned.append(opponent)
    unique = list(dict.fromkeys(cleaned))
    if len(unique) != 1:
        return None
    return unique[0]


def _is_home(title: str, text: str) -> bool:
    """Home unless the title says the team is playing at the opponent."""
    title_text = title or ""
    if re.search(r"\b(at|@)\s+[A-Z]", title_text) and not re.search(r"\b(at|@)\s+home\b", title_text, re.I):
        return False
    blob = f"{title_text} {(text or '')[:600]}"
    if re.search(r"\b(home game|at home|to host|will host|hosts)\b", blob, re.I):
        return True
    if re.search(r"\b(vs\.?|versus|against)\b", title_text, re.I):
        return True
    return True


def _copies_source(description: str, text: str) -> bool:
    """True when an 8-word stretch of the description is lifted from the article."""
    words = _WS.sub(" ", description).split()
    if len(words) < 8:
        return False
    source = _WS.sub(" ", text or "").casefold()
    for index in range(len(words) - 7):
        window = " ".join(words[index : index + 8]).casefold()
        if window in source:
            return True
    return False


def _join(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


def _plain(value: str) -> str:
    text = unescape(_TAG.sub(" ", value or ""))
    return _WS.sub(" ", text).strip()


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    match = _ISO_DT.match(value.strip())
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def checked_stamp(day: date | None = None) -> str:
    return (day or date.today()).isoformat()
