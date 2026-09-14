import copy
import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.utils import check_random_state, shuffle

from fxnn import mlp_adam_budget as new
from fxnn import mlp_comparison as prior
from fxnn import cusum_continuation as logistic
from fxnn.fit_ledger import FitLedger
from fxnn.protocol import partition_indices
from test_cusum import synthetic


def new_ledger(path):
    ledger = FitLedger(path)
    ledger.initialize(0, {'synthetic': True})
    ledger.start_run(new.EXPERIMENT, 12, {'synthetic': True}, independent_failures=True)
    return ledger


class AdamBudgetTests(unittest.TestCase):
    def test_full_epochs_identical_to_original_including_adam(self):
        spec, _ = new.load_contract()
        X = np.random.RandomState(7).normal(size=(11, 3))
        y, w = np.arange(11) % 2, np.linspace(.2, 1.8, 11)
        params = {**spec['model'], 'batch_size': 4}
        actual = new.FixedUpdates().fit(X, y, w, params, 9)
        expected = prior.FixedMLP().fit(X, y, w, params, 3)
        self.assertEqual(actual.calls, 3)
        self.assertEqual(actual.model.batch_sizes, [4, 4, 3]*3)
        for a, b in zip(actual.model.coefs_ + actual.model.intercepts_ + actual.model._optimizer.ms + actual.model._optimizer.vs,
                        expected.model.coefs_ + expected.model.intercepts_ + expected.model._optimizer.ms + expected.model._optimizer.vs):
            np.testing.assert_array_equal(a, b)
        np.testing.assert_array_equal(actual.model.loss_curve_, expected.model.loss_curve_)
        np.testing.assert_array_equal(actual.scaler.mean_, expected.scaler.mean_)

    def test_partial_epoch_matches_independent_minibatch_reference(self):
        spec, _ = new.load_contract()
        X = np.random.RandomState(8).normal(size=(11, 3))
        y, w = np.arange(11) % 2, np.linspace(.3, 1.7, 11)
        params = {**spec['model'], 'batch_size': 4}
        actual = new.FixedUpdates().fit(X, y, w, params, 5)
        # Native first epoch includes RNG consumption for initialization.
        reference = prior.FixedMLP().fit(X, y, w, params, 1)
        model = reference.model
        transformed = reference.scaler.transform(X)
        order = shuffle(np.arange(11), random_state=check_random_state(0))
        # Second native call resets integer RNG; use its first two batches,
        # no new shuffle inside manual calls. Optimizer persists.
        model.shuffle = False
        for batch in (order[:4], order[4:8]):
            model.partial_fit(transformed[batch], y[batch], classes=[0, 1], sample_weight=w[batch])
        self.assertEqual(actual.model._optimizer.t, 5)
        self.assertEqual(actual.calls, 2)
        self.assertEqual(len(actual.model.loss_curve_), 1)
        self.assertEqual(actual.model.batch_sizes, [4, 4, 3, 4, 4])
        for a, b in zip(actual.model.coefs_ + actual.model.intercepts_ + actual.model._optimizer.ms + actual.model._optimizer.vs,
                        model.coefs_ + model.intercepts_ + model._optimizer.ms + model._optimizer.vs):
            np.testing.assert_array_equal(a, b)
        with patch('sklearn.neural_network._multilayer_perceptron.train_test_split', side_effect=AssertionError):
            twin = new.FixedUpdates().fit(X, y, w, params, 5)
        np.testing.assert_array_equal(actual.predict(X), twin.predict(X))

    def test_exact_single_update_and_weighted_scaler(self):
        spec, _ = new.load_contract()
        X, y, w = np.array([[0., 1.], [4., 2.], [8., 0.]]), np.array([0, 1, 0]), np.array([.5, 1., 1.5])
        m = new.FixedUpdates().fit(X, y, w, {**spec['model'], 'batch_size': 2}, 1)
        self.assertEqual(m.model._optimizer.t, 1)
        self.assertEqual(m.model.loss_curve_, [])
        np.testing.assert_allclose(m.scaler.mean_, np.average(X, weights=w, axis=0))
        for budget in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                new.FixedUpdates().fit(X, y, w, spec['model'], budget)

    def test_isolation_support_cache_and_failures(self):
        data, _, _, protocol, _ = synthetic()
        spec, _ = new.load_contract()
        spec = {**spec, 'updates': 7}
        rows = partition_indices(data.starts, data.info_ends, protocol, protocol['folds'][0])['refit']
        contract = new.training_contract(data, rows, spec)[1]
        future = np.setdiff1d(np.arange(len(data.y)), rows)
        changed = replace(data, X=data.X.copy(), y=data.y.copy(), ends=data.ends.copy())
        changed.X[future] = 9999
        changed.y[future] = 1-changed.y[future]
        changed.ends[future] += 600
        self.assertEqual(contract, new.training_contract(changed, rows, spec)[1])
        for field in ('X', 'y', 'ends', 'info_ends'):
            changed = replace(data, **{field:getattr(data, field).copy()})
            getattr(changed, field)[rows[0]] += 1 if field != 'y' else 1-2*data.y[rows[0]]
            self.assertNotEqual(contract, new.training_contract(changed, rows, spec)[1])
        self.assertNotEqual(contract, new.training_contract(data, rows, {**spec, 'updates': 8})[1])
        with tempfile.TemporaryDirectory() as tmp:
            ledger = new_ledger(Path(tmp)/'ledger')
            cache = {}
            model, fit = new.fit_cached(data, rows, spec, ledger, 'one', 'Q2', {}, cache)
            self.assertEqual(fit['updates'], 7)
            self.assertTrue(fit['finite_loss_coefficients_adam'])
            same, alias = new.fit_cached(data, rows, spec, ledger, 'alias', 'Q3', {}, cache)
            self.assertIs(same, model)
            self.assertTrue(alias['reused'])
            tiny = np.array([np.flatnonzero(data.y == c)[0] for c in (0, 1)])
            self.assertEqual(new.fit_cached(data, tiny, spec, ledger, 'tiny', 'Q2', {}, cache)[1]['status'], 'succeeded')
            self.assertEqual(new.fit_cached(data, tiny[:1], spec, ledger, 'class', 'Q2', {}, cache)[1]['status'], 'technically_unavailable')
            def failure(*args, **kwargs):
                self.assertEqual(ledger.records()[-1]['kind'], 'fit_started')
                raise ValueError('synthetic failure')
            with patch.object(StandardScaler, 'fit', side_effect=failure):
                failed, record = new.fit_cached(data, rows, {**spec, 'updates': 8}, ledger, 'failed', 'Q2', {}, cache)
            self.assertIsNone(failed)
            self.assertEqual(record['status'], 'failed')
            with patch.object(new.FixedUpdates, 'fit', side_effect=AssertionError('No retry')):
                self.assertTrue(new.fit_cached(data, rows, {**spec, 'updates': 8}, ledger, 'failed-alias', 'Q3', {}, cache)[1]['reused'])
            self.assertEqual(ledger.consumed(), 3)

    def test_historical_budget_derived_without_scores(self):
        report = json.loads((new.ROOT/'docs/experiments/mlp-cusum-v1.json').read_text())
        budget, derivation = new.derive_budget(report)
        self.assertEqual(budget, 9580)
        self.assertEqual(len(derivation), 4)
        report['folds'][0]['phases']['inner']['fits']['temporal']['updates'] += 1
        with self.assertRaises(ValueError):
            new.derive_budget(report)

    def test_full_pipeline_reuse_and_reject_divergence(self):
        data, masks, obs, protocol, _ = synthetic()
        spec, _ = new.load_contract()
        spec = {**spec, 'updates': 7}
        original, _ = prior.load_contract()
        def grouped(path):
            result = {}
            with path.open() as stream:
                for r in csv.DictReader(stream):
                    result.setdefault((r['fold'], r['phase'], r['universe']), []).append(r)
            return result
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ('logistic', 'mlp', 'new'):
                (root/folder).mkdir()
            ledger = FitLedger(root/'logistic-ledger')
            ledger.initialize(0, {'synthetic': True})
            ledger.start_run(logistic.EXPERIMENT, 24, {'synthetic': True}, independent_failures=True)
            old = dict(input_hashes={'synthetic': True}, folds=logistic.run_models(data, masks, obs, protocol, ledger, {}, root/'logistic'))
            controls = prior.validate_controls(data, masks, protocol, old, grouped(root/'logistic/predictions.csv'), {'synthetic': True})
            ledger = FitLedger(root/'mlp-ledger')
            ledger.initialize(0, {'synthetic': True})
            ledger.start_run(prior.EXPERIMENT, 12, {'synthetic': True}, independent_failures=True)
            mlp = dict(input_hashes={'synthetic': True}, folds=prior.run_models(data, masks, protocol, original, ledger, {}, controls, old, root/'mlp'))
            records = grouped(root/'mlp/predictions.csv')
            all_controls = new.validate_mlp(data, masks, protocol, spec, mlp, records, {'synthetic': True}, controls)
            for field in ('y', 'side', 'entry_epoch', 'mlp_temporal'):
                bad = copy.deepcopy(records)
                first = next(iter(bad.values()))[0]
                first[field] = str(float(first[field])+.1) if field == 'mlp_temporal' else str(int(first[field])+1)
                with self.assertRaises(ValueError):
                    new.validate_mlp(data, masks, protocol, spec, mlp, bad, {'synthetic': True}, controls)
            changed = replace(data, X=data.X+1)
            with self.assertRaises(ValueError):
                new.validate_mlp(changed, masks, protocol, spec, mlp, records, {'synthetic': True}, controls)
            ledger = new_ledger(root/'new-ledger')
            reports = new.run_models(data, masks, protocol, spec, ledger, {}, all_controls, old, root/'new')
            self.assertEqual(ledger.consumed(), 12)
            for i, fold in enumerate(reports):
                for phase in ('inner','refit'):
                    for fit in fold['phases'][phase]['fits'].values():
                        self.assertEqual(fit['updates'], 7)
                        self.assertEqual(fit['reused'], phase == 'inner' and i > 0)
                    for universe, ev in fold['phases'][phase]['evaluations'].items():
                        self.assertEqual(len(ev['scores']), 4 if universe == 'temporal' else 7)
                        self.assertTrue(all(s['support'] == ev['support'] for s in ev['scores'].values()))
            json.dumps(new.conclusion(reports, ['temporal', *masks]), allow_nan=False)

    def test_nonfinite_and_interruption_not_silently_accepted(self):
        spec, _ = new.load_contract()
        X, y, w = np.array([[0., 1.], [1., 0.]]), np.array([0, 1]), np.ones(2)
        params = {**spec['model'], 'batch_size': 2}
        with patch.object(MLPClassifier, '_backprop', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                new.FixedUpdates().fit(X, y, w, params, 2)
        native = MLPClassifier._backprop
        def nonfinite(model, *args):
            _, a, b = native(model, *args)
            return float('nan'), a, b
        with patch.object(MLPClassifier, '_backprop', nonfinite):
            with self.assertRaisesRegex(ValueError, 'Non-finite minibatch loss'):
                new.FixedUpdates().fit(X, y, w, params, 2)

    def test_mlp_artifact_versions_and_ledger_fail_closed(self):
        import shutil
        spec, _ = new.load_contract()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'docs/experiments').mkdir(parents=True)
            (root/'fxnn').mkdir()
            report = json.loads((new.ROOT/'docs/experiments/mlp-cusum-v1.json').read_text())
            for name in report['hashes']['source_hashes']:
                shutil.copy(new.ROOT/'fxnn'/name, root/'fxnn'/name)
            # Synthetic artifacts adapt to Python patch version; real loaders stay strict.
            report['versions'] = new.versions()
            predictions = root/'predictions.csv'
            predictions.write_text('fold,phase,universe\n')
            report['predictions_sha256'] = new.digest(predictions)
            path = root/'report.json'
            path.write_text(json.dumps(report))
            shutil.copy(path, root/'docs/experiments/mlp-cusum-v1.json')
            spec = {**spec, 'historical_mlp_report_sha256':new.digest(path),
                    'historical_mlp_predictions_sha256':new.digest(predictions)}
            ledger = FitLedger(root/'ledger')
            ledger.initialize(0, {'synthetic':True})
            missing = ledger.path.read_bytes()
            ledger.start_run(prior.EXPERIMENT, 12, {'synthetic':True})
            ledger.finish_run(prior.EXPERIMENT, 'completed', {'report_sha256':new.digest(path)})
            raw = ledger.path.read_bytes()
            with patch.object(new, 'ROOT', root):
                self.assertEqual(new.load_mlp(root, spec, raw)[0], report)
                with patch.object(new, 'versions', return_value={**report['versions'], 'python':'different-patch'}):
                    with self.assertRaisesRegex(ValueError, 'versions'):
                        new.load_mlp(root, spec, raw)
                with self.assertRaisesRegex(ValueError, 'linked'):
                    new.load_mlp(root, spec, missing)
                (root/'fxnn/mlp_comparison.py').write_text('modified')
                with self.assertRaisesRegex(ValueError, 'implementation changed'):
                    new.load_mlp(root, spec, raw)
                predictions.write_text('modified')
                with self.assertRaisesRegex(ValueError, 'artifact hash mismatch'):
                    new.load_mlp(root, spec, raw)
