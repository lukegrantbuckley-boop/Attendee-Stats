from attendee_tracker.history import assemble_history, find_school


def test_history_follows_team_id_across_a_conference_move_and_leaves_gaps_blank():
    earlier = _raw(
        2021,
        [
            _team(10, "Demo State", "Big 12"),
            _team(11, "Other State", "ACC"),
        ],
        [
            _game(1, 2021, 10, "Demo State", 40000, "Visitor", 1),
            _game(2, 2021, 11, "Other State", 22000, "Visitor", 1),
        ],
    )
    later = _raw(
        2024,
        [
            _team(10, "Demo State", "SEC"),
            _team(11, "Other State", "ACC"),
        ],
        [
            _game(3, 2024, 10, "Demo State", 61000, "Visitor", 1),
            _game(4, 2024, 10, "Demo State", None, "Blank", 2),
            _game(5, 2024, 11, "Other State", 23000, "Visitor", 1),
        ],
    )
    history = assemble_history({2021: earlier, 2024: later}, 2021, 2024, include_games=True)
    assert history["missing_years"] == [2022, 2023]
    assert history["years_present"] == [2021, 2024]
    assert history["sample_years"] == []

    demo = find_school(history, "demo-state")
    assert demo["id"] == 10
    assert demo["conference"] == "SEC"
    assert [row["year"] for row in demo["seasons"]] == [2021, 2024]
    assert demo["seasons"][0]["conference"] == "Big 12"
    assert demo["seasons"][0]["avg_home_attendance"] == 40000
    assert demo["seasons"][1]["conference"] == "SEC"
    assert demo["seasons"][1]["avg_home_attendance"] == 61000
    blank = [game for game in demo["seasons"][1]["home_games"] if game["opponent"] == "Blank"]
    assert blank[0]["attendance"] is None
    assert blank[0]["attendance_status"] == "not_reported"
    assert all(
        game["attendance"] != 0
        for season in demo["seasons"]
        for game in season["home_games"]
    )

    other = find_school(history, "other-state")
    assert other["id"] == 11
    assert len(other["seasons"]) == 2
    assert other["seasons"][0]["avg_home_attendance"] == 22000


def test_history_joins_a_changed_team_id_when_the_school_name_is_unique():
    earlier = _raw(2020, [_team(10, "Demo State", "Big 12")], [_game(1, 2020, 10, "Demo State", 30000, "Visitor", 1)])
    later = _raw(2024, [_team(77, "Demo State", "SEC")], [_game(2, 2024, 77, "Demo State", 45000, "Visitor", 1)])
    history = assemble_history({2020: earlier, 2024: later}, 2020, 2024, include_games=False)
    school = find_school(history, "demo-state")
    assert school["id"] == 77
    assert [row["year"] for row in school["seasons"]] == [2020, 2024]
    assert earlier["games"][0]["attendance"] == 30000
    assert school["seasons"][0]["avg_home_attendance"] is None
    assert school["seasons"][0]["attendance_omitted"] == "covid"
    assert school["seasons"][0]["last_home_attendance"] is None
    assert school["seasons"][1]["avg_home_attendance"] == 45000
    assert school["seasons"][1]["attendance_omitted"] is None
    assert history["omitted_years"] == [2020]
    assert "COVID" in history["attendance_note"]
    assert "home_games" not in school["seasons"][0]
    assert find_school(history, "missing") is None


def test_history_keeps_a_rename_on_the_same_team_id():
    earlier = _raw(2018, [_team(10, "Old Name", "Big 12")], [_game(1, 2018, 10, "Old Name", 28000, "Visitor", 1)])
    later = _raw(2025, [_team(10, "New Name", "SEC")], [_game(2, 2025, 10, "New Name", 51000, "Visitor", 1)])
    history = assemble_history({2018: earlier, 2025: later}, 2018, 2025)
    school = find_school(history, "new-name")
    assert school["school"] == "New Name"
    assert school["conference"] == "SEC"
    assert [row["year"] for row in school["seasons"]] == [2018, 2025]
    assert school["seasons"][0]["conference"] == "Big 12"
    assert find_school(history, "old-name")["id"] == 10
    assert history["missing_years"] == list(range(2019, 2025))


def test_two_teams_that_share_a_name_are_not_merged():
    later = _raw(
        2024,
        [_team(1, "Alpha", "SEC"), _team(2, "Alpha", "Big Ten")],
        [
            _game(1, 2024, 1, "Alpha", 10000, "Visitor", 1),
            _game(2, 2024, 2, "Alpha", 20000, "Visitor", 1),
        ],
    )
    earlier = _raw(2020, [_team(3, "Alpha", "ACC")], [_game(3, 2020, 3, "Alpha", 9000, "Visitor", 1)])
    history = assemble_history({2020: earlier, 2024: later}, 2020, 2024)
    alphas = [school for school in history["schools"] if school["school"] == "Alpha"]
    assert len(alphas) == 3
    assert {school["id"] for school in alphas} == {1, 2, 3}
    assert all(len(school["seasons"]) == 1 for school in alphas)


def _raw(year, teams, games):
    return {
        "source": "cfbd",
        "synthetic": False,
        "season": year,
        "teams": teams,
        "venues": [{"id": 1, "name": "Stadium", "capacity": 80000}],
        "games": games,
        "records": [],
        "rankings": [],
    }


def _team(team_id, school, conference):
    return {
        "id": team_id,
        "school": school,
        "conference": conference,
        "color": "#123456",
        "capacity": 80000,
        "venue_id": 1,
        "stadium": "Stadium",
    }


def _game(game_id, year, home_id, home, attendance, opponent, week):
    return {
        "id": game_id,
        "season": year,
        "week": week,
        "season_type": "regular",
        "start_date": f"{year}-09-{week:02d}T23:30:00Z",
        "completed": True,
        "neutral_site": False,
        "attendance": attendance,
        "venue_id": 1,
        "venue": "Stadium",
        "home_id": home_id,
        "home_team": home,
        "home_points": 24,
        "away_id": 5000 + game_id,
        "away_team": opponent,
        "away_points": 10,
    }
