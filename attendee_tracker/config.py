"""Paths, season year, and environment loading.

The API key is read from the environment only. Nothing in this module
writes secrets to disk.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEASON = 2026
DEFAULT_PORT = 8742

# Daily cron is the intended cadence. A second run inside this window
# reuses the games cache unless --force is passed.
DEFAULT_MIN_INTERVAL_HOURS = 18
TEAMS_TTL_DAYS = 7
VENUES_TTL_DAYS = 14

# Free CFBD tier, documented at https://collegefootballdata.com/api-tiers
FREE_TIER_MONTHLY_CALLS = 1000


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines into the environment without overriding real env."""
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def season_year() -> int:
    raw = os.environ.get("SEASON_YEAR", str(DEFAULT_SEASON)).strip()
    try:
        year = int(raw)
    except ValueError as exc:
        raise SystemExit(f"SEASON_YEAR must be an integer, got {raw!r}") from exc
    if year < 1869 or year > 2100:
        raise SystemExit(f"SEASON_YEAR {year} is outside the supported range.")
    return year


def api_key() -> str:
    return os.environ.get("CFBD_API_KEY", "").strip()


def data_dir() -> Path:
    override = os.environ.get("ATTENDEE_DATA_DIR", "").strip()
    return Path(override) if override else ROOT / "data"


def sample_path() -> Path:
    return ROOT / "data" / "sample_season.json"


def port() -> int:
    raw = os.environ.get("PORT", str(DEFAULT_PORT)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"PORT must be an integer, got {raw!r}") from exc
