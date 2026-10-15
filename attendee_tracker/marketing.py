"""Marketing lists from the record-versus-fill line.

The fit is the Analysis scatter: ordinary least squares of average home
capacity filled on season win percentage. A team is far enough off that
line when its residual is at least ``RESIDUAL_Z`` (1.25) residual
standard deviations. That is the same cutoff the scatter uses to flag
an outlier.

A winning record is a win percentage strictly above .500 (more wins
than losses). A losing or poor record is a win percentage at or below
.500. The second list keeps Group of 5 and other non-Power 4 schools,
the same tier the Schools page uses. NFL and other pro-primary homes
never enter the fit, because ``analyze`` already leaves them out.
2020 is refused. Crowds from that season are not comparable.
"""

from __future__ import annotations

import json
from pathlib import Path

from attendee_tracker.analysis import RESIDUAL_Z, analyze
from attendee_tracker.assemble import assemble
from attendee_tracker.config import ROOT
from attendee_tracker.excluded_years import attendance_year_omitted
from attendee_tracker.store import live_path, load_live

APPROACHES_PATH = ROOT / "data" / "marketing_approaches.json"
WORKED_PATH = ROOT / "data" / "what_has_worked.json"

# Most recent complete season with a full attendance cache. 2026 is the
# season the rest of the site is showing, and it is still in progress.
COMPLETE_SEASON = 2025
TOGGLE_YEARS = (2025, 2026)

WINNING_WIN_PCT = 0.5
POOR_WIN_PCT = 0.5
PLACEHOLDER = "Luke's take: coming soon"
NO_PROMOTION = "No documented promotion found"

THRESHOLD_SUMMARY = (
    "A team is far enough off the line when its capacity fill is at least "
    f"{RESIDUAL_Z:g} residual standard deviations from the ordinary-least-squares "
    "fit of average capacity filled on season win percentage. That is the same "
    "cutoff the Analysis scatter uses. A winning record is a win percentage above "
    ".500. A losing or poor record is .500 or worse. The second list keeps Group of 5 "
    "and other non-Power 4 schools. NFL and shared pro stadiums never enter the fit. "
    "2020 is omitted."
)


class MarketingError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def select_marketing_groups(points: list[dict]) -> dict:
    """Split analysis points into the two marketing lists.

    ``points`` are the rows ``analyze`` already qualified. Pro-shared
    homes and the COVID season are not in that list. A missing residual
    (too few teams to label outliers) selects nobody.
    """
    approaches = []
    worked = []
    for point in points:
        residual_z = point.get("residual_z")
        win_pct = point.get("win_pct")
        if residual_z is None or win_pct is None:
            continue
        if win_pct > WINNING_WIN_PCT and residual_z <= -RESIDUAL_Z:
            approaches.append(point)
        elif (
            point.get("tier") != "Power 4"
            and win_pct <= POOR_WIN_PCT
            and residual_z >= RESIDUAL_Z
        ):
            worked.append(point)
    approaches.sort(key=lambda point: (point.get("residual") or 0, _name(point)))
    worked.sort(key=lambda point: (-(point.get("residual") or 0), _name(point)))
    return {"approaches": approaches, "what_has_worked": worked}


def marketing_report(
    year: int,
    *,
    approaches_path: Path | None = None,
    worked_path: Path | None = None,
) -> dict:
    """One season's lists, with Luke's notes and sourced promotions joined on."""
    if year < 1869 or year > 2100:
        raise MarketingError("bad_year", "Season year must be between 1869 and 2100.", 400)
    if attendance_year_omitted(year):
        raise MarketingError(
            "covid_year",
            "2020 is omitted as the COVID season. Marketing approaches are not drawn from that year's crowds.",
            400,
        )
    if not live_path(year).is_file():
        raise MarketingError(
            "no_cache",
            (
                f"No CFBD cache for {year}. Attendance is not fabricated, "
                "so this season has no marketing list."
            ),
            404,
        )
    view = assemble(load_live(year))
    analysis = view["analysis"]
    groups = select_marketing_groups(analysis.get("points") or [])
    schools = {school["slug"]: school for school in view.get("schools") or []}
    strategies = load_strategies(approaches_path or APPROACHES_PATH)
    promotions = load_promotions(worked_path or WORKED_PATH)
    return {
        "year": year,
        "season_partial": bool(view["meta"].get("season_partial")),
        "complete_season": COMPLETE_SEASON,
        "years": [item for item in TOGGLE_YEARS if live_path(item).is_file()],
        "placeholder": PLACEHOLDER,
        "no_promotion": NO_PROMOTION,
        "threshold": {
            "residual_z": RESIDUAL_Z,
            "winning_win_pct_above": WINNING_WIN_PCT,
            "poor_win_pct_at_or_below": POOR_WIN_PCT,
            "summary": THRESHOLD_SUMMARY,
        },
        "n_teams": analysis.get("n_teams"),
        "pearson_r": analysis.get("pearson_r"),
        "line": analysis.get("line"),
        "approaches": [
            _approach_card(point, schools.get(point["slug"]), strategies)
            for point in groups["approaches"]
        ],
        "what_has_worked": [
            _worked_card(point, schools.get(point["slug"]), promotions.get(point["slug"]) or [])
            for point in groups["what_has_worked"]
        ],
    }


def load_strategies(path: Path) -> dict[str, str]:
    """Slug to Luke's note. Missing file is an error. Blank text stays blank."""
    payload = _read_object(path, "marketing approaches")
    raw = payload.get("strategies")
    if not isinstance(raw, dict):
        raise MarketingError(
            "bad_marketing",
            "marketing_approaches.json needs a strategies object keyed by school slug.",
            500,
        )
    strategies = {}
    for slug, text in raw.items():
        if not isinstance(slug, str) or not isinstance(text, str):
            raise MarketingError(
                "bad_marketing",
                "Each marketing strategy must be a school slug mapped to text.",
                500,
            )
        strategies[slug] = text
    return strategies


def load_promotions(path: Path) -> dict[str, list[dict]]:
    """Promotions keyed by slug. An empty list means nothing documented was stored."""
    payload = _read_object(path, "what has worked")
    rows = payload.get("schools")
    if not isinstance(rows, list):
        raise MarketingError(
            "bad_marketing",
            "what_has_worked.json needs a schools list.",
            500,
        )
    by_slug: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("slug"), str):
            raise MarketingError(
                "bad_marketing",
                "Each what-has-worked row needs a school slug.",
                500,
            )
        promotions = []
        for item in row.get("promotions") or []:
            if not isinstance(item, dict):
                raise MarketingError(
                    "bad_marketing",
                    f"{row['slug']} has a promotion that is not an object.",
                    500,
                )
            summary = item.get("summary")
            url = item.get("source_url")
            date = item.get("date")
            if not isinstance(summary, str) or not summary.strip():
                raise MarketingError(
                    "bad_marketing",
                    f"{row['slug']} has a promotion with no summary.",
                    500,
                )
            if not isinstance(url, str) or not url.startswith("https://"):
                raise MarketingError(
                    "bad_marketing",
                    f"{row['slug']} has a promotion without an https source URL.",
                    500,
                )
            if not isinstance(date, str) or len(date) < 10:
                raise MarketingError(
                    "bad_marketing",
                    f"{row['slug']} has a promotion without a date.",
                    500,
                )
            promotions.append(
                {
                    "summary": summary.strip(),
                    "source_url": url,
                    "source_name": item.get("source_name") or "",
                    "date": date[:10],
                }
            )
        by_slug.setdefault(row["slug"], []).extend(promotions)
    return by_slug


def _approach_card(point: dict, school: dict | None, strategies: dict[str, str]) -> dict:
    text = strategies.get(point["slug"], "")
    card = _card(point, school)
    card["strategy"] = text.strip()
    card["strategy_is_empty"] = card["strategy"] == ""
    return card


def _worked_card(point: dict, school: dict | None, promotions: list[dict]) -> dict:
    card = _card(point, school)
    card["promotions"] = promotions
    return card


def _card(point: dict, school: dict | None) -> dict:
    school = school or {}
    return {
        "slug": point["slug"],
        "school": point["school"],
        "conference": point.get("conference"),
        "tier": point.get("tier"),
        "record": point.get("record"),
        "win_pct": point.get("win_pct"),
        "fill_pct": point.get("avg_capacity_pct"),
        "residual": point.get("residual"),
        "residual_z": point.get("residual_z"),
        "logo": school.get("logo") or point.get("logo"),
        "color": school.get("color") or point.get("color") or "#1e3a5f",
        "abbreviation": school.get("abbreviation") or point.get("abbreviation"),
    }


def _read_object(path: Path, label: str) -> dict:
    if not path.is_file():
        raise MarketingError(
            "no_marketing",
            f"No {label} file at {path.name}. Notes were not invented.",
            500,
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MarketingError(
            "bad_marketing",
            f"The {label} file could not be read.",
            500,
        ) from exc
    if not isinstance(payload, dict):
        raise MarketingError("bad_marketing", f"The {label} file must be a JSON object.", 500)
    return payload


def _name(point: dict) -> str:
    return str(point.get("school") or point.get("slug") or "").casefold()


def groups_from_rows(rows: list[dict]) -> dict:
    """Test helper. Runs the shared fit, then the marketing split."""
    return select_marketing_groups(analyze(rows).get("points") or [])
