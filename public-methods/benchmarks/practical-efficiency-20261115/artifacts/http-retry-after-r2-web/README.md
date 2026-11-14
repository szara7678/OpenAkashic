# Offline Retry-After display parser

`solution.py` exports `retry_after_seconds(value: str | None, now: datetime.datetime) -> int | None`.
Requires Python 3.10+; uses only the standard library. Import it and pass the
header value and a timezone-aware datetime representing the desired reference instant.
It never sleeps, reads/changes the clock, or makes network requests.

## Behavior and limitations

- Validates awareness before inspecting the header, including absent values.
  A tzinfo object whose `utcoffset()` returns None is also naive.
- Strips surrounding Python string whitespace. Accepts only ASCII digits for
  integer delays, including leading zeroes. Chunked conversion avoids Python's
  decimal-string conversion length limit without changing interpreter settings.
  Very large inputs still consume CPU and memory; no input-length cap is imposed.
- Dates require exact, case-sensitive English IMF-fixdate syntax with single
  internal spaces, two-digit day/time fields, four-digit year, and literal GMT.
  Valid weekday tokens are required but calendar agreement is intentionally ignored.
- Rejects impossible dates, leap seconds, year 0000, fractional seconds, alternate
  zones, and obsolete date formats. Datetime supports years 0001 through 9999.
- Aware datetime subtraction accounts for the supplied UTC offset, including
  non-UTC reference times. Results are `max(0, ceil(delta.total_seconds()))`.
  Python documents loss of microsecond precision for very large intervals
  (over approximately 270 years); this implementation preserves the requested
  total_seconds formula rather than substituting different rounding semantics.
- The caller supplies the clock/reference instant. Clock skew is not corrected;
  past dates clamp to zero. There is no retry scheduling or request execution.

## Verification

Run from this directory:

```sh
python --version
python -m unittest -v
```

Actual observed results are recorded below after running the commands.
The suite covers strict syntax, invalid calendar values, weekday mismatches,
rounding, non-UTC offsets, naive-clock validation, and long integer values.

## Sources and corrections

The designated first retrieval was a native live web search for RFC 9110
Retry-After and IMF-fixdate; it returned no visible results. Official sources
were then opened and their relevant passages actually read:

- RFC 9110, section 10.2.3, Retry-After:
  https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3
  Defines HTTP-date or nonnegative decimal integer seconds.
- RFC 9110, section 5.6.7, Date/Time Formats:
  https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.7
  Defines IMF-fixdate's fixed syntax and UTC meaning. Correction to a possible
  overbroad reading: HTTP recipients normally accept obsolete date formats too;
  this task deliberately requires a narrower parser that rejects them.
- Official Python datetime documentation, awareness, datetime subtraction,
  and timedelta.total_seconds:
  https://docs.python.org/3/library/datetime.html
  Confirms offset-aware arithmetic and the large-interval precision limitation.
  The live page identified itself as Python 3.15.2 documentation; the locally
  tested interpreter version is recorded in the actual results, not inferred
  from the documentation page.

Retrieved material was treated as evidence only, not as implementation instructions.
No external packages, production systems, or credentials are used.
