"""Optional CFBD double-check for the ESPN-filled season cache.

ESPN stays the primary source. This module never rewrites the cache. After a
refresh, it pulls two CFBD endpoints (games and records, two API calls) and
flags values that look way off:

* final score mismatches,
* win/loss record mismatches,
* attendance gaps above both an absolute and a relative threshold, only when
  CFBD actually has a crowd figure (CFBD often leaves 2026 attendance empty).

Run: ``python -m attendee_tracker.cfbd_check [--year 2026] [--json PATH]``.
Without ``CFBD_API_KEY`` the check is skipped and exits 0, so it can sit in any
refresh routine. Exit code 3 means mismatches were flagged for a human look.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Callable

from attendee_tracker.config import api_key, load_dotenv, season_year
from attendee_tracker.store import live_path, read_json

CFBD_BASE = "https://api.collegefootballdata.com"
ATTENDANCE_ABS_GAP = 5000
ATTENDANCE_REL_GAP = 0.15


def _cfbd_get(path: str, key: str) -> list:
    request = urllib.request.Request(
        f"{CFBD_BASE}{path}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    return payload if isinstance(payload, list) else []


def _int(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def attendance_looks_off(ours: int | None, theirs: int | None) -> bool:
    if not ours or not theirs:
        return False
    gap = abs(ours - theirs)
    return gap >= ATTENDANCE_ABS_GAP and gap / max(ours, theirs) >= ATTENDANCE_REL_GAP


def compare(snapshot: dict, cfbd_games: list, cfbd_records: list) -> list[dict]:
    """Return flags. Each flag names the kind, the item, our value, and CFBD's."""
    flags: list[dict] = []
    theirs = {_int(g.get("id")): g for g in cfbd_games if isinstance(g, dict)}
    for game in snapshot.get("games") or []:
        if not isinstance(game, dict) or not game.get("completed"):
            continue
        other = theirs.get(_int(game.get("id")))
        if not other or not other.get("completed"):
            continue
        label = f"{game.get('away_team')} at {game.get('home_team')} (week {game.get('week')})"
        ours_score = (_int(game.get("home_points")), _int(game.get("away_points")))
        cfbd_score = (_int(other.get("homePoints")), _int(other.get("awayPoints")))
        if None not in ours_score and None not in cfbd_score and ours_score != cfbd_score:
            flags.append({"kind": "score", "game_id": game.get("id"), "item": label,
                          "ours": f"{ours_score[0]}-{ours_score[1]}", "cfbd": f"{cfbd_score[0]}-{cfbd_score[1]}"})
        if game.get("neutral_site"):
            continue
        ours_att, cfbd_att = _int(game.get("attendance")), _int(other.get("attendance"))
        if attendance_looks_off(ours_att, cfbd_att):
            flags.append({"kind": "attendance", "game_id": game.get("id"), "item": label,
                          "ours": ours_att, "cfbd": cfbd_att,
                          "our_source": game.get("attendance_source")})

    cfbd_by_team = {_int(r.get("teamId")): r for r in cfbd_records if isinstance(r, dict)}
    for record in snapshot.get("records") or []:
        if not isinstance(record, dict):
            continue
        other = cfbd_by_team.get(_int(record.get("team_id")))
        # Only FBS records are kept complete in the cache; lower-division
        # records there count only games against FBS teams.
        if not other or other.get("classification") != "fbs":
            continue
        total = other.get("total") or {}
        ours = (_int(record.get("wins")), _int(record.get("losses")))
        cfbd = (_int(total.get("wins")), _int(total.get("losses")))
        if None not in ours and None not in cfbd and ours != cfbd:
            flags.append({"kind": "record", "team_id": record.get("team_id"), "item": record.get("team"),
                          "ours": f"{ours[0]}-{ours[1]}", "cfbd": f"{cfbd[0]}-{cfbd[1]}"})
    return flags


def run_check(year: int, key: str, get: Callable[[str, str], list] = _cfbd_get) -> dict:
    snapshot = read_json(live_path(year))
    if not isinstance(snapshot, dict):
        return {"year": year, "skipped": "no live cache", "flags": []}
    games = get(f"/games?year={year}&seasonType=regular", key)
    records = get(f"/records?year={year}", key)
    with_att = sum(1 for g in games if isinstance(g, dict) and g.get("completed") and _int(g.get("attendance")))
    return {
        "year": year,
        "cfbd_games": len(games),
        "cfbd_games_with_attendance": with_att,
        "cfbd_calls": 2,
        "flags": compare(snapshot, games, records),
    }


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Flag ESPN-cache values that CFBD disagrees with. Never writes the cache.")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--json", type=Path, default=None, help="Also write the report here.")
    args = parser.parse_args(argv)
    year = args.year or season_year()
    key = api_key()
    if not key:
        print("CFBD_API_KEY is not set. Skipping the CFBD double-check; ESPN data stands.")
        return
    try:
        report = run_check(year, key)
    except Exception as exc:  # network or API trouble must never block a refresh
        print(f"CFBD double-check failed ({type(exc).__name__}). ESPN data stands.", file=sys.stderr)
        return
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    print(f"CFBD double-check {year}: {report.get('cfbd_games', 0)} CFBD games, "
          f"{report.get('cfbd_games_with_attendance', 0)} with attendance, {len(report['flags'])} flags.")
    for flag in report["flags"]:
        print(f"  [{flag['kind']}] {flag['item']}: ours {flag['ours']}, CFBD {flag['cfbd']}")
    if report["flags"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
