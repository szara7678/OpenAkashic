import datetime
import unittest
from unittest.mock import patch

from solution import retry_after_seconds


UTC = datetime.timezone.utc
HEADER = "Sun, 06 Nov 1994 08:49:37 GMT"
REFERENCE = datetime.datetime(1994, 11, 6, 8, 49, 37, tzinfo=UTC)


class NoOffset(datetime.tzinfo):
    def utcoffset(self, date):
        return None


class RetryAfterTests(unittest.TestCase):
    def test_decimal(self):
        for value, expected in [("0", 0), ("120", 120), ("00012", 12),
                                (" \t120\r\n", 120), ("\u200312\u2003", 12)]:
            with self.subTest(value=value):
                self.assertEqual(retry_after_seconds(value, REFERENCE), expected)

    def test_long_decimal(self):
        self.assertEqual(retry_after_seconds("1" + "0" * 5000, REFERENCE), 10 ** 5000)

    def test_absent_and_invalid_numbers(self):
        for value in [None, "", " \t\r\n", "+1", "-1", "1.5", "1e3", "1_000",
                      "１２", "١٢", "²", "1 2", "12\x00", "120, 60"]:
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, REFERENCE))

    def test_naive_always_raises(self):
        for reference in [REFERENCE.replace(tzinfo=None), REFERENCE.replace(tzinfo=NoOffset())]:
            for value in [None, "", "120", HEADER, "bad"]:
                with self.subTest(reference=reference, value=value):
                    with self.assertRaises(ValueError):
                        retry_after_seconds(value, reference)

    def test_rounding_and_clamping(self):
        for offset, expected in [(-1.1, 2), (-1, 1), (-0.000001, 1),
                                 (0, 0), (0.000001, 0), (100, 0)]:
            with self.subTest(offset=offset):
                reference = REFERENCE + datetime.timedelta(seconds=offset)
                self.assertEqual(retry_after_seconds(HEADER, reference), expected)

    def test_timezone_conversion(self):
        reference = REFERENCE - datetime.timedelta(seconds=61, microseconds=1)
        for offset in [-720, -210, 0, 330, 840]:
            with self.subTest(offset=offset):
                zone = datetime.timezone(datetime.timedelta(minutes=offset))
                self.assertEqual(retry_after_seconds(HEADER, reference.astimezone(zone)), 62)

    def test_weekday_not_calendar_checked(self):
        for weekday in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            self.assertEqual(retry_after_seconds(weekday + HEADER[3:], REFERENCE), 0)

    def test_exact_shape(self):
        for value in [HEADER.lower(), HEADER.replace("Sun", "Foo"),
                      HEADER.replace("Sun", "Sunday"), HEADER.replace("Nov", "NOV"),
                      HEADER.replace("GMT", "UTC"), HEADER.replace("GMT", "+0000"),
                      HEADER.replace("06", "6"), HEADER.replace("1994", "94"),
                      HEADER.replace("06", "０６"), HEADER.replace(" ", "\t", 1),
                      HEADER.replace(" ", "  ", 1), HEADER + " extra",
                      "Sunday, 06-Nov-94 08:49:37 GMT", "Sun Nov  6 08:49:37 1994",
                      "1994-11-06T08:49:37Z"]:
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, REFERENCE))
        self.assertEqual(retry_after_seconds(" \n" + HEADER + "\t ", REFERENCE), 0)

    def test_impossible_dates(self):
        for value in [HEADER.replace("06", "00"), HEADER.replace("06 Nov", "31 Nov"),
                      HEADER.replace("1994", "0000"), HEADER.replace("08:", "24:"),
                      HEADER.replace(":49:", ":60:"), HEADER.replace(":37", ":60"),
                      "Mon, 29 Feb 2023 08:49:37 GMT"]:
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, REFERENCE))

    def test_leap_date_and_year_boundaries(self):
        self.assertEqual(retry_after_seconds("Mon, 29 Feb 2024 00:00:00 GMT",
                         datetime.datetime(2024, 2, 28, 23, 59, 59, tzinfo=UTC)), 1)
        for year in [1, 9999]:
            reference = datetime.datetime(year, 1, 1, tzinfo=UTC)
            self.assertEqual(retry_after_seconds(f"Mon, 01 Jan {year:04d} 00:00:00 GMT",
                                               reference), 0)

    def test_no_sleep_or_network(self):
        with patch("time.sleep", side_effect=AssertionError("sleep")), \
             patch("socket.socket", side_effect=AssertionError("network")):
            self.assertEqual(retry_after_seconds("120", REFERENCE), 120)
            self.assertEqual(retry_after_seconds(HEADER, REFERENCE), 0)


if __name__ == "__main__":
    unittest.main()
