"""Summarize genuine pandas missing values without changing the input."""

import pandas as pd


def summarize_missing(frame: pd.DataFrame) -> pd.DataFrame:
    """Return one summary row per positional input column, including duplicates."""
    total_rows = len(frame)
    missing_counts = frame.isna().sum(axis=0).to_numpy(dtype="int64")
    missing_fractions = (
        missing_counts / total_rows
        if total_rows
        else missing_counts.astype("float64")
    )
    return pd.DataFrame(
        {
            "column": pd.Series(list(frame.columns), dtype="object"),
            "missing_count": missing_counts,
            "total_rows": pd.Series(total_rows, index=range(frame.shape[1]), dtype="int64"),
            "missing_fraction": missing_fractions,
        }
    )


if __name__ == "__main__":
    example = pd.concat(
        [
            pd.Series([None, "NaN", "None", ""], name="value", dtype="object"),
            pd.Series([1, pd.NA, 3, 4], name="value", dtype="Int64"),
            pd.Series([True, False, pd.NA, True], name="flag", dtype="boolean"),
        ],
        axis=1,
    )
    print(summarize_missing(example).to_string(index=False))
