"""Descriptive missingness and policy comparison for synthetic desk intake."""

import math

import pandas as pd


NUMERIC_COLUMNS = ["wait_minutes", "charge"]


def _summary(values: pd.DataFrame) -> dict:
    result = {"rows": int(len(values))}
    for column, key in (("wait_minutes", "wait_mean"), ("charge", "charge_mean")):
        mean = values[column].mean(skipna=True)
        if pd.isna(mean):
            result[key] = None
        else:
            number = float(mean)
            if not math.isfinite(number):
                raise ValueError("Policy means must be finite for JSON output")
            result[key] = number
    return result


def diagnose(df: pd.DataFrame) -> dict:
    """Compare observed, complete-case, and within-desk median summaries.

    Requires desk, wait_minutes, and charge columns. Missing desk labels form
    one group. Only private numeric copies are converted for fractional medians.
    """
    values = df[NUMERIC_COLUMNS].copy(deep=True)
    missing = values.isna()
    row_count = len(df)
    columns = {}
    for column in NUMERIC_COLUMNS:
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
                patterns.append(
                    {
                        "wait_missing": wait_missing,
                        "charge_missing": charge_missing,
                        "rows": count,
                    }
                )

    median_values = values.astype("Float64")
    medians = median_values.groupby(
        df["desk"], sort=False, observed=True, dropna=False
    ).transform("median")
    filled = median_values.fillna(medians)
    return {
        "columns": columns,
        "patterns": patterns,
        "policies": {
            "observed": _summary(values),
            "complete_case": _summary(values.loc[~missing.any(axis=1)]),
            "desk_median": _summary(filled),
        },
    }
