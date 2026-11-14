# Offline Retry-After display delay

`solution.py` exports `retry_after_seconds(value: str | None, now: datetime.datetime) -> int | None`.
Requires Python 3.10+ and only the standard library. Import and call it; no setup,
network access, credentials, sleeping, or system-clock changes are needed.

```python
import datetime
from solution import retry_after_seconds

now = datetime.datetime(1994, 11, 6, 8, 49, 36, 500000,
                        tzinfo=datetime.timezone.utc)
assert retry_after_seconds("Sun, 06 Nov 1994 08:49:37 GMT", now) == 1
assert retry_after_seconds(" 120 ", now) == 120
```

## Behavior and limitations

- Validates `now` awareness before looking at the header, including absent values.
  A `tzinfo` whose `utcoffset()` returns `None` is also rejected with `ValueError`.
- Strips surrounding Python string whitespace. Accepts only ASCII digits for
  integer delays, including leading zeroes. Small-chunk conversion supports long
  inputs without changing Python's process-wide integer conversion limit.
- Date matching is case-sensitive and locale-independent, with exact internal
  spacing, English abbreviated names, two-digit fields, four-digit years and
  literal `GMT`. Calendar validation uses `datetime`; weekday/date agreement is
  deliberately not checked. Unsupported or impossible dates return `None`.
- Aware datetime subtraction accounts for the supplied UTC offset. The delay is
  exactly `max(0, ceil((header_time - now).total_seconds()))` as requested.
  Only the caller's supplied clock is used: clock skew or stale incident clocks
  are not corrected. No current-time lookup or synchronization occurs.
- Years are limited to 1–9999; leap seconds are rejected. Floating-point
  `total_seconds()` can lose microsecond precision over very large spans.
  Very long integer inputs consume CPU and memory; no application size cap is set.
- The typed contract accepts strings or `None` and a `datetime`; arbitrary other
  object types and broken custom timezone implementations are outside scope.

## Validation

Run from `/work`:

```sh
python --version
python -m unittest -v
```

Observed on Python 3.12.16: `Ran 13 tests in 0.003s`, followed by `OK` (all passed). Tests cover blank/malformed
values, Unicode digits, strict date syntax, impossible dates, leap years,
weekday mismatches, non-UTC offsets, fractional rounding, clamping, awareness
validation order, large integers and extreme datetime years.

## Evidence and corrections

The designated first retrieval was OpenAkashic `oa bundle`, using the actual
parser situation and desired outcome with `mode=hybrid`, `limit=3`, and
`max_tokens=2048`. It returned `items: []`. No method IDs or versions were
returned, read, or applied. Retrieved material was treated as evidence only.

Official primary sources actually read:

- RFC 9110, section 5.6.7, read from the official plain-text response:
  https://www.rfc-editor.org/rfc/rfc9110.txt
  Used its IMF-fixdate shape, English case-sensitive weekday/month tokens and
  GMT/UTC interpretation. The numeric-delay rule comes directly from TASK.md.
  The initial HTML fetch was truncated before the relevant sections; the later
  plain-text fetch contained section 5.6.7 in full, but not section 10.2.3.
- Python `datetime` documentation, awareness, aware subtraction,
  `timedelta.total_seconds()`, supported years and leap-second limitations:
  https://docs.python.org/3/library/datetime.html
  Used the offset-based awareness check, calendar-constructor constraints and
  total-seconds precision warning. Public fetch responses were truncated, so
  targeted excerpts from their returned bodies were read. Native web calls
  produced no readable output and are not counted as evidence. The subtraction
  and ceiling formula are explicitly required by TASK.md. A direct urllib
  source fetch failed with a DNS error; the research fetch succeeded instead.

Scope correction: RFC 9110 requires general HTTP-date recipients to accept two
obsolete formats as well. This task intentionally specifies a narrower offline
viewer: those formats are rejected, not treated as invalid HTTP universally.
Python's datetime model does not represent leap seconds, so a seconds field of
60 is rejected. No general-purpose, permissive email-date parser is used.

Final rerun: `python -m unittest -v` passed all 13 tests again.
`python -m py_compile solution.py test_solution.py` exited 0 with no output.
