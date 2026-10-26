"""Refresh football campaign files from public athletics pages.

Usage:
    python scripts/campaigns_refresh.py --since 7d
    python scripts/campaigns_refresh.py --since 2025-01-01

The script reads each school's athletics site, keeps football fan and
marketing items, and appends the ones that are not already stored. It
bumps checked_at for every school it was able to review. A date is taken
from the page, never from the URL alone. Descriptions are written here.
Article sentences are not copied.

Nothing in this script reads or writes API keys or .env.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from attendee_tracker.assemble import slugify
from attendee_tracker.campaigns import (
    CAMPAIGN_YEARS,
    append_items,
    campaigns_path,
    canonical_url,
    checked_stamp,
    compose_item,
    load_year,
    parse_since,
    story_from_html,
)
from attendee_tracker.store import live_path, read_json, write_json

USER_AGENT = "AttendeeTracker/1.0 (campaign research; public pages only)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
PAUSE_SECONDS = 0.35
DDG_PAUSE = 2.0
_DDG_LOCK = threading.Lock()
_DDG_BLOCKED = False

# Pages the product owner named. They are fetched and parsed like any other
# URL. A page that does not qualify is dropped.
KNOWN_CANDIDATES = {
    "james-madison": [
        "https://jmusports.com/news/2025/7/21/james-madison-athletics-announces-its-full-promotional-schedule-for-the-2025-football-season",
        "https://jmusports.com/news/2025/8/22/james-madison-football-to-host-first-ever-collegiate-marvel-super-hero-day",
        "https://jmusports.com/news/2026/6/4/jmu-announces-full-promotional-schedule-for-2026-football-season",
    ],
    "memphis": [
        "https://gotigersgo.com/news/2026/6/2/football-themes-announced-for-2026-tiger-home-games",
    ],
    "app-state": [
        "https://appstatesports.com/news/2026/4/3/2026-app-state-football-home-game-themes-announced.aspx",
    ],
    "colorado-state": [
        "https://csurams.com/news/2026/10/24/general-10-24-g-que-bbq-20pt-free-sandwich",
    ],
}

# Official athletics sites. A host that does not answer is skipped and the
# school stays unreviewed unless another public page identifies the site.
ATHLETICS_SITES = {
    "air-force": "goairforcefalcons.com",
    "akron": "gozips.com",
    "alabama": "rolltide.com",
    "app-state": "appstatesports.com",
    "arizona": "arizonawildcats.com",
    "arizona-state": "thesundevils.com",
    "arkansas": "arkansasrazorbacks.com",
    "arkansas-state": "astateredwolves.com",
    "army": "goarmywestpoint.com",
    "auburn": "auburntigers.com",
    "ball-state": "ballstatesports.com",
    "baylor": "baylorbears.com",
    "boise-state": "broncosports.com",
    "boston-college": "bceagles.com",
    "bowling-green": "bgsufalcons.com",
    "buffalo": "ubbulls.com",
    "byu": "byucougars.com",
    "california": "calbears.com",
    "central-michigan": "cmuchippewas.com",
    "charlotte": "charlotte49ers.com",
    "cincinnati": "gobearcats.com",
    "clemson": "clemsontigers.com",
    "coastal-carolina": "goccusports.com",
    "colorado": "cubuffs.com",
    "colorado-state": "csurams.com",
    "delaware": "bluehens.com",
    "duke": "goduke.com",
    "east-carolina": "ecupirates.com",
    "eastern-michigan": "emueagles.com",
    "florida": "floridagators.com",
    "florida-atlantic": "fausports.com",
    "florida-international": "fiusports.com",
    "florida-state": "seminoles.com",
    "fresno-state": "gobulldogs.com",
    "georgia": "georgiadogs.com",
    "georgia-southern": "gseagles.com",
    "georgia-state": "georgiastatesports.com",
    "georgia-tech": "ramblinwreck.com",
    "hawai-i": "hawaiiathletics.com",
    "houston": "uhcougars.com",
    "illinois": "fightingillini.com",
    "indiana": "iuhoosiers.com",
    "iowa": "hawkeyesports.com",
    "iowa-state": "cyclones.com",
    "jacksonville-state": "jaxstatesports.com",
    "james-madison": "jmusports.com",
    "kansas": "kuathletics.com",
    "kansas-state": "kstatesports.com",
    "kennesaw-state": "ksuowls.com",
    "kent-state": "kentstatesports.com",
    "kentucky": "ukathletics.com",
    "liberty": "libertyflames.com",
    "louisiana": "ragincajuns.com",
    "louisiana-tech": "latechsports.com",
    "louisville": "gocards.com",
    "lsu": "lsusports.net",
    "marshall": "herdzone.com",
    "maryland": "umterps.com",
    "massachusetts": "umassathletics.com",
    "memphis": "gotigersgo.com",
    "miami": "miamihurricanes.com",
    "miami-oh": "miamiredhawks.com",
    "michigan": "mgoblue.com",
    "michigan-state": "msuspartans.com",
    "middle-tennessee": "goblueraiders.com",
    "minnesota": "gophersports.com",
    "mississippi-state": "hailstate.com",
    "missouri": "mutigers.com",
    "missouri-state": "missouristatebears.com",
    "navy": "navysports.com",
    "nc-state": "gopack.com",
    "nebraska": "huskers.com",
    "nevada": "nevadawolfpack.com",
    "new-mexico": "golobos.com",
    "new-mexico-state": "nmstatesports.com",
    "north-carolina": "goheels.com",
    "north-dakota-state": "gobison.com",
    "north-texas": "meangreensports.com",
    "northern-illinois": "niuhuskies.com",
    "northwestern": "nusports.com",
    "notre-dame": "und.com",
    "ohio": "ohiobobcats.com",
    "ohio-state": "ohiostatebuckeyes.com",
    "oklahoma": "soonersports.com",
    "oklahoma-state": "okstate.com",
    "old-dominion": "odusports.com",
    "ole-miss": "olemisssports.com",
    "oregon": "goducks.com",
    "oregon-state": "osubeavers.com",
    "penn-state": "gopsusports.com",
    "pittsburgh": "pittsburghpanthers.com",
    "purdue": "purduesports.com",
    "rice": "riceowls.com",
    "rutgers": "scarletknights.com",
    "sacramento-state": "hornetsports.com",
    "sam-houston": "gobearkats.com",
    "san-diego-state": "goaztecs.com",
    "san-jos-state": "sjsuspartans.com",
    "smu": "smumustangs.com",
    "south-alabama": "usajaguars.com",
    "south-carolina": "gamecocksonline.com",
    "south-florida": "gousfbulls.com",
    "southern-miss": "southernmiss.com",
    "stanford": "gostanford.com",
    "syracuse": "cuse.com",
    "tcu": "gofrogs.com",
    "temple": "owlsports.com",
    "tennessee": "utsports.com",
    "texas": "texaslonghorns.com",
    "texas-a-m": "12thman.com",
    "texas-state": "txst.com",
    "texas-tech": "texastech.com",
    "toledo": "utrockets.com",
    "troy": "troytrojans.com",
    "tulane": "tulanegreenwave.com",
    "tulsa": "tulsahurricane.com",
    "uab": "uabsports.com",
    "ucf": "ucfknights.com",
    "ucla": "uclabruins.com",
    "uconn": "uconnhuskies.com",
    "ul-monroe": "ulmwarhawks.com",
    "unlv": "unlvrebels.com",
    "usc": "usctrojans.com",
    "utah": "utahutes.com",
    "utah-state": "utahstateaggies.com",
    "utep": "utepminers.com",
    "utsa": "goutsa.com",
    "vanderbilt": "vucommodores.com",
    "virginia": "virginiasports.com",
    "virginia-tech": "hokiesports.com",
    "wake-forest": "godeacs.com",
    "washington": "gohuskies.com",
    "washington-state": "wsucougars.com",
    "west-virginia": "wvusports.com",
    "western-kentucky": "wkusports.com",
    "western-michigan": "wmubroncos.com",
    "wisconsin": "uwbadgers.com",
    "wyoming": "gowyo.com",
}

SITEMAP_KEYWORDS = (
    "promotion",
    "promo",
    "theme",
    "giveaway",
    "give-away",
    "white-out",
    "whiteout",
    "blackout",
    "stripe-out",
    "pink-out",
    "senior-day",
    "senior-night",
    "homecoming",
    "community-day",
    "heroes",
    "military",
    "student",
    "ticket",
    "fan-fest",
    "youth-day",
    "appreciation",
    "free-sandwich",
    "bbq",
    "super-hero",
    "marvel",
)

SKIP_SLUG_BITS = (
    "recap",
    "notebook",
    "preview",
    "all-american",
    "all-america",
    "scholar",
    "deans-list",
    "presidents-list",
    "coaching",
    "press-conference",
    "injury",
    "sellout",
    "sold-out",
    "kickoff",
    "promoted",
    "-drop-",
    "finale",
    "defeats",
    "victory",
    "-wins-",
    "falls-",
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Append football campaigns and bump checked_at.")
    parser.add_argument("--since", required=True, help="7d or YYYY-MM-DD. New items must be dated on or after this day.")
    parser.add_argument("--schools", default="", help="Comma-separated slugs. Default: every FBS school in the 2026 cache.")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent school reviews. Each school still pauses between requests.")
    args = parser.parse_args(argv)
    since = parse_since(args.since, date.today())
    schools = load_schools()
    if args.schools.strip():
        wanted = {part.strip() for part in args.schools.split(",") if part.strip()}
        schools = [school for school in schools if school["slug"] in wanted]
    summary = refresh_schools(schools, since=since, today=date.today(), workers=max(1, args.workers))
    print(
        f"Reviewed {summary['reviewed']} schools. "
        f"Added {summary['added']} items. "
        f"Unchecked {summary['unchecked']}."
    )


def load_schools() -> list[dict]:
    payload = read_json(live_path(2026))
    teams = payload.get("teams") if isinstance(payload, dict) else None
    if not isinstance(teams, list):
        raise SystemExit("data/live/2026.json has no teams list.")
    schools = []
    for team in teams:
        if not isinstance(team, dict) or not team.get("school"):
            continue
        schools.append(
            {
                "slug": slugify(team["school"]),
                "school": team["school"],
                "mascot": team.get("mascot") or "",
            }
        )
    schools.sort(key=lambda row: row["slug"])
    return schools


def refresh_schools(schools: list[dict], *, since: date, today: date, fetcher=None, sleeper=None, workers: int = 4) -> dict:
    """Review each school, append new items, and write the season files."""
    get = fetcher or fetch_text
    pause = sleeper or time.sleep
    files = {year: load_year(year) for year in CAMPAIGN_YEARS}
    added = 0
    reviewed = 0
    unchecked = []
    stamp = checked_stamp(today)
    total = len(schools)

    def review(pair: tuple[int, dict]):
        index, school = pair
        host = ATHLETICS_SITES.get(school["slug"])
        try:
            stories = discover_school(school, host, since, get, pause)
        except Exception as exc:  # noqa: BLE001 — one school should not abort the run
            return index, school, None, str(exc)
        return index, school, stories, ""

    completed = 0
    pool_size = max(1, min(workers, total or 1))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        futures = [pool.submit(review, pair) for pair in enumerate(schools, start=1)]
        for future in as_completed(futures):
            index, school, stories, error = future.result()
            slug = school["slug"]
            prefix = f"[{index}/{total}] {school['school']}"
            if error:
                unchecked.append(slug)
                print(f"{prefix} skipped ({error})", flush=True)
            elif stories is None:
                unchecked.append(slug)
                print(f"{prefix} not reviewed", flush=True)
            else:
                reviewed += 1
                for year in CAMPAIGN_YEARS:
                    incoming = []
                    for story in stories:
                        if story["season"] != year:
                            continue
                        if date.fromisoformat(story["date"]) < since:
                            continue
                        item = dict(story)
                        item.pop("season", None)
                        incoming.append(item)
                    before = len((files[year].get(slug) or {}).get("items") or [])
                    files[year][slug] = append_items(files[year].get(slug) or {"items": []}, incoming, stamp)
                    added += len(files[year][slug]["items"]) - before
                found = sum(len((files[year].get(slug) or {}).get("items") or []) for year in CAMPAIGN_YEARS)
                print(f"{prefix} {found} items on file", flush=True)
            completed += 1
            if completed % 10 == 0:
                _write_campaign_files(files)
    _write_campaign_files(files)
    return {"reviewed": reviewed, "added": added, "unchecked": len(unchecked), "unchecked_slugs": unchecked}


def _write_campaign_files(files: dict) -> None:
    for year in CAMPAIGN_YEARS:
        ordered = {slug: files[year][slug] for slug in sorted(files[year])}
        write_json(campaigns_path(year), ordered)


def discover_school(school: dict, host: str | None, since: date, get, pause) -> list[dict] | None:
    """Return new campaign dicts, or None when the school could not be reviewed."""
    if not host:
        return None
    urls = candidate_urls(host, since, get, pause, school["slug"])
    if urls is None:
        return None
    source_name = site_name(host)
    items = []
    seen = set()
    fetched_ok = 0
    for url in urls:
        key = canonical_url(url)
        if key in seen:
            continue
        seen.add(key)
        pause(PAUSE_SECONDS)
        try:
            html = get(url)
        except Exception:
            continue
        if not html:
            continue
        fetched_ok += 1
        slug = url.rstrip("/").split("/")[-1].removesuffix(".aspx")
        story = story_from_html(html, slug)
        if not story or not story.get("date"):
            continue
        item = compose_item(
            school=school["school"],
            source_url=absolute_url(host, story.get("url") or url),
            source_name=source_name_from(html, source_name),
            source_type="official",
            title=story.get("title") or "",
            text=story.get("text") or "",
            published=story["date"],
            sport=story.get("sport") or "",
        )
        if item is None:
            continue
        item["source_url"] = canonical_url(item["source_url"])
        if not item["source_url"].startswith("https://"):
            item["source_url"] = absolute_url(host, item["source_url"])
        items.append(item)
    # URLs were found, but every fetch failed. Leave the school unreviewed.
    if urls and fetched_ok == 0:
        return None
    return items


def normalize_loc(url: str) -> str:
    """Collapse duplicated slashes in the path. Sitemap indexes sometimes emit them."""
    text = (url or "").strip()
    if "://" not in text:
        return re.sub(r"/{2,}", "/", text)
    scheme, rest = text.split("://", 1)
    host, sep, path = rest.partition("/")
    path = re.sub(r"/{2,}", "/", path)
    if not sep:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}/{path}"


def candidate_urls(host: str, since: date, get, pause, slug: str = "") -> list[str] | None:
    """News URLs worth opening. None when the athletics site could not be read."""
    pause(PAUSE_SECONDS)
    try:
        index = get(f"https://{host}/sitemap.xml") or ""
    except Exception:
        index = ""
    urls: list[str] = []
    maps_read = 0
    comprehensive = False
    story_maps: list[str] = []
    if "<loc" in index.casefold():
        locs = [normalize_loc(loc) for loc in re.findall(r"<loc>\s*([^<]+)\s*</loc>", index)]
        story_maps = [loc for loc in locs if _story_map(loc, since)]
        if any(not _is_sitemap_loc(loc) for loc in locs):
            urls.extend(filter_sitemap(index, host, since))
            maps_read += 1
    if not story_maps:
        # A news urlset only lists recent stories. The SIDEARM archive is separate.
        story_maps = [f"https://{host}/sitemap/sitemap_story_1.xml"]
        if maps_read == 0:
            story_maps.append(f"https://{host}/sitemap.xml")
    for loc in story_maps[:36]:
        pause(PAUSE_SECONDS)
        try:
            xml = get(normalize_loc(loc)) or ""
        except Exception:
            continue
        if "<loc" not in xml.casefold():
            continue
        maps_read += 1
        if _comprehensive_map(loc):
            comprehensive = True
        urls.extend(filter_sitemap(xml, host, since))
    # Google News is a discovery pass. Links that stay on news.google.com are dropped.
    pause(PAUSE_SECONDS)
    urls.extend(google_news_urls(host, since, get))
    # A rolling news sitemap is not the archive. Search only when that archive
    # was not read. A blocked search leaves the school unreviewed.
    known = [normalize_loc(url) for url in KNOWN_CANDIDATES.get(slug, [])]
    if not comprehensive and not any(_strong_url(url) for url in urls):
        extra, ddg_ok = duckduckgo_urls(host, pause)
        if not ddg_ok and not known:
            return None
        urls.extend(extra)
    urls.sort(key=lambda url: (_rank_url(url), url))
    deduped = []
    seen = set()
    for url in known + urls:
        url = normalize_loc(url)
        key = canonical_url(url)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(url if url.startswith("http") else f"https://{host}{url}")
    if not deduped and maps_read == 0:
        return None
    return deduped[:50]


def _is_sitemap_loc(url: str) -> bool:
    low = url.casefold()
    return low.endswith(".xml") or "/sitemap" in low


def _story_map(url: str, since: date) -> bool:
    """Child sitemaps that can hold 2025–2026 football stories."""
    low = url.casefold()
    if not _is_sitemap_loc(url):
        return False
    numbered = re.search(r"wp-sitemap-posts-post-(\d+)\.xml", low)
    if numbered:
        return int(numbered.group(1)) <= 4
    if not any(bit in low for bit in ("sitemap_story", "sitemap-story", "posttype-post", "post-sitemap")):
        return False
    match = re.search(r"(20\d{2})(\d{2})", low)
    if match:
        year = int(match.group(1))
        if year < since.year or year > since.year + 2:
            return False
    return True


def _comprehensive_map(url: str) -> bool:
    """True for an archive sitemap, not a rolling 'latest stories' urlset."""
    low = url.casefold()
    return any(bit in low for bit in ("sitemap_story", "sitemap-story", "posttype-post", "wp-sitemap-posts-post-", "post-sitemap"))


def _strong_url(url: str) -> bool:
    """URLs that already look like a promotion, not a senior-day recap in another sport."""
    low = url.casefold()
    return any(
        bit in low
        for bit in ("promo", "theme", "giveaway", "white-out", "whiteout", "marvel", "super-hero", "blackout", "pink-out", "stripe-out")
    )


def _rank_url(url: str) -> int:
    """Football promotions first. 'Promoted' coaching notes are not promotions."""
    low = url.casefold()
    if "promoted" in low:
        return 5
    football = "/football" in low or "football-" in low
    if football and _strong_url(low):
        return 0
    if football and _priority_url(low):
        return 1
    if _strong_url(low):
        return 2
    if _priority_url(low):
        return 3
    return 4


def _priority_url(url: str) -> bool:
    low = url.casefold()
    return any(bit in low for bit in ("promo", "theme", "giveaway", "white-out", "whiteout", "senior-day", "homecoming", "marvel", "super-hero"))


def duckduckgo_urls(host: str, pause) -> tuple[list[str], bool]:
    """Publisher URLs from DuckDuckGo. The bool is False when search was blocked."""
    global _DDG_BLOCKED
    if _DDG_BLOCKED:
        return [], False
    queries = (
        f'site:{host} football "promotional schedule"',
        f"site:{host} football themes announced",
    )
    found: list[str] = []
    for query in queries:
        with _DDG_LOCK:
            if _DDG_BLOCKED:
                return [], False
            pause(DDG_PAUSE)
            url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
            try:
                html = fetch_text(url, user_agent=BROWSER_UA)
            except Exception:
                continue
        if _duckduckgo_blocked(html):
            _DDG_BLOCKED = True
            return [], False
        for encoded in re.findall(r"uddg=([^&\"']+)", html or ""):
            link = urllib.parse.unquote(encoded).split("?")[0]
            if host not in link.casefold():
                continue
            low = link.casefold()
            if "/news/" not in low and not any(bit in low for bit in ("promo", "theme", "giveaway", "ticket", "senior", "homecoming", "white")):
                continue
            found.append(link)
        if len(found) >= 8:
            break
    return found[:8], True


def _duckduckgo_blocked(html: str) -> bool:
    text = html or ""
    if "uddg=" in text:
        return False
    return "anomaly-modal" in text.casefold()


def filter_sitemap(xml: str, host: str, since: date) -> list[str]:
    found = []
    if not xml:
        return found
    for loc in re.findall(r"<loc>\s*([^<]+)\s*</loc>", xml):
        url = normalize_loc(loc.strip())
        low = url.casefold()
        if any(bit in low for bit in ("sitemap", "/shop", "/roster", "/staff", ".jpg", ".pdf")):
            continue
        if not any(bit in low for bit in SITEMAP_KEYWORDS):
            continue
        if "/news/" not in low and low.count("/") < 3:
            continue
        if any(bit in low for bit in SKIP_SLUG_BITS):
            continue
        # The path year is only a candidate filter. The page date is checked later.
        # Keep a prior year in the path so a stale URL can still be opened.
        match = re.search(r"/news/(\d{4})/", low)
        strong = any(bit in low for bit in ("promo", "theme", "giveaway", "white-out", "whiteout"))
        if match:
            path_year = int(match.group(1))
            # A stale year in the path is still opened for the strongest keywords.
            if path_year < (2024 if strong else since.year):
                continue
            if path_year > since.year + 2:
                continue
        if url.startswith("http"):
            found.append(url)
        else:
            found.append(f"https://{host}{url}")
    return found


def google_news_urls(host: str, since: date, get) -> list[str]:
    query = (
        f"site:{host} football (promotion OR promotional OR giveaway OR "
        f"\"white out\" OR \"senior day\" OR homecoming OR theme OR tickets)"
    )
    if (date.today() - since).days <= 14:
        query = f"{query} when:{(date.today() - since).days or 1}d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )
    try:
        xml = get(url)
    except Exception:
        return []
    found = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    for node in root.iter():
        if not str(node.tag).endswith("item"):
            continue
        link = ""
        title = ""
        for child in list(node):
            if str(child.tag).endswith("title"):
                title = child.text or ""
            elif str(child.tag).endswith("link"):
                link = child.text or ""
        if host not in link:
            continue
        if not any(bit.replace("-", " ") in title.casefold() for bit in ("promo", "theme", "giveaway", "senior", "homecoming", "ticket", "white out", "student")):
            continue
        found.append(link.strip())
    return found


def absolute_url(host: str, url: str) -> str:
    if url.startswith("https://") or url.startswith("http://"):
        if url.startswith("http://"):
            return "https://" + url[len("http://") :]
        return url
    path = url if url.startswith("/") else f"/{url}"
    return f"https://{host}{path}"


def site_name(host: str) -> str:
    stem = host.removeprefix("www.").split(".")[0]
    return stem


def source_name_from(html: str, fallback: str) -> str:
    match = re.search(r'property="og:site_name"\s+content="([^"]+)"', html or "", re.I)
    if not match:
        match = re.search(r'content="([^"]+)"\s+property="og:site_name"', html or "", re.I)
    name = match.group(1).strip() if match else ""
    return name or fallback


def fetch_text(url: str, user_agent: str | None = None) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent or USER_AGENT,
            "Accept": "text/html,application/xml,application/rss+xml,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            raw = response.read(12_000_000)
            encoding = (response.headers.get("Content-Encoding") or "").lower()
            if "gzip" in encoding or raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{exc.code} {url}") from exc
    return raw.decode(charset, "replace")


if __name__ == "__main__":
    main()
