# Offline Retry-After viewer helper

`solution.py` exports `retry_after_seconds(value: str | None, now: datetime.datetime) -> int | None`.
Requires Python 3.10+; standard library only, with no installation required.

```python
import datetime
from solution import retry_after_seconds

reference = datetime.datetime(1994, 11, 6, 8, 49, 36, tzinfo=datetime.timezone.utc)
assert retry_after_seconds("Sun, 06 Nov 1994 08:49:37 GMT", reference) == 1
assert retry_after_seconds("120", reference) == 120
```

## Contract and limitations

- Validates awareness before examining the header: missing `tzinfo` or a `None`
  UTC offset raises `ValueError`, including for an absent header.
- Strips surrounding Python string whitespace; interior whitespace is strict.
  Only ASCII digits are numeric delays. Chunked conversion avoids Python's
  decimal-string conversion length limit without changing interpreter settings.
  No application length limit is imposed; enormous inputs still cost memory/CPU.
- Accepts only the exact case-sensitive English IMF-fixdate shape with literal
  `GMT`, two-digit day/time fields and four-digit year. Calendar-invalid dates,
  leap seconds, year zero, obsolete HTTP dates, and other formats return `None`.
- Weekday spelling is checked, but agreement with the calendar is deliberately
  not checked. Explicit English tokens avoid locale-dependent date parsing.
- Aware datetime subtraction accounts for the reference's UTC offset rather than
  relabeling its wall-clock fields. Past/equal dates clamp to zero; future dates
  use `max(0, ceil((header_time - now).total_seconds()))` exactly as requested.
- Python's Gregorian datetime range is years 1–9999 and does not model leap
  seconds. `total_seconds()` uses floating point and can lose microsecond
  accuracy on intervals over roughly 270 years; the requested formula is kept.
- This is display-only: no sleeping, requests, system-clock reads, or clock changes.
  The caller supplies a trusted aware reference time; clock skew and historical
  response-receipt time are not inferred. Out-of-contract argument types and
  broken custom `tzinfo` implementations are not normalized.

## Evidence and corrections

The designated first retrieval was a native general-web search for RFC 9110
Retry-After / IMF-fixdate. The search and subsequent native open/find calls
returned no visible material. Public fetches through `/runtime/research.py`
returned official documents. The initial RFC 9110 HTML response was truncated
before the relevant sections, so it is not claimed as support for their contents.
The following complete relevant passages were actually read:

- RFC 7231 §7.1.3: https://www.rfc-editor.org/rfc/rfc7231.txt
  defines the date-or-nonnegative-decimal alternatives and `1*DIGIT` grammar.
- RFC 7231 §7.1.1.1, in that same official document, defines IMF-fixdate,
  English case-sensitive tokens, GMT/UTC, obsolete formats, and leap seconds.
  RFC 7231 is historical (superseded by RFC 9110); it is used here only as
  evidence for the fixed format specified explicitly by this task.
- Python 3.12 datetime documentation:
  https://docs.python.org/3.12/library/datetime.html
  passages on awareness, aware datetime subtraction, constructor ranges, and
  `timedelta.total_seconds()` support offset handling and precision limitations.
  The unversioned documentation was also fetched, but version-pinned 3.12
  passages were used to match the actual runtime.

Scope correction: the RFC's general HTTP recipient rules include obsolete
HTTP-date formats and its grammar allows leap seconds. This task intentionally
implements a narrower offline format contract, not a fully general HTTP recipient;
Python datetime cannot represent leap seconds. No retrieved instructions were
used as authority over the task. No method IDs or hashes are asserted.
Direct `urllib` retrieval failed with a DNS resolution error; the provided
public-fetch helper succeeded. This research traffic is not part of the helper
or its tests, which remain offline.

## Validation

Run from this directory:

```sh
python --version
python -m unittest -v
python -m py_compile solution.py test_solution.py
```

Actually executed in `/work`:

- `python --version`: `Python 3.12.16`.
- `python -m unittest -v`: `Ran 11 tests in 0.003s`, `OK`.
- `python -m py_compile solution.py test_solution.py`: exit status 0, no output.

Tests cover decimal and very long input, invalid/non-ASCII inputs, awareness
validation before absent headers, rounding/clamping, timezone offsets, all
weekday tokens without date agreement, strict date shape, impossible dates,
leap-year/year boundaries, and guards against sleeping/network socket creation.
The no-I/O test is a regression guard, not an exhaustive sandbox proof.

