import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from solution import summarize_missing


class SummarizeMissingTests(unittest.TestCase):
    def test_real_sentinels_and_literal_strings(self):
        frame = pd.DataFrame(
            {"mixed": [None, float("nan"), pd.NaT, pd.NA, "NaN", "None", "", 0, False]},
            dtype="object",
        )
        before = frame.copy(deep=True)
        result = summarize_missing(frame)
        expected = pd.DataFrame(
            {"column": ["mixed"], "missing_count": [4], "total_rows": [9],
             "missing_fraction": [4 / 9]}
        )
        assert_frame_equal(result, expected)
        assert_frame_equal(frame, before)

    def test_supported_dtypes(self):
        frame = pd.DataFrame(
            {
                "integer": pd.Series([1, pd.NA, 3], dtype="Int64"),
                "boolean": pd.Series([True, pd.NA, False], dtype="boolean"),
                "string": pd.Series(["", pd.NA, "NaN"], dtype="string"),
                "datetime": pd.to_datetime(["2026-01-01", None, "2026-01-03"]),
                "object": pd.Series([None, "None", ""], dtype="object"),
            }
        )
        before = frame.copy(deep=True)
        result = summarize_missing(frame)
        self.assertEqual(result["column"].tolist(), frame.columns.tolist())
        self.assertEqual(result["missing_count"].tolist(), [1] * 5)
        self.assertEqual(result["total_rows"].tolist(), [3] * 5)
        self.assertEqual(result["missing_fraction"].tolist(), [1 / 3] * 5)
        assert_frame_equal(frame, before)

    def test_duplicate_labels_have_independent_counts(self):
        frame = pd.DataFrame([[None, "NaN", None], [1, "", None]], columns=["z", "a", "z"])
        result = summarize_missing(frame)
        self.assertEqual(result["column"].tolist(), ["z", "a", "z"])
        self.assertEqual(result["missing_count"].tolist(), [1, 0, 2])
        self.assertEqual(result["missing_fraction"].tolist(), [0.5, 0.0, 1.0])

    def test_zero_rows(self):
        result = summarize_missing(pd.DataFrame(columns=["same", "same", "last"]))
        self.assertEqual(result["column"].tolist(), ["same", "same", "last"])
        self.assertEqual(result["missing_count"].tolist(), [0, 0, 0])
        self.assertEqual(result["total_rows"].tolist(), [0, 0, 0])
        self.assertEqual(result["missing_fraction"].tolist(), [0.0, 0.0, 0.0])

    def test_zero_columns(self):
        for frame in [pd.DataFrame(), pd.DataFrame(index=range(3))]:
            with self.subTest(rows=len(frame)):
                result = summarize_missing(frame)
                self.assertEqual(result.shape, (0, 4))
                self.assertEqual(list(result), ["column", "missing_count", "total_rows", "missing_fraction"])
                self.assertEqual(str(result["missing_count"].dtype), "int64")
                self.assertEqual(str(result["total_rows"].dtype), "int64")
                self.assertEqual(str(result["missing_fraction"].dtype), "float64")

    def test_tuple_and_nonstring_labels(self):
        labels_to_test = [
            [2, None, ("tuple", 3)],
            pd.MultiIndex.from_tuples([("a", 1), ("a", 1), ("b", 2)]),
        ]
        for labels in labels_to_test:
            with self.subTest(labels=labels):
                result = summarize_missing(pd.DataFrame([[None, 2, 3]], columns=labels))
                self.assertEqual(result["column"].tolist(), list(labels))
                self.assertEqual(result["missing_count"].tolist(), [1, 0, 0])

    def test_nondefault_duplicate_row_index(self):
        result = summarize_missing(pd.DataFrame({"value": [None, 1, None]}, index=[7, 7, 2]))
        self.assertEqual(result["missing_count"].tolist(), [2])
        self.assertEqual(result["total_rows"].tolist(), [3])

    def test_no_missing_and_all_missing(self):
        frame = pd.DataFrame({"complete": [0, False, ""], "missing": [pd.NA, None, pd.NaT]})
        result = summarize_missing(frame)
        self.assertEqual(result["missing_count"].tolist(), [0, 3])
        self.assertEqual(result["missing_fraction"].tolist(), [0.0, 1.0])
        self.assertEqual(str(result["missing_count"].dtype), "int64")
        self.assertEqual(str(result["total_rows"].dtype), "int64")


if __name__ == "__main__":
    unittest.main()
