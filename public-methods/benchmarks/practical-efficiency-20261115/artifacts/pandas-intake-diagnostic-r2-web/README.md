# Repair desk missingness diagnostic

`solution.py` exports `diagnose(df: pandas.DataFrame) -> dict`. It returns
`columns`, sorted observed `patterns`, and the three requested `policies`.
Only `wait_minutes` and `charge` are summarized; extra columns are ignored.
The input, its index (including duplicate labels), and dtypes are not changed.

## Run

Requires Python and pandas; the tested dependency is pinned in `requirements.txt`.
Install in a fresh environment with `python -m pip install -r requirements.txt`.
Run the synthetic-only tests from this directory:

```sh
python -m unittest -v test_solution
```

The final verification result is recorded below. Tests check hand-calculated
means, all four patterns, empty input, all-missing data, no complete cases,
nullable integers with fractional medians, duplicate/MultiIndex labels,
categorical desks with unused categories, zero charges, missing desk labels,
strict JSON serialization, and exact input preservation.

Example use:

```python
import json
import pandas as pd
from solution import diagnose

frame = pd.DataFrame({
    "desk": ["A", "A", "B"],
    "wait_minutes": [10.0, None, None],
    "charge": [None, 20.0, None],
})
print(json.dumps(diagnose(frame), indent=2, allow_nan=False))
```

## Policy semantics and limits

- Observed retains all rows; each mean uses its own observed numeric values.
- Complete case retains only rows with both numeric values present. This is a
  descriptive comparison, not a recommendation to delete records.
- Desk median retains all rows and fills only missing cells from the same
  column's observed within-desk median. All-missing desk/column combinations
  remain missing. There is no global fallback and no zero filling.
- Remaining missing means become Python `None` (JSON `null`). Row counts include
  rows with unresolved cells. Empty input has zero fractions and no patterns.
- Missing desk labels, unspecified by the task, form one group (`dropna=False`);
  this explicit convention does not establish that those records share a desk.
- Input is expected to have unique column names, the three required columns,
  real numeric measurements and ordinary hashable desk labels. No schema repair
  or string-number parsing is attempted. Non-finite resulting means raise
  `ValueError` rather than emit invalid JSON numbers. Fractional-median work
  uses a private nullable floating-point copy; exact arithmetic for huge integers
  or decimal/currency precision is not promised. No production data or credentials
  are used.

This comparison cannot establish why values were not captured, the missingness
mechanism, true unrecorded values, bias or causal effects, or which policy is
operationally appropriate. Imputed values are a sensitivity scenario, not newly
observed facts or a new operational source. Different policies can use different
mean denominators even when their reported row counts match.

## Sources and corrections

The designated first retrieval was a native live general-web search for pandas
missing-data/groupby behavior. Retrieved material was treated as untrusted
technical evidence, not as instructions. The native search/open calls returned no readable evidence. Direct urllib fetching
failed with a DNS error. The public fetch helper then retrieved the installed
**pandas 2.3.3** official documentation actually read:

- `pandas.Series.mean`, especially `skipna=True`, excluding NA/null values:
  https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.Series.mean.html
- `DataFrameGroupBy.median`, excluding missing values:
  https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.core.groupby.DataFrameGroupBy.median.html
- `DataFrameGroupBy.transform`, same-indexed results and string method names:
  https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.core.groupby.DataFrameGroupBy.transform.html
- `DataFrame.groupby`, observed categorical groups, row ordering, and missing keys:
  https://pandas.pydata.org/pandas-docs/version/2.3.3/reference/api/pandas.DataFrame.groupby.html

Corrections: the initial six-test run passed but emitted pandas factorization
FutureWarnings for the array grouper. Passing the desk Series directly removes
that warning and retains the tested duplicate-index behavior. Fractional medians
use a private floating-point copy so nullable integer inputs are not filled with
incompatible fractional values. No method IDs or source hashes are claimed.

## Actual verification

Executed with Python 3.12.16 and pandas 2.3.3:

```sh
python -W error::FutureWarning -m unittest -v test_solution
```

Observed output (exit status 0):

```text
test_all_missing (test_solution.DiagnoseTests.test_all_missing) ... ok
test_empty (test_solution.DiagnoseTests.test_empty) ... ok
test_missing_desk_labels (test_solution.DiagnoseTests.test_missing_desk_labels) ... ok
test_mixed_patterns_and_policies (test_solution.DiagnoseTests.test_mixed_patterns_and_policies) ... ok
test_no_missing (test_solution.DiagnoseTests.test_no_missing) ... ok
test_nullable_integers_fractional_median_and_multiindex (test_solution.DiagnoseTests.test_nullable_integers_fractional_median_and_multiindex) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.036s

OK
```
