import unittest

from personalized_radio_station.weather import time_of_day_from_hour


class TimeOfDayBucketingTests(unittest.TestCase):
    def test_morning_5_to_11(self) -> None:
        for hour in (5, 8, 11):
            self.assertEqual(time_of_day_from_hour(hour), "morning")

    def test_afternoon_12_to_16(self) -> None:
        for hour in (12, 14, 16):
            self.assertEqual(time_of_day_from_hour(hour), "afternoon")

    def test_evening_17_to_21(self) -> None:
        for hour in (17, 19, 21):
            self.assertEqual(time_of_day_from_hour(hour), "evening")

    def test_late_night_22_to_4(self) -> None:
        for hour in (22, 23, 0, 3, 4):
            self.assertEqual(time_of_day_from_hour(hour), "late_night")


if __name__ == "__main__":
    unittest.main()
