"""Missingness diagnostics for synthetic repair-desk intake records."""

import pandas as pd


NUMERIC_COLUMNS = ["wait_minutes", "charge"]


def _summary(values: pd.DataFrame) -> dict:
    result = {"rows": int(len(values))}
    for column, key in (("wait_minutes", "wait_mean"), ("charge", "charge_mean")):
        observed = values[column].dropna()
        result[key] = float(observed.mean()) if len(observed) else None
    return result


def diagnose(df: pd.DataFrame) -> dict:
    """Compare three descriptive policies without modifying the input frame."""
    missing = df[NUMERIC_COLUMNS].isna()
    row_count = len(df)
    columns = {
        column: {
            "missing": int(missing[column].sum()),
            "fraction": float(missing[column].sum() / row_count) if row_count else 0.0,
        }
        for column in NUMERIC_COLUMNS
    }
    patterns = []
    for wait_missing in (False, True):
        for charge_missing in (False, True):
            count = int(
                ((missing["wait_minutes"] == wait_missing)
                 & (missing["charge"] == charge_missing)).sum()
            )
            if count:
                patterns.append({
                    "wait_missing": wait_missing,
                    "charge_missing": charge_missing,
                    "rows": count,
                })

    values = df[NUMERIC_COLUMNS].astype("float64").copy()
    complete = values.dropna(subset=NUMERIC_COLUMNS)
    medians = values.groupby(
        df["desk"], sort=False, observed=True, dropna=True
    ).transform("median")
    filled = values.fillna(medians)
    return {
        "columns": columns,
        "patterns": patterns,
        "policies": {
            "observed": _summary(values),
            "complete_case": _summary(complete),
            "desk_median": _summary(filled),
        },
    }
