import pytest

from attendee_tracker.analysis import analyze, median, ols, pearson, recent_form, win_pct


def test_pearson_and_ols_known_line():
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1)
    intercept, slope = ols([0, 1, 2], [1, 3, 5])
    assert intercept == pytest.approx(1)
    assert slope == pytest.approx(2)


def test_pearson_needs_variation():
    assert pearson([1, 1, 1], [1, 2, 3]) is None


def test_win_pct_and_recent_form():
    assert win_pct(3, 1, 0) == pytest.approx(0.75)
    assert win_pct(1, 1, 1) == pytest.approx(1 / 3)
    assert win_pct(0, 0, 0) is None
    form = recent_form(["W", "L", "W", "T", "L"], window=3)
    assert form["wins"] == 1
    assert form["losses"] == 1
    assert form["ties"] == 1
    assert form["games"] == 3


def test_median():
    assert median([1, 3, 2, 4]) == pytest.approx(2.5)
    assert median([1, 9, 3]) == 3


def test_loyalty_lists_rank_below_median_records_by_capacity_not_headcount():
    rows = [
        _row("Champion", 1.0, [0.90, 0.90], crowds=[90000, 90000]),
        _row("Solid", 0.75, [0.80, 0.80], crowds=[80000, 80000]),
        _row("Median", 0.50, [0.70, 0.70], crowds=[70000, 70000]),
        _row("Loyal", 0.25, [0.95, 0.95], crowds=[12000, 12000]),
        _row("Empty", 0.00, [0.20, 0.20], crowds=[88000, 88000]),
        _row("NoCap", 0.00, [], crowds=[50000, 50000], reported=2),
        _row("Blank", 0.00, [], crowds=[], reported=0),
    ]
    result = analyze(rows)
    loyalty = result["loyalty"]
    assert loyalty["win_pct_median"] == pytest.approx(0.5)
    assert loyalty["n_bad_record"] == 3
    loyal_names = [row["school"] for row in loyalty["most_loyal"]]
    soft_names = [row["school"] for row in loyalty["softest_support"]]
    assert loyal_names == ["Loyal", "Median", "Empty"]
    assert soft_names == ["Empty", "Median", "Loyal"]
    assert "Champion" not in loyal_names
    assert "NoCap" not in loyal_names + soft_names
    assert "Blank" not in loyal_names + soft_names
    assert loyalty["most_loyal"][0]["avg_home_attendance"] == 12000
    assert loyalty["most_loyal"][0]["avg_capacity_pct"] == pytest.approx(0.95)
    assert loyalty["most_loyal"][0]["games_played"] == 2
    assert loyalty["softest_support"][0]["avg_home_attendance"] == 88000
    assert all(row["avg_capacity_pct"] is not None for row in loyalty["most_loyal"])
    assert all(row["games_played"] == 2 for row in loyalty["most_loyal"] + loyalty["softest_support"])


def test_loyalty_ties_break_by_name_not_crowd_size():
    rows = [
        _row("Winner", 1.0, [0.9, 0.9], crowds=[1000, 1000]),
        _row("Anchor", 0.0, [0.50, 0.50], crowds=[1000, 1000]),
        _row("Middling", 0.0, [0.50, 0.50], crowds=[90000, 90000]),
    ]
    loyalty = analyze(rows)["loyalty"]
    assert loyalty["win_pct_median"] == pytest.approx(0.0)
    assert [row["school"] for row in loyalty["most_loyal"]] == ["Anchor", "Middling"]
    assert [row["school"] for row in loyalty["softest_support"]] == ["Anchor", "Middling"]
    assert loyalty["most_loyal"][0]["avg_home_attendance"] < loyalty["most_loyal"][1]["avg_home_attendance"]


def test_loyalty_lists_keep_ten_teams():
    rows = [_row("Good", 1.0, [0.9, 0.9], crowds=[1000, 1000])]
    for index in range(12):
        fill = 0.2 + index * 0.03
        rows.append(_row(f"Bad {index:02d}", 0.0, [fill, fill], crowds=[1000 + index, 1000 + index]))
    loyalty = analyze(rows)["loyalty"]
    assert loyalty["list_size"] == 10
    assert len(loyalty["most_loyal"]) == 10
    assert len(loyalty["softest_support"]) == 10
    loyal_fills = [row["avg_capacity_pct"] for row in loyalty["most_loyal"]]
    soft_fills = [row["avg_capacity_pct"] for row in loyalty["softest_support"]]
    assert loyal_fills == sorted(loyal_fills, reverse=True)
    assert soft_fills == sorted(soft_fills)
    assert loyal_fills[0] > soft_fills[0]
    assert "Good" not in {row["school"] for row in loyalty["most_loyal"]}


def test_null_attendance_is_not_imputed_into_the_fit():
    rows = [
        _row("full", 1.0, [0.9, 0.9], crowds=[90000, 90000]),
        _row("mid", 0.5, [0.6, 0.6], crowds=[60000, 60000]),
        _row("low", 0.0, [0.3, 0.3], crowds=[30000, 30000]),
        _row("blank", 0.0, [], crowds=[], reported=0),
    ]
    result = analyze(rows)
    schools = {point["school"] for point in result["points"]}
    assert "blank" not in schools
    assert any(row["school"] == "blank" for row in result["omitted"])
    assert result["pearson_r"] == pytest.approx(1)


def _row(name, win_value, capacity_pcts, crowds, reported=None):
    reported_games = len(capacity_pcts) if reported is None else reported
    return {
        "slug": name,
        "school": name,
        "conference": "SEC",
        "tier": "Power 4",
        "record": "1-0",
        "win_pct": win_value,
        "decided_games": 2,
        "reported_home_games": reported_games,
        "avg_home_attendance": (sum(crowds) / len(crowds)) if crowds else None,
        "avg_capacity_pct": (sum(capacity_pcts) / len(capacity_pcts)) if capacity_pcts else None,
        "recent_win_pct": win_value,
        "recent_record": "1-0",
        "pregame_points": [],
    }
