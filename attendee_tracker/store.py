"""JSON cache layout under data/.

Season snapshots in data/live/ are committed so the site runs without a
CFBD key. Raw responses, quota logs, and .env stay out of git.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from attendee_tracker.config import data_dir, sample_path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    value = moment or utc_now()
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def live_path(year: int) -> Path:
    return data_dir() / "live" / f"{year}.json"


def raw_dir(year: int | None = None) -> Path:
    base = data_dir() / "raw"
    return base if year is None else base / str(year)


def meta_path() -> Path:
    return data_dir() / "cache_meta.json"


def quota_path() -> Path:
    return data_dir() / "quota_log.jsonl"


def read_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_meta() -> dict:
    payload = read_json(meta_path())
    return payload if isinstance(payload, dict) else {}


def save_meta(payload: dict) -> None:
    write_json(meta_path(), payload)


def append_quota(endpoint: str, status: int, year: int | None) -> None:
    path = quota_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": iso(), "endpoint": endpoint, "status": status, "year": year}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def quota_calls_this_month(now: datetime | None = None) -> int:
    path = quota_path()
    if not path.is_file():
        return 0
    moment = now or utc_now()
    prefix = moment.strftime("%Y-%m")
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("ts", "")).startswith(prefix) and int(row.get("status") or 0) < 400:
            count += 1
    return count


def load_sample() -> dict:
    payload = read_json(sample_path())
    if not isinstance(payload, dict):
        raise FileNotFoundError(
            f"Sample fixture is missing at {sample_path()}. "
            "Regenerate it with python -m attendee_tracker.sample_data"
        )
    return payload


def load_live(year: int) -> dict | None:
    payload = read_json(live_path(year))
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError(f"Live cache {live_path(year)} is not a JSON object.")
    return payload
