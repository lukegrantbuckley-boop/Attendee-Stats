"""NFL and other pro-primary buildings used as an FBS home stadium.

Official CFBD capacity for these venues is the pro number, so percent full
is a poor comparison with an on-campus college stadium. This registry only
identifies the building. It does not change capacity or attendance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def venue_key(name: str | None) -> str:
    """Fold a stadium name so aliases and punctuation still match."""
    if not name:
        return ""
    text = str(name).casefold().replace("’", "'").replace("`", "'").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _keys(*names: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(venue_key(name) for name in names if venue_key(name)))


@dataclass(frozen=True)
class ProVenue:
    names: tuple[str, ...]
    note: str
    schools: tuple[str, ...] = ()
    venue_ids: tuple[int, ...] = ()

    def matches(self, key: str, venue_id: int | None) -> bool:
        if venue_id is not None and venue_id in self.venue_ids:
            return True
        return bool(key) and key in self.names


# Seeded FBS homes, then other pro houses. A team is flagged only when its
# listed home stadium matches one of these names or venue ids.
PRO_VENUES: tuple[ProVenue, ...] = (
    ProVenue(
        names=_keys("Allegiant Stadium"),
        note="NFL stadium (Raiders / Allegiant)",
        schools=("UNLV",),
    ),
    ProVenue(
        names=_keys("Raymond James Stadium"),
        note="NFL stadium (Buccaneers / Raymond James)",
        schools=("South Florida",),
    ),
    ProVenue(
        names=_keys(
            "Hard Rock Stadium",
            "Sun Life Stadium",
            "Joe Robbie Stadium",
            "Pro Player Stadium",
            "Dolphin Stadium",
            "Land Shark Stadium",
        ),
        note="NFL stadium (Dolphins / Hard Rock)",
        schools=("Miami",),
    ),
    ProVenue(
        names=_keys("Lincoln Financial Field"),
        note="NFL stadium (Eagles / Lincoln Financial)",
        schools=("Temple",),
    ),
    ProVenue(
        names=_keys("Acrisure Stadium", "Heinz Field"),
        note="NFL stadium (Steelers / Acrisure)",
        schools=("Pittsburgh",),
    ),
    ProVenue(
        names=_keys("Mercedes-Benz Stadium"),
        note="NFL stadium (Falcons / Mercedes-Benz Stadium)",
    ),
    ProVenue(
        names=_keys("SoFi Stadium"),
        note="NFL stadium (Rams and Chargers / SoFi)",
    ),
    ProVenue(
        names=_keys("Levi's Stadium", "Levis Stadium"),
        note="NFL stadium (49ers / Levi's)",
    ),
    ProVenue(
        names=_keys("Gillette Stadium"),
        note="NFL stadium (Patriots / Gillette)",
    ),
    ProVenue(
        names=_keys("Caesars Superdome", "Mercedes-Benz Superdome", "Louisiana Superdome"),
        note="NFL stadium (Saints / Caesars Superdome)",
    ),
    ProVenue(
        names=_keys("NRG Stadium", "Reliant Stadium"),
        note="NFL stadium (Texans / NRG)",
    ),
    ProVenue(
        names=_keys("Lucas Oil Stadium"),
        note="NFL stadium (Colts / Lucas Oil)",
    ),
    ProVenue(
        names=_keys("MetLife Stadium"),
        note="NFL stadium (Giants and Jets / MetLife)",
    ),
)


def matching_venue(stadium: str | None, venue_id: int | None = None) -> ProVenue | None:
    key = venue_key(stadium)
    for venue in PRO_VENUES:
        if venue.matches(key, venue_id):
            return venue
    return None


def pro_stadium_note(stadium: str | None, venue_id: int | None = None) -> str | None:
    venue = matching_venue(stadium, venue_id)
    return venue.note if venue else None
