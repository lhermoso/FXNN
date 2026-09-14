import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler

from fxnn import cusum_continuation as old
from fxnn.cusum_research import identity_hash
from fxnn.fit_ledger import FitLedger
from fxnn.mlp_comparison import (EXPERIMENT, FixedMLP, aligned_controls, conclusion,
    fit_cached, load_contract, run_models, training_contract, validate_controls)
from fxnn.protocol import partition_indices
from fxnn.temporal import uniqueness_weights
from test_cusum import synthetic


def ledger_at(tmp):
    ledger = FitLedger(Path(tmp)/'ledger.jsonl')
    ledger.initialize(0, {'synthetic': True})
    ledger.start_run(EXPERIMENT, 12, {'synthetic': True}, independent_failures=True)
    return ledger


class MLPComparisonTests(unittest.TestCase):
    def test_weighted_scaler_fixed_epochs_no_random_validation(self):
        spec, _ = load_contract()
        X = np.array([[0., 1.], [2., 0.], [30., -2.]])
        y, w = np.array([0, 1, 0]), np.array([1., 2., 7.])
        params = {**spec['model'], 'batch_size': 3}
        with patch('sklearn.neural_network._multilayer_perceptron.train_test_split',
                   side_effect=AssertionError('No internal random split')):
            model = FixedMLP().fit(X, y, w, params, 20)
        np.testing.assert_allclose(model.scaler.mean_, np.average(X, axis=0, weights=w))
        self.assertEqual(len(model.model.loss_curve_), 20)
        self.assertEqual(model.model._optimizer.t, 20)
        twin = FixedMLP().fit(X, y, w, params, 20)
        np.testing.assert_array_equal(model.predict(X), twin.predict(X))
        unweighted = FixedMLP().fit(X, y, np.ones(3), params, 20)
        self.assertFalse(np.array_equal(model.predict(X), unweighted.predict(X)))

    def test_two_rows_viable_one_class_unavailable_failure_cached(self):
        spec, _ = load_contract()
        data, *_ = synthetic()
        rows = np.array([np.flatnonzero(data.y == 0)[0], np.flatnonzero(data.y == 1)[0]])
        with tempfile.TemporaryDirectory() as tmp:
            ledger, cache = ledger_at(tmp), {}
            model, result = fit_cached(data, rows, spec, ledger, 'two', 'Q2', {}, cache)
            self.assertEqual(result['status'], 'succeeded')
            self.assertEqual(result['contract']['parameters']['batch_size'], 2)
            same, reuse = fit_cached(data, rows, spec, ledger, 'alias', 'Q3', {}, cache)
            self.assertIs(same, model)
            self.assertTrue(reuse['reused'])
            model, result = fit_cached(data, rows[:1], spec, ledger, 'one', 'Q2', {}, cache)
            self.assertIsNone(model)
            self.assertEqual(result['status'], 'technically_unavailable')
            self.assertEqual(ledger.consumed(), 1)
            def failure(*args):
                self.assertEqual(ledger.records()[-1]['kind'], 'fit_started')
                raise ConvergenceWarning('synthetic nonconvergence')
            changed = replace(data, X=data.X+1)
            with patch.object(FixedMLP, 'fit', side_effect=failure):
                model, result = fit_cached(changed, rows, spec, ledger, 'failed', 'Q2', {}, cache)
            self.assertEqual(result['status'], 'failed')
            with patch.object(FixedMLP, 'fit', side_effect=AssertionError('No retry')):
                model, result = fit_cached(changed, rows, spec, ledger, 'failed_alias', 'Q3', {}, cache)
            self.assertIsNone(model)
            self.assertTrue(result['reused'])
            self.assertEqual(ledger.consumed(), 2)

    def test_temporal_isolation_and_cache_requires_exact_contract(self):
        data, _, _, protocol, _ = synthetic()
        spec, _ = load_contract()
        parts = [partition_indices(data.starts, data.info_ends, protocol, f) for f in protocol['folds']]
        rows = parts[0]['refit']
        w, contract = training_contract(data, rows, spec)
        self.assertEqual(contract, training_contract(data, parts[1]['train'], spec)[1])
        np.testing.assert_array_equal(w, uniqueness_weights(data.starts[rows], data.ends[rows]))
        self.assertLess(data.info_ends[rows].max(), data.starts[parts[0]['test']].min()-241*60)
        future = np.setdiff1d(np.arange(len(data.y)), rows)
        changed = replace(data, X=data.X.copy(), y=data.y.copy(), ends=data.ends.copy())
        changed.X[future] = 1e8
        changed.y[future] = 1-changed.y[future]
        changed.ends[future] += 60
        self.assertEqual(contract, training_contract(changed, rows, spec)[1])
        for name in ('X', 'y', 'ends'):
            altered = replace(data, **{name: getattr(data, name).copy()})
            if name == 'y':
                altered.y[rows[0]] = 1-altered.y[rows[0]]
            else:
                getattr(altered, name)[rows[0]] += 1
            self.assertNotEqual(contract['sha256'], training_contract(altered, rows, spec)[1]['sha256'])
        self.assertNotEqual(contract['sha256'], training_contract(data, rows, {**spec, 'epochs': 19})[1]['sha256'])

    def test_control_alignment_rejects_reordering_labels_and_scores(self):
        data, *_ = synthetic()
        rows = np.arange(10)
        records = [dict(entry_index=str(data.entry_indices[i]), side=str(data.sides[i]),
                        entry_epoch=str(data.starts[i]), y=str(data.y[i]), temporal='.4', constant='.5') for i in rows]
        evaluation = dict(identity_sha256=identity_hash(data, rows), scores={
            'temporal': old.score(data.y[rows], np.full(10, .4)),
            'constant': old.score(data.y[rows], np.full(10, .5))})
        self.assertEqual(len(aligned_controls(data, rows, records, evaluation)['constant']), 10)
        for altered in (records[::-1], [dict(r, y=str(1-int(r['y']))) for r in records],
                        [dict(r, temporal='.3') for r in records]):
            with self.assertRaises(ValueError):
                aligned_controls(data, rows, altered, evaluation)

    def test_all_phases_pairing_and_twelve_unique_fits(self):
        data, masks, obs, protocol, _ = synthetic()
        spec, _ = load_contract()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root/'prior'
            prior.mkdir()
            ledger = FitLedger(root/'old-ledger.jsonl')
            ledger.initialize(0, {'synthetic': True})
            ledger.start_run(old.EXPERIMENT, 24, {'synthetic': True}, independent_failures=True)
            historical = dict(input_hashes={'synthetic': True}, folds=old.run_models(data, masks, obs, protocol, ledger, {}, prior))
            grouped = {}
            with (prior/'predictions.csv').open() as stream:
                for row in csv.DictReader(stream):
                    grouped.setdefault((row['fold'], row['phase'], row['universe']), []).append(row)
            controls = validate_controls(data, masks, protocol, historical, grouped, {'synthetic': True})
            ledger = ledger_at(root)
            reports = run_models(data, masks, protocol, spec, ledger, {}, controls, historical, root)
            self.assertEqual(ledger.consumed(), 12)
            for index, report in enumerate(reports):
                for phase in ('inner', 'refit'):
                    fits = report['phases'][phase]['fits']
                    self.assertTrue(all(f['reused'] == (phase == 'inner' and index > 0) for f in fits.values()))
                    for universe, evaluation in report['phases'][phase]['evaluations'].items():
                        self.assertEqual(len(evaluation['scores']), 3 if universe == 'temporal' else 5)
                        self.assertTrue(all(s['support'] == evaluation['support'] for s in evaluation['scores'].values()))
            json.dumps(reports, allow_nan=False)
            result = conclusion(reports, ['temporal', *masks])
            self.assertFalse(result['profit_claim'])
            self.assertEqual(result['initialization_scope'], 'seed_0_only')
            reports[0]['phases']['refit']['evaluations']['temporal']['scores']['mlp_temporal'] = None
            self.assertEqual(conclusion(reports, ['temporal'])['descriptive']['temporal']['mlp_temporal-vs-constant'],
                             'technically_unavailable_comparison')

    def test_conclusion_negative_undefined_and_brier_rule(self):
        def reports(losses, briers):
            return [{'phases': {'refit': {'evaluations': {'temporal': {'scores': {
                'mlp_temporal': {'log_loss': ll, 'brier': b},
                'logistic_temporal': {'log_loss': .5, 'brier': .2},
                'constant': {'log_loss': .5, 'brier': .2}}}}}}} for ll, b in zip(losses, briers)]
        def verdict(rows):
            return conclusion(rows, ['temporal'])['descriptive']['temporal']['mlp_temporal-vs-constant']
        self.assertEqual(verdict(reports([.4]*3, [.19]*3)), 'consistent_descriptive_gain')
        self.assertEqual(verdict(reports([.4, .5, .4], [.19]*3)), 'mixed_or_unfavorable_predictive_result')
        self.assertEqual(verdict(reports([.4]*3, [.21]*3)), 'mixed_or_unfavorable_predictive_result')
        self.assertEqual(verdict(reports([None, .4, .4], [.19]*3)), 'inconclusive_undefined_metrics')

    def test_published_evidence_budget_aliases_and_prior_prefix(self):
        from fxnn.cusum_evidence import export_evidence, verify_ledger
        from fxnn.data_audit import digest
        root = Path(__file__).resolve().parents[1]/'docs/experiments'
        manifest = json.loads((root/'mlp-cusum-v1-evidence.json').read_text())
        for name, expected in manifest['files'].items():
            self.assertEqual(digest(root/name), expected)
        raw = (root/'mlp-cusum-v1-ledger.jsonl').read_bytes()
        self.assertTrue(raw.startswith((root/'cusum-temporal-v2-ledger.jsonl').read_bytes()))
        records = verify_ledger(raw)
        fits = [r for r in records if r['kind'] == 'fit_started' and r['experiment'] == EXPERIMENT]
        self.assertEqual(len(fits), 12)
        self.assertEqual(len({r['hashes']['training_contract']['sha256'] for r in fits}), 12)
        self.assertEqual(records[-1]['consumed_total'], 36)
        report = json.loads((root/'mlp-cusum-v1.json').read_text())
        self.assertEqual(report['conclusion'], conclusion(report['folds'], ['temporal', '0.0005', '0.001']))
        self.assertEqual(report['years'], [2022, 2023])
        self.assertFalse(report['confirmation_opened'])
        aliases = [f for r in report['folds'] for p in r['phases'].values() for f in p['fits'].values() if f['reused']]
        self.assertEqual(len(aliases), 6)
        for alias in aliases:
            original = next(f for f in fits if f['fit_id'] == alias['fit_id'])
            self.assertEqual(alias['contract'], original['hashes']['training_contract'])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(export_evidence(root/'mlp-cusum-v1.json', root/'mlp-cusum-v1-ledger.jsonl', tmp, EXPERIMENT), manifest)

    def test_control_artifact_and_ledger_guards_without_market_data(self):
        import shutil
        from fxnn.cusum_evidence import verify_ledger
        from fxnn.data_audit import digest
        from fxnn.fit_ledger import _hash
        from fxnn import mlp_comparison as module
        spec, _ = load_contract()
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ('fxnn', 'configs', 'docs/experiments', 'controls'):
                (root/folder).mkdir(parents=True, exist_ok=True)
            for name in ('cusum.py', 'cusum_continuation.py', 'cusum_research.py', 'data_audit.py',
                         'features.py', 'indexed.py', 'labeling.py', 'protocol.py', 'research.py', 'temporal.py'):
                shutil.copy(source/'fxnn'/name, root/'fxnn'/name)
            for name in ('configs/cusum_temporal_v2.json', 'docs/experiments/cusum-temporal-v2-protocol.md'):
                shutil.copy(source/name, root/name)
            control = root/'controls'
            predictions = control/'predictions.csv'
            predictions.write_text('fold,phase,universe,entry_index,side,entry_epoch,y,temporal,constant,cusum\n')
            report = json.loads((source/'docs/experiments/cusum-temporal-v2.json').read_text())
            report['versions'] = module.versions()  # Synthetic fixture follows its runtime.
            report['predictions_sha256'] = digest(predictions)
            report_path = control/'report.json'
            report_path.write_text(json.dumps(report))
            shutil.copy(report_path, root/'docs/experiments/cusum-temporal-v2.json')
            spec = {**spec, 'controls_report_sha256': digest(report_path),
                    'controls_predictions_sha256': digest(predictions)}
            ledger = FitLedger(root/'ledger.jsonl')
            ledger.initialize(0, {'synthetic': True})
            missing = ledger.path.read_bytes()
            ledger.start_run(old.EXPERIMENT, 24, {'synthetic': True})
            ledger.finish_run(old.EXPERIMENT, 'completed', {'report_sha256': digest(report_path)})
            raw = ledger.path.read_bytes()
            records = verify_ledger(raw)
            duplicate = {**records[-1], 'sequence': len(records), 'previous': records[-1]['sha256']}
            duplicate.pop('sha256')
            duplicate['sha256'] = _hash(duplicate)
            duplicated = raw + (json.dumps(duplicate)+'\n').encode()
            with patch.object(module, 'ROOT', root):
                self.assertEqual(module.load_controls(control, spec, raw)[0], report)
                with patch.object(module, 'versions', return_value={**report['versions'], 'python': 'mismatch'}):
                    with self.assertRaisesRegex(ValueError, 'Control versions or predictions changed'):
                        module.load_controls(control, spec, raw)
                for invalid in (missing, duplicated):
                    with self.assertRaisesRegex(ValueError, 'linked to canonical ledger'):
                        module.load_controls(control, spec, invalid)
                predictions.write_text('tampered\n')
                with self.assertRaisesRegex(ValueError, 'artifact hash mismatch'):
                    module.load_controls(control, spec, raw)
                changed_spec = {**spec, 'controls_predictions_sha256': digest(predictions)}
                with self.assertRaisesRegex(ValueError, 'Control versions or predictions changed'):
                    module.load_controls(control, changed_spec, raw)
