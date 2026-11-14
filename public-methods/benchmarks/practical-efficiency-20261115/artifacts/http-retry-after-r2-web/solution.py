"""Strict, offline Retry-After parsing for incident-log displays."""

import datetime
import math
import re


_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}
_IMF_FIXDATE = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
    r"(?P<day>[0-9]{2}) "
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"(?P<year>[0-9]{4}) "
    r"(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2}) GMT"
)


def retry_after_seconds(value: str | None, now: datetime.datetime) -> int | None:
    """Return a display delay, or None for unsupported header syntax.

    Raise ValueError for naive now, including when the header is missing.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if re.fullmatch(r"[0-9]+", value):
        delay = 0
        for start in range(0, len(value), 9):
            chunk = value[start:start + 9]
            delay = delay * 10 ** len(chunk) + int(chunk)
        return delay
    match = _IMF_FIXDATE.fullmatch(value)
    if match is None:
        return None
    try:
        header_time = datetime.datetime(
            int(match["year"]), _MONTHS[match["month"]], int(match["day"]),
            int(match["hour"]), int(match["minute"]), int(match["second"]),
            tzinfo=datetime.timezone.utc,
        )
    except ValueError:
        return None
    return max(0, math.ceil((header_time - now).total_seconds()))
