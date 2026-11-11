"""College Football Playoff rankings from ESPN, with CFBD as backup only.

A season publishes the CFP poll once ESPN (or, if ESPN has no committee
poll, CFBD) has a type ``cfp`` ranking for that season dated on or after
the first Tuesday in November. Until then the site keeps showing the AP
Top 25. AP rows stay in the season cache either way.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from attendee_tracker.store import live_path, read_json

ESPN_SITE_RANKINGS = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/rankings"
)
ESPN_CORE_RANKING = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/"
    "college-football/seasons/{season}/types/{season_type}/weeks/{week}/rankings/21?lang=en"
)
CFP_POLL_ID = 21
CFP_POLL_NAME = "Playoff Committee Rankings"

# Official committee pages confirmed for these release dates. Other weeks
# keep a null official_url rather than a guessed path.
OFFICIAL_URLS = {
    "2025-12-07": "https://collegefootballplayoff.com/news/2025/12/7/cfp-rankings",
    "2026-11-03": "https://collegefootballplayoff.com/news/2026/11/3/rankings",
    "2026-11-10": "https://collegefootballplayoff.com/news/2026/11/10/rankings",
}


def cfp_path(year: int):
    from attendee_tracker.config import data_dir

    return data_dir() / "cfp" / f"{year}.json"


def bracket_path(year: int):
    from attendee_tracker.config import data_dir

    return data_dir() / "cfp" / f"{year}_projected_bracket.json"


def first_release_date(season: int) -> date:
    """First Tuesday of November, the committee's usual first release."""
    opening = date(season, 11, 1)
    offset = (1 - opening.weekday()) % 7
    return opening + timedelta(days=offset)


def load_cfp(year: int) -> dict | None:
    payload = read_json(cfp_path(year))
    return payload if isinstance(payload, dict) else None


def ranking_is_cfp(ranking: dict | None) -> bool:
    if not isinstance(ranking, dict):
        return False
    poll_type = str(ranking.get("type") or ranking.get("poll_type") or "").casefold()
    if poll_type == "cfp":
        return True
    poll_id = ranking.get("id") if ranking.get("id") is not None else ranking.get("poll_id")
    if str(poll_id) == str(CFP_POLL_ID):
        return True
    name = str(ranking.get("name") or ranking.get("poll") or ranking.get("poll_name") or "")
    folded = name.casefold()
    return "playoff committee" in folded or folded == "cfp"


def parse_released_at(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def released_on_or_after_first(released_at: str | None, season: int) -> bool:
    moment = parse_released_at(released_at)
    if moment is None:
        return False
    return moment.date() >= first_release_date(season)


def cfp_is_available(document: dict | None, season: int) -> bool:
    """True when this file is a committee poll for ``season`` after the first release."""
    if not isinstance(document, dict):
        return False
    if document.get("season") not in (None, season):
        return False
    if document.get("poll_type") not in (None, "cfp"):
        return False
    if not document.get("teams"):
        return False
    return released_on_or_after_first(document.get("released_at"), season)


def public_poll(document: dict | None, season: int) -> str:
    return "CFP" if cfp_is_available(document, season) else "AP"


def rank_note(document: dict | None, season: int) -> str | None:
    """Why a season is still on the AP poll. 2025 is the only fallback we explain."""
    if public_poll(document, season) == "CFP":
        return None
    if season == 2025:
        return (
            "2025 final CFP rankings were not available from ESPN, "
            "so this season still shows the AP Top 25."
        )
    return None


def official_url_for(released_at: str | None) -> str | None:
    moment = parse_released_at(released_at)
    if moment is None:
        return None
    return OFFICIAL_URLS.get(moment.date().isoformat())


def _previous_rank(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _team_id_from_ref(ref: str | None) -> int | None:
    if not isinstance(ref, str):
        return None
    match = re.search(r"/teams/(\d+)", ref)
    if not match:
        return None
    return int(match.group(1))


def _school_name(team: dict) -> str | None:
    for key in ("location", "displayName", "shortDisplayName", "nickname", "name"):
        value = team.get(key)
        if isinstance(value, str) and value.strip():
            if key == "displayName" and value.endswith(" Bulldogs"):
                # Prefer location when both exist. displayName is only a fallback.
                continue
            return value.strip()
    display = team.get("displayName")
    if isinstance(display, str) and display.strip():
        return display.strip()
    return None


def _conference_name(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("shortName", "name", "abbreviation"):
            text = value.get(key)
            if isinstance(text, str) and text.strip() and not text.startswith("http"):
                return text.strip()
    return None


def _record_summary(row: dict) -> str | None:
    summary = row.get("recordSummary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    record = row.get("record")
    if isinstance(record, dict):
        summary = record.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
    return None


def _week_number(ranking: dict) -> int | None:
    occurrence = ranking.get("occurrence")
    if isinstance(occurrence, dict) and occurrence.get("number") is not None:
        try:
            return int(occurrence["number"])
        except (TypeError, ValueError):
            return None
    week = ranking.get("week")
    if isinstance(week, int):
        return week
    if isinstance(week, str) and week.isdigit():
        return int(week)
    return None


def _season_year(ranking: dict) -> int | None:
    season = ranking.get("season")
    if isinstance(season, dict) and season.get("year") is not None:
        try:
            return int(season["year"])
        except (TypeError, ValueError):
            return None
    if isinstance(season, int):
        return season
    return None


def parse_rank_row(row: dict, catalog: dict | None = None) -> dict | None:
    """One committee rank. ``team_id`` is the id shared by ESPN and the season cache."""
    if not isinstance(row, dict):
        return None
    try:
        rank = int(row.get("current") if row.get("current") is not None else row.get("rank"))
    except (TypeError, ValueError):
        return None
    if rank <= 0:
        return None
    team = row.get("team") if isinstance(row.get("team"), dict) else {}
    espn_id = None
    if team.get("id") is not None:
        try:
            espn_id = int(team["id"])
        except (TypeError, ValueError):
            espn_id = _team_id_from_ref(team.get("$ref"))
    else:
        espn_id = _team_id_from_ref(team.get("$ref"))
    known = (catalog or {}).get(espn_id) if espn_id is not None else None
    school = _school_name(team) or (known or {}).get("school")
    if not school:
        return None
    conference = _conference_name(row.get("conference")) or (known or {}).get("conference")
    return {
        "rank": rank,
        "previous": _previous_rank(row.get("previous")),
        "record": _record_summary(row),
        "conference": conference,
        "team_id": espn_id if known or espn_id is not None else None,
        "espn_team_id": espn_id,
        "school": school,
    }


def parse_cfp_ranking(ranking: dict, catalog: dict | None = None, season: int | None = None) -> dict | None:
    """Turn one ESPN or CFBD committee poll into a snapshot body."""
    if not ranking_is_cfp(ranking):
        return None
    season = _season_year(ranking) or season
    released_at = ranking.get("date") or ranking.get("released_at")
    if isinstance(released_at, datetime):
        released_at = released_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    teams = []
    for row in ranking.get("ranks") or ranking.get("teams") or []:
        parsed = parse_rank_row(row, catalog)
        if parsed:
            teams.append(parsed)
    teams.sort(key=lambda item: item["rank"])
    if season is None or not teams:
        return None
    moment = parse_released_at(released_at) if isinstance(released_at, str) else None
    released = moment.strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None
    return {
        "season": season,
        "released_at": released,
        "week": _week_number(ranking),
        "official_url": ranking.get("official_url") or official_url_for(released),
        "headline": ranking.get("headline") or ranking.get("shortHeadline"),
        "teams": teams,
    }


def select_site_cfp(payload: dict, season: int) -> dict | None:
    """The committee poll from the ESPN site rankings payload, if it is this season."""
    if not isinstance(payload, dict):
        return None
    for ranking in payload.get("rankings") or []:
        if not isinstance(ranking, dict) or not ranking_is_cfp(ranking):
            continue
        if _season_year(ranking) != season:
            continue
        return ranking
    return None


def snapshot_from_cfbd_weeks(weeks: list, season: int, catalog: dict | None = None) -> dict | None:
    """Latest CFBD committee poll for ``season``. Backup only. AP weeks are ignored."""
    snapshots = []
    for week in weeks or []:
        if not isinstance(week, dict):
            continue
        week_season = week.get("season")
        try:
            if int(week_season) != season:
                continue
        except (TypeError, ValueError):
            continue
        polls = week.get("polls") or []
        for poll in polls:
            if not isinstance(poll, dict):
                continue
            wrapped = {
                "type": "cfp" if ranking_is_cfp(poll) else poll.get("poll"),
                "name": poll.get("poll"),
                "season": {"year": season},
                "date": week.get("date") or week.get("released_at"),
                "occurrence": {"number": week.get("week")},
                "ranks": [
                    {
                        "current": row.get("rank"),
                        "previous": row.get("previous") or row.get("prevRank"),
                        "recordSummary": row.get("record"),
                        "conference": row.get("conference"),
                        "team": {
                            "id": row.get("teamId") or row.get("team_id"),
                            "location": row.get("school"),
                        },
                    }
                    for row in (poll.get("ranks") or [])
                    if isinstance(row, dict)
                ],
            }
            parsed = parse_cfp_ranking(wrapped, catalog)
            if parsed and released_on_or_after_first(parsed.get("released_at"), season):
                snapshots.append(parsed)
    if not snapshots:
        return None
    return max(snapshots, key=lambda item: item.get("released_at") or "")


def merge_document(season: int, snapshots: list[dict], *, source: str, source_url: str) -> dict | None:
    usable = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if snapshot.get("season") != season or not snapshot.get("teams"):
            continue
        if not released_on_or_after_first(snapshot.get("released_at"), season):
            continue
        usable.append(snapshot)
    if not usable:
        return None
    deduped: dict[str, dict] = {}
    for snapshot in usable:
        key = snapshot.get("released_at") or f"week-{snapshot.get('week')}"
        current = deduped.get(key)
        if current is None or len(snapshot.get("teams") or []) >= len(current.get("teams") or []):
            deduped[key] = snapshot
    ordered = sorted(deduped.values(), key=lambda item: item.get("released_at") or "")
    latest = ordered[-1]
    return {
        "season": season,
        "poll_type": "cfp",
        "poll_id": CFP_POLL_ID,
        "poll_name": CFP_POLL_NAME,
        "source": source,
        "source_url": source_url,
        "first_release": first_release_date(season).isoformat(),
        "released_at": latest.get("released_at"),
        "week": latest.get("week"),
        "official_url": latest.get("official_url"),
        "teams": latest.get("teams"),
        "snapshots": [
            {
                "released_at": item.get("released_at"),
                "week": item.get("week"),
                "official_url": item.get("official_url"),
                "headline": item.get("headline"),
                "teams": item.get("teams"),
            }
            for item in ordered
        ],
    }


def team_catalog(year: int) -> dict[int, dict]:
    """School and conference from the committed season cache, keyed by team id."""
    payload = read_json(live_path(year))
    catalog: dict[int, dict] = {}
    if not isinstance(payload, dict):
        return catalog
    for team in payload.get("teams") or []:
        if not isinstance(team, dict) or team.get("id") is None:
            continue
        try:
            team_id = int(team["id"])
        except (TypeError, ValueError):
            continue
        school = team.get("school")
        if not isinstance(school, str) or not school.strip():
            continue
        catalog[team_id] = {
            "school": school.strip(),
            "conference": team.get("conference") if isinstance(team.get("conference"), str) else None,
        }
    return catalog


def indexes(document: dict | None) -> tuple[dict[int, dict], dict[str, dict]]:
    by_id: dict[int, dict] = {}
    by_name: dict[str, dict] = {}
    if not isinstance(document, dict):
        return by_id, by_name
    for row in document.get("teams") or []:
        if not isinstance(row, dict) or row.get("rank") is None:
            continue
        if row.get("team_id") is not None:
            by_id[int(row["team_id"])] = row
        school = row.get("school")
        if isinstance(school, str) and school.strip():
            by_name[school.casefold()] = row
    return by_id, by_name


def lookup_rank(school: dict, by_id: dict, by_name: dict) -> dict | None:
    team_id = school.get("id")
    if team_id is not None and int(team_id) in by_id:
        return by_id[int(team_id)]
    name = school.get("school")
    if isinstance(name, str):
        return by_name.get(name.casefold())
    return None


def core_week_url(season: int, season_type: int, week: int) -> str:
    return ESPN_CORE_RANKING.format(season=season, season_type=season_type, week=week)


def team_url_is_espn(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc.endswith("api.espn.com")
