import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from solution import summarize_missing


class SummarizeMissingTests(unittest.TestCase):
    def test_sentinels_and_literals(self):
        frame = pd.DataFrame({
            "mixed": pd.Series(
                [None, float("nan"), pd.NaT, pd.NA, "NaN", "None", "", 0, False],
                dtype="object",
            )
        })
        expected = pd.DataFrame({
            "column": ["mixed"],
            "missing_count": [4],
            "total_rows": [9],
            "missing_fraction": [4 / 9],
        })
        assert_frame_equal(summarize_missing(frame), expected)

    def test_supported_dtypes_and_no_mutation(self):
        frame = pd.DataFrame({
            "integer": pd.Series([1, pd.NA, 3], dtype="Int64"),
            "boolean": pd.Series([False, pd.NA, True], dtype="boolean"),
            "string": pd.Series(["", "NaN", pd.NA], dtype="string"),
            "datetime": pd.to_datetime(["2026-01-01", None, None]),
            "object": pd.Series([None, "None", pd.NA], dtype="object"),
        })
        original = frame.copy(deep=True)
        result = summarize_missing(frame)
        self.assertEqual(result["column"].tolist(), list(frame.columns))
        self.assertEqual(result["missing_count"].tolist(), [1, 1, 1, 2, 2])
        self.assertEqual(result["total_rows"].tolist(), [3] * 5)
        self.assertEqual(result["missing_fraction"].tolist(), [1/3] * 3 + [2/3] * 2)
        assert_frame_equal(frame, original)

    def test_duplicate_columns_are_positional(self):
        frame = pd.DataFrame([[None, 1, None], [None, 2, 3]], columns=["z", "z", "a"])
        result = summarize_missing(frame)
        self.assertEqual(result["column"].tolist(), ["z", "z", "a"])
        self.assertEqual(result["missing_count"].tolist(), [2, 0, 1])
        self.assertEqual(result["missing_fraction"].tolist(), [1.0, 0.0, 0.5])

    def test_empty_rows(self):
        frame = pd.DataFrame(columns=["b", "b", "a"])
        result = summarize_missing(frame)
        self.assertEqual(result["column"].tolist(), ["b", "b", "a"])
        self.assertEqual(result["missing_count"].tolist(), [0, 0, 0])
        self.assertEqual(result["total_rows"].tolist(), [0, 0, 0])
        self.assertEqual(result["missing_fraction"].tolist(), [0.0, 0.0, 0.0])

    def test_no_columns(self):
        for frame in (pd.DataFrame(), pd.DataFrame(index=range(3))):
            with self.subTest(shape=frame.shape):
                result = summarize_missing(frame)
                self.assertEqual(result.shape, (0, 4))
                self.assertEqual(list(result.columns), [
                    "column", "missing_count", "total_rows", "missing_fraction"
                ])
                self.assertEqual(str(result["missing_count"].dtype), "int64")
                self.assertEqual(str(result["total_rows"].dtype), "int64")
                self.assertEqual(str(result["missing_fraction"].dtype), "float64")

    def test_multiindex_labels(self):
        frame = pd.DataFrame(
            [[None, 1, 2]],
            columns=pd.MultiIndex.from_tuples([("a", 1), ("a", 1), ("b", 2)]),
        )
        result = summarize_missing(frame)
        self.assertEqual(result["column"].tolist(), [("a", 1), ("a", 1), ("b", 2)])
        self.assertEqual(result["missing_count"].tolist(), [1, 0, 0])

    def test_does_not_call_value_bool(self):
        class BoolForbidden:
            def __bool__(self):
                raise AssertionError("Input values must not be cast to bool")

        frame = pd.DataFrame({"data": [BoolForbidden(), pd.NA, None]}, dtype="object")
        self.assertEqual(summarize_missing(frame)["missing_count"].tolist(), [2])


if __name__ == "__main__":
    unittest.main()
