import unittest
from datetime import datetime, timezone
from decimal import Decimal as D

import numpy as np

from fxnn.labeling import Candle
from fxnn.session_clock import SessionClock, weekly_fx_clock
from fxnn.volatility import barrier_labels, volatility_partitions


def candle(minute, price='1.1', high=None, low=None):
    p = D(price)
    return Candle(datetime.fromtimestamp(minute * 60, timezone.utc), p,
                  D(high) if high else p, D(low) if low else p, p)


def scalar(candles, clock, tp, sl, horizon, threshold):
    quotes = {int(c.timestamp.timestamp()): c for c in candles}
    endfile = max(quotes) + 60
    result = []
    for i, entry in enumerate(candles):
        start = int(entry.timestamp.timestamp())
        deadline = int(clock.deadlines(np.array([start]), horizon)[0])
        for side in (1, -1):
            target = entry.open + side * D(str(tp[i]))
            stop = entry.open - side * D(str(sl[i]))
            missing = 0
            price = None
            outcome = 'censored'
            last = entry.close
            end = information = start
            for t in range(start, min(deadline, endfile), 60):
                end = information = t + 60
                if not clock.active[(t - clock.first_epoch) // 60]:
                    continue
                if t not in quotes:
                    missing += 1
                    if missing >= threshold:
                        break
                    if end == deadline:
                        outcome, price = 'timeout', last
                    continue
                missing = 0
                bar = quotes[t]
                last = bar.close
                if side * (bar.open - stop) <= 0:
                    outcome, price, end = 'stop_loss', bar.open, t
                    break
                if side * (bar.open - target) >= 0:
                    outcome, price, end = 'take_profit', target, t
                    break
                target_hit = bar.high >= target if side == 1 else bar.low <= target
                stop_hit = bar.low <= stop if side == 1 else bar.high >= stop
                if target_hit and stop_hit:
                    outcome = 'ambiguous'
                    break
                if stop_hit:
                    outcome, price = 'stop_loss', stop
                    break
                if target_hit:
                    outcome, price = ('take_profit' if end < deadline else 'boundary'), target
                    break
                if end == deadline:
                    outcome, price = 'timeout', last
                    break
            result.append((outcome, end, information, float(price) if price is not None else np.nan))
    return result


class VolatilityLabelsTests(unittest.TestCase):
    def test_independent_scalar_all_outcomes_and_frozen_entry_distances(self):
        clock = SessionClock(0, np.ones(10000, dtype=bool))
        rng = np.random.default_rng(923)
        seen = set()
        for missing in ([], [4, 5], list(range(4, 19)), list(range(4, 20))):
            source = []
            for i in range(100):
                if i in missing:
                    continue
                p = D(str(1.1 + rng.normal(0, .001)))
                source.append(candle(i, str(p), str(p + D('.0009')), str(p - D('.0009'))))
            sl = np.linspace(.0004, .007, len(source))
            tp = 2.5 * sl
            actual = barrier_labels(source, clock, tp, sl, horizon=30)
            expected = scalar(source, clock, tp, sl, 30, 15)
            self.assertEqual(actual['outcomes'].tolist(), [v[0] for v in expected])
            np.testing.assert_array_equal(actual['ends'], [v[1] for v in expected])
            np.testing.assert_array_equal(actual['last_information_bar_end'], [v[2] for v in expected])
            np.testing.assert_allclose(actual['exit_price'], [v[3] for v in expected], equal_nan=True)
            seen.update(actual['outcomes'].tolist())
        self.assertTrue({'take_profit', 'stop_loss', 'timeout', 'censored'} <= seen)
        source = [candle(0, high='1.106', low='1.094')]
        actual = barrier_labels(source, clock, np.array([.005]), np.array([.002]), horizon=30)
        self.assertEqual(actual['outcomes'].tolist(), ['ambiguous', 'ambiguous'])
        self.assertEqual(actual['outcomes'].tolist(), [v[0] for v in scalar(source, clock, [.005], [.002], 30, 15)])

    def test_terminal_target_boundary_stop_and_stale_timeout(self):
        clock = SessionClock(0, np.ones(100, dtype=bool))
        for last, outcome in ((candle(2, high='1.105'), 'boundary'),
                              (candle(2, low='1.098'), 'stop_loss')):
            actual = barrier_labels([candle(0), candle(1), last], clock,
                                    np.full(3, .005), np.full(3, .002), horizon=3)
            self.assertEqual(actual['outcomes'][0], outcome)
        source = [candle(0), candle(11)]
        actual = barrier_labels(source, clock, np.full(2, .005), np.full(2, .002), horizon=10)
        self.assertEqual(actual['outcomes'][0], 'timeout')
        self.assertEqual(actual['last_information_bar_end'][0], 600)
        self.assertEqual(actual['exit_price'][0], 1.1)

    def test_opening_hit_includes_terminal_bar_in_information(self):
        source = [candle(0), candle(1, '1.106')]
        clock = SessionClock(0, np.ones(100, dtype=bool))
        actual = barrier_labels(source, clock, np.full(2, .005), np.full(2, .002), horizon=30)
        self.assertEqual(actual['ends'][0], 60)
        self.assertEqual(actual['last_information_bar_end'][0], 120)
        self.assertEqual(actual['exit_price'][0], 1.105)
        self.assertEqual(actual['exit_price'][1], 1.106)

    def test_eligibility_and_invalid_distance_fail_closed(self):
        source = [candle(0), candle(1)]
        clock = SessionClock(0, np.ones(100, dtype=bool))
        actual = barrier_labels(source, clock, np.array([np.nan, .005]),
                                np.array([np.nan, .002]), eligible=np.array([False, True]), horizon=30)
        self.assertEqual(actual['outcomes'][:2].tolist(), ['causally_ineligible'] * 2)
        for distance in (0, -1, np.nan, np.inf, 2):
            with self.assertRaises(ValueError):
                barrier_labels(source, clock, np.full(2, distance), np.full(2, .002), horizon=30)

    def test_extended_history_buffer_and_strict_horizon(self):
        clock = SessionClock(0, np.ones(40000, dtype=bool))
        stamps = np.arange(0, 20000, 2, dtype=np.int64) * 60
        def iso(m):
            return datetime.fromtimestamp(m * 60, timezone.utc).isoformat()
        protocol = {'development': [iso(0), iso(30000)]}
        fold = {'validation_start': iso(10000), 'test_start': iso(15000), 'test_end': iso(20000)}
        ends = clock.deadlines(stamps)
        parts = volatility_partitions(stamps, ends, protocol, fold, clock, stamps)
        cutoff = stamps[stamps < 15000 * 60][-1941]
        self.assertTrue(np.all(ends[parts['refit']] < cutoff))
        self.assertTrue(np.all(ends[parts['test']] < 20000 * 60))
        self.assertTrue(len(parts['refit']) > 0)
        with self.assertRaises(ValueError):
            volatility_partitions(stamps, ends + 60, protocol, fold, clock, stamps)

    def test_dst_closure_pauses_barrier_clock(self):
        def epoch(s):
            return int(datetime.fromisoformat(s).timestamp())
        a = epoch('2023-03-10T21:59:00+00:00')
        b = epoch('2023-03-12T21:00:00+00:00')
        clock = weekly_fx_clock(a, b + 10 * 86400)
        source = [candle(a // 60), candle(b // 60, '1.106')]
        actual = barrier_labels(source, clock, np.full(2, .005), np.full(2, .002), horizon=30)
        self.assertEqual(actual['outcomes'][0], 'take_profit')
        self.assertEqual(actual['ends'][0], b)
        self.assertEqual(actual['last_information_bar_end'][0], b + 60)
