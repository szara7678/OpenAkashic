import json
import random
import statistics
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from solution import diagnose


class DiagnoseTests(unittest.TestCase):
    def checked(self, frame):
        before = frame.copy(deep=True)
        result = diagnose(frame)
        assert_frame_equal(frame, before, check_exact=True)
        json.dumps(result, allow_nan=False)
        self.assertEqual(sum(item["rows"] for item in result["patterns"]), len(frame))
        return result

    def test_full_comparison(self):
        frame = pd.DataFrame({
            "desk": ["A", "A", "A", "B", "B", "C"],
            "wait_minutes": [1, 3, None, 10, None, None],
            "charge": [10, None, 30, None, None, 90],
        }, index=pd.Index([7, 7, 2, 9, 1, 1], name="ticket"))
        result = self.checked(frame)
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
            "observed": {"rows": 6, "wait_mean": 14 / 3, "charge_mean": 130 / 3},
            "complete_case": {"rows": 1, "wait_mean": 1.0, "charge_mean": 10.0},
            "desk_median": {"rows": 6, "wait_mean": 26 / 5, "charge_mean": 37.5},
        })

    def test_empty(self):
        frame = pd.DataFrame({"desk": pd.Series(dtype="category"),
                              "wait_minutes": pd.Series(dtype="Int64"),
                              "charge": pd.Series(dtype="Float64")})
        result = self.checked(frame)
        self.assertEqual(result["patterns"], [])
        for item in result["columns"].values():
            self.assertEqual(item, {"missing": 0, "fraction": 0.0})
        for item in result["policies"].values():
            self.assertEqual(item, {"rows": 0, "wait_mean": None, "charge_mean": None})

    def test_all_missing(self):
        result = self.checked(pd.DataFrame({"desk": ["A", "B"],
                                            "wait_minutes": [None, None],
                                            "charge": [None, None]}))
        self.assertEqual(result["policies"]["desk_median"],
                         {"rows": 2, "wait_mean": None, "charge_mean": None})
        self.assertEqual(result["policies"]["complete_case"]["rows"], 0)

    def test_nullable_integer_fractional_median(self):
        frame = pd.DataFrame({"desk": pd.Categorical(["A", "A", "A"], categories=["A", "unused"]),
                              "wait_minutes": pd.array([1, 2, None], dtype="Int64"),
                              "charge": pd.array([None, 0, 5], dtype="Int64")})
        result = self.checked(frame)
        self.assertEqual(result["policies"]["desk_median"],
                         {"rows": 3, "wait_mean": 1.5, "charge_mean": 2.5})

    def test_no_complete_cases(self):
        result = self.checked(pd.DataFrame({"desk": ["A", "A"],
                                            "wait_minutes": [2, None], "charge": [None, 8]}))
        self.assertEqual(result["policies"]["complete_case"],
                         {"rows": 0, "wait_mean": None, "charge_mean": None})
        self.assertEqual(result["policies"]["desk_median"],
                         {"rows": 2, "wait_mean": 2.0, "charge_mean": 8.0})

    def test_missing_desk_not_pooled(self):
        result = self.checked(pd.DataFrame({"desk": [None, None, "A"],
                                            "wait_minutes": [2, None, 10],
                                            "charge": [None, 8, 10]}))
        self.assertEqual(result["policies"]["desk_median"], result["policies"]["observed"])

    def test_multiindex_and_nullable_float(self):
        frame = pd.DataFrame({"desk": ["A", "A"],
                              "wait_minutes": pd.array([1, None], dtype="Float64"),
                              "charge": pd.array([0, None], dtype="Float64")},
                             index=pd.MultiIndex.from_tuples([("x", 1), ("x", 1)], names=["desk", "id"]))
        self.assertEqual(self.checked(frame)["policies"]["desk_median"],
                         {"rows": 2, "wait_mean": 1.0, "charge_mean": 0.0})

    def test_no_missing(self):
        result = self.checked(pd.DataFrame({"desk": ["A", "B"],
                                            "wait_minutes": [0, 4], "charge": [0, 12]}))
        self.assertEqual(result["policies"]["observed"], result["policies"]["complete_case"])
        self.assertEqual(result["policies"]["observed"], result["policies"]["desk_median"])

    def test_randomized_against_scalar_reference(self):
        generator = random.Random(824)
        for trial in range(100):
            records = [{"desk": generator.choice(["A", "B", "C"]),
                        "wait_minutes": generator.choice([None, 0, 1, 5, 12]),
                        "charge": generator.choice([None, 0, 10, 25, 90])}
                       for _ in range(generator.randrange(1, 30))]
            with self.subTest(trial=trial):
                result = self.checked(pd.DataFrame(records))
                complete = [record for record in records if all(
                    record[column] is not None for column in ("wait_minutes", "charge"))]
                filled = [record.copy() for record in records]
                for record in filled:
                    for column in ("wait_minutes", "charge"):
                        observed = [candidate[column] for candidate in records
                                    if candidate["desk"] == record["desk"]
                                    and candidate[column] is not None]
                        if record[column] is None and observed:
                            record[column] = statistics.median(observed)
                for name, selected in (("observed", records), ("complete_case", complete),
                                       ("desk_median", filled)):
                    self.assertEqual(result["policies"][name]["rows"], len(selected))
                    for column, key in (("wait_minutes", "wait_mean"), ("charge", "charge_mean")):
                        observed = [record[column] for record in selected if record[column] is not None]
                        expected = statistics.mean(observed) if observed else None
                        if expected is None:
                            self.assertIsNone(result["policies"][name][key])
                        else:
                            self.assertAlmostEqual(result["policies"][name][key], expected)


if __name__ == "__main__":
    unittest.main()
