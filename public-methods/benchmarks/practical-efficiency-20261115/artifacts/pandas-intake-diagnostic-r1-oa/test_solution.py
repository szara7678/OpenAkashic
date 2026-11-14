import json
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from solution import diagnose


class DiagnoseTests(unittest.TestCase):
    def check(self, frame):
        before = frame.copy(deep=True)
        result = diagnose(frame)
        assert_frame_equal(frame, before)
        json.dumps(result, allow_nan=False)
        self.assertEqual(set(result), {"columns", "patterns", "policies"})
        self.assertEqual(sum(item["rows"] for item in result["patterns"]), len(frame))
        return result

    def test_policy_comparison_and_patterns(self):
        frame = pd.DataFrame({
            "desk": ["A", "A", "A", "B", "B", "C"],
            "wait_minutes": [10, 30, None, 100, None, None],
            "charge": [100, None, 300, None, 500, None],
        })
        result = self.check(frame)
        self.assertEqual(result["columns"], {
            "wait_minutes": {"missing": 3, "fraction": 0.5},
            "charge": {"missing": 3, "fraction": 0.5},
        })
        self.assertEqual(result["patterns"], [
            {"wait_missing": False, "charge_missing": False, "rows": 1},
            {"wait_missing": False, "charge_missing": True, "rows": 2},
            {"wait_missing": True, "charge_missing": False, "rows": 2},
            {"wait_missing": True, "charge_missing": True, "rows": 1},
        ])
        self.assertEqual(result["policies"], {
            "observed": {"rows": 6, "wait_mean": 140 / 3, "charge_mean": 300.0},
            "complete_case": {"rows": 1, "wait_mean": 10.0, "charge_mean": 100.0},
            "desk_median": {"rows": 6, "wait_mean": 52.0, "charge_mean": 320.0},
        })

    def test_empty(self):
        result = self.check(pd.DataFrame(columns=["desk", "wait_minutes", "charge"]))
        self.assertEqual(result["patterns"], [])
        for column in result["columns"].values():
            self.assertEqual(column, {"missing": 0, "fraction": 0.0})
        for policy in result["policies"].values():
            self.assertEqual(policy, {"rows": 0, "wait_mean": None, "charge_mean": None})

    def test_all_missing(self):
        result = self.check(pd.DataFrame({
            "desk": ["A", "B"], "wait_minutes": [None, None], "charge": [None, None],
        }))
        self.assertEqual(result["policies"]["desk_median"], {
            "rows": 2, "wait_mean": None, "charge_mean": None,
        })
        self.assertEqual(result["policies"]["complete_case"]["rows"], 0)

    def test_column_specific_all_missing_desk(self):
        result = self.check(pd.DataFrame({
            "desk": ["A", "A", "B", "B"],
            "wait_minutes": [None, None, 2, 4],
            "charge": [10, None, None, None],
        }))
        self.assertEqual(result["policies"]["desk_median"], {
            "rows": 4, "wait_mean": 3.0, "charge_mean": 10.0,
        })

    def test_nullable_integer_fractional_median_and_duplicate_index(self):
        frame = pd.DataFrame({
            "desk": pd.Categorical(["A", "A", "A"], categories=["A", "unused"]),
            "wait_minutes": pd.array([1, 2, None], dtype="Int64"),
            "charge": pd.array([0, None, 10], dtype="Float64"),
        }, index=pd.Index([7, 7, 2], name="record"))
        result = self.check(frame)
        self.assertEqual(result["policies"]["desk_median"], {
            "rows": 3, "wait_mean": 1.5, "charge_mean": 5.0,
        })

    def test_complete_data_zero_is_observed(self):
        result = self.check(pd.DataFrame({
            "desk": ["A", "B"], "wait_minutes": [0, 2], "charge": [0, 20],
        }))
        for policy in result["policies"].values():
            self.assertEqual(policy, {"rows": 2, "wait_mean": 1.0, "charge_mean": 10.0})
        self.assertEqual(len(result["patterns"]), 1)

    def test_no_complete_cases(self):
        result = self.check(pd.DataFrame({
            "desk": ["A", "A"], "wait_minutes": [2, None], "charge": [None, 8],
        }))
        self.assertEqual(result["policies"]["complete_case"], {
            "rows": 0, "wait_mean": None, "charge_mean": None,
        })
        self.assertEqual(result["policies"]["desk_median"], {
            "rows": 2, "wait_mean": 2.0, "charge_mean": 8.0,
        })

    def test_missing_desk_is_not_an_invented_desk(self):
        result = self.check(pd.DataFrame({
            "desk": [None, None, "A"],
            "wait_minutes": [1, None, 10], "charge": [None, 4, 20],
        }))
        self.assertEqual(result["policies"]["observed"], result["policies"]["desk_median"])


if __name__ == "__main__":
    unittest.main()
