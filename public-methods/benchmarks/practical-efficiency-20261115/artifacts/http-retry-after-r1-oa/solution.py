"""Strict, offline conversion of Retry-After headers into display delays."""

import datetime
import math
import re


_INTEGER = re.compile(r"[0-9]+")
_IMF_FIXDATE = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
    r"([0-9]{2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"([0-9]{4}) ([0-9]{2}):([0-9]{2}):([0-9]{2}) GMT"
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}


def retry_after_seconds(value: str | None, now: datetime.datetime) -> int | None:
    """Return a nonnegative delay, or None for an unsupported header.

    A naive reference time raises ValueError, even when the header is absent.
    Weekday names are checked syntactically, not against the calendar date.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if value is None:
        return None
    value = value.strip()
    if _INTEGER.fullmatch(value):
        delay = 0
        for offset in range(0, len(value), 9):
            chunk = value[offset:offset + 9]
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
