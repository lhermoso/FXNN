"""Synthetic tests only; frozen states are hand-written, never trained."""
import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from fxnn.features import FeatureFrame
from fxnn.session_stability import (candidate_X, class_summaries, compare, contributions,
    horizon_mask, losses, no_training, paired_rows, quantiles, reference, removal, summary)


class StabilityTests(unittest.TestCase):
    def test_weighted_quantiles_and_ties(self):
        x = np.array([0., 10., 10., 20.])
        w = np.array([1., 7., 1., 1.])
        np.testing.assert_array_equal(quantiles(x, w), [0., 10., 20.])
        self.assertEqual(summary(x, w)['mean'], 10.)
        r = reference(x[:, None], w)[0]
        self.assertEqual(r['outside_fraction'], 0.)

    def test_train_only_reference_and_weighting(self):
        X = np.array([[0.], [2.]])
        r = reference(X, np.array([3., 1.]))
        self.assertEqual(r[0]['mean'], .5)
        self.assertAlmostEqual(r[0]['std'], np.sqrt(.75))
        before = repr(r)
        a = compare(np.array([[100.], [102.]]), r)[0]
        self.assertEqual(repr(r), before)
        self.assertAlmostEqual(a['standardized_mean_shift'], 100.5/np.sqrt(.75))
        self.assertEqual(a['outside_fraction'], 1.)
        self.assertEqual(reference(X, np.ones(2))[0]['mean'], 1.)

    def test_empty_and_constant_reference(self):
        r = reference(np.ones((3, 1)), np.ones(3))
        c = compare(np.ones((2, 1))*2, r)[0]
        self.assertIsNone(c['standardized_mean_shift'])
        self.assertEqual(c['normalization_reason'], 'zero_train_std')
        self.assertEqual(c['outside_fraction'], 1.)
        self.assertIsNone(compare(np.empty((0, 1)), r)[0]['mean'])
        with self.assertRaises(ValueError):
            summary(np.array([np.nan]))

    def test_logit_reconstruction_and_single_removal(self):
        state = dict(kind=np.array('logistic'), mean=np.array([1., 2., 3.]),
                     scale=np.array([2., 1., 4.]), coef=np.array([[2., -1., .5]]),
                     intercept=np.array([-.4]))
        X = np.array([[3., 4., 7.], [1., 2., 3.]])
        groups = {'first': [0, 2], 'second': [1]}
        c, logits, error = contributions(X, state, groups)
        np.testing.assert_allclose(c, [[2.5, -2.], [0., 0.]])
        np.testing.assert_allclose(logits, [.1, -.4])
        y = np.array([1, 0]); baseline = losses(y, logits)
        result = removal(y, logits, c[:, 0])
        expected = losses(y, np.array([-2.4, -.4]))
        self.assertAlmostEqual(result['delta']['log_loss'], expected['log_loss']-baseline['log_loss'])
        np.testing.assert_array_equal(state['coef'], [[2., -1., .5]])
        self.assertLess(error, 1e-12)
        with self.assertRaises(ValueError):
            contributions(X, state, {'bad': [0, 1, 1]})
        self.assertTrue(np.isfinite(losses(y, np.array([-1000., 1000.]))['log_loss']))

    def test_observed_class_association(self):
        v = np.array([0., 2., 3., 5.]); y = np.array([0, 0, 1, 1])
        s = class_summaries(v, y, np.array([3., 1., 1., 3.]))
        self.assertEqual(s['class1_minus_class0_mean'], 4.)
        self.assertIsNone(class_summaries(v, np.zeros(4))['class1_minus_class0_mean'])

    def test_no_history_no_imputation(self):
        frame = FeatureFrame(np.array([[99., 1.], [2., 1.]]), np.array([False, True]),
                             ['return', 'direction'], {'movement': [0], 'context': [1]}, [0])
        X = candidate_X(frame, np.array([0, 1]), np.array([1, -1]))
        self.assertTrue(np.isnan(X[0]).all())
        np.testing.assert_array_equal(X[1], [-2., -1.])

    def test_strict_horizon_not_realized_end(self):
        candidates = dict(starts=np.array([0, 10, 20, 30]), info_ends=np.array([20, 30, 40, 50]),
                          ends=np.array([1, 11, 21, 31]))
        np.testing.assert_array_equal(horizon_mask(candidates, 10, 40), [False, True, False, False])

    def test_pairing_rejects_reorder_or_label_change(self):
        data = SimpleNamespace(starts=np.array([1, 2]), entry_indices=np.array([10, 20]),
                               sides=np.array([-1, 1]), y=np.array([0, 1]))
        p = {k: getattr(data, k).copy() for k in vars(data)}; p['rows'] = np.array([0, 1])
        paired_rows(data, p['rows'], p)
        with self.assertRaises(AssertionError):
            paired_rows(data, np.array([1, 0]), p)
        p['y'][0] = 1
        with self.assertRaises(AssertionError):
            paired_rows(data, p['rows'], p)

    def test_guards_reject_training_and_input_write(self):
        class Fake:
            def fit(self):
                raise AssertionError('must not execute')
        with self.assertRaisesRegex(RuntimeError, 'forbidden'):
            with no_training():
                Fake().fit()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'ledger'; p.write_bytes(b'unchanged')
            with self.assertRaisesRegex(RuntimeError, 'Protected'):
                with no_training([p]):
                    self.assertEqual(p.read_bytes(), b'unchanged')
                    p.write_bytes(b'bad')
            self.assertEqual(p.read_bytes(), b'unchanged')

    def test_runner_has_no_fit_or_ledger_mutation_calls(self):
        source = Path(__file__).resolve().parents[1]/'fxnn/session_stability.py'
        tree = ast.parse(source.read_text())
        calls = [n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
                 for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name))]
        self.assertFalse(set(calls) & {'fit', 'partial_fit', 'fit_transform', 'FitLedger',
                                     'start_fit', 'finish_fit', 'start_run', 'finish_run', 'session_labels'})


if __name__ == '__main__':
    unittest.main()
