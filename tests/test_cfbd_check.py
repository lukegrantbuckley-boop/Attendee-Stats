from attendee_tracker.cfbd_check import attendance_looks_off, compare


def _snapshot():
    return {
        "games": [
            {"id": 1, "week": 1, "completed": True, "neutral_site": False, "home_team": "A", "away_team": "B",
             "home_points": 21, "away_points": 14, "attendance": 80000, "attendance_source": "espn_summary"},
            {"id": 2, "week": 1, "completed": True, "neutral_site": False, "home_team": "C", "away_team": "D",
             "home_points": 10, "away_points": 3, "attendance": 50000},
        ],
        "records": [
            {"team_id": 10, "team": "A", "wins": 1, "losses": 0},
            {"team_id": 11, "team": "C", "wins": 1, "losses": 0},
        ],
    }


def test_matching_data_has_no_flags():
    games = [{"id": 1, "completed": True, "homePoints": 21, "awayPoints": 14, "attendance": 81000},
             {"id": 2, "completed": True, "homePoints": 10, "awayPoints": 3, "attendance": None}]
    records = [{"teamId": 10, "classification": "fbs", "total": {"wins": 1, "losses": 0}}]
    assert compare(_snapshot(), games, records) == []


def test_flags_score_attendance_and_record():
    games = [{"id": 1, "completed": True, "homePoints": 24, "awayPoints": 14, "attendance": 40000},
             {"id": 2, "completed": True, "homePoints": 10, "awayPoints": 3}]
    records = [{"teamId": 11, "classification": "fbs", "total": {"wins": 0, "losses": 1}}]
    kinds = sorted(flag["kind"] for flag in compare(_snapshot(), games, records))
    assert kinds == ["attendance", "record", "score"]


def test_attendance_threshold_needs_both_gaps():
    assert not attendance_looks_off(80000, 76000)
    assert not attendance_looks_off(10000, 7000)
    assert attendance_looks_off(84315, 0) is False
    assert attendance_looks_off(84315, 41000)


def test_non_fbs_records_are_ignored():
    records = [{"teamId": 11, "classification": "ii", "total": {"wins": 0, "losses": 1}}]
    assert compare({"games": [], "records": _snapshot()["records"]}, [], records) == []
