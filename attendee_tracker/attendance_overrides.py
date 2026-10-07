"""Published attendance corrections that outlive an ESPN refresh.

``data/attendance_overrides.json`` is the source of truth. A weekly refresh
rewrites ``data/live/{year}.json`` from CFBD and ESPN, which puts a bad
``gameInfo.attendance`` of 0 back. This module merges the approved figures
onto a snapshot after that fill. A null attendance in the file means the
game is not reported. It is not stored as a crowd of 0.

Only games listed in the file are touched. Nothing here estimates a crowd.
"""

from __future__ import annotations

import json
from pathlib import Path

from attendee_tracker.config import ROOT

OFFICIAL_SOURCE = "official"
OVERRIDES_PATH = ROOT / "data" / "attendance_overrides.json"


def load_overrides(path: Path | None = None) -> list[dict]:
    """Return validated override rows. A missing file means there are none."""
    source = path or OVERRIDES_PATH
    if not source.is_file():
        return []
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Attendance overrides in {source} must be a JSON object.")
    rows = payload.get("overrides")
    if not isinstance(rows, list):
        raise ValueError(f"Attendance overrides in {source} need an overrides list.")
    parsed = [_parse_override(row, index) for index, row in enumerate(rows, start=1)]
    seen: set[tuple[int, int]] = set()
    for row in parsed:
        key = (row["season"], row["game_id"])
        if key in seen:
            raise ValueError(
                f"Duplicate attendance override for season {row['season']} game {row['game_id']}."
            )
        seen.add(key)
    return parsed


def override_is_unreported(game: dict) -> bool:
    """True when an approved override says this game has no official crowd.

    ESPN's 0 is not filled in for that game. A later merge still clears a 0
    if one was already stored.
    """
    if not isinstance(game, dict):
        return False
    row = _matching_override(game, game.get("season"))
    return row is not None and row["attendance"] is None


def apply_attendance_overrides(snapshot: dict, overrides: list[dict] | None = None) -> dict:
    """Replace feed attendance for listed games. Other games are left alone.

    A positive override stores the published crowd and its source URL.
    A null override clears the crowd so the game is not reported.
    """
    if not isinstance(snapshot, dict):
        return snapshot
    season = snapshot.get("season")
    if isinstance(season, bool) or not isinstance(season, int):
        return snapshot
    rows = [row for row in (overrides if overrides is not None else load_overrides()) if row["season"] == season]
    if not rows:
        return snapshot
    games = [game for game in snapshot.get("games") or [] if isinstance(game, dict)]
    changed: list[str] = []
    for row in rows:
        game = _game_for_override(snapshot, games, row)
        if game is None:
            continue
        if _apply_one(game, row):
            changed.append(_label(row))
    if changed:
        _add_warning(
            snapshot,
            (
                "Official attendance overrides replaced the feed figure for "
                + ", ".join(changed)
                + ". Published crowds were used where one was reported. "
                "No attendance was estimated."
            ),
        )
    return snapshot


def _game_for_override(snapshot: dict, games: list[dict], row: dict) -> dict | None:
    matches = [game for game in games if game.get("id") == row["game_id"]]
    if not matches:
        return None
    if len(matches) != 1:
        _add_warning(
            snapshot,
            (
                f"Official attendance override for {_label(row)} matched more than one game "
                "and was not applied."
            ),
        )
        return None
    game = matches[0]
    reason = _identity_problem(game, row)
    if reason:
        _add_warning(
            snapshot,
            f"Official attendance override for {_label(row)} was not applied ({reason}).",
        )
        return None
    return game


def _identity_problem(game: dict, row: dict) -> str | None:
    game_season = game.get("season")
    if game_season is not None and game_season != row["season"]:
        return "the game is from a different season"
    if game.get("home_team") != row["home_team"] or game.get("away_team") != row["away_team"]:
        return "home and away teams do not match the override"
    if game.get("week") != row["week"]:
        return "the week does not match the override"
    if game.get("neutral_site"):
        return "the game is on a neutral site"
    if not game.get("completed"):
        return "the game is not completed"
    return None


def _matching_override(game: dict, season) -> dict | None:
    if isinstance(season, bool) or not isinstance(season, int):
        return None
    if game.get("season") not in (None, season):
        return None
    for row in load_overrides():
        if row["season"] != season or row["game_id"] != game.get("id"):
            continue
        if _identity_problem(game, row):
            return None
        return row
    return None


def _apply_one(game: dict, row: dict) -> bool:
    note = row["note"]
    if row["attendance"] is None:
        changed = (
            game.get("attendance") is not None
            or "attendance_source" in game
            or "attendance_source_url" in game
            or "attendance_source_urls" in game
            or game.get("attendance_source_note") != note
        )
        if not changed:
            return False
        game["attendance"] = None
        game.pop("attendance_source", None)
        game.pop("attendance_source_url", None)
        game.pop("attendance_source_urls", None)
        if note:
            game["attendance_source_note"] = note
        else:
            game.pop("attendance_source_note", None)
        return True

    urls = list(row["sources"])
    desired_note = note if note else None
    changed = (
        game.get("attendance") != row["attendance"]
        or game.get("attendance_source") != OFFICIAL_SOURCE
        or game.get("attendance_source_url") != urls[0]
        or game.get("attendance_source_urls") != urls
        or game.get("attendance_source_note") != desired_note
    )
    if not changed:
        return False
    game["attendance"] = row["attendance"]
    game["attendance_source"] = OFFICIAL_SOURCE
    game["attendance_source_url"] = urls[0]
    game["attendance_source_urls"] = urls
    if desired_note:
        game["attendance_source_note"] = desired_note
    else:
        game.pop("attendance_source_note", None)
    return True


def _label(row: dict) -> str:
    matchup = f"{row['home_team']} vs {row['away_team']}"
    if row["attendance"] is None:
        return f"{matchup} (not reported)"
    return f"{matchup} ({row['attendance']:,})"


def _parse_override(row, index: int) -> dict:
    if not isinstance(row, dict):
        raise ValueError(f"Attendance override {index} is not an object.")
    season = row.get("season")
    game_id = row.get("game_id")
    week = row.get("week")
    home = row.get("home_team")
    away = row.get("away_team")
    if isinstance(season, bool) or not isinstance(season, int):
        raise ValueError(f"Attendance override {index} needs an integer season.")
    if isinstance(game_id, bool) or not isinstance(game_id, int):
        raise ValueError(f"Attendance override {index} needs an integer game_id.")
    if isinstance(week, bool) or not isinstance(week, int):
        raise ValueError(f"Attendance override {index} needs an integer week.")
    if not isinstance(home, str) or not home.strip() or not isinstance(away, str) or not away.strip():
        raise ValueError(f"Attendance override {index} needs home_team and away_team.")
    if "attendance" not in row:
        raise ValueError(f"Attendance override {index} needs attendance.")
    attendance = row.get("attendance")
    if attendance is not None and (isinstance(attendance, bool) or not isinstance(attendance, int) or attendance <= 0):
        raise ValueError(
            f"Attendance override for {home} vs {away} must be a positive integer or null. "
            "Zero is not a published crowd."
        )
    sources = row.get("sources") or []
    if not isinstance(sources, list) or any(not isinstance(item, str) or not item.startswith("https://") for item in sources):
        raise ValueError(f"Attendance override for {home} vs {away} needs https source URLs.")
    if attendance is not None and not sources:
        raise ValueError(f"Attendance override for {home} vs {away} needs a source URL.")
    note = row.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError(f"Attendance override for {home} vs {away} has a note that is not text.")
    cleaned_note = note.strip() if isinstance(note, str) else ""
    return {
        "season": season,
        "game_id": game_id,
        "week": week,
        "home_team": home.strip(),
        "away_team": away.strip(),
        "attendance": attendance,
        "sources": list(sources),
        "note": cleaned_note or None,
    }


def _add_warning(snapshot: dict, message: str) -> None:
    warnings = snapshot.setdefault("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        snapshot["warnings"] = warnings
    if message not in warnings:
        warnings.append(message)
