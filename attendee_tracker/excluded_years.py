"""Years left out of attendance averages.

2020 is the COVID season. Fans largely could not attend, so a crowd from
that year is not comparable with a normal season. The raw cache is kept.
"""

from __future__ import annotations

EXCLUDED_ATTENDANCE_YEARS = frozenset({2020})
COVID_OMISSION = "covid"

COVID_AVERAGE_NOTE = (
    "2020 is omitted as the COVID season. "
    "Crowds from that year stay in the cache but are not used in averages or growth rates."
)

COVID_WINDOW_NOTE = (
    COVID_AVERAGE_NOTE
    + " That year does not count as a season with a reported average. "
    "A last-10 window that includes 2020 uses the other seasons only."
)


def attendance_year_omitted(year) -> str | None:
    """Return a reason code when this season must not enter an average."""
    try:
        if int(year) in EXCLUDED_ATTENDANCE_YEARS:
            return COVID_OMISSION
    except (TypeError, ValueError):
        return None
    return None
