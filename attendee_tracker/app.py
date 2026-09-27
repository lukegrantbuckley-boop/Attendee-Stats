"""HTTP API and static site for Attendee Tracker."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from attendee_tracker.assemble import assemble
from attendee_tracker.attendance_growth import rank_attendance_growth
from attendee_tracker.business_news import load_business_news, safe_slug
from attendee_tracker.config import load_dotenv, season_year
from attendee_tracker.history import HistoryWindowError, assemble_history, find_school, validate_window
from attendee_tracker.revenue import UnknownSchool, school_revenue
from attendee_tracker.store import live_path, load_live, load_sample, sample_path
from attendee_tracker.valuations import ValuationsError, list_valuations

WEB = Path(__file__).resolve().parent.parent / "web"

load_dotenv()
app = FastAPI(title="Attendee Tracker", docs_url=None, redoc_url=None)


@app.get("/api/health")
def health():
    year = season_year()
    return {
        "ok": True,
        "season": year,
        "has_live_cache": live_path(year).is_file(),
        "sample_available": sample_path().is_file(),
    }


@app.get("/api/season")
def season(year: int | None = None, demo: int = Query(0)):
    selected = year or season_year()
    if selected < 1869 or selected > 2100:
        return JSONResponse(
            {"error": "bad_year", "message": "Season year must be between 1869 and 2100."},
            status_code=400,
        )
    try:
        raw = _load_raw(selected, force_sample=bool(demo))
    except FileNotFoundError as exc:
        return JSONResponse({"error": "no_sample", "message": str(exc)}, status_code=500)
    except ValueError as exc:
        return JSONResponse(
            {
                "error": "bad_cache",
                "message": (
                    f"{exc} The sample fixture was not substituted, so synthetic attendance "
                    "is not shown in place of a broken live cache."
                ),
            },
            status_code=500,
        )
    if raw is None:
        sample_season = _sample_season()
        extra = f" The labeled sample fixture covers {sample_season}." if sample_season else ""
        return JSONResponse(
            {
                "error": "no_cache",
                "message": (
                    f"No CFBD cache for {selected}. Set CFBD_API_KEY and run "
                    "python -m attendee_tracker.ingest. Attendance is not fabricated."
                    f"{extra}"
                ),
            },
            status_code=404,
        )
    return assemble(raw)


@app.get("/api/history")
def history(
    year_from: int | None = Query(None, alias="from"),
    year_to: int | None = Query(None, alias="to"),
    demo: int = Query(0),
):
    window = _window(year_from, year_to)
    if isinstance(window, JSONResponse):
        return window
    start, end = window
    loaded = _load_window(start, end, force_sample=bool(demo))
    if isinstance(loaded, JSONResponse):
        return loaded
    raws = loaded
    if not raws:
        return _no_cache(start, end)
    payload = assemble_history(raws, start, end, include_games=False)
    payload["attendance_growth"] = rank_attendance_growth(payload["schools"])
    return payload


@app.get("/api/school/{slug}")
def school_history(
    slug: str,
    year_from: int | None = Query(None, alias="from"),
    year_to: int | None = Query(None, alias="to"),
    demo: int = Query(0),
):
    window = _window(year_from, year_to)
    if isinstance(window, JSONResponse):
        return window
    start, end = window
    loaded = _load_window(start, end, force_sample=bool(demo))
    if isinstance(loaded, JSONResponse):
        return loaded
    raws = loaded
    if not raws:
        return _no_cache(start, end)
    payload = assemble_history(raws, start, end, include_games=True)
    school = find_school(payload, slug)
    if school is None:
        return JSONResponse(
            {
                "error": "unknown_school",
                "message": (
                    f"No cached school matches {slug} between {start} and {end}. "
                    "Attendance was not fabricated."
                ),
            },
            status_code=404,
        )
    return {
        "from": payload["from"],
        "to": payload["to"],
        "missing_years": payload["missing_years"],
        "years_present": payload["years_present"],
        "sample_years": payload["sample_years"],
        "omitted_years": payload["omitted_years"],
        "attendance_note": payload["attendance_note"],
        "school": school,
    }


@app.get("/api/school/{slug}/business-news")
def school_business_news(slug: str):
    """Headlines for one program. Loaded when the school page opens, not with the season."""
    try:
        safe_slug(slug)
    except ValueError:
        return JSONResponse(
            {"error": "unknown_school", "message": "That school is not in the loaded season."},
            status_code=404,
        )
    school = _find_current_school(slug)
    if school is None:
        return JSONResponse(
            {
                "error": "unknown_school",
                "message": f"No cached school matches {slug}. Headlines were not invented.",
            },
            status_code=404,
        )
    return load_business_news(
        slug,
        school["school"],
        school.get("abbreviation"),
        school.get("mascot"),
        school.get("city"),
    )


@app.get("/api/valuations")
def valuations(sort: str = Query("valuation")):
    """Power program values from the committed file. No API key, no invented dollars."""
    try:
        return list_valuations(sort)
    except ValuationsError as exc:
        return JSONResponse(
            {"error": exc.code, "message": exc.message},
            status_code=exc.status,
        )


@app.get("/api/revenue/{slug}")
def revenue(slug: str):
    """Reported EADA football revenue for one school. No API key and no estimated years."""
    try:
        return school_revenue(slug)
    except (UnknownSchool, ValueError):
        return JSONResponse({"error": "unknown_school"}, status_code=404)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


def _load_raw(year: int, force_sample: bool) -> dict | None:
    if not force_sample and live_path(year).is_file():
        return load_live(year)
    sample = load_sample()
    if sample.get("season") == year:
        return sample
    return None


def _window(year_from: int | None, year_to: int | None):
    try:
        return validate_window(year_from, year_to, season_year())
    except HistoryWindowError as exc:
        return JSONResponse({"error": "bad_window", "message": str(exc)}, status_code=400)


def _load_window(start: int, end: int, force_sample: bool):
    raws: dict[int, dict] = {}
    for year in range(start, end + 1):
        try:
            raw = _load_raw(year, force_sample=force_sample)
        except FileNotFoundError as exc:
            return JSONResponse({"error": "no_sample", "message": str(exc)}, status_code=500)
        except ValueError as exc:
            return JSONResponse(
                {
                    "error": "bad_cache",
                    "message": (
                        f"{exc} The sample fixture was not substituted, so synthetic attendance "
                        "is not shown in place of a broken live cache."
                    ),
                },
                status_code=500,
            )
        if raw is None:
            continue
        if raw.get("season") not in (None, year):
            continue
        raws[year] = raw
    return raws


def _no_cache(start: int, end: int) -> JSONResponse:
    span = f"{start}" if start == end else f"{start}–{end}"
    sample_season = _sample_season()
    extra = f" The labeled sample fixture covers {sample_season}." if sample_season else ""
    return JSONResponse(
        {
            "error": "no_cache",
            "message": (
                f"No CFBD cache for {span}. Set CFBD_API_KEY and run "
                f"python -m attendee_tracker.ingest --years {start}-{end}. "
                "Attendance is not fabricated."
                f"{extra}"
            ),
        },
        status_code=404,
    )


def _find_current_school(slug: str) -> dict | None:
    try:
        raw = _load_raw(season_year(), force_sample=False)
    except (FileNotFoundError, ValueError):
        return None
    if raw is None:
        return None
    for school in assemble(raw).get("schools") or []:
        if school.get("slug") == slug:
            return school
    return None


def _sample_season() -> int | None:
    try:
        season = load_sample().get("season")
    except FileNotFoundError:
        return None
    return season if isinstance(season, int) else None


app.mount("/assets", StaticFiles(directory=WEB), name="assets")
