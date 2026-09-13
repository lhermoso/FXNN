import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np

from fxnn.afml import Prepared, diagnostic_rows, diagnostics, prepare, run_fold
from fxnn.fracdiff import FractionalFrame
from fxnn.research import Dataset
from fxnn.temporal import split_before


class AFMLTests(unittest.TestCase):
    def data(self, starts):
        rng = np.random.default_rng(29)
        X = rng.normal(size=(len(starts), 2))
        y = (X[:, 0] + rng.normal(size=len(starts)) > .5).astype(int)
        sides = np.where(np.arange(len(starts)) % 2, -1, 1)
        return Dataset(X, y, starts, starts+60, starts+72*3600,
                       np.arange(len(starts)), sides, ['signal', 'noise'],
                       {'signal': [0], 'noise': [1]}, 0)

    def prepared(self):
        start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
        starts = start + np.arange(48*273)*1800
        data = self.data(starts)
        logs = np.random.default_rng(31).normal(size=len(starts))
        frames = {str(d): FractionalFrame(logs*d, np.ones(len(logs), dtype=bool), np.ones(445))
                  for d in (.25, .5, .75)}
        extras = {key: frame.values * data.sides for key, frame in frames.items()}
        return Prepared(data, extras, frames, logs, starts, 445, {})

    def test_common_mask_preserves_every_aligned_field(self):
        stamps = np.arange(1500)*60
        stamps[600:] += 120
        data = self.data(stamps)
        logs = np.random.default_rng(3).normal(size=1500)
        result = prepare(data, logs, stamps)
        expected = np.concatenate((np.arange(445, 600), np.arange(1045, 1500)))
        self.assertEqual(result.lookback, 445)
        for field in ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides'):
            np.testing.assert_array_equal(getattr(result.data, field), getattr(data, field)[expected])
        for key, extra in result.extras.items():
            np.testing.assert_array_equal(extra, result.frames[key].values[expected]*data.sides[expected])

    def test_outer_labels_cannot_change_selection_states_or_predictions(self):
        original = self.prepared()
        report, test, predictions, weight_data = run_fold(original, 7)
        cutoff = int(datetime(2025, 7, 1, tzinfo=timezone.utc).timestamp())
        y = original.data.y.copy()
        y[original.data.starts >= cutoff] = 1-y[original.data.starts >= cutoff]
        changed = replace(original, data=replace(original.data, y=y))
        report2, test2, predictions2, _ = run_fold(changed, 7)
        for key in ('best_d', 'adaptive_choice', 'inner', 'inner_constant', 'sfi',
                    'external_models', 'training_diagnostics'):
            self.assertEqual(report[key], report2[key])
        np.testing.assert_array_equal(test, test2)
        for name in predictions:
            np.testing.assert_array_equal(predictions[name], predictions2[name])
        train, weights, refit, refit_weights = weight_data
        # Verify learned scaling uses exactly authorized weighted training rows.
        for key in report['inner']:
            X = original.data.X if key == 'control' else np.column_stack((original.data.X, original.extras[key]))
            np.testing.assert_allclose(report['inner'][key]['model']['scaler_mean'],
                                       np.average(X[train], axis=0, weights=weights))
        np.testing.assert_allclose(report['external_models']['control']['scaler_mean'],
                                   np.average(original.data.X[refit], axis=0, weights=refit_weights))
        inner = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp())
        self.assertLess(report['last_train_information_epoch'], inner-445*60)
        self.assertLess(report['last_refit_information_epoch'], cutoff-445*60)
        stale, _ = split_before(original.data.starts, original.data.info_ends, cutoff,
                                 cutoff+31*86400, buffer_seconds=241*60)
        self.assertGreater(len(stale), len(refit))
        self.assertEqual(report['fit_count'], 11)  # two synthetic baseline features + three FFD

    def test_diagnostic_sequence_deduplicates_and_never_joins_gaps(self):
        stamps = np.arange(600)*60
        data = self.data(stamps)
        # Excluded training entries split runs; choose first longest run.
        train = np.concatenate((np.arange(120), np.arange(200, 320), np.arange(500, 550)))
        np.testing.assert_array_equal(diagnostic_rows(data, train), np.arange(120))
        duplicate = replace(data, entry_indices=np.repeat(np.arange(300), 2), starts=np.repeat(np.arange(300)*60, 2))
        np.testing.assert_array_equal(diagnostic_rows(duplicate, np.arange(600)), np.arange(0, 600, 2))

    def test_diagnostics_see_only_inner_train_and_previous_closes(self):
        stamps = np.arange(1000)*60
        prepared = prepare(self.data(stamps), np.random.default_rng(9).normal(size=1000), stamps)
        train = np.arange(150)
        with patch('fxnn.afml.adfuller', return_value=(-2., .2, 1, 148, {'5%': -2.9})) as mocked:
            report = diagnostics(prepared, train)
        first = prepared.data.entry_indices[0]
        np.testing.assert_array_equal(mocked.call_args_list[0].args[0], prepared.logs[first-1:first+149])
        self.assertEqual(mocked.call_count, 4)
        self.assertEqual(report['last_entry_index'], first+149)
        # Future diagnostic input cannot change ADF or redundancy output.
        changed = prepared.logs.copy()
        changed[first+150:] += 100
        frames = {key: replace(frame, values=frame.values.copy()) for key, frame in prepared.frames.items()}
        for frame in frames.values():
            frame.values[first+150:] += 500
        self.assertEqual(diagnostics(prepared, train), diagnostics(replace(prepared, logs=changed, frames=frames), train))
