"""Daily CFBD refresh.

One games call for the whole FBS season re-pulls every week, including the
recent weeks where attendance fills in late. Team metadata refreshes weekly
and venues every 14 days, so a daily cron stays well under the free tier of
1,000 calls per month.

A one-time backfill (``--years 2016-2025`` or repeated ``--year``) costs
about 3–5 calls per season: games, records, rankings, and teams when that
season's team cache is missing or older than 7 days. Venues are shared
across the seasons in one run. Daily cron should refresh the current
season only.

This module does not install a cron job. The README has the 10:00
America/New_York schedule.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone

from attendee_tracker.cfbd_client import CfbdClient, CfbdError, MissingApiKey
from attendee_tracker.config import (
    DEFAULT_MIN_INTERVAL_HOURS,
    FREE_TIER_MONTHLY_CALLS,
    TEAMS_TTL_DAYS,
    VENUES_TTL_DAYS,
    api_key,
    load_dotenv,
    season_year,
)
from attendee_tracker.normalize import (
    normalize_game,
    normalize_rankings,
    normalize_record,
    normalize_team,
    normalize_venue,
)
from attendee_tracker.store import (
    append_quota,
    iso,
    live_path,
    load_meta,
    quota_calls_this_month,
    raw_dir,
    read_json,
    save_meta,
    utc_now,
    write_json,
)

MISSING_KEY_MESSAGE = """CFBD_API_KEY is not set.
Copy .env.example to .env and paste a key from https://collegefootballdata.com/key
Attendee Tracker will not invent attendance figures.
The site can still be reviewed with the labeled sample fixture. Start it with:
  python -m attendee_tracker.serve
"""

# A full backfill of a decade is fine. A century would blow the free tier.
MAX_INGEST_YEARS = 30
_YEAR_RANGE = re.compile(r"(\d{4})\s*[-:]\s*(\d{4})")


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Refresh the CFBD cache for Attendee Tracker.")
    parser.add_argument(
        "--year",
        type=int,
        action="append",
        dest="years",
        default=None,
        help="Season year. Repeat for several seasons. Defaults to SEASON_YEAR or 2026.",
    )
    parser.add_argument(
        "--years",
        dest="year_range",
        default=None,
        help="Inclusive range, for example 2016-2025. One-time backfill, not the daily cron.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh even if the cache is inside the freshness window.",
    )
    parser.add_argument(
        "--min-interval-hours",
        type=float,
        default=DEFAULT_MIN_INTERVAL_HOURS,
        help="Skip the refresh when games were fetched more recently than this. Default: 18.",
    )
    args = parser.parse_args(argv)
    years = resolve_years(args.years, args.year_range, season_year())
    key = api_key()
    if not key:
        print(MISSING_KEY_MESSAGE, file=sys.stderr)
        raise SystemExit(2)

    client = CfbdClient(
        key,
        on_call=lambda endpoint, status, call_year: append_quota(endpoint, status, call_year),
    )
    try:
        calls = run_ingest_years(
            years=years,
            force=args.force,
            min_interval_hours=args.min_interval_hours,
            client=client,
        )
    except MissingApiKey:
        print(MISSING_KEY_MESSAGE, file=sys.stderr)
        raise SystemExit(2)
    except CfbdError as exc:
        print(str(exc), file=sys.stderr)
        print(
            "Seasons that failed kept their previous cache. No attendance figures were invented.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    month_calls = quota_calls_this_month()
    print(f"CFBD calls this run: {calls}")
    print(
        f"Successful CFBD calls logged this month: {month_calls} "
        f"(free tier guidance {FREE_TIER_MONTHLY_CALLS}/month)"
    )
    if month_calls >= int(FREE_TIER_MONTHLY_CALLS * 0.8):
        print("Warning: this key is at or above 80% of the free monthly call budget.", file=sys.stderr)


def resolve_years(years: list[int] | None, year_range: str | None, default_year: int) -> list[int]:
    """Union of repeated ``--year`` values and one ``--years`` range.

    Neither flag means the configured season only, which is what daily
    cron should keep using.
    """
    chosen: set[int] = set(years or [])
    if year_range:
        chosen.update(_parse_year_range(year_range))
    if not chosen:
        _check_year(default_year)
        return [default_year]
    for year in chosen:
        _check_year(year)
    ordered = sorted(chosen)
    if len(ordered) > MAX_INGEST_YEARS:
        raise SystemExit(
            f"Refusing to ingest {len(ordered)} seasons in one run (limit {MAX_INGEST_YEARS}). "
            "Split the backfill. A season costs about 3–5 CFBD calls, and venues are shared."
        )
    return ordered


def run_ingest_years(*, years: list[int], force: bool, min_interval_hours: float, client) -> int:
    """Refresh each season. Venues are fetched at most once for the run."""
    venue_cache: dict | None = {} if len(years) > 1 else None
    total = 0
    failures: list[str] = []
    for year in years:
        if len(years) > 1:
            print(f"--- Season {year} ---")
        try:
            total += run_ingest(
                year=year,
                force=force,
                min_interval_hours=min_interval_hours,
                client=client,
                venue_cache=venue_cache,
            )
        except CfbdError as exc:
            failures.append(f"{year}: {exc}")
            print(str(exc), file=sys.stderr)
            print(
                f"The previous cache for {year}, if any, was left in place.",
                file=sys.stderr,
            )
    if failures:
        detail = "; ".join(failures)
        raise CfbdError(
            f"One or more seasons failed to refresh ({detail}). No attendance figures were invented."
        )
    return total


def run_ingest(
    *,
    year: int,
    force: bool,
    min_interval_hours: float,
    client,
    venue_cache: dict | None = None,
) -> int:
    meta = load_meta()
    seasons = meta.setdefault("seasons", {})
    season_meta = seasons.setdefault(str(year), {})
    now = utc_now()
    if not force and _fresh(season_meta.get("games_fetched_at"), hours=min_interval_hours, now=now):
        print(
            f"Cache is fresh. Games for {year} were fetched at {season_meta['games_fetched_at']}. "
            "Use --force to refresh anyway."
        )
        print(f"Live snapshot: {live_path(year)}")
        return 0

    calls = 0
    warnings: list[str] = []

    def pull(label: str, name: str, fetch, cache_year: int | None, required: bool) -> list:
        nonlocal calls
        previous = _read_raw(cache_year, name)
        try:
            payload = fetch()
        except CfbdError as exc:
            if required and not previous:
                raise
            if previous:
                warnings.append(f"{label} refresh failed ({exc}). Showing the previous cache.")
                print(warnings[-1], file=sys.stderr)
                return previous
            warnings.append(f"{label} refresh failed ({exc}). Continuing without it.")
            print(warnings[-1], file=sys.stderr)
            return []
        if not isinstance(payload, list):
            raise CfbdError(f"CFBD {label} response was not a list.")
        calls += 1
        _write_raw(cache_year, name, payload)
        print(f"Fetched {label}: {len(payload)} rows")
        return payload

    games = pull("games", "games.json", lambda: client.fetch_games(year), year, True)
    records = pull("records", "records.json", lambda: client.fetch_records(year), year, False)
    rankings = pull("rankings", "rankings.json", lambda: client.fetch_rankings(year), year, False)

    teams_due = force or not _fresh(season_meta.get("teams_fetched_at"), hours=TEAMS_TTL_DAYS * 24, now=now)
    if teams_due or not _read_raw(year, "teams.json"):
        teams = pull("teams", "teams.json", lambda: client.fetch_teams(year), year, True)
        season_meta["teams_fetched_at"] = iso(now)
    else:
        teams = _read_raw(year, "teams.json") or []
        print(f"Teams cache is under {TEAMS_TTL_DAYS} days old. Skipping /teams/fbs.")

    # A multi-year run fetches /venues at most once. Later seasons reuse
    # that payload even when --force is set. Teams stay on the per-season TTL.
    if venue_cache is not None and "rows" in venue_cache:
        venues = venue_cache["rows"]
        print("Reusing venues already fetched in this run.")
    else:
        venues_due = force or not _fresh(meta.get("venues_fetched_at"), hours=VENUES_TTL_DAYS * 24, now=now)
        if venues_due or not _read_raw(None, "venues.json"):
            venues = pull("venues", "venues.json", lambda: client.fetch_venues(), None, True)
            meta["venues_fetched_at"] = iso(now)
        else:
            venues = _read_raw(None, "venues.json") or []
            print(f"Venues cache is under {VENUES_TTL_DAYS} days old. Skipping /venues.")
        if venue_cache is not None:
            venue_cache["rows"] = venues

    snapshot = {
        "source": "cfbd",
        "synthetic": False,
        "notice": None,
        "season": year,
        "fetched_at": iso(now),
        "warnings": warnings,
        "calls_this_run": calls,
        "teams": [team for row in teams if (team := normalize_team(row))],
        "venues": [venue for row in venues if (venue := normalize_venue(row))],
        "games": [game for row in games if (game := normalize_game(row))],
        "records": [record for row in records if (record := normalize_record(row))],
        "rankings": normalize_rankings(rankings),
    }
    if not snapshot["teams"] or not snapshot["games"]:
        raise CfbdError("CFBD returned no FBS teams or no games. The live snapshot was not replaced.")

    write_json(live_path(year), snapshot)
    season_meta["games_fetched_at"] = iso(now)
    season_meta["records_fetched_at"] = iso(now)
    season_meta["rankings_fetched_at"] = iso(now)
    save_meta(meta)

    completed = [game for game in snapshot["games"] if game.get("completed") and not game.get("neutral_site")]
    missing = sum(1 for game in completed if game.get("attendance") is None)
    print(f"Season {year}")
    print(f"Teams: {len(snapshot['teams'])}")
    print(f"Games: {len(snapshot['games'])}")
    if completed:
        print(
            f"Completed non-neutral games with null attendance: "
            f"{missing} of {len(completed)} ({missing / len(completed):.0%})"
        )
    print(f"Wrote {live_path(year)}")
    return calls


def _parse_year_range(spec: str) -> list[int]:
    match = _YEAR_RANGE.fullmatch(spec.strip())
    if not match:
        raise SystemExit(
            "Use --years like 2016-2025 (inclusive). Repeat --year for individual seasons."
        )
    start, end = int(match.group(1)), int(match.group(2))
    if end < start:
        raise SystemExit(f"--years {spec} is reversed. Put the earlier season first, for example 2016-2025.")
    return list(range(start, end + 1))


def _check_year(year: int) -> None:
    if year < 1869 or year > 2100:
        raise SystemExit(f"Season year {year} is outside 1869–2100.")


def _read_raw(year: int | None, name: str) -> list | None:
    path = (raw_dir() / name) if year is None else (raw_dir(year) / name)
    payload = read_json(path)
    return payload if isinstance(payload, list) else None


def _write_raw(year: int | None, name: str, payload: list) -> None:
    path = (raw_dir() / name) if year is None else (raw_dir(year) / name)
    write_json(path, payload)


def _fresh(fetched_at: str | None, hours: float, now: datetime) -> bool:
    if not fetched_at:
        return False
    try:
        moment = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return now - moment < timedelta(hours=hours)


if __name__ == "__main__":
    main()
