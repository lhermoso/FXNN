"""Independent causal, numerical and session fixtures for finite EW volatility."""
import math
import unittest
from datetime import datetime, timezone

import numpy as np

from fxnn.session_clock import SessionClock, weekly_fx_clock
from fxnn.volatility_estimator import causal_volatility


def fixture(n=2100):
    clock = SessionClock(0, np.ones(n + 100, dtype=bool))
    stamps = np.arange(n, dtype=np.int64) * 60
    closes = np.exp(.003 * np.sin(np.arange(n) / 37.) + .000001 * np.arange(n))
    return closes, stamps, clock, clock.gap_breaks(stamps, 15)


def oracle(closes, stamps, clock, breaks, i, lag=1440, window=500, span=100):
    coordinate = clock.prefix[clock.indices(stamps)]
    lookup = {int(x): k for k, x in enumerate(coordinate)}
    segment = max([0] + [k for k in range(i + 1) if breaks[k]])
    values, weights, anchors = [], [], []
    for j in range(max(segment, i-window), i):
        a = lookup.get(int(coordinate[j])-lag)
        if a is not None and a >= segment:
            values.append(float(closes[j]/closes[a]-1))
            weights.append((1-2/(span+1))**(i-1-j))
            anchors.append(a)
    if len(values) < 2:
        return len(values), math.nan, min(anchors, default=-1)
    z = [v-values[0] for v in values]
    total = math.fsum(weights)
    mean = math.fsum(w*v for w, v in zip(weights, z))/total
    var = math.fsum(w*(v-mean)**2 for w, v in zip(weights, z))/(total-math.fsum(w*w for w in weights)/total)
    return len(values), math.sqrt(var), min(anchors)


class VolatilityEstimatorTests(unittest.TestCase):
    def test_scalar_reference_and_exact_provenance(self):
        args = fixture()
        got = causal_volatility(*args)
        for i in (1539, 1540, 1660, 1940, 2099):
            count, sigma, start = oracle(*args, i)
            self.assertEqual(got['valid_returns'][i], count)
            self.assertEqual(got['history_start_index'][i], start)
            if count >= 100:
                self.assertAlmostEqual(got['sigma'][i], sigma, delta=2e-12*sigma)
                self.assertAlmostEqual(got['price_volatility'][i], sigma*args[0][i-1], delta=2e-12*sigma)
        self.assertEqual(got['valid_returns'][1539], 99)
        self.assertEqual(got['reason'][1539], 'insufficient_history')
        self.assertTrue(got['valid'][1540])
        self.assertEqual(2099-got['history_start_index'][2099], 1940)
        self.assertEqual(got['reason'][1540], '')

    def test_current_future_and_prefix_invariance(self):
        closes, stamps, clock, breaks = fixture()
        before = causal_volatility(closes, stamps, clock, breaks)
        changed = closes.copy(); changed[1800:] *= np.linspace(2, 3, len(changed)-1800)
        after = causal_volatility(changed, stamps, clock, breaks)
        prefix = causal_volatility(closes[:1801], stamps[:1801], clock, breaks[:1801])
        for key in before:
            np.testing.assert_array_equal(before[key][:1801], after[key][:1801])
            np.testing.assert_array_equal(before[key][:1801], prefix[key])

    def test_zero_and_nearly_constant(self):
        _, stamps, clock, breaks = fixture(800)
        zero = causal_volatility(np.ones(800), stamps, clock, breaks, lag=1)
        self.assertEqual(zero['reason'][101], 'zero_volatility')
        self.assertEqual(zero['sigma'][101], 0)
        r = .01 + 1e-12*np.sin(np.arange(800))
        closes = np.cumprod(1+r)
        got = causal_volatility(closes, stamps, clock, breaks, lag=1)
        for i in (101, 500, 799):
            _, sigma, _ = oracle(closes, stamps, clock, breaks, i, lag=1)
            self.assertTrue(got['valid'][i])
            self.assertAlmostEqual(got['sigma'][i], sigma, delta=2e-12*sigma)

    def test_missing_exact_endpoint_and_gap_14_15(self):
        closes, stamps, clock, _ = fixture(2600)
        for missing in (1, 14, 15):
            keep = np.ones(len(stamps), dtype=bool); keep[1600:1600+missing] = False
            s, c = stamps[keep], closes[keep]; br = clock.gap_breaks(s, 15)
            got = causal_volatility(c, s, clock, br)
            if missing == 15:
                self.assertEqual(got['valid_returns'][1600], 0)
                self.assertEqual(got['history_start_index'][1600], -1)
            else:
                self.assertTrue(got['valid'][1600])
            for i in (1600, len(s)-1):
                count, sigma, start = oracle(c, s, clock, br, i)
                self.assertEqual(got['valid_returns'][i], count)
                self.assertEqual(got['history_start_index'][i], start)
                if count >= 100:
                    self.assertAlmostEqual(got['sigma'][i], sigma, delta=2e-12*sigma)
        # Missing a lag anchor while its later endpoint exists removes one return.
        keep = np.ones(len(stamps), dtype=bool); keep[10] = False
        got = causal_volatility(closes[keep], stamps[keep], clock, clock.gap_breaks(stamps[keep], 15))
        i = int(np.searchsorted(stamps[keep], 1540*60))
        self.assertEqual(got['valid_returns'][i], 99)

    def test_weekend_dst_and_buffer(self):
        begin = int(datetime(2023, 3, 9, tzinfo=timezone.utc).timestamp())
        end = int(datetime(2023, 3, 15, tzinfo=timezone.utc).timestamp())
        clock = weekly_fx_clock(begin, end)
        stamps = begin+np.flatnonzero(clock.active).astype(np.int64)*60
        closes = np.exp(.003*np.sin(np.arange(len(stamps))/37))
        breaks = clock.gap_breaks(stamps, 15)
        self.assertFalse(breaks.any())
        got = causal_volatility(closes, stamps, clock, breaks)
        weekend = np.flatnonzero(np.diff(stamps)>60)[0]+1
        for i in (weekend, len(stamps)-1):
            count, sigma, start = oracle(closes, stamps, clock, breaks, i)
            self.assertEqual(got['valid_returns'][i], count)
            self.assertAlmostEqual(got['sigma'][i], sigma, delta=2e-12*sigma)
            self.assertEqual(got['history_start_index'][i], start)
            self.assertLessEqual(i-start, 1940)
        reopen = datetime.fromtimestamp(int(stamps[weekend]), timezone.utc)
        self.assertEqual(reopen.hour, 21)

    def test_input_guards_empty_and_nonfinite_result(self):
        c, s, clock, b = fixture(800)
        for kwargs in ({'lag': True}, {'window': 0}, {'span': 1}, {'minimum': 1}, {'minimum': 501}):
            with self.assertRaises(ValueError): causal_volatility(c, s, clock, b, **kwargs)
        with self.assertRaises(ValueError): causal_volatility(c[:-1], s, clock, b)
        with self.assertRaises(ValueError): causal_volatility(c, s[::-1], clock, b)
        with self.assertRaises(ValueError): causal_volatility(c, s[::-1].astype(np.uint64), clock, b)
        inactive = SessionClock(0, np.zeros(900, dtype=bool))
        with self.assertRaises(ValueError): causal_volatility(c, s, inactive, b)
        with self.assertRaises(ValueError): causal_volatility(c, s, clock, np.ones(len(b), dtype=bool))
        with self.assertRaises(ValueError): causal_volatility(np.full(len(c), np.nan), s, clock, b)
        with self.assertRaises(ValueError): causal_volatility(c, s, clock, b.astype(int))
        empty = causal_volatility(c[:0], s[:0], clock, b[:0])
        self.assertTrue(all(len(v)==0 for v in empty.values()))
        c = np.where(np.arange(800)%2, 1e300, 1e-300)
        got = causal_volatility(c, s, clock, b, lag=1)
        self.assertFalse(got['valid'][101])
        self.assertEqual(got['reason'][101], 'nonfinite_volatility')
