"""Missingness summaries and descriptive policy comparisons for synthetic intake."""

import pandas as pd


NUMERIC_COLUMNS = ["wait_minutes", "charge"]


def _summary(values: pd.DataFrame) -> dict:
    means = values.mean(skipna=True)
    return {
        "rows": int(len(values)),
        "wait_mean": None if pd.isna(means["wait_minutes"]) else float(means["wait_minutes"]),
        "charge_mean": None if pd.isna(means["charge"]) else float(means["charge"]),
    }


def diagnose(df: pd.DataFrame) -> dict:
    """Compare three descriptive policies without changing the supplied DataFrame.

    Numeric inputs are finite real values or pandas-recognized missing values.
    Missing desk labels have no known same-desk peers, so are not imputed.
    """
    work = df.loc[:, ["desk", *NUMERIC_COLUMNS]].reset_index(drop=True).copy()
    values = work[NUMERIC_COLUMNS].astype("Float64")
    missing = values.isna()
    row_count = len(values)
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
            rows = int(
                (
                    (missing["wait_minutes"] == wait_missing)
                    & (missing["charge"] == charge_missing)
                ).sum()
            )
            if rows:
                patterns.append({
                    "wait_missing": wait_missing,
                    "charge_missing": charge_missing,
                    "rows": rows,
                })
    medians = values.groupby(work["desk"], sort=False, observed=True).transform("median")
    filled = values.where(~missing, medians)
    return {
        "columns": columns,
        "patterns": patterns,
        "policies": {
            "observed": _summary(values),
            "complete_case": _summary(values.loc[~missing.any(axis=1)]),
            "desk_median": _summary(filled),
        },
    }
