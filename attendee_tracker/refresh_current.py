"""Refresh the current season: CFBD first, then ESPN attendance fills.

CFBD stays the source for games, records, rankings, teams, and venues.
When a completed non-neutral home game has null attendance, this command
reads ESPN's summary ``gameInfo.attendance``. It never invents a crowd.
A CFBD number is never replaced. Missing ESPN figures stay null.

Usage:
    python -m attendee_tracker.refresh_current
    python -m attendee_tracker.refresh_current --year 2026
    python -m attendee_tracker.refresh_current --force
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from attendee_tracker.cfbd_client import CfbdClient, CfbdError, MissingApiKey
from attendee_tracker.config import DEFAULT_MIN_INTERVAL_HOURS, api_key, load_dotenv, season_year
from attendee_tracker.ingest import MISSING_KEY_MESSAGE, resolve_years, run_ingest
from attendee_tracker.store import append_quota, live_path, load_live, write_json

ESPN_SOURCE = "espn_summary"
CFBD_SOURCE = "cfbd"
MATCH_WINDOW = timedelta(hours=18)
SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/scoreboard?seasontype={season_type}&week={week}"
    "&groups=80&dates={year}&limit=300"
)
SUMMARY = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/summary?event={event_id}"
)


class EspnUnavailable(CfbdError):
    """ESPN could not be read. Callers leave the previous cache in place when this escapes."""


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Re-pull the current season from CFBD, then fill null attendance from ESPN summaries."
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Season year. Defaults to SEASON_YEAR or 2026.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-pull CFBD even if the cache is inside the freshness window.",
    )
    parser.add_argument(
        "--min-interval-hours",
        type=float,
        default=DEFAULT_MIN_INTERVAL_HOURS,
        help="Skip the CFBD pull when games were fetched more recently than this. Default: 18.",
    )
    args = parser.parse_args(argv)
    year = resolve_years([args.year] if args.year is not None else None, None, season_year())[0]
    if not api_key():
        print(MISSING_KEY_MESSAGE, file=sys.stderr)
        raise SystemExit(2)

    client = CfbdClient(
        api_key(),
        on_call=lambda endpoint, status, call_year: append_quota(endpoint, status, call_year),
    )
    try:
        calls = refresh_season(
            year=year,
            force=args.force,
            min_interval_hours=args.min_interval_hours,
            client=client,
        )
    except MissingApiKey:
        print(MISSING_KEY_MESSAGE, file=sys.stderr)
        raise SystemExit(2)
    except (CfbdError, EspnUnavailable) as exc:
        print(str(exc), file=sys.stderr)
        print(
            "The previous cache, if any, was left in place. No attendance figures were invented.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print(f"CFBD calls this run: {calls}")


def refresh_season(
    *,
    year: int,
    force: bool,
    min_interval_hours: float,
    client,
    get_json: Callable[[str], dict] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Re-pull CFBD, then fill null attendance. Returns the CFBD call count."""
    getter = get_json or curl_json
    pause = sleep or time.sleep
    prior = prior_espn_attendance(load_live(year))

    def finalize(snapshot: dict) -> dict:
        return fill_from_espn(snapshot, year, prior, getter, pause)

    calls = run_ingest(
        year=year,
        force=force,
        min_interval_hours=min_interval_hours,
        client=client,
        finalize=finalize,
    )
    if calls == 0:
        snapshot = load_live(year)
        games = snapshot.get("games") if isinstance(snapshot, dict) else None
        if isinstance(snapshot, dict) and any(needs_espn_fill(game) for game in games or [] if isinstance(game, dict)):
            updated = fill_from_espn(snapshot, year, prior, getter, pause)
            write_json(live_path(year), updated)
            print(f"Wrote {live_path(year)}")
        else:
            print("No completed home games were missing attendance. ESPN was not called.")
    written = load_live(year)
    if isinstance(written, dict):
        print_fill_summary(written)
    return calls


def espn_attendance_value(value) -> int | None:
    """Return ESPN's whole-number crowd, or None when the summary has no figure.

    Zero is kept when ESPN reports zero. Negatives, booleans, and partial
    numbers are not used. A missing value stays null and is never filled in.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not value.is_integer():
            return None
        number = int(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text.isdigit():
            return None
        number = int(text)
    else:
        return None
    if number < 0:
        return None
    return number


def needs_espn_fill(game: dict) -> bool:
    if not isinstance(game, dict) or game.get("attendance") is not None:
        return False
    return bool(game.get("completed")) and not bool(game.get("neutral_site"))


def prior_espn_attendance(snapshot: dict | None) -> dict[int, int]:
    """Previously recorded ESPN crowds, keyed by CFBD game id."""
    found: dict[int, int] = {}
    if not isinstance(snapshot, dict):
        return found
    for game in snapshot.get("games") or []:
        if not isinstance(game, dict) or game.get("attendance_source") != ESPN_SOURCE:
            continue
        value = espn_attendance_value(game.get("attendance"))
        game_id = game.get("id")
        if value is None or game_id is None:
            continue
        found[game_id] = value
    return found


def match_espn_event(game: dict, events: list[dict]) -> dict | None:
    """Match a CFBD game to an ESPN event by team id and start time."""
    home = _as_int_id(game.get("home_id"))
    away = _as_int_id(game.get("away_id"))
    game_time = _parse_time(game.get("start_date"))
    if home is None or away is None or game_time is None:
        return None
    best = None
    best_delta = None
    window = MATCH_WINDOW.total_seconds()
    for event in events:
        if _as_int_id(event.get("home_id")) != home or _as_int_id(event.get("away_id")) != away:
            continue
        event_time = _parse_time(event.get("date") or event.get("start_date"))
        if event_time is None:
            continue
        delta = abs((event_time - game_time).total_seconds())
        if delta > window:
            continue
        if best is None or delta < best_delta:
            best = event
            best_delta = delta
    return best


def apply_attendance_sources(snapshot: dict, espn_events: list[dict], *, prior: dict[int, int] | None = None) -> dict:
    """Record cfbd or espn_summary on each game. Never invent a crowd."""
    remembered = prior or {}
    filled = 0
    restored = 0
    left_null = 0
    for game in snapshot.get("games") or []:
        if not isinstance(game, dict):
            continue
        if game.get("attendance") is not None:
            if game.get("attendance_source") != ESPN_SOURCE:
                game["attendance_source"] = CFBD_SOURCE
            continue
        if not needs_espn_fill(game):
            game.pop("attendance_source", None)
            continue
        event = match_espn_event(game, espn_events)
        if event is None or not event.get("summary_ok"):
            if _restore_prior(game, remembered):
                restored += 1
            else:
                left_null += 1
            continue
        value = espn_attendance_value(event.get("attendance"))
        if value is None or event.get("neutral_site") or not event.get("completed"):
            game["attendance"] = None
            game.pop("attendance_source", None)
            left_null += 1
            continue
        game["attendance"] = value
        game["attendance_source"] = ESPN_SOURCE
        filled += 1
    if filled or restored or left_null:
        _add_warning(
            snapshot,
            (
                f"ESPN summaries filled {filled} completed non-neutral home games that CFBD left null. "
                f"{restored} kept a previously recorded ESPN attendance value. "
                f"{left_null} stayed null. No attendance was invented."
            ),
        )
    return snapshot


def fill_from_espn(snapshot: dict, year: int, prior: dict[int, int], get_json, sleep) -> dict:
    games = [game for game in snapshot.get("games") or [] if isinstance(game, dict)]
    if not any(needs_espn_fill(game) for game in games):
        return apply_attendance_sources(snapshot, [], prior=prior)
    try:
        events = fetch_espn_events(year, games, get_json=get_json, sleep=sleep)
    except EspnUnavailable as exc:
        restored = 0
        for game in games:
            if game.get("attendance") is not None:
                if game.get("attendance_source") != ESPN_SOURCE:
                    game["attendance_source"] = CFBD_SOURCE
                continue
            if needs_espn_fill(game) and _restore_prior(game, prior):
                restored += 1
        _add_warning(
            snapshot,
            (
                f"ESPN attendance fill failed ({exc}). Restored {restored} previously recorded "
                "ESPN attendance values where CFBD is still null. No attendance was invented."
            ),
        )
        return snapshot
    return apply_attendance_sources(snapshot, events, prior=prior)


def fetch_espn_events(year: int, games: list[dict], *, get_json, sleep) -> list[dict]:
    """Scoreboard first, then summaries only for matched games that still need a crowd."""
    needed = [game for game in games if needs_espn_fill(game)]
    if not needed:
        return []
    events = load_scoreboard_events(year, get_json=get_json, sleep=sleep)
    if not events:
        raise EspnUnavailable("ESPN scoreboard returned no college football events.")
    chosen: list[dict] = []
    seen: set[str] = set()
    for game in needed:
        event = match_espn_event(game, events)
        if event is None:
            continue
        event_id = str(event.get("espn_id") or "")
        if event_id in seen:
            chosen.append(event)
            continue
        seen.add(event_id)
        if not event.get("completed") or event.get("neutral_site"):
            event["summary_ok"] = True
            event["attendance"] = None
            chosen.append(event)
            continue
        try:
            summary = get_json(SUMMARY.format(event_id=event_id))
        except EspnUnavailable:
            event["summary_ok"] = False
            event["attendance"] = None
            chosen.append(event)
            continue
        info = summary.get("gameInfo") if isinstance(summary, dict) else None
        event["attendance"] = info.get("attendance") if isinstance(info, dict) else None
        event["summary_ok"] = True
        if espn_attendance_value(event["attendance"]) is not None:
            event["source"] = ESPN_SOURCE
        chosen.append(event)
        sleep(0.08)
    return chosen


def load_scoreboard_events(year: int, *, get_json, sleep) -> list[dict]:
    found: dict[str, dict] = {}
    saw_success = False
    # Regular season is scanned in full so a blank week does not hide a later one.
    # Postseason stops after two empty weeks.
    passes = ((2, range(1, 17), False), (3, range(1, 6), True))
    for season_type, weeks, stop_when_empty in passes:
        empty = 0
        for week in weeks:
            url = SCOREBOARD.format(season_type=season_type, week=week, year=year)
            try:
                payload = get_json(url)
            except EspnUnavailable:
                empty += 1
                if stop_when_empty and empty >= 2:
                    break
                continue
            if not isinstance(payload, dict):
                raise EspnUnavailable("ESPN scoreboard response was not a JSON object.")
            saw_success = True
            rows = payload.get("events") or []
            if not rows:
                empty += 1
                if stop_when_empty and empty >= 2:
                    break
                continue
            empty = 0
            for row in rows:
                parsed = parse_scoreboard_event(row, week)
                if parsed and parsed["espn_id"]:
                    found[parsed["espn_id"]] = parsed
            sleep(0.15)
    if not found and not saw_success:
        raise EspnUnavailable("ESPN scoreboard could not be read.")
    return list(found.values())


def parse_scoreboard_event(event: dict, week: int) -> dict | None:
    if not isinstance(event, dict) or event.get("id") is None:
        return None
    competition = (event.get("competitions") or [{}])[0]
    if not isinstance(competition, dict):
        competition = {}
    status = (event.get("status") or {}).get("type") or {}
    competitors = competition.get("competitors") or []
    home = next((row for row in competitors if isinstance(row, dict) and row.get("homeAway") == "home"), None)
    away = next((row for row in competitors if isinstance(row, dict) and row.get("homeAway") == "away"), None)
    return {
        "espn_id": str(event.get("id")),
        "week": week,
        "date": event.get("date"),
        "completed": bool(isinstance(status, dict) and status.get("completed")),
        "neutral_site": bool(competition.get("neutralSite")),
        "home_id": _team_id(home),
        "away_id": _team_id(away),
        "attendance": None,
        "source": None,
        "summary_ok": False,
    }


def curl_json(url: str) -> dict:
    """GET JSON the way the 2026 ESPN pull did: curl, default user agent, retries."""
    if shutil.which("curl") is None:
        raise EspnUnavailable("curl is not installed, so ESPN attendance could not be read.")
    last = "empty response"
    for attempt in range(4):
        try:
            raw = subprocess.check_output(
                ["curl", "-sS", "--max-time", "45", url],
                text=True,
                stderr=subprocess.STDOUT,
            )
        except subprocess.CalledProcessError as exc:
            last = (exc.output or "").strip()[:200] or f"curl exited {exc.returncode}"
            time.sleep(0.6 * (attempt + 1))
            continue
        except OSError as exc:
            raise EspnUnavailable(f"Could not run curl: {exc}") from exc
        if not raw.strip():
            last = "empty response"
            time.sleep(0.6 * (attempt + 1))
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            last = "response was not JSON"
            time.sleep(0.6 * (attempt + 1))
            continue
        if not isinstance(data, dict):
            raise EspnUnavailable("ESPN response was not a JSON object.")
        return data
    raise EspnUnavailable(f"ESPN request failed ({last}).")


def print_fill_summary(snapshot: dict) -> None:
    games = [game for game in snapshot.get("games") or [] if isinstance(game, dict)]
    completed = [game for game in games if game.get("completed") and not game.get("neutral_site")]
    espn = sum(1 for game in completed if game.get("attendance_source") == ESPN_SOURCE and game.get("attendance") is not None)
    cfbd = sum(1 for game in completed if game.get("attendance_source") == CFBD_SOURCE and game.get("attendance") is not None)
    missing = sum(1 for game in completed if game.get("attendance") is None)
    print(
        f"Completed non-neutral games: {len(completed)}. "
        f"Attendance from CFBD: {cfbd}. From ESPN summaries: {espn}. Still null: {missing}."
    )


def _restore_prior(game: dict, prior: dict[int, int]) -> bool:
    previous = prior.get(game.get("id"))
    if previous is None:
        game["attendance"] = None
        game.pop("attendance_source", None)
        return False
    game["attendance"] = previous
    game["attendance_source"] = ESPN_SOURCE
    return True


def _add_warning(snapshot: dict, message: str) -> None:
    warnings = snapshot.setdefault("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        snapshot["warnings"] = warnings
    if message not in warnings:
        warnings.append(message)


def _team_id(competitor: dict | None) -> int | None:
    if not isinstance(competitor, dict):
        return None
    team = competitor.get("team")
    if not isinstance(team, dict):
        return None
    return _as_int_id(team.get("id"))


def _as_int_id(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _parse_time(value) -> datetime | None:
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


if __name__ == "__main__":
    main()
