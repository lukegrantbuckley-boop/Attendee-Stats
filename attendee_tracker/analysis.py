"""Relate season record and recent form to home attendance.

The fit uses percent of listed stadium capacity so a 25,000-seat stadium
and a 100,000-seat stadium can sit on the same scale. Raw crowd size is
reported beside it. Null attendance is dropped, never filled in.
"""

from __future__ import annotations

from attendee_tracker.excluded_years import COVID_AVERAGE_NOTE, COVID_OMISSION

MIN_REPORTED_HOME_GAMES = 2
MIN_DECIDED_GAMES = 2
MIN_TEAMS_FOR_FIT = 3
MIN_TEAMS_FOR_OUTLIERS = 8
RESIDUAL_Z = 1.25
RECENT_FORM_WINDOW = 3
LOYALTY_LIST_SIZE = 10

METHODOLOGY = [
    "Each point is one FBS team in this season.",
    "Season record is win percentage from CFBD team records: wins divided by wins, losses, and ties. Recent form is the win percentage of the last three completed games in this cache, home or away. Teams with fewer completed games use the games they have.",
    "The primary attendance measure is the average share of stadium capacity at non-neutral home games. A game is home when this team is the home team and neutralSite is false. Only completed games with a non-null attendance integer are included. Blank attendance stays blank. It is not stored as zero and it is not imputed.",
    "Percent of capacity is the primary measure because stadium size dominates raw crowd counts. Average raw attendance is still shown, and a secondary correlation against raw attendance is reported.",
    "Capacity for a game is the CFBD capacity of that game's venue. When the venue has no capacity and the game is at the team's own stadium, the team location capacity is used. A different venue with no listed capacity does not inherit the home stadium number.",
    "The line is ordinary least squares of average capacity percentage on season win percentage. Pearson's r is shown for that fit, for recent form, and for raw attendance. A team enters the fit with at least two reported home attendances, a capacity percentage, and at least two decided games. Teams whose listed home stadium is an NFL or other pro-primary building are left out of this fit.",
    "Outliers break a weaker-record, thinner-crowd pattern. A team is highlighted when its capacity percentage is at least 1.25 residual standard deviations above the fitted line and its win percentage is at or below the group median, or at least 1.25 standard deviations below the line and its win percentage is at or above the median. Outliers are labeled only when at least eight teams are in the fit. Pro-shared home stadiums are not outliers here, because their official capacity is the pro building.",
    "Most loyal fans and softest home support use that same group, after pro-shared homes are removed: at least two reported home games with a capacity percentage, and at least two decided games. A bad record is a season win percentage at or below the median win percentage of those teams. Most loyal fans ranks the bad-record teams by highest average capacity percentage. Softest home support ranks them by lowest average capacity percentage. Each list keeps at most ten teams. Ties break by school name, not by raw attendance. Headcount is context beside the percentage, never the sort.",
    "NFL home stadiums are listed on their own. The official CFBD capacity is unchanged and is shown next to the average reported crowd. Percent full at those buildings is labeled and is not used as a college comparison, and the list is ordered by average crowd, not by fill percentage.",
    COVID_AVERAGE_NOTE,
    "This describes the season currently loaded. It is not a claim that winning causes attendance, and it is not adjusted for opponent, weather, or kickoff time.",
]


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < MIN_TEAMS_FOR_FIT or n != len(ys):
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def ols(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / var_x
    intercept = mean_y - slope * mean_x
    return intercept, slope


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def sample_stdev(values: list[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    return variance ** 0.5


def win_pct(wins: int | None, losses: int | None, ties: int | None) -> float | None:
    if wins is None or losses is None:
        return None
    decided = wins + losses + (ties or 0)
    if decided <= 0:
        return None
    return wins / decided


def recent_form(results: list[str], window: int = RECENT_FORM_WINDOW) -> dict:
    usable = [result for result in results if result in {"W", "L", "T"}]
    chunk = usable[-window:]
    wins = sum(1 for result in chunk if result == "W")
    losses = sum(1 for result in chunk if result == "L")
    ties = sum(1 for result in chunk if result == "T")
    return {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "games": len(chunk),
        "win_pct": win_pct(wins, losses, ties) if chunk else None,
        "window": window,
    }


def analyze(rows: list[dict]) -> dict:
    """rows are per-team metric dicts already filtered to FBS schools."""
    included = []
    omitted = []
    for row in rows:
        if row.get("attendance_omitted") == COVID_OMISSION:
            omitted.append(
                {
                    "slug": row["slug"],
                    "school": row["school"],
                    "reasons": ["2020 is omitted as the COVID season"],
                }
            )
            continue
        reasons = []
        if row.get("pro_shared_stadium"):
            reasons.append("home stadium is an NFL venue, so capacity fill is not used in the fit")
        if (row.get("reported_home_games") or 0) < MIN_REPORTED_HOME_GAMES:
            reasons.append("fewer than 2 home games with reported attendance")
        if row.get("avg_capacity_pct") is None:
            reasons.append("no capacity percentage")
        if (row.get("decided_games") or 0) < MIN_DECIDED_GAMES or row.get("win_pct") is None:
            reasons.append("fewer than 2 decided games in the season record")
        if reasons:
            omitted.append(
                {
                    "slug": row["slug"],
                    "school": row["school"],
                    "reasons": reasons,
                }
            )
            continue
        included.append(row)

    xs = [row["win_pct"] for row in included]
    ys = [row["avg_capacity_pct"] for row in included]
    fit = ols(xs, ys)
    correlation = pearson(xs, ys)
    form_pairs = [
        (row["recent_win_pct"], row["avg_capacity_pct"])
        for row in included
        if row.get("recent_win_pct") is not None
    ]
    raw_pairs = [
        (row["win_pct"], row["avg_home_attendance"])
        for row in included
        if row.get("avg_home_attendance") is not None
    ]
    pregame_pairs = []
    for row in rows:
        if row.get("attendance_omitted") == COVID_OMISSION:
            continue
        for game in row.get("pregame_points") or []:
            pregame_pairs.append((game["entering_win_pct"], game["capacity_pct"]))

    points = []
    outliers = []
    line = None
    if fit is not None:
        intercept, slope = fit
        residuals = [row["avg_capacity_pct"] - (intercept + slope * row["win_pct"]) for row in included]
        resid_sd = sample_stdev(residuals)
        win_median = median(xs)
        x_min, x_max = min(xs), max(xs)
        line = {
            "intercept": intercept,
            "slope": slope,
            "x1": x_min,
            "y1": intercept + slope * x_min,
            "x2": x_max,
            "y2": intercept + slope * x_max,
        }
        label_outliers = len(included) >= MIN_TEAMS_FOR_OUTLIERS and resid_sd not in (None, 0)
        for row, residual in zip(included, residuals):
            z_score = residual / resid_sd if label_outliers else None
            kind = None
            if label_outliers and win_median is not None and z_score is not None:
                if z_score >= RESIDUAL_Z and row["win_pct"] <= win_median:
                    kind = "draws_above_record"
                elif z_score <= -RESIDUAL_Z and row["win_pct"] >= win_median:
                    kind = "soft_crowd_for_record"
            point = _point(row, residual, z_score, kind)
            points.append(point)
            if kind:
                outliers.append(point)
    else:
        points = [_point(row, None, None, None) for row in included]

    outliers.sort(key=lambda item: abs(item["residual"] or 0), reverse=True)
    relationship = _relationship_sentence(correlation, fit, len(included))
    return {
        "methodology": {
            "min_reported_home_games": MIN_REPORTED_HOME_GAMES,
            "min_decided_games": MIN_DECIDED_GAMES,
            "min_teams_for_fit": MIN_TEAMS_FOR_FIT,
            "min_teams_for_outliers": MIN_TEAMS_FOR_OUTLIERS,
            "residual_z": RESIDUAL_Z,
            "recent_form_window": RECENT_FORM_WINDOW,
            "loyalty_list_size": LOYALTY_LIST_SIZE,
            "paragraphs": METHODOLOGY,
        },
        "n_teams": len(included),
        "n_omitted": len(omitted),
        "omitted": omitted,
        "pearson_r": _round(correlation, 3),
        "recent_form_pearson_r": _round(pearson([p[0] for p in form_pairs], [p[1] for p in form_pairs]), 3),
        "recent_form_n": len(form_pairs),
        "raw_attendance_pearson_r": _round(
            pearson([p[0] for p in raw_pairs], [p[1] for p in raw_pairs]),
            3,
        ),
        "raw_attendance_n": len(raw_pairs),
        "pregame": {
            "n_games": len(pregame_pairs),
            "pearson_r": _round(
                pearson([p[0] for p in pregame_pairs], [p[1] for p in pregame_pairs]),
                3,
            ),
            "note": (
                "Completed non-neutral home games that already had a prior decided game, "
                "with reported attendance and a capacity percentage. The record is the "
                "team's win percentage entering that game, from earlier games in this cache."
            ),
        },
        "line": _round_line(line),
        "slope_capacity_points_per_10_win_points": _slope_sentence(fit),
        "relationship": relationship,
        "outlier_note": _outlier_note(len(included), outliers),
        "points": points,
        "outliers": outliers,
        "loyalty": build_loyalty_lists(included),
        "pro_stadiums": build_pro_stadium_section(rows),
    }


def build_pro_stadium_section(rows: list[dict]) -> list[dict]:
    """List pro-shared homes by average crowd, not by capacity fill.

    Null attendance stays null and sorts after teams that have a reported
    average. Capacity is the official figure already on the row.
    """
    flagged = [row for row in rows if row.get("pro_shared_stadium")]

    def sort_key(row: dict) -> tuple:
        crowd = row.get("avg_home_attendance")
        return (crowd is None, -(crowd if crowd is not None else 0), row["school"].casefold())

    listed = []
    for row in sorted(flagged, key=sort_key):
        listed.append(
            {
                "slug": row["slug"],
                "school": row["school"],
                "conference": row.get("conference"),
                "record": row.get("record"),
                "win_pct": _round(row.get("win_pct"), 4),
                "avg_home_attendance": _round(row.get("avg_home_attendance"), 1),
                "capacity": row.get("capacity"),
                "avg_capacity_pct": _round(row.get("avg_capacity_pct"), 4),
                "reported_home_games": row.get("reported_home_games"),
                "stadium": row.get("stadium"),
                "pro_stadium_note": row.get("pro_stadium_note") or "NFL stadium",
                "logo": row.get("logo"),
                "color": row.get("color") or "#1e3a5f",
                "abbreviation": row.get("abbreviation"),
            }
        )
    return listed


def build_loyalty_lists(included: list[dict], limit: int = LOYALTY_LIST_SIZE) -> dict:
    """Rank below-median records by stadium fill, not by headcount.

    ``included`` is the analysis group: reported home crowds, a capacity
    percentage, and enough decided games. Teams outside that group never
    appear. A null capacity percentage cannot be ranked.
    """
    qualified = [
        row
        for row in included
        if row.get("win_pct") is not None and row.get("avg_capacity_pct") is not None
    ]
    win_median = median([row["win_pct"] for row in qualified])
    if win_median is None:
        bad = []
    else:
        bad = [row for row in qualified if row["win_pct"] <= win_median]
    return {
        "list_size": limit,
        "win_pct_median": _round(win_median, 4),
        "n_qualifying": len(qualified),
        "n_bad_record": len(bad),
        "most_loyal": _rank_loyalty(bad, highest_fill_first=True, limit=limit),
        "softest_support": _rank_loyalty(bad, highest_fill_first=False, limit=limit),
    }


def _rank_loyalty(rows: list[dict], *, highest_fill_first: bool, limit: int) -> list[dict]:
    def sort_key(row: dict) -> tuple:
        fill = row["avg_capacity_pct"]
        # Name is the tie break. Raw attendance is not part of the key.
        return ((-fill if highest_fill_first else fill), row["school"].casefold(), row.get("slug") or "")

    ranked = []
    for index, row in enumerate(sorted(rows, key=sort_key)[:limit], start=1):
        ranked.append(
            {
                "rank": index,
                "slug": row["slug"],
                "school": row["school"],
                "conference": row.get("conference"),
                "record": row.get("record"),
                "win_pct": _round(row["win_pct"], 4),
                "avg_capacity_pct": _round(row["avg_capacity_pct"], 4),
                "avg_home_attendance": _round(row.get("avg_home_attendance"), 1),
                "reported_home_games": row.get("reported_home_games"),
                "games_played": row.get("decided_games"),
                "logo": row.get("logo"),
                "color": row.get("color") or "#1e3a5f",
                "abbreviation": row.get("abbreviation"),
            }
        )
    return ranked


def _point(row: dict, residual: float | None, z_score: float | None, kind: str | None) -> dict:
    return {
        "slug": row["slug"],
        "school": row["school"],
        "conference": row["conference"],
        "tier": row["tier"],
        "record": row["record"],
        "win_pct": _round(row["win_pct"], 4),
        "recent_record": row.get("recent_record"),
        "recent_win_pct": _round(row.get("recent_win_pct"), 4),
        "avg_home_attendance": _round(row.get("avg_home_attendance"), 1),
        "avg_capacity_pct": _round(row.get("avg_capacity_pct"), 4),
        "reported_home_games": row.get("reported_home_games"),
        "residual": _round(residual, 4),
        "residual_z": _round(z_score, 2),
        "kind": kind,
    }


def _relationship_sentence(correlation: float | None, fit: tuple[float, float] | None, n_teams: int) -> str:
    if fit is None or correlation is None:
        return (
            f"{n_teams} teams have enough reported home attendance and a decided record "
            "to plot. That is short of the three-team minimum for a line, or the records "
            "do not vary, so no relationship is estimated."
        )
    if correlation >= 0.2:
        pattern = "A better season record lines up with a fuller stadium in this data."
    elif correlation <= -0.2:
        pattern = (
            "A better season record does not line up with a fuller stadium here. "
            "The association runs the other way."
        )
    else:
        pattern = "Season record and capacity percentage only weakly move together in this data."
    return f"{pattern} Pearson r is {correlation:.2f} across {n_teams} teams."


def _slope_sentence(fit: tuple[float, float] | None) -> str | None:
    if fit is None:
        return None
    _intercept, slope = fit
    points = slope * 0.10 * 100
    direction = "more" if points >= 0 else "less"
    return (
        f"In this fit, a 10-point higher win percentage associates with "
        f"{abs(points):.1f} percentage points {direction} of stadium capacity."
    )


def _outlier_note(n_teams: int, outliers: list[dict]) -> str:
    if n_teams < MIN_TEAMS_FOR_OUTLIERS:
        return (
            f"{n_teams} teams are in the fit. Outliers are labeled only when at least "
            f"{MIN_TEAMS_FOR_OUTLIERS} teams qualify, so none are flagged."
        )
    if not outliers:
        return (
            "No team clears the outlier rule. A weak record with an unusually full stadium, "
            "or a strong record with an unusually soft crowd, would appear here."
        )
    return (
        f"{len(outliers)} team{'s' if len(outliers) != 1 else ''} break the weaker-record, "
        "thinner-crowd pattern under the rule in the methodology."
    )


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _round_line(line: dict | None) -> dict | None:
    if line is None:
        return None
    return {key: round(float(value), 4) for key, value in line.items()}
