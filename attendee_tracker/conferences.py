"""Power 4 vs Group of 5 is not a CFBD field. Map it from conference name."""

from __future__ import annotations

# Display order for conferences we expect. Anything else sorts after these,
# still inside its tier. Names are matched case-insensitively.
POWER_4_ORDER = ("SEC", "Big Ten", "Big 12", "ACC")
OTHER_FBS_ORDER = (
    "American Athletic",
    "Sun Belt",
    "Mountain West",
    "Mid-American",
    "Conference USA",
    "Pac-12",
    "FBS Independents",
    "Independent",
)

_POWER_4_KEYS = {
    "sec",
    "southeastern conference",
    "big ten",
    "big 12",
    "big twelve",
    "acc",
    "atlantic coast conference",
}


def conference_key(name: str | None) -> str:
    if not name or not str(name).strip():
        return "independent"
    return " ".join(str(name).casefold().split())


def is_power_4(name: str | None) -> bool:
    return conference_key(name) in _POWER_4_KEYS


def tier_for(name: str | None) -> str:
    """SEC, Big Ten, Big 12, and ACC are Power 4. Every other FBS conference is Group of 5."""
    if is_power_4(name):
        return "Power 4"
    return "Group of 5"


def display_conference(name: str | None) -> str:
    if not name or not str(name).strip():
        return "FBS Independents"
    return str(name).strip()


def conference_sort_index(name: str | None) -> tuple[int, int, str]:
    label = display_conference(name)
    key = conference_key(label)
    tier_rank = 0 if is_power_4(label) else 1
    order = POWER_4_ORDER if tier_rank == 0 else OTHER_FBS_ORDER
    for index, candidate in enumerate(order):
        if conference_key(candidate) == key:
            return (tier_rank, index, label.casefold())
    return (tier_rank, len(order) + 1, label.casefold())
