# Repair-desk missingness diagnosis

`solution.py` exports `diagnose(df: pandas.DataFrame) -> dict`. It returns
`columns`, sorted observed `patterns`, and `policies` (`observed`,
`complete_case`, `desk_median`). Only `wait_minutes` and `charge` are measured.
Missing means **not captured**, never zero. Input values, index and dtypes are
not changed; calculations use a separate floating-point numeric frame so
fractional medians can fill nullable integer input without truncation.

Observed means use each column's available values. Complete-case results use
only rows with both numeric values. Desk-median results retain every row and
fill only from the corresponding column's observed values in that desk.
An all-missing desk/column stays missing, with no global fallback. Empty means
are Python `None` (JSON `null`), and empty-input missing fractions are `0.0`.
Missing desk labels are unspecified by the task: this implementation leaves
those rows' missing numeric cells unfilled, rather than treating unknown desks
as a shared operational desk. Their observed values still contribute to means.

## Run and validation

Requires Python and pandas; the actual environment has pandas 2.3.3.
From `/work`, run:

```sh
python -m unittest -v test_solution.py
```

Observed result on November 14, 2026: **8 tests passed** (`Ran 8 tests in
0.060s`, `OK`), with Python 3.12.16 and pandas 2.3.3. The tests cover the exact
comparison table, all four patterns, empty input, all-missing columns/desks,
column-specific missing desks, nullable dtypes and fractional medians,
duplicate indices, categorical desks with unused categories, observed zeroes,
no complete cases, strict JSON serialization, and input preservation.

Example:

```python
import json
import pandas as pd
from solution import diagnose

frame = pd.DataFrame({
    "desk": ["A", "A"],
    "wait_minutes": [10, None],
    "charge": [None, 30],
})
print(json.dumps(diagnose(frame), allow_nan=False, indent=2))
```

## Evidence actually read and applied

The designated first retrieval was an OpenAkashic hybrid bundle about this
specific repair-desk missingness comparison. Retrieved content was treated as
untrusted evidence, not executable instructions. Both complete methods were
read directly; neither required a method fetch:

- `method_6562f35901794b5e9f8f477796e7505b`, version 2: applied steps 1–5:
  count missing cells and joint patterns, retain the task's source definition
  of missingness, distinguish the prescribed alternatives, compare sample sizes
  and means, and preserve original data. No interpolation or additional policy
  was introduced.
- `method_f040265d2ae640c49d8614c218e06d61`, version 2: applied steps 1–3 and 5:
  identify policy choices/defaults, use the three requested alternatives,
  compute consistent metrics and row counts, and report uncertainty. Step 4's
  separate ranking/change flags were not added because the requested schema
  calls only for side-by-side results.

Complete methods contained attributed official pandas passages on `dropna`
and missing group keys, but not enough detail for the median implementation.
Additional official documentation actually read:

- pandas `Series.mean` API (`https://pandas.pydata.org/docs/reference/api/pandas.Series.mean.html`):
  mean calculation and default NA exclusion. The live page identified itself
  as pandas 3.1.1, not the installed version.
- pandas 2.3.3 `SeriesGroupBy.transform` API
  (`https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.core.groupby.SeriesGroupBy.transform.html`):
  same-indexed results and named group operations.
- pandas 2.3.3 `DataFrame.groupby` API
  (`https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.DataFrame.groupby.html`):
  explicit `observed=True`, `sort=False` and `dropna=True` semantics.
- pandas 2.3.3 `Series.median` API
  (`https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.Series.median.html`):
  median excludes missing values by default.

## Corrections and limitations

The first public fetch of the live transform API returned HTTP 502; it supplied
no evidence. Version-pinned official documentation was subsequently read
successfully. The methods' attributed documentation was labeled 3.1.0, whereas
the runtime is 2.3.3; no claim is made that these are the same version. Local
validation, not a retrieved contributor's reported results, establishes the
results recorded here.

This is a descriptive policy comparison, not a recommendation to delete rows
or replace an operational source. It cannot establish why values were not
captured, whether missingness is random, the true uncaptured values, unbiased
population means, causal effects, or the best operational policy. Different
policies use different effective column denominators; retained row counts do
not imply every numeric cell was observed or filled. Entirely unobserved
values cannot be recovered from a desk median. Assumes the required columns
exist with numeric measurements (finite or missing) and ordinary hashable desk
labels. Schema validation and nonfinite numeric inputs are outside the stated
intake contract. Calculations have ordinary floating-point precision.
No production systems or credentials are used.
