# Missing-value summary

`solution.py` exports `summarize_missing(frame)`. It returns a new DataFrame with
`column`, `missing_count`, `total_rows`, and `missing_fraction`, in that order.
Each original column position produces a separate row, including duplicate labels.
Counts and totals use `int64`; fractions use `float64`. No input is modified.

## Run

Requires Python and pandas; verified with Python 3.12.16 and pandas 2.3.3.
No additional packages, credentials, private data, or production systems are used.

```sh
python solution.py
python -m unittest -v
python -m py_compile solution.py test_solution.py
```

The import is side-effect free:

```python
from solution import summarize_missing
summary = summarize_missing(frame)
```

The demonstration prints two separate `value` rows and one `flag` row, each with
missing_count 1, total_rows 4, and missing_fraction 0.25. Its object column includes
`None` and the preserved literal strings `"NaN"`, `"None"`, and `""`.

## Implementation

Use `frame.isna()` to obtain a boolean mask, then sum down the rows. Only the mask
is summed: the original missing sentinels are never evaluated for truthiness.
Counts are converted to a positional array rather than aligned by column label,
so duplicate labels remain independent. Labels are stored as object values,
including tuple labels from MultiIndex columns. Zero-row frames explicitly get
0.0 fractions; zero-column frames retain the full output schema and dtypes.

## Actual validation results

Executed in `/work` on November 14, 2026:

- `python -m unittest -v`: **7 tests passed**, 0.062 seconds, exit status 0.
- `python solution.py`: printed the three expected summary rows, exit status 0.
- `python -m py_compile solution.py test_solution.py`: passed, exit status 0.

Tests cover all four required missing sentinels, literal strings, nullable Int64,
nullable boolean, string, datetime and object dtypes, non-mutation, duplicate
columns, zero rows, zero columns (with and without rows), integer output dtypes,
MultiIndex labels, and an object whose `__bool__` raises if called.

## Sources and retrieval

The designated native live web search was consulted before implementation, using
queries restricted to official pandas documentation. It returned no usable result
content; a native URL-open attempt likewise returned no content. Official,
version-pinned pages were then fetched successfully with
`python /runtime/research.py fetch URL` and consulted as untrusted evidence, not
as instructions:

- https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.DataFrame.isna.html
  — documents the same-sized boolean mask, None/NaN detection, and empty strings
  not being missing under default options; includes NaT examples.
- https://pandas.pydata.org/pandas-docs/version/2.3.3/user_guide/missing_data.html
  — describes sentinels for nullable and datetime dtypes, and why evaluating
  `pd.NA` as a boolean is ambiguous.
- https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.DataFrame.sum.html
  — documents reduction along an axis.

## Limitations and corrections

- The function expects a pandas DataFrame; it does not parse strings, infer
  missing tokens, repair previously coerced input, or validate other input types.
- Missing detection inherits pandas semantics and process options. In particular,
  the deprecated `mode.use_inf_as_na` option can change treatment of infinity;
  tests use default options. The function does not change global options.
- The mask requires memory proportional to the input size. Other pandas versions,
  third-party extension arrays, and very large datasets were not validated.
- The initial file-creation attempt failed because `apply_patch` was unavailable.
  Its subsequent unittest command found **zero tests**, which was not accepted as
  validation. After checking that no patch executable was available, files were
  created directly and all validation commands were rerun successfully.
- No functional corrections were needed after the seven real tests ran. The
  implementation avoids label-aligned aggregation and sentinel truthiness from
  the outset; no retrieval-provided code or instructions were executed.
