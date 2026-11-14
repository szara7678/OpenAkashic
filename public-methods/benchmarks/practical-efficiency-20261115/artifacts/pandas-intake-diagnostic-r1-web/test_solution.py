import json
import random
import statistics
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from solution import diagnose


class DiagnoseTests(unittest.TestCase):
    def checked(self, frame):
        original = frame.copy(deep=True)
        result = diagnose(frame)
        assert_frame_equal(frame, original)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertEqual(set(result), {"columns", "patterns", "policies"})
        return result

    def test_all_patterns_and_policies(self):
        frame = pd.DataFrame({
            "desk": ["A", "A", "A", "A", "B", "B", "C"],
            "wait_minutes": [10, 30, None, None, 100, None, None],
            "charge": [0, None, 40, None, None, 80, None],
        }, index=pd.Index([8, 8, 2, 9, 0, 4, 4], name="intake"))
        result = self.checked(frame)
        self.assertEqual(result["columns"], {
            "wait_minutes": {"missing": 4, "fraction": 4 / 7},
            "charge": {"missing": 4, "fraction": 4 / 7},
        })
        self.assertEqual(result["patterns"], [
            {"wait_missing": False, "charge_missing": False, "rows": 1},
            {"wait_missing": False, "charge_missing": True, "rows": 2},
            {"wait_missing": True, "charge_missing": False, "rows": 2},
            {"wait_missing": True, "charge_missing": True, "rows": 2},
        ])
        self.assertEqual(result["policies"], {
            "observed": {"rows": 7, "wait_mean": 140 / 3, "charge_mean": 40.0},
            "complete_case": {"rows": 1, "wait_mean": 10.0, "charge_mean": 0.0},
            "desk_median": {"rows": 7, "wait_mean": 280 / 6, "charge_mean": 40.0},
        })

    def test_empty(self):
        result = self.checked(pd.DataFrame(columns=["desk", "wait_minutes", "charge"]))
        self.assertEqual(result["patterns"], [])
        for column in result["columns"].values():
            self.assertEqual(column, {"missing": 0, "fraction": 0.0})
        for policy in result["policies"].values():
            self.assertEqual(policy, {"rows": 0, "wait_mean": None, "charge_mean": None})

    def test_all_missing(self):
        result = self.checked(pd.DataFrame({
            "desk": ["A", "B"], "wait_minutes": [None, pd.NA], "charge": [None, pd.NA],
        }))
        for name, policy in result["policies"].items():
            self.assertEqual(policy, {
                "rows": 0 if name == "complete_case" else 2,
                "wait_mean": None, "charge_mean": None,
            })

    def test_nullable_integer_fractional_medians(self):
        frame = pd.DataFrame({
            "desk": pd.Categorical(["A", "A", "A"], categories=["A", "unused"]),
            "wait_minutes": pd.array([1, 2, None], dtype="Int64"),
            "charge": pd.array([None, 2, 5], dtype="Int64"),
        })
        result = self.checked(frame)
        self.assertEqual(result["policies"]["desk_median"], {
            "rows": 3, "wait_mean": 1.5, "charge_mean": 3.5,
        })

    def test_no_cross_desk_or_cross_column_fallback(self):
        result = self.checked(pd.DataFrame({
            "desk": ["A", "A", "B", "B"],
            "wait_minutes": [1, None, None, None],
            "charge": [None, None, 100, None],
        }))
        self.assertEqual(result["policies"]["desk_median"], {
            "rows": 4, "wait_mean": 1.0, "charge_mean": 100.0,
        })
        self.assertEqual(result["policies"]["complete_case"]["rows"], 0)

    def test_no_missing_and_unrelated_column(self):
        result = self.checked(pd.DataFrame({
            "desk": ["A", "B"], "wait_minutes": [0, 2], "charge": [0, 4],
            "unrelated": [None, None],
        }))
        for policy in result["policies"].values():
            self.assertEqual(policy, {"rows": 2, "wait_mean": 1.0, "charge_mean": 2.0})
        self.assertEqual(len(result["patterns"]), 1)

    def test_missing_desks_not_imputed(self):
        result = self.checked(pd.DataFrame({
            "desk": [None, None, "A"], "wait_minutes": [2, None, 8],
            "charge": [None, 10, None],
        }))
        self.assertEqual(result["policies"]["observed"], result["policies"]["desk_median"])

    def test_multiindex_and_nullable_float(self):
        frame = pd.DataFrame({
            "desk": ["A", "A"],
            "wait_minutes": pd.array([1, None], dtype="Float64"),
            "charge": pd.array([None, 3], dtype="Float32"),
        }, index=pd.MultiIndex.from_tuples([("x", 2), ("x", 2)], names=["desk", "row"]))
        self.assertEqual(self.checked(frame)["policies"]["desk_median"], {
            "rows": 2, "wait_mean": 1.0, "charge_mean": 3.0,
        })

    def test_seeded_reference_comparison(self):
        generator = random.Random(2026)
        for trial in range(100):
            with self.subTest(trial=trial):
                records = [
                    (generator.choice(["A", "B", "C"]),
                     generator.choice([None, 0, 1, 5, 20]),
                     generator.choice([None, 0, 2, 10, 100]))
                    for row in range(generator.randrange(25))
                ]
                result = self.checked(pd.DataFrame(records, columns=["desk", "wait_minutes", "charge"]))
                filled = []
                for desk, wait, charge in records:
                    cells = []
                    for position, value in enumerate([wait, charge], start=1):
                        peers = [record[position] for record in records
                                 if record[0] == desk and record[position] is not None]
                        cells.append(value if value is not None else statistics.median(peers) if peers else None)
                    filled.append(cells)
                variants = {
                    "observed": [record[1:] for record in records],
                    "complete_case": [record[1:] for record in records if None not in record[1:]],
                    "desk_median": filled,
                }
                for name, rows in variants.items():
                    actual = result["policies"][name]
                    self.assertEqual(actual["rows"], len(rows))
                    for position, key in enumerate(["wait_mean", "charge_mean"]):
                        observed = [row[position] for row in rows if row[position] is not None]
                        if observed:
                            self.assertAlmostEqual(actual[key], statistics.mean(observed))
                        else:
                            self.assertIsNone(actual[key])


if __name__ == "__main__":
    unittest.main()
