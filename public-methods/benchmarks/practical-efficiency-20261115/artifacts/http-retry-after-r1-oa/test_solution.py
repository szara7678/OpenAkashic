import datetime
import unittest
from unittest.mock import patch

from solution import retry_after_seconds


UTC = datetime.timezone.utc
HEADER = "Sun, 06 Nov 1994 08:49:37 GMT"
REFERENCE = datetime.datetime(1994, 11, 6, 8, 49, 37, tzinfo=UTC)


class NoOffset(datetime.tzinfo):
    def utcoffset(self, value):
        return None


class RetryAfterTests(unittest.TestCase):
    def test_integer_delays(self):
        for value, expected in [("0", 0), ("120", 120), ("000123", 123), (" \t42\r\n", 42)]:
            with self.subTest(value=value):
                self.assertEqual(retry_after_seconds(value, REFERENCE), expected)

    def test_unbounded_integer_conversion(self):
        self.assertEqual(retry_after_seconds("1" + "0" * 5000, REFERENCE), 10 ** 5000)
        self.assertEqual(retry_after_seconds("0" * 5000, REFERENCE), 0)

    def test_missing_and_invalid_values(self):
        for value in [None, "", " \t\r\n", "+1", "-1", "1.0", "1e2", "1_000", "1 2",
                      "١٢", "１２", "²", "123\x00", "12\n34"]:
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, REFERENCE))

    def test_requires_aware_now_before_parsing(self):
        for now in [REFERENCE.replace(tzinfo=None), REFERENCE.replace(tzinfo=NoOffset())]:
            for value in [None, "", "120", HEADER, "invalid"]:
                with self.subTest(now=now, value=value):
                    with self.assertRaises(ValueError):
                        retry_after_seconds(value, now)

    def test_future_and_fractional_rounding(self):
        for delta, expected in [(datetime.timedelta(seconds=60), 60),
                                (datetime.timedelta(microseconds=1), 1),
                                (datetime.timedelta(seconds=1, microseconds=1), 2),
                                (datetime.timedelta(seconds=1, microseconds=999999), 2)]:
            with self.subTest(delta=delta):
                self.assertEqual(retry_after_seconds(HEADER, REFERENCE - delta), expected)

    def test_past_and_equal_clamped_to_zero(self):
        for delta in [datetime.timedelta(), datetime.timedelta(microseconds=1), datetime.timedelta(days=30)]:
            with self.subTest(delta=delta):
                self.assertEqual(retry_after_seconds(HEADER, REFERENCE + delta), 0)

    def test_timezone_offsets(self):
        for offset in [datetime.timedelta(hours=5, minutes=30), datetime.timedelta(hours=-8),
                       datetime.timedelta(seconds=37)]:
            with self.subTest(offset=offset):
                now = (REFERENCE - datetime.timedelta(microseconds=1)).astimezone(datetime.timezone(offset))
                self.assertEqual(retry_after_seconds(HEADER, now), 1)

    def test_all_weekdays_without_calendar_agreement(self):
        for weekday in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            with self.subTest(weekday=weekday):
                self.assertEqual(retry_after_seconds(weekday + HEADER[3:], REFERENCE), 0)

    def test_all_months(self):
        for month in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]:
            with self.subTest(month=month):
                self.assertEqual(retry_after_seconds(f"Sun, 06 {month} 1994 08:49:37 GMT",
                                                   datetime.datetime(1995, 1, 1, tzinfo=UTC)), 0)

    def test_strict_date_shape(self):
        for value in ["Sunday, 06-Nov-94 08:49:37 GMT", "Sun Nov  6 08:49:37 1994",
                      HEADER.replace("Sun", "Foo"), HEADER.lower(), HEADER.replace("GMT", "UTC"),
                      HEADER.replace("GMT", "+0000"), HEADER.replace("06", "6"),
                      HEADER.replace("1994", "94"), HEADER.replace("08:", "8:"),
                      HEADER.replace(", ", ",  "), HEADER.replace(" Nov ", "\tNov "),
                      HEADER.replace("06", "０６"), HEADER + "junk", HEADER.replace("37 GMT", "37.5 GMT")]:
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, REFERENCE))
        self.assertEqual(retry_after_seconds(" \n" + HEADER + "\t ", REFERENCE), 0)

    def test_impossible_dates(self):
        for value in ["Sun, 00 Nov 1994 08:49:37 GMT", "Sun, 31 Nov 1994 08:49:37 GMT",
                      "Sun, 29 Feb 1900 08:49:37 GMT", "Sun, 06 Nov 0000 08:49:37 GMT",
                      HEADER.replace("08:", "24:"), HEADER.replace(":49:", ":60:"),
                      HEADER.replace("37 GMT", "60 GMT")]:
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, REFERENCE))
        self.assertEqual(retry_after_seconds("Sun, 29 Feb 2000 08:49:37 GMT",
                                           datetime.datetime(2000, 2, 28, 8, 49, 37, tzinfo=UTC)), 86400)

    def test_boundary_timezone_does_not_overflow(self):
        now = datetime.datetime(1, 1, 1, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
        self.assertEqual(retry_after_seconds("Mon, 01 Jan 0001 00:00:00 GMT", now), 3600)

    def test_no_sleep_network_or_clock_lookup(self):
        with patch("time.sleep", side_effect=AssertionError("sleep")), \
             patch("time.time", side_effect=AssertionError("clock")), \
             patch("socket.socket", side_effect=AssertionError("network")):
            self.assertEqual(retry_after_seconds(HEADER, REFERENCE), 0)
            self.assertEqual(retry_after_seconds("120", REFERENCE), 120)


if __name__ == "__main__":
    unittest.main()
