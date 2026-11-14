import datetime
import math
import unittest

from solution import retry_after_seconds


UTC = datetime.timezone.utc
HEADER = "Sun, 06 Nov 1994 08:49:37 GMT"
TARGET = datetime.datetime(1994, 11, 6, 8, 49, 37, tzinfo=UTC)


class NoOffset(datetime.tzinfo):
    def utcoffset(self, value):
        return None


class RetryAfterTests(unittest.TestCase):
    def test_missing_and_blank(self):
        for value in (None, "", " ", "\t\r\n", "\u2003"):
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, TARGET))

    def test_ascii_integers(self):
        for value, expected in (("0", 0), ("120", 120), ("00009", 9),
                                ("\t 42\r\n", 42), ("12345678901", 12345678901)):
            with self.subTest(value=value):
                self.assertEqual(retry_after_seconds(value, TARGET), expected)

    def test_integer_beyond_default_conversion_limit(self):
        self.assertEqual(retry_after_seconds("1" + "0" * 5000, TARGET), 10 ** 5000)
        self.assertEqual(retry_after_seconds("0" * 5000, TARGET), 0)

    def test_invalid_numbers(self):
        for value in ("-1", "+1", "1.0", "1e3", "1_000", "1 2", "１２", "١٢",
                      "²", "1\x00", "NaN", "Infinity"):
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, TARGET))

    def test_awareness_checked_first(self):
        for now in (TARGET.replace(tzinfo=None), TARGET.replace(tzinfo=NoOffset())):
            for value in (None, "", "12", HEADER, "invalid"):
                with self.subTest(now=now, value=value):
                    with self.assertRaises(ValueError):
                        retry_after_seconds(value, now)

    def test_date_ceiling_and_clamping(self):
        for delta, expected in ((-2, 2), (-1.1, 2), (-0.000001, 1),
                                (0, 0), (0.000001, 0), (20, 0)):
            with self.subTest(delta=delta):
                now = TARGET + datetime.timedelta(seconds=delta)
                self.assertEqual(retry_after_seconds(HEADER, now), expected)

    def test_non_utc_offsets(self):
        for offset in (330, -420, 840, -720):
            with self.subTest(offset=offset):
                zone = datetime.timezone(datetime.timedelta(minutes=offset))
                now = (TARGET - datetime.timedelta(seconds=10.5)).astimezone(zone)
                self.assertEqual(retry_after_seconds(HEADER, now), 11)

    def test_weekday_mismatch_is_allowed(self):
        for weekday in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            self.assertEqual(retry_after_seconds(weekday + HEADER[3:], TARGET), 0)

    def test_all_months(self):
        for month, name in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1):
            with self.subTest(month=month):
                now = datetime.datetime(2024, month, 1, tzinfo=UTC)
                self.assertEqual(retry_after_seconds(
                    f"Sun, 01 {name} 2024 00:00:01 GMT", now), 1)

    def test_invalid_shapes(self):
        invalid = (
            "Sunday, 06-Nov-94 08:49:37 GMT", "Sun Nov  6 08:49:37 1994",
            "1994-11-06T08:49:37Z", "sun, 06 Nov 1994 08:49:37 GMT",
            "Foo, 06 Nov 1994 08:49:37 GMT", "Sun, 6 Nov 1994 08:49:37 GMT",
            "Sun, 06 nov 1994 08:49:37 GMT", "Sun, 06 Nov 94 08:49:37 GMT",
            "Sun, 06 Nov 1994 8:49:37 GMT", "Sun, 06 Nov 1994 08:49:37 UTC",
            "Sun, 06 Nov 1994 08:49:37 +0000", "Sun, 06 Nov 1994 08:49:37 gmt",
            "Sun, 06 Nov 1994 08:49:37.0 GMT", "Sun,  06 Nov 1994 08:49:37 GMT",
            "Sun,\t06 Nov 1994 08:49:37 GMT", "Sun, ０６ Nov 1994 08:49:37 GMT",
            HEADER + " junk", HEADER + "\x00", HEADER + ", 10",
        )
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, TARGET))

    def test_impossible_dates(self):
        for value in ("Sun, 00 Nov 1994 08:49:37 GMT",
                      "Sun, 31 Apr 1994 08:49:37 GMT",
                      "Sun, 29 Feb 1900 08:49:37 GMT",
                      "Sun, 06 Nov 0000 08:49:37 GMT",
                      "Sun, 06 Nov 1994 24:49:37 GMT",
                      "Sun, 06 Nov 1994 08:60:37 GMT",
                      "Sun, 06 Nov 1994 08:49:60 GMT"):
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, TARGET))

    def test_leap_year_and_surrounding_whitespace(self):
        now = datetime.datetime(2000, 2, 29, tzinfo=UTC)
        self.assertEqual(retry_after_seconds(
            " \tSun, 29 Feb 2000 00:00:01 GMT\r\n", now), 1)

    def test_extreme_years_and_offsets(self):
        for year, offset in ((1, 60), (9999, -60)):
            with self.subTest(year=year):
                now = datetime.datetime(year, 1 if year == 1 else 12,
                                        1 if year == 1 else 31,
                                        tzinfo=datetime.timezone(
                                            datetime.timedelta(minutes=offset)))
                expected = max(0, math.ceil((TARGET - now).total_seconds()))
                self.assertEqual(retry_after_seconds(HEADER, now), expected)


if __name__ == "__main__":
    unittest.main()
