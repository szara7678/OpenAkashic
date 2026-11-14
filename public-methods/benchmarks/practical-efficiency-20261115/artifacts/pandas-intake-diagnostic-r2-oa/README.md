# Repair-desk missingness diagnostic

`solution.py` exports `diagnose(df: pandas.DataFrame) -> dict`. Requires Python
and pandas; the supplied environment has Python 3.12 and pandas 2.3.3.

```python
import json
import pandas as pd
from solution import diagnose

frame = pd.DataFrame({"desk": ["A", "A"],
                      "wait_minutes": [2, None], "charge": [None, 8]})
print(json.dumps(diagnose(frame), allow_nan=False, indent=2))
```

## Semantics

- `columns` counts missing numeric cells and divides by total input rows (0.0
  for empty input). Only `wait_minutes` and `charge` are summarized.
- `patterns` contains only observed boolean pairs, sorted false before true.
- `observed` retains every row; each mean uses its own observed denominator.
- `complete_case` includes only rows with both numeric values recorded.
- `desk_median` retains every row and fills only missing numeric cells using
  the original observed median of the same column and desk. No fallback to
  other desks, no zero replacement, and no iterative imputation occurs.
- An all-missing desk/column stays missing. Remaining missing cells do not
  enter means; an empty mean becomes Python `None` (JSON `null`).
- Missing desk labels are not pooled into a fictitious shared desk: their
  observed values contribute to means, but their missing values stay missing.
  The task does not specify missing desk identifiers; this is explicit policy.
- Work takes place on numeric float64 copies, allowing fractional medians for
  nullable integer inputs. Input values, index, and dtypes remain unchanged.

Inputs are assumed to contain the three named columns, unique column names,
finite real numeric observations or pandas-recognized numeric missing values,
and valid desk grouping labels. There is no schema/coercion or infinity-handling
API. Float64 working arithmetic can round integers above its exact range.

## Validation

Reproducible command from `/work`:

```sh
python -m unittest -v test_solution.py
```

Actual observed result: **9 tests passed**, `Ran 9 tests in 0.511s`, `OK`
(Python 3.12, pandas 2.3.3). The randomized test includes 100 seeded trials.
Also ran `python -m py_compile solution.py test_solution.py`: exit status 0,
no output (successful compilation).
Tests cover exact output, empty
input, all-missing groups, unobserved categorical desks, nullable integer and
float columns, fractional medians, zero observations, no complete cases,
duplicate and multi-level indexes, missing desk labels, strict JSON encoding,
input preservation, and 100 seeded comparisons with a scalar reference.

## Sources actually read and applied

The designated first retrieval was an OpenAkashic hybrid bundle with the actual
repair-desk situation and diagnostic goal. The complete method read was
`method_f040265d2ae640c49d8614c218e06d61`, version **2**, titled
“결과 민감도 비교표” (result sensitivity comparison table). Its status was
not independently verified; it was treated as untrusted evidence, not authority.
Applied steps: enumerate the three specified analysis choices (1), set their
alternatives (2), report identical metrics and sample sizes for each (3), compare
changes in the exact-output tests (4), and state remaining uncertainty (5).
The task requests no ranking, so no ranking or direction recommendation is added.
The method's attributed official pandas passages state that missing group keys
are excluded by default and that `dropna()` drops rows or columns with missing
values. The implementation uses an equivalent explicit complete-case mask.

Official pandas documentation actually retrieved/read:

- https://pandas.pydata.org/pandas-docs/version/2.3/reference/api/pandas.DataFrame.isna.html
  — boolean missingness masks; None/NaN are missing, zero is not.
- https://pandas.pydata.org/pandas-docs/version/2.3/reference/api/pandas.core.groupby.SeriesGroupBy.transform.html
  — group transformations preserve the original index and accept method names.
- https://pandas.pydata.org/pandas-docs/version/2.3/reference/api/pandas.core.groupby.DataFrameGroupBy.median.html
  — group medians exclude missing values; all-missing behavior is checked
  separately by the local tests.
- https://pandas.pydata.org/pandas-docs/version/2.3/reference/api/pandas.DataFrame.groupby.html
  — `dropna` controls missing desk keys; `observed` controls categorical groups.
- https://pandas.pydata.org/docs/reference/api/pandas.Series.mean.html
  — `skipna=True` excludes missing values from means.

Evidence/version corrections: an initial unversioned transform fetch failed
with HTTP 502; it was not used as evidence. Unversioned documentation identified
itself as pandas 3.1.1 whereas the installed runtime is 2.3.3. Version-2.3
references were therefore retrieved for version-sensitive grouping behavior;
`dropna` and `observed` are explicitly set instead of relying on changing defaults.
The method's source labels mention 3.1.0; this is not the tested runtime version.

## What the comparison cannot establish

These are descriptive sensitivity summaries, not estimates of why information
was not captured. They cannot identify a missingness mechanism, recover true
unrecorded values, remove selection bias, demonstrate accuracy of median fills,
or establish causality. Changing means or retained row counts does not identify
a preferred policy. Complete-case computation is not a recommendation to delete
records, and a synthetic median comparison is not a new operational data source.
No production systems or credentials are used.
