import datetime
import unittest

from solution import retry_after_seconds


UTC = datetime.timezone.utc
HEADER = "Sun, 06 Nov 1994 08:49:37 GMT"
INSTANT = datetime.datetime(1994, 11, 6, 8, 49, 37, tzinfo=UTC)


class NoOffset(datetime.tzinfo):
    def utcoffset(self, date):
        return None


class RetryAfterTests(unittest.TestCase):
    def test_missing_and_blank(self):
        for value in (None, "", " ", "\t\r\n"):
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, INSTANT))

    def test_naive_now_always_raises(self):
        for now in (INSTANT.replace(tzinfo=None), INSTANT.replace(tzinfo=NoOffset())):
            for value in (None, "", "120", HEADER, "malformed"):
                with self.subTest(now=now, value=value):
                    with self.assertRaises(ValueError):
                        retry_after_seconds(value, now)

    def test_numeric(self):
        for value, expected in (("0", 0), ("00012", 12), (" \t120\r\n", 120)):
            with self.subTest(value=value):
                self.assertEqual(retry_after_seconds(value, INSTANT), expected)

    def test_long_numeric(self):
        self.assertEqual(retry_after_seconds("1" + "0" * 5000, INSTANT), 10 ** 5000)
        self.assertEqual(retry_after_seconds("0" * 5000, INSTANT), 0)

    def test_bad_numeric(self):
        for value in ("-1", "+1", "1.5", "1e3", "1_000", "١٢", "１２", "²", "1 2", "12\x00"):
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, INSTANT))

    def test_rounding_and_past(self):
        for difference, expected in ((0, 0), (1, 1), (1.1, 2), (0.000001, 1), (-0.1, 0), (-86400, 0), (86401.2, 86402)):
            with self.subTest(difference=difference):
                now = INSTANT - datetime.timedelta(seconds=difference)
                self.assertEqual(retry_after_seconds(HEADER, now), expected)

    def test_timezone_offsets(self):
        for minutes in (-720, -210, 0, 330, 840):
            with self.subTest(minutes=minutes):
                local = (INSTANT - datetime.timedelta(seconds=1.5)).astimezone(
                    datetime.timezone(datetime.timedelta(minutes=minutes))
                )
                self.assertEqual(retry_after_seconds(HEADER, local), 2)

    def test_valid_weekdays_need_not_agree(self):
        for weekday in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            with self.subTest(weekday=weekday):
                self.assertEqual(retry_after_seconds(weekday + HEADER[3:], INSTANT), 0)

    def test_whitespace_and_leap_day(self):
        self.assertEqual(retry_after_seconds(" \t" + HEADER + "\n", INSTANT), 0)
        leap = datetime.datetime(2000, 2, 28, tzinfo=UTC)
        self.assertEqual(retry_after_seconds("Tue, 29 Feb 2000 00:00:00 GMT", leap), 86400)

    def test_malformed_dates(self):
        values = (
            "Sunday, 06-Nov-94 08:49:37 GMT", "Sun Nov  6 08:49:37 1994",
            HEADER.replace("Sun", "Foo"), HEADER.replace("Sun", "sun"),
            HEADER.replace("Nov", "nov"), HEADER.replace("GMT", "UTC"),
            HEADER.replace("GMT", "gmt"), HEADER.replace("GMT", "+0000"),
            HEADER.replace("06", "6"), HEADER.replace("06", "０６"),
            HEADER.replace("1994", "94"), HEADER.replace("1994", "0000"),
            HEADER.replace("06", "31"), HEADER.replace("Nov", "Feb" ).replace("06", "30"),
            "Mon, 29 Feb 1900 00:00:00 GMT",
            HEADER.replace("08:", "24:"), HEADER.replace(":49:", ":60:"),
            HEADER.replace(":37", ":60"), HEADER.replace(":37", ":37.0"),
            HEADER.replace(", ", ",  "), HEADER.replace(" Nov", "\tNov"),
            HEADER + " junk", HEADER + "\nother",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(retry_after_seconds(value, INSTANT))

    def test_extreme_aware_now(self):
        now = datetime.datetime(1, 1, 1, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
        self.assertEqual(retry_after_seconds("Mon, 01 Jan 0001 00:00:00 GMT", now), 3600)


if __name__ == "__main__":
    unittest.main()
