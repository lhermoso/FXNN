import unittest
import numpy as np
from fxnn.meta_primary import primary_signals, join_candidates, choose_threshold, decisions


class MetaPrimaryTests(unittest.TestCase):
    def test_exact_decimal_causality_and_reset(self):
        closes = np.full(125, '1.0000000000000000000000', dtype='<U30')
        closes[60] = '1.0000000000000000000001'
        breaks = np.zeros(125, dtype=bool)
        result = primary_signals(closes, breaks)
        self.assertEqual(result['side'][61], 1)
        self.assertEqual(result['side'][62], 0)
        self.assertEqual(result['primary_reason'][62], 'no_momentum')
        changed = closes.copy(); changed[61:] = '99.0'
        np.testing.assert_array_equal(primary_signals(changed, breaks)['side'][:62], result['side'][:62])
        breaks[61] = True
        self.assertFalse(primary_signals(closes, breaks)['primary_available'][61])
        np.testing.assert_array_equal(primary_signals(closes[:62], np.zeros(62, bool))['side'], result['side'][:62])

    def test_join_shuffled_side_and_no_signal(self):
        source = dict(entry_local=np.array([1, 0, 1, 0]), sides=np.array([-1, 1, 1, -1]))
        np.testing.assert_array_equal(join_candidates(np.array([1, -1]), source), [1, 0])
        np.testing.assert_array_equal(join_candidates(np.array([0, -1]), source), [-1, 0])
        bad = {k: np.append(v, v[0]) for k, v in source.items()}
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            join_candidates(np.array([1, -1]), bad)
        with self.assertRaisesRegex(ValueError, 'missing'):
            join_candidates(np.array([1, -1]), {k: v[1:] for k, v in source.items()})

    def test_threshold_hand_counts_ties_and_unavailable(self):
        selection = choose_threshold(np.array([1, 0, 1]), np.array([.5, .4, .6]), 'fixture')
        self.assertEqual(selection['threshold'], .5)
        self.assertEqual(selection['grid']['0.3']['f1'], .8)
        self.assertEqual(selection['grid']['0.5']['f1'], 1)
        self.assertEqual(choose_threshold(np.array([1, 0]), np.array([.8, .1]), 'x')['threshold'], .5)
        self.assertEqual(choose_threshold(np.array([1]), np.array([.1]), 'x')['threshold'], .5)
        missing = choose_threshold(np.zeros(3, dtype=int), np.array([.2, .4, .6]), 'Q2')
        self.assertEqual(missing['reason'], 'no_validation_positives')
        result = decisions(np.array([.1, .9]), np.ones(2, bool), missing)
        np.testing.assert_array_equal(result['accepted'], [-1, -1])
        self.assertFalse(result['acceptance_available'].any())
        self.assertEqual(choose_threshold(np.array([], int), np.array([]), 'x')['reason'], 'empty_validation')
        np.testing.assert_array_equal(decisions(np.array([.5, .4]), np.ones(2, bool), selection)['accepted'], [1, 0])
