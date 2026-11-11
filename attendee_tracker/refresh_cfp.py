"""Fetch CFP rankings and write data/cfp/{year}.json plus the projected bracket.

ESPN is the source. CFBD is used only when ESPN has no committee poll for
the season and a CFBD client is passed in. The command does not need
CFBD_API_KEY for the ESPN path.

Usage:
    python -m attendee_tracker.refresh_cfp
    python -m attendee_tracker.refresh_cfp --year 2026
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable

from attendee_tracker.bracket import bracket_document
from attendee_tracker.cfp import (
    ESPN_SITE_RANKINGS,
    bracket_path,
    cfp_path,
    core_week_url,
    merge_document,
    parse_cfp_ranking,
    select_site_cfp,
    snapshot_from_cfbd_weeks,
    team_catalog,
)
from attendee_tracker.config import load_dotenv, season_year
from attendee_tracker.store import write_json


class CfpUnavailable(RuntimeError):
    """ESPN had no usable committee poll and the backup did not either."""


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Fetch the CFP rankings for one season from ESPN.")
    parser.add_argument("--year", type=int, default=None, help="Season year. Defaults to SEASON_YEAR or 2026.")
    args = parser.parse_args(argv)
    year = args.year if args.year is not None else season_year()
    try:
        document = refresh_cfp(year)
    except CfpUnavailable as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    print(
        f"Wrote {cfp_path(year)} "
        f"({document.get('released_at')}, week {document.get('week')}, "
        f"{len(document.get('teams') or [])} teams)"
    )


def refresh_cfp(
    year: int,
    *,
    get_json: Callable[[str], dict] | None = None,
    cfbd_weeks: list | None = None,
    write: bool = True,
) -> dict:
    """Pull ESPN, fall back to CFBD weeks when those are passed in, and store the file.

    A failed refresh leaves the previous file in place.
    """
    getter = get_json or fetch_json
    catalog = team_catalog(year)
    snapshots: list[dict] = []
    source = "espn"
    source_url = ESPN_SITE_RANKINGS
    espn_error = None
    try:
        site = getter(ESPN_SITE_RANKINGS)
        ranking = select_site_cfp(site, year)
        if ranking is not None:
            parsed = parse_cfp_ranking(ranking, catalog, season=year)
            if parsed is not None:
                snapshots.append(parsed)
    except (CfpUnavailable, OSError, ValueError, json.JSONDecodeError) as exc:
        espn_error = exc

    for season_type, weeks in ((2, range(10, 17)), (3, range(1, 3))):
        for week in weeks:
            url = core_week_url(year, season_type, week)
            try:
                payload = getter(url)
            except (CfpUnavailable, OSError, ValueError, json.JSONDecodeError):
                continue
            parsed = parse_cfp_ranking(payload, catalog, season=year)
            if parsed is not None and parsed.get("season") == year:
                snapshots.append(_fill_names(parsed, catalog, getter))

    document = merge_document(year, snapshots, source=source, source_url=source_url)
    if document is None and cfbd_weeks:
        backup = snapshot_from_cfbd_weeks(cfbd_weeks, year, catalog)
        if backup is not None:
            document = merge_document(
                year,
                [backup],
                source="cfbd",
                source_url="https://api.collegefootballdata.com/rankings",
            )
    if document is None:
        detail = f" ESPN request failed: {espn_error}." if espn_error else ""
        raise CfpUnavailable(
            f"No CFP ranking for {year} on or after {year}-11's first release.{detail} "
            "The previous file, if any, was left in place."
        )
    if write:
        write_json(cfp_path(year), document)
        if year == 2026:
            write_json(bracket_path(year), bracket_document(document))
    return document


def _fill_names(snapshot: dict, catalog: dict, getter: Callable[[str], dict]) -> dict:
    """Fill a school name from the season cache or, if needed, the ESPN team document."""
    teams = []
    for team in snapshot.get("teams") or []:
        row = dict(team)
        if row.get("school") and row.get("conference"):
            teams.append(row)
            continue
        known = catalog.get(row.get("espn_team_id"))
        if known:
            row["school"] = row.get("school") or known.get("school")
            row["conference"] = row.get("conference") or known.get("conference")
            if row.get("team_id") is None:
                row["team_id"] = row.get("espn_team_id")
        elif row.get("espn_team_id") is not None and not row.get("school"):
            url = (
                "https://sports.core.api.espn.com/v2/sports/football/leagues/"
                f"college-football/teams/{row['espn_team_id']}?lang=en"
            )
            try:
                payload = getter(url)
            except (CfpUnavailable, OSError, ValueError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                name = payload.get("location") or payload.get("displayName") or payload.get("shortDisplayName")
                if isinstance(name, str) and name.strip():
                    row["school"] = name.strip()
        if row.get("school"):
            teams.append(row)
    snapshot["teams"] = teams
    return snapshot


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "attendee-stats-cfp/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise CfpUnavailable(f"ESPN returned {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise CfpUnavailable(f"ESPN could not be reached: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise CfpUnavailable("ESPN response was not a JSON object.")
    return payload


def refresh_from_current_season(year: int, *, cfbd_weeks: list | None = None) -> None:
    """Used by the weekly refresh. A CFP miss does not roll back attendance."""
    try:
        document = refresh_cfp(year, cfbd_weeks=cfbd_weeks)
    except CfpUnavailable as exc:
        print(f"CFP rankings were not updated: {exc}")
        return
    print(f"CFP rankings updated for {year}: {document.get('released_at')} week {document.get('week')}")


if __name__ == "__main__":
    main()
