import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import numpy as np

from fxnn.features import build_features, orient_features, past_sum
from fxnn.labeling import Candle
from fxnn.research import Baseline, Dataset, run_fold
from fxnn.temporal import split_before, uniqueness_weights


class FeatureTests(unittest.TestCase):
    def candles(self, n=800):
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        result = []
        for i in range(n):
            price = D('1.1') + D(i % 31) / D(100000)
            result.append(Candle(start + timedelta(minutes=i), price,
                                 price + D('.0002'), price - D('.0002'), price + D('.0001')))
        return result

    def test_current_and_future_prices_cannot_change_entry_features(self):
        candles = self.candles()
        original = build_features(candles)
        changed = candles[:400] + [replace(c, open=c.open*2, high=c.high*2,
                                          low=c.low*2, close=c.close*2) for c in candles[400:]]
        np.testing.assert_array_equal(original.values[:401], build_features(changed).values[:401])
        np.testing.assert_array_equal(original.values[:401], build_features(candles[:401]).values)
        self.assertTrue(original.valid[400])

    def test_gap_restarts_full_warmup(self):
        candles = self.candles()
        candles[300:] = [replace(c, timestamp=c.timestamp+timedelta(minutes=1)) for c in candles[300:]]
        valid = build_features(candles).valid
        self.assertTrue(valid[299])
        self.assertFalse(valid[300:541].any())
        self.assertTrue(valid[541])

    def test_past_sum_excludes_current(self):
        np.testing.assert_array_equal(past_sum(np.arange(6), 3)[3:], [3, 6, 9])

    def test_side_only_changes_directional_features(self):
        frame = build_features(self.candles())
        rows = orient_features(frame, [400, 400], [1, -1])
        np.testing.assert_array_equal(rows[0, frame.directional], -rows[1, frame.directional])
        other = [i for i in range(len(frame.names)-1) if i not in frame.directional]
        np.testing.assert_array_equal(rows[0, other], rows[1, other])


class TemporalTests(unittest.TestCase):
    def test_purge_buffer_and_right_boundary(self):
        starts = np.array([0, 10, 20, 100, 150, 190])
        ends = np.array([50, 90, 99, 130, 180, 210])
        train, test = split_before(starts, ends, 100, 200, buffer_seconds=10)
        np.testing.assert_array_equal(train, [0])
        np.testing.assert_array_equal(test, [3, 4])

    def test_uniqueness_matches_discrete_reference(self):
        starts = np.array([0, 0, 2, 7])
        ends = np.array([4, 4, 6, 9])
        expected = []
        for start, end in zip(starts, ends):
            expected.append(np.mean([1 / ((starts <= t) & (ends > t)).sum() for t in range(start, end)]))
        expected = np.array(expected)
        np.testing.assert_allclose(uniqueness_weights(starts, ends), expected/expected.mean())

    def test_invalid_intervals_rejected(self):
        with self.assertRaises(ValueError):
            uniqueness_weights([1], [1])

    def test_scaler_and_prior_use_training_weights(self):
        model = Baseline().fit(np.array([[0.], [2.], [4.], [6.]]),
                               np.array([0, 0, 1, 1]), np.array([1., 1., 1., 3.]))
        self.assertAlmostEqual(model.scaler.mean_[0], 4.)
        self.assertAlmostEqual(model.prior, 2/3)
        model.predict(np.array([[1000000.]]))
        self.assertAlmostEqual(model.scaler.mean_[0], 4.)
        constant = Baseline().fit(np.empty((4, 0)), np.array([0, 0, 1, 1]), np.ones(4))
        np.testing.assert_array_equal(constant.predict(np.empty((2, 0))), [.5, .5])

    def test_outer_labels_cannot_affect_selection_or_predictions(self):
        rng = np.random.default_rng(23)
        start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
        starts = start + np.arange(24*243)*3600
        X = rng.normal(size=(len(starts), 3))
        y = (X[:, 0] + rng.normal(size=len(starts)) > 0).astype(int)
        data = Dataset(X, y, starts, starts+3600, starts+72*3600,
                       np.arange(len(starts)), np.ones(len(starts)), ['signal', 'noise1', 'noise2'],
                       {'signal': [0], 'noise': [1, 2]}, 0)
        report, test, prediction = run_fold(data, 2025, 7)
        changed = y.copy()
        changed[test] = 1-changed[test]
        report2, test2, prediction2 = run_fold(replace(data, y=changed), 2025, 7)
        self.assertEqual(report['selected_groups'], report2['selected_groups'])
        self.assertEqual(report['inner_importance'], report2['inner_importance'])
        np.testing.assert_array_equal(test, test2)
        np.testing.assert_array_equal(prediction, prediction2)


if __name__ == '__main__':
    unittest.main()
