"""Project the 12-team College Football Playoff bracket from a CFP ranking.

2026 rules, from the CFP and NCAA.com:

- Automatic bids for the ACC, Big Ten, Big 12, and SEC champions. Until the
  games are played, the highest-ranked team in each conference stands in.
- One automatic bid for the highest-ranked team from the American, Conference
  USA, MAC, Mountain West, Pac-12, or Sun Belt. That team does not have to
  be a conference champion.
- Notre Dame is automatic when it is ranked in the top 12. The field then
  takes six at-large teams. Otherwise it takes seven.
- Automatic qualifiers ranked outside the top 12 are seeded at the bottom,
  in CFP rank order.
- The four highest-ranked teams in the field are seeds 1–4 and get a
  first-round bye. They do not have to be conference champions.
- First round, on the higher seed's campus: 5 vs 12, 6 vs 11, 7 vs 10, 8 vs 9.
- Quarterfinals are fixed. There is no reseeding.
- Seeds 1–3 choose quarterfinal and semifinal sites on Selection Day.
  Those bowls are not assigned here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

SELECTION_DAY = date(2026, 12, 6)
SITE_CHOICE = "Chosen by seeds 1–3 on Dec 6"
TOP_12_CUTOFF = 12
FIELD_SIZE = 12

P4_CONFERENCES = ("SEC", "Big Ten", "Big 12", "ACC")
G6_GROUPS = ("american", "cusa", "mac", "mwc", "pac-12", "sun belt")

QUARTERFINAL_POOL = (
    {
        "bowl": "Vrbo Fiesta Bowl",
        "date": "2026-12-30",
        "time_et": "7:30 p.m.",
        "tv": "TNT/truTV/HBO Max",
        "venue": "State Farm Stadium",
        "city": "Glendale, Ariz.",
    },
    {
        "bowl": "Goodyear Cotton Bowl",
        "date": "2027-01-01",
        "time_et": None,
        "tv": None,
        "venue": "AT&T Stadium",
        "city": "Arlington, Texas",
    },
    {
        "bowl": "Chick-fil-A Peach Bowl",
        "date": "2027-01-01",
        "time_et": None,
        "tv": None,
        "venue": "Mercedes-Benz Stadium",
        "city": "Atlanta",
    },
    {
        "bowl": "Rose Bowl",
        "date": "2027-01-01",
        "time_et": None,
        "tv": None,
        "venue": "Rose Bowl",
        "city": "Pasadena, Calif.",
    },
)

SEMIFINAL_POOL = (
    {
        "bowl": "Capital One Orange Bowl",
        "date": "2027-01-14",
        "time_et": "7:30 p.m.",
        "tv": "TNT/truTV/HBO Max",
        "venue": "Hard Rock Stadium",
        "city": "Miami Gardens, Fla.",
    },
    {
        "bowl": "Allstate Sugar Bowl",
        "date": "2027-01-15",
        "time_et": "7:30 p.m.",
        "tv": "ABC/ESPN",
        "venue": "Caesars Superdome",
        "city": "New Orleans",
    },
)

FIRST_ROUND_SLOTS = (
    {"higher": 5, "lower": 12, "date": "2026-12-18", "time_et": "8:00 p.m.", "tv": "ESPN"},
    {"higher": 6, "lower": 11, "date": "2026-12-19", "time_et": "12:00 p.m.", "tv": "ABC/ESPN"},
    {"higher": 7, "lower": 10, "date": "2026-12-19", "time_et": "3:30 p.m.", "tv": "TNT/truTV/HBO Max"},
    {"higher": 8, "lower": 9, "date": "2026-12-19", "time_et": "7:30 p.m.", "tv": "TNT/truTV/HBO Max"},
)

# Winner of the first pair meets the seed. Order is the fixed bracket, not a reseed.
QUARTERFINAL_PAIRS = (
    {"bye": 1, "first_round": (8, 9)},
    {"bye": 4, "first_round": (5, 12)},
    {"bye": 2, "first_round": (7, 10)},
    {"bye": 3, "first_round": (6, 11)},
)


def conference_group(name: str | None) -> str:
    if not name or not str(name).strip():
        return "independent"
    key = " ".join(str(name).casefold().replace(".", " ").split())
    aliases = {
        "sec": "sec",
        "southeastern": "sec",
        "southeastern conference": "sec",
        "big ten": "big ten",
        "big 12": "big 12",
        "big twelve": "big 12",
        "acc": "acc",
        "atlantic coast": "acc",
        "atlantic coast conference": "acc",
        "american": "american",
        "american athletic": "american",
        "aac": "american",
        "conference usa": "cusa",
        "cusa": "cusa",
        "c usa": "cusa",
        "mid american": "mac",
        "mac": "mac",
        "mountain west": "mwc",
        "mwc": "mwc",
        "pac 12": "pac-12",
        "pac-12": "pac-12",
        "sun belt": "sun belt",
        "sbc": "sun belt",
        "fbs independents": "independent",
        "fbs indep": "independent",
        "independent": "independent",
    }
    return aliases.get(key, key)


def _is_notre_dame(team: dict) -> bool:
    return str(team.get("school") or "").casefold() == "notre dame"


def _copy_team(team: dict, bid: str) -> dict:
    return {
        "school": team.get("school"),
        "rank": team.get("rank"),
        "conference": team.get("conference"),
        "record": team.get("record"),
        "team_id": team.get("team_id"),
        "bid": bid,
    }


def _best(teams: list[dict], predicate) -> dict | None:
    matched = [team for team in teams if predicate(team)]
    if not matched:
        return None
    return min(matched, key=lambda team: (team.get("rank") is None, team.get("rank") or 10_000))


def project_bracket(teams: list[dict], *, as_of: str | None = None, today: date | None = None) -> dict:
    """Build the projected field. ``today`` decides the Projected label, not the seeds."""
    ranked = [team for team in teams if isinstance(team, dict) and team.get("rank") is not None and team.get("school")]
    ranked.sort(key=lambda team: int(team["rank"]))

    autos: list[dict] = []
    missing_conferences: list[str] = []
    for conference in P4_CONFERENCES:
        champ = _best(ranked, lambda team, conference=conference: conference_group(team.get("conference")) == conference_group(conference))
        if champ is None:
            missing_conferences.append(conference)
            continue
        autos.append(_copy_team(champ, f"{conference} auto"))

    g6 = _best(ranked, lambda team: conference_group(team.get("conference")) in G6_GROUPS)
    if g6 is None:
        missing_conferences.append("Group of 6")
    else:
        autos.append(_copy_team(g6, "Group of 6 auto"))

    notre_dame = _best(ranked, _is_notre_dame)
    nd_auto = bool(notre_dame and int(notre_dame["rank"]) <= TOP_12_CUTOFF)
    if nd_auto and notre_dame is not None:
        autos.append(_copy_team(notre_dame, "Notre Dame auto"))
    at_large_spots = 6 if nd_auto else 7

    auto_names = {team["school"].casefold() for team in autos if team.get("school")}
    pool = [team for team in ranked if str(team.get("school")).casefold() not in auto_names]
    at_large = [_copy_team(team, "at-large") for team in pool[:at_large_spots]]
    field = autos + at_large

    outside = [team for team in field if team["bid"] != "at-large" and int(team["rank"]) > TOP_12_CUTOFF]
    inside = [team for team in field if team not in outside]
    outside.sort(key=lambda team: int(team["rank"]))
    inside.sort(key=lambda team: int(team["rank"]))

    seeds: list[dict] = []
    for index, team in enumerate(inside + outside, start=1):
        seeded = dict(team)
        seeded["seed"] = index
        seeded["bye"] = index <= 4
        seeds.append(seeded)
    by_seed = {team["seed"]: team for team in seeds}

    def side(seed: int) -> dict | None:
        team = by_seed.get(seed)
        if team is None:
            return None
        return {
            "seed": seed,
            "school": team["school"],
            "rank": team["rank"],
            "conference": team["conference"],
            "record": team["record"],
            "team_id": team["team_id"],
            "bid": team["bid"],
        }

    first_round = []
    for slot in FIRST_ROUND_SLOTS:
        first_round.append(
            {
                "higher_seed": slot["higher"],
                "lower_seed": slot["lower"],
                "home": side(slot["higher"]),
                "away": side(slot["lower"]),
                "site": "Campus of the higher seed",
                "date": slot["date"],
                "time_et": slot["time_et"],
                "tv": slot["tv"],
            }
        )
    quarterfinals = []
    for pair in QUARTERFINAL_PAIRS:
        left, right = pair["first_round"]
        quarterfinals.append(
            {
                "bye_seed": pair["bye"],
                "bye": side(pair["bye"]),
                "opponent": f"Winner of {left} vs {right}",
                "first_round_seeds": [left, right],
                "site": SITE_CHOICE,
            }
        )
    semifinals = [
        {
            "game": "Semifinal 1",
            "teams": "Winner of 1 vs 8/9 against winner of 4 vs 5/12",
            "site": SITE_CHOICE,
        },
        {
            "game": "Semifinal 2",
            "teams": "Winner of 2 vs 7/10 against winner of 3 vs 6/11",
            "site": SITE_CHOICE,
        },
    ]

    moment = today or datetime.now(timezone.utc).date()
    official = moment >= SELECTION_DAY
    first_four = [
        {
            "school": team.get("school"),
            "rank": team.get("rank"),
            "conference": team.get("conference"),
            "record": team.get("record"),
            "team_id": team.get("team_id"),
        }
        for team in pool[at_large_spots:at_large_spots + 4]
    ]
    return {
        "season": 2026,
        "label": "Official" if official else "Projected",
        "status": "official" if official else "projected",
        "selection_day": SELECTION_DAY.isoformat(),
        "as_of": as_of,
        "notre_dame_auto": nd_auto,
        "at_large_spots": at_large_spots,
        "field_size": len(seeds),
        "missing_automatic_bids": missing_conferences,
        "seeds": seeds,
        "byes": [team["seed"] for team in seeds if team["bye"]],
        "first_round": first_round,
        "quarterfinals": quarterfinals,
        "quarterfinal_sites": {
            "assignment": SITE_CHOICE,
            "bowls": list(QUARTERFINAL_POOL),
        },
        "semifinals": semifinals,
        "semifinal_sites": {
            "assignment": SITE_CHOICE,
            "bowls": list(SEMIFINAL_POOL),
        },
        "championship": {
            "date": "2027-01-25",
            "time_et": "7:30 p.m.",
            "tv": "ABC",
            "venue": "Allegiant Stadium",
            "city": "Las Vegas",
            "site": "Allegiant Stadium, Las Vegas",
        },
        "first_four_out": first_four,
        "rules": {
            "no_reseeding": True,
            "byes_are_top_ranked_teams": True,
            "byes_require_conference_champions": False,
            "first_round": ["5 vs 12", "6 vs 11", "7 vs 10", "8 vs 9"],
            "quarterfinals": ["1 vs winner of 8/9", "4 vs winner of 5/12", "2 vs winner of 7/10", "3 vs winner of 6/11"],
        },
    }


def bracket_document(cfp_document: dict, *, today: date | None = None) -> dict:
    """Projected bracket for the latest snapshot in a CFP file."""
    projected = project_bracket(
        list(cfp_document.get("teams") or []),
        as_of=cfp_document.get("released_at"),
        today=today,
    )
    projected["source"] = "cfp_rankings"
    projected["source_url"] = cfp_document.get("source_url")
    projected["official_rankings_url"] = cfp_document.get("official_url")
    projected["week"] = cfp_document.get("week")
    projected["note"] = (
        "Projected from the latest CFP rankings. Conference champions are the "
        "highest-ranked team in each Power conference. Quarterfinal and semifinal "
        "bowl sites are chosen by seeds 1–3 on Dec. 6 and are not assigned here."
    )
    return projected
