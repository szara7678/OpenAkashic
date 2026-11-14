import json
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from solution import diagnose


class DiagnoseTests(unittest.TestCase):
    def check_unchanged(self, frame):
        before = frame.copy(deep=True)
        result = diagnose(frame)
        assert_frame_equal(frame, before, check_exact=True)
        json.dumps(result, allow_nan=False)
        return result

    def test_mixed_patterns_and_policies(self):
        frame = pd.DataFrame({
            "desk": ["A", "A", "A", "B", "B", "C"],
            "wait_minutes": [10., 20., None, 100., None, None],
            "charge": [0., None, 40., 80., 120., None],
        }, index=pd.Index([9, 9, 2, 7, 3, 1], name="intake"))
        result = self.check_unchanged(frame)
        self.assertEqual(result["columns"], {
            "wait_minutes": {"missing": 3, "fraction": .5},
            "charge": {"missing": 2, "fraction": 2 / 6},
        })
        self.assertEqual(result["patterns"], [
            {"wait_missing": False, "charge_missing": False, "rows": 2},
            {"wait_missing": False, "charge_missing": True, "rows": 1},
            {"wait_missing": True, "charge_missing": False, "rows": 2},
            {"wait_missing": True, "charge_missing": True, "rows": 1},
        ])
        policies = result["policies"]
        self.assertEqual(policies["observed"], {
            "rows": 6, "wait_mean": 130 / 3, "charge_mean": 60.,
        })
        self.assertEqual(policies["complete_case"], {
            "rows": 2, "wait_mean": 55., "charge_mean": 40.,
        })
        self.assertEqual(policies["desk_median"], {
            "rows": 6, "wait_mean": 49., "charge_mean": 52.,
        })

    def test_empty(self):
        result = self.check_unchanged(pd.DataFrame({
            "desk": pd.Series(dtype="string"),
            "wait_minutes": pd.Series(dtype="Int64"),
            "charge": pd.Series(dtype="Float64"),
        }))
        self.assertEqual(result["patterns"], [])
        for column in result["columns"].values():
            self.assertEqual(column, {"missing": 0, "fraction": 0.0})
        for policy in result["policies"].values():
            self.assertEqual(policy, {"rows": 0, "wait_mean": None, "charge_mean": None})

    def test_all_missing(self):
        result = self.check_unchanged(pd.DataFrame({
            "desk": ["A", "B"],
            "wait_minutes": pd.array([None, None], dtype="Int64"),
            "charge": [float("nan"), float("nan")],
        }))
        self.assertEqual(result["patterns"], [
            {"wait_missing": True, "charge_missing": True, "rows": 2},
        ])
        for name, policy in result["policies"].items():
            self.assertEqual(policy, {
                "rows": 0 if name == "complete_case" else 2,
                "wait_mean": None, "charge_mean": None,
            })

    def test_nullable_integers_fractional_median_and_multiindex(self):
        frame = pd.DataFrame({
            "desk": pd.Categorical(["A", "A", "A", "B"], categories=["A", "B", "unused"]),
            "wait_minutes": pd.array([1, 2, None, None], dtype="Int64"),
            "charge": pd.array([None, None, None, 8], dtype="Int64"),
        }, index=pd.MultiIndex.from_tuples([(1, 2), (1, 2), (3, 4), (5, 6)], names=["desk", "id"]))
        result = self.check_unchanged(frame)
        self.assertEqual(result["policies"]["desk_median"], {
            "rows": 4, "wait_mean": 1.5, "charge_mean": 8.,
        })
        self.assertEqual(result["policies"]["complete_case"]["rows"], 0)

    def test_no_missing(self):
        result = self.check_unchanged(pd.DataFrame({
            "desk": ["A", "B"], "wait_minutes": [2, 4], "charge": [0, 10],
        }))
        self.assertEqual(result["patterns"], [
            {"wait_missing": False, "charge_missing": False, "rows": 2},
        ])
        for policy in result["policies"].values():
            self.assertEqual(policy, {"rows": 2, "wait_mean": 3., "charge_mean": 5.})

    def test_missing_desk_labels(self):
        result = self.check_unchanged(pd.DataFrame({
            "desk": pd.Categorical([None, None, "A"]),
            "wait_minutes": [4., None, 10.], "charge": [None, 6., 12.],
        }))
        self.assertEqual(result["policies"]["desk_median"], {
            "rows": 3, "wait_mean": 6., "charge_mean": 8.,
        })


if __name__ == "__main__":
    unittest.main()
