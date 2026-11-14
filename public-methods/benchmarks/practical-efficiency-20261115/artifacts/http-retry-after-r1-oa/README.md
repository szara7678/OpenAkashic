# Offline Retry-After display delay

`solution.py` exports `retry_after_seconds(value: str | None, now: datetime.datetime) -> int | None`.
Requires Python 3.10+ and only the standard library. The caller supplies the
reference time; the parser does not sleep, read/change the clock, or make requests.

## Example

```python
import datetime
from solution import retry_after_seconds

now = datetime.datetime(1994, 11, 6, 8, 49, 36, 500000,
                        tzinfo=datetime.timezone.utc)
assert retry_after_seconds("Sun, 06 Nov 1994 08:49:37 GMT", now) == 1
assert retry_after_seconds(" 120 ", now) == 120
```

## Behavior and limitations

- Awareness is checked first, including for missing headers: `tzinfo` must exist
  and `utcoffset()` must not return `None`; otherwise `ValueError` is raised.
- `str.strip()` removes surrounding whitespace. Integer headers require ASCII
  digits only. Nine-digit conversion chunks avoid Python's decimal conversion
  length limit without changing interpreter settings. There is no arbitrary
  length cap; extremely large inputs still consume CPU and memory.
- Dates require the exact case-sensitive English shape
  `Sun, 06 Nov 1994 08:49:37 GMT`, including single literal internal spaces.
  GMT means UTC. Recognized weekdays need not match the calendar date.
- Missing, blank, signed, fractional, non-ASCII numeric, malformed, impossible,
  and alternative date-format inputs return `None`. Leap seconds are rejected.
- Python's Gregorian datetime calendar supports years 1–9999. Aware subtraction
  handles timezone offsets without converting `now` to a potentially
  out-of-range UTC datetime.
- Date delays follow exactly
  `max(0, math.ceil((header_time - now).total_seconds()))`.
  Python documents microsecond precision loss in `total_seconds()` for very
  long durations (roughly over 270 years). This intentionally follows the
  requested float-based formula rather than substituting integer rounding.
- Reference-clock accuracy, clock skew, and timezone rules are the caller's
  responsibility. This is a display parser, not a retry scheduler or complete
  HTTP header processor.

## Actual validation

From `/work`, run:

```sh
python -m unittest -v
python -m py_compile solution.py test_solution.py
```

Actually observed on Python 3.12.16, November 14, 2026:

```text
Ran 13 tests in 0.005s
OK
```

Both final commands exited with status 0; `py_compile` produced no output.
Tests cover awareness (including tzinfo returning no offset), missing/invalid
values, exact syntax, all weekday/month tokens, impossible dates and leap days,
fractional rounding, past clamping, positive/negative/subminute offsets,
datetime boundaries, and 5,001-digit integers. A guard test patches sleep,
system-time lookup, and socket creation to fail if called.

Correction: the first test run had one failure due to an incorrect hard-coded
multi-year leap-day expectation (expected 167875200; observed 167702400).
Replaced that brittle assertion with the independently obvious one-day interval
from February 28 to February 29, 2000 (86400 seconds). No parser change was
necessary. The subsequent run passed all 13 tests.

## Sources and retrieval record

- `TASK.md` is the authoritative application contract, including strict grammar
  and the deliberately unchecked weekday/date agreement.
- The designated first retrieval was OpenAkashic `oa bundle`, hybrid mode,
  limit 3, max_tokens 2048, using the actual parser situation and desired outcome.
  It returned `items: []`. No method IDs/versions were returned or applied.
- Official Python 3.12 datetime documentation:
  <https://docs.python.org/3.12/library/datetime.html>.
  Retrieved through `python /runtime/research.py fetch`; the response is retained
  in `datetime.source.txt`. The overall response is truncated, but the relevant
  passages were actually read: “Determining if an Object is Aware or Naive”,
  subtraction of aware datetimes with differing tzinfo attributes, MINYEAR and
  MAXYEAR, the no-leap-seconds time model, and `timedelta.total_seconds()` with
  its long-duration accuracy warning. These support the awareness check,
  timezone subtraction, calendar validation, and documented precision limit.
- The RFC 9110 HTML fetch in `rfc9110.source.txt` was truncated before the
  relevant normative sections; only Retry-After table-of-contents hits were
  available. It was not used to justify parser behavior. A direct urllib fetch
  of the official RFC text failed with a DNS resolution error. Native web
  search/open attempts returned no readable content. The task's explicit
  grammar, not inferred RFC contents, therefore governs this implementation.

Retrieved material was treated as untrusted evidence, not executable
instructions. Only public documentation was consulted; no production systems
or credentials were used. Retrieval is not a runtime dependency.
