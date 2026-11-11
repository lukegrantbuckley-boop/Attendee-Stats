"""2026-27 bowl slate. Numbers in the business block need a source URL."""

from __future__ import annotations

from datetime import date, datetime, timezone

from attendee_tracker.cfp import bracket_path
from attendee_tracker.store import read_json

SELECTION_DAY = date(2026, 12, 6)


class BowlsError(Exception):
    def __init__(self, code: str, message: str, status: int = 404):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def bowls_path(year: int):
    from attendee_tracker.config import data_dir

    return data_dir() / "bowls" / f"{year}.json"


def load_bowls_file(year: int) -> dict:
    payload = read_json(bowls_path(year))
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
        raise BowlsError(
            "no_bowls",
            f"No bowl file for {year}. Matchups and business figures were not invented.",
        )
    return payload


def business_numbers_without_sources(payload: dict) -> list[str]:
    """Paths of numeric business values that have no http(s) source URL."""
    missing: list[str] = []

    def urls(node: dict) -> list[str]:
        found = node.get("source_urls")
        if not isinstance(found, list):
            return []
        return [item for item in found if isinstance(item, str) and item.startswith("http")]

    def walk(node, path: str, inherited: list[str]) -> None:
        if isinstance(node, dict):
            here = urls(node) or inherited
            for key, value in node.items():
                if key == "source_urls":
                    continue
                walk(value, f"{path}.{key}", here)
            return
        if isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]", inherited)
            return
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)) and not inherited:
            missing.append(path)

    for index, game in enumerate(payload.get("games") or []):
        if isinstance(game, dict):
            walk(game.get("business"), f"games[{index}].business", [])
    return missing


def _selection_label(payload: dict, today: date) -> tuple[str, str | None]:
    """Projected until Selection Day, then official only when matchups are stored."""
    if today < SELECTION_DAY or not payload.get("official_matchups"):
        note = None
        if today >= SELECTION_DAY and not payload.get("official_matchups"):
            note = "Selection Day has passed, but official matchups are not in this cache, so the field stays projected."
        return "Projected", note
    return "Official", None


def public_bowls(year: int, *, today: date | None = None) -> dict:
    payload = load_bowls_file(year)
    moment = today or datetime.now(timezone.utc).date()
    label, note = _selection_label(payload, moment)
    bracket = read_json(bracket_path(year))
    if isinstance(bracket, dict):
        bracket = dict(bracket)
        bracket["label"] = label
        bracket["status"] = label.casefold()
        if note:
            bracket["note"] = note
    return {
        "season": payload.get("season", year),
        "label": label,
        "status_note": note,
        "selection_day": payload.get("selection_day"),
        "as_of": (bracket or {}).get("as_of") if isinstance(bracket, dict) else None,
        "projection": payload.get("projection"),
        "schedule_sources": payload.get("schedule_sources") or [],
        "omitted": payload.get("omitted") or [],
        "unassigned_quarterfinal_projections": payload.get("unassigned_quarterfinal_projections"),
        "explainers": payload.get("explainers") or {},
        "bracket": bracket,
        "games": payload.get("games") or [],
    }
