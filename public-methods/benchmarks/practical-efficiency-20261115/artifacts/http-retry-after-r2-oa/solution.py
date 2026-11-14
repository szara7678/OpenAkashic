"""Strict, offline Retry-After display-delay parsing."""

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
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), ([0-9]{2}) "
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"([0-9]{4}) ([0-9]{2}):([0-9]{2}):([0-9]{2}) GMT"
)


def retry_after_seconds(
    value: str | None, now: datetime.datetime
) -> int | None:
    """Return a display delay, or None for an unsupported header value."""
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
    day, month, year, hour, minute, second = match.groups()
    try:
        header_time = datetime.datetime(
            int(year), _MONTHS[month], int(day),
            int(hour), int(minute), int(second),
            tzinfo=datetime.timezone.utc,
        )
    except ValueError:
        return None
    return max(0, math.ceil((header_time - now).total_seconds()))
