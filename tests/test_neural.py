import unittest
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np

from fxnn.neural import choose_epochs, refit_predict, run_fold
from fxnn.research import Dataset


class NeuralTests(unittest.TestCase):
    def test_network_learns_nonlinear_signal_and_is_reproducible(self):
        rng = np.random.default_rng(7)
        X = rng.normal(size=(4096, 2))
        y = (X[:, 0]*X[:, 1] > 0).astype(int)
        args = (X[:3072], y[:3072], np.ones(3072), X[3072:], 30, (11,))
        p = refit_predict(*args)
        self.assertGreater(np.mean((p[0] >= .5) == y[3072:]), .90)
        np.testing.assert_array_equal(p, refit_predict(*args))

    def test_outer_labels_do_not_change_epoch_selection_or_predictions(self):
        rng = np.random.default_rng(23)
        start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
        starts = start + np.arange(24*243)*3600
        X = rng.normal(size=(len(starts), 3))
        y = (X[:, 0]*X[:, 1] > 0).astype(int)
        data = Dataset(X, y, starts, starts+3600, starts+72*3600,
                       np.arange(len(starts)), np.ones(len(starts)), ['a', 'b', 'c'], {}, 0)
        report, test, p = run_fold(data, 2025, 7, seeds=(11,), checkpoints=(1, 2))
        changed = y.copy()
        changed[test] = 1-changed[test]
        other, test2, p2 = run_fold(replace(data, y=changed), 2025, 7, seeds=(11,), checkpoints=(1, 2))
        self.assertEqual(report['inner_selection'], other['inner_selection'])
        self.assertEqual(report['selected_epochs'], other['selected_epochs'])
        np.testing.assert_array_equal(test, test2)
        np.testing.assert_array_equal(p, p2)
        self.assertLess(report['last_train_information_time'], report['test_start']-241*60)

    def test_invalid_checkpoints_rejected(self):
        with self.assertRaises(ValueError):
            choose_epochs(None, None, None, None, None, checkpoints=(2, 1))
