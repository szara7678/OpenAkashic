"""Descriptive missingness and policy comparisons for synthetic desk records."""

import pandas as pd


_NUMERIC_COLUMNS = ["wait_minutes", "charge"]


def _summary(values: pd.DataFrame) -> dict:
    result = {"rows": int(len(values))}
    for column, key in zip(_NUMERIC_COLUMNS, ("wait_mean", "charge_mean")):
        mean = values[column].mean(skipna=True)
        result[key] = None if pd.isna(mean) else float(mean)
    return result


def diagnose(df: pd.DataFrame) -> dict:
    """Compare observed, complete-case, and within-desk median summaries.

    Missing desk labels do not establish a shared desk; their missing numeric
    values remain unfilled. Numeric working copies support fractional medians
    even when the input uses nullable integer columns.
    """
    missing = df[_NUMERIC_COLUMNS].isna()
    row_count = len(df)
    columns = {}
    for column in _NUMERIC_COLUMNS:
        count = int(missing[column].sum())
        columns[column] = {
            "missing": count,
            "fraction": float(count / row_count) if row_count else 0.0,
        }

    patterns = []
    for wait_missing in (False, True):
        for charge_missing in (False, True):
            count = int(
                (
                    (missing["wait_minutes"] == wait_missing)
                    & (missing["charge"] == charge_missing)
                ).sum()
            )
            if count:
                patterns.append({
                    "wait_missing": wait_missing,
                    "charge_missing": charge_missing,
                    "rows": count,
                })

    values = df[_NUMERIC_COLUMNS].astype("float64")
    complete = values.loc[~missing.any(axis=1)]
    filled = values.copy(deep=True)
    for column in _NUMERIC_COLUMNS:
        medians = values[column].groupby(
            df["desk"], sort=False, observed=True, dropna=True
        ).transform("median")
        filled[column] = values[column].fillna(medians)

    return {
        "columns": columns,
        "patterns": patterns,
        "policies": {
            "observed": _summary(values),
            "complete_case": _summary(complete),
            "desk_median": _summary(filled),
        },
    }
