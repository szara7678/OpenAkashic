"""Summarize missing values without coercing the original data."""

import pandas as pd


def summarize_missing(frame: pd.DataFrame) -> pd.DataFrame:
    """Return one missing-value summary row per input column position."""
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
            "total_rows": pd.Series(
                total_rows, index=range(frame.shape[1]), dtype="int64"
            ),
            "missing_fraction": missing_fractions,
        }
    )


def main() -> None:
    """Run a synthetic example, including duplicate labels and literals."""
    frame = pd.concat(
        [
            pd.Series([1, pd.NA, 3, 4], dtype="Int64", name="value"),
            pd.Series([None, "NaN", "None", ""], dtype="object", name="value"),
            pd.Series([True, False, pd.NA, True], dtype="boolean", name="flag"),
        ],
        axis=1,
    )
    print(summarize_missing(frame).to_string(index=False))


if __name__ == "__main__":
    main()
