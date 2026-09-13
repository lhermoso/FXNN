import math
import unittest
import numpy as np
from fxnn.fracdiff import fractional_features, fractional_weights


class FractionalTests(unittest.TestCase):
    def test_zero_and_one_are_exact_level_and_difference(self):
        logs = np.arange(20, dtype=float) ** 2
        stamps = np.arange(20) * 60
        zero = fractional_features(logs, stamps, 0)
        one = fractional_features(logs, stamps, 1)
        np.testing.assert_array_equal(zero.weights, [1])
        np.testing.assert_array_equal(one.weights, [1, -1])
        np.testing.assert_array_equal(zero.values[1:], logs[:-1])
        np.testing.assert_array_equal(one.values[2:], np.diff(logs)[:-1])
        self.assertFalse(one.valid[:2].any())

    def test_truncation_and_convolution_match_binomial_reference(self):
        d, threshold = .5, .01
        # Generalized binomial formula, independent of production recurrence.
        reference = []
        for k in range(100):
            weight = (-1)**k * math.prod(d-j for j in range(k)) / math.factorial(k)
            if abs(weight) < threshold:
                break
            reference.append(weight)
        weights = fractional_weights(d, threshold)
        np.testing.assert_allclose(weights, reference, rtol=1e-14)
        logs = np.random.default_rng(42).normal(size=100)
        frame = fractional_features(logs, np.arange(100)*60, d, threshold)
        for t in range(len(reference), len(logs)):
            expected = sum(w*logs[t-1-k] for k, w in enumerate(reference))
            self.assertAlmostEqual(frame.values[t], expected, places=13)
        self.assertEqual([len(fractional_weights(d)) for d in (.25, .5, .75)], [445, 200, 79])

    def test_gap_restarts_full_history(self):
        stamps = np.arange(1200)*60
        stamps[500:] += 60
        frame = fractional_features(np.arange(1200)*.01, stamps, .25)
        self.assertTrue(frame.valid[499])
        self.assertFalse(frame.valid[500:945].any())
        self.assertTrue(frame.valid[945])
        self.assertTrue(np.isnan(frame.values[500:945]).all())

    def test_current_future_and_truncated_input_invariance(self):
        rng = np.random.default_rng(1)
        logs = rng.normal(size=1200)
        stamps = np.arange(1200)*60
        frame = fractional_features(logs, stamps, .25)
        changed = logs.copy()
        changed[700:] += 1000
        future = fractional_features(changed, stamps, .25)
        truncated = fractional_features(logs[:701], stamps[:701], .25)
        np.testing.assert_array_equal(frame.values[:701], future.values[:701])
        np.testing.assert_array_equal(frame.values[:701], truncated.values)
        np.testing.assert_array_equal(frame.valid[:701], truncated.valid)

    def test_short_input_and_invalid_configuration(self):
        frame = fractional_features(np.ones(10), np.arange(10)*60, .25)
        self.assertFalse(frame.valid.any())
        for args in ((-1,), (1.1,), (float('nan'),), (.5, 0), (.5, 1), (.5, 1e-4, 2)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                fractional_weights(*args)
        for logs, stamps in (([0, float('nan')], [0, 60]), ([0, 1], [0, 0]),
                             ([0, 1], [0, 61]), ([0], [0, 60])):
            with self.assertRaises(ValueError):
                fractional_features(logs, stamps, .5)
