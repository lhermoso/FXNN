import unittest
from fxnn.economic_clock import SessionClockMs, utc_ms


class EconomicClockTests(unittest.TestCase):
    def test_dense_oracle_and_plateau(self):
        clock = SessionClockMs(0, 30, [(2, 7), (12, 21)])
        for a in range(31):
            for b in range(a, 31):
                expected = sum(2 <= t < 7 or 12 <= t < 21 for t in range(a, b))
                self.assertEqual(clock.elapsed(a, b), expected)
            for duration in range(clock.elapsed(a, 30)+1):
                expected = next(t for t in range(a, 31) if clock.elapsed(a, t) == duration)
                self.assertEqual(clock.advance(a, duration), expected)
        self.assertEqual(clock.advance(4, 3), 7)
        self.assertEqual(clock.advance(10, 0), 10)
        self.assertEqual(clock.next_open(7), 12)

    def test_friday_dst_subminute_and_caps(self):
        a = utc_ms('2023-03-10T21:59:00+00:00')
        close = a+60000
        sunday = utc_ms('2023-03-12T21:00:00+00:00')
        clock = SessionClockMs.weekly(a-60000, sunday+120000)
        self.assertEqual(clock.advance(a, 60000), close)
        self.assertEqual(clock.advance(a+1, 60000), sunday+1)
        self.assertFalse(clock.is_open(close))
        self.assertTrue(clock.is_open(sunday))
        self.assertEqual(clock.elapsed(close-1, sunday), 1)
        self.assertEqual(clock.advance(close-1, 1), close)
        self.assertEqual(clock.advance(close, 1), sunday+1)

    def test_validation(self):
        with self.assertRaises(ValueError): SessionClockMs(0, 5, [(0, 4), (3, 5)])
        with self.assertRaises(ValueError): utc_ms('2023-01-01T00:00:00.000001+00:00')
        with self.assertRaises(ValueError): utc_ms('2023-01-01T00:00:00')
