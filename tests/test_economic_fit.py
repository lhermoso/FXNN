"""Synthetic stage9 weighted fitting and readonly replay contracts."""
import unittest
import numpy as np
from fxnn.economic_fit import training_weights
from fxnn.economic_clock import SessionClockMs


class WeightTests(unittest.TestCase):
    def test_independent_dense_overlap_oracle(self):
        clock = SessionClockMs(0, 100, [(0, 100)])
        starts = np.array([0, 2, 3, 10, 0, 12])
        ends = np.array([10, 5, 12, 15, 10, 20])
        occupied = (np.arange(20)[None, :] >= starts[:, None]) & (np.arange(20)[None, :] < ends[:, None])
        concurrency = occupied.sum(axis=0)
        reciprocal = np.divide(1., concurrency, out=np.zeros(20), where=concurrency > 0)
        raw = (occupied * reciprocal).sum(axis=1) / occupied.sum(axis=1)
        weights, report = training_weights(starts, ends, clock)
        np.testing.assert_allclose(weights, raw / raw.mean(), rtol=1e-12, atol=1e-14)
        self.assertEqual(report['rows'], 6)



import copy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from fxnn import economic_fit as fit
from fxnn.economic_lifecycle import Lifecycle, fingerprint
from fxnn.fit_ledger import FitLedger
from fxnn.tick_economic_source import EventKey, Hazard

PARAMETERS = dict(C=1., class_weight=None, dual=False, fit_intercept=True,
                  intercept_scaling=1, l1_ratio=0., max_iter=1000, n_jobs=None,
                  penalty='deprecated', random_state=0, solver='lbfgs', tol=.0001,
                  verbose=0, warm_start=False)
MINUTE = 60000


def fixture():
    minutes = np.array([10, 20, 30, 100, 500, 1100, 2100, 3100, 4100, 5100, 6100, 6500])
    decisions = minutes*MINUTE
    n = len(decisions)
    X = np.arange(n*28, dtype=float).reshape(n, 28)/31
    X[:, ::2] = np.sin(X[:, ::2])
    flags = np.ones(n, dtype=bool)
    bars = np.arange(0, 8000)*MINUTE
    data = fit.EconomicMatrix(decisions, X, np.where(np.arange(n) % 2, -1, 1).astype(np.int8),
        flags.copy(), flags.copy(), flags.copy(), flags.copy(),
        (np.arange(n) % 2).astype(np.int8), decisions+1, decisions+20001,
        decisions+40*MINUTE, decisions-5*MINUTE, bars, bars+MINUTE, (), {'synthetic': 'fixed'})
    phases = []
    for i, (cutoff, right) in enumerate(((3000,4000), (4000,5000), (4000,5000),
                                        (5000,6000), (5000,6000), (6000,7000))):
        phases.append({'name': f'phase{i}', 'cutoff_ms': cutoff*MINUTE,
                       'evaluation_start_ms': cutoff*MINUTE, 'evaluation_end_ms': right*MINUTE})
    phases.append({'name': 'final', 'cutoff_ms': 7000*MINUTE,
                   'evaluation_start_ms': None, 'evaluation_end_ms': None})
    return data, phases, SessionClockMs(0, 9000*MINUTE, [(0, 9000*MINUTE)])


class ProductionFitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='economic-fit-synthetic-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data, self.phases, self.clock = fixture()
        self.ledger = self.root/'ledger.jsonl'
        FitLedger(self.ledger).initialize(0, {'synthetic': True})
        source = self.root/'scientific-code'; source.write_text('fixture fixed scientific source')
        self.lifecycle = Lifecycle(self.ledger)
        self.lifecycle.reserve(0, fingerprint(self.ledger)['sha256'], {'source': fingerprint(source)},
                               {'synthetic': True, 'model_phases':self.phases,
                                'logistic':PARAMETERS, 'versions':fit.runtime()},
                               fit.slots(self.phases), independent_failures=True)

    def test_reserved_dates_and_parameters_cannot_change_before_fit(self):
        for changed_phases,params in [(copy.deepcopy(self.phases),dict(PARAMETERS,C=2)),
                                     (copy.deepcopy(self.phases),PARAMETERS)]:
            if params==PARAMETERS:changed_phases[0]['cutoff_ms']+=MINUTE
            before=self.ledger.read_bytes()
            with self.assertRaisesRegex(ValueError,'reserved configuration'):
                fit.run_phases(self.data,self.clock,changed_phases,params,fit.runtime(),
                               self.lifecycle,self.root/'invalid')
            self.assertEqual(self.ledger.read_bytes(),before)
            self.assertFalse((self.root/'invalid').exists())

    def fitted(self, family='logistic', slot=None, data=None):
        data = self.data if data is None else data
        rows, _ = fit.admit(data, self.phases[0]['cutoff_ms'])
        weights, info = fit.training_weights(data.entry_ms[rows], data.information_end_ms[rows], self.clock)
        return fit.fit_model(data, rows, weights, info, family, PARAMETERS, self.lifecycle,
                             slot or self.phases[0]['name']+':'+family, 'synthetic', self.root/'models')

    def starts(self):
        return sum(r['kind'] == 'fit_started' for r in FitLedger(self.ledger).records())

    def test_weighted_scaler_actual_state_training_only_and_exact_alias(self):
        self.data.information_end_ms[0] = 25*MINUTE
        self.data.information_end_ms[1] = 35*MINUTE
        state, report = self.fitted()
        rows, _ = fit.admit(self.data, self.phases[0]['cutoff_ms'])
        weights, _ = fit.training_weights(self.data.entry_ms[rows], self.data.information_end_ms[rows], self.clock)
        self.assertGreater(float(np.ptp(weights)), .1)
        np.testing.assert_allclose(state['mean'], np.average(self.data.X[rows], axis=0, weights=weights))
        before = self.ledger.read_bytes()
        alias_state, alias = self.fitted(slot='phase1:logistic')
        self.assertEqual(report, alias)
        for key in state:
            np.testing.assert_array_equal(state[key], alias_state[key])
        self.assertEqual(before, self.ledger.read_bytes())
        self.assertEqual(self.starts(), 1)

    def test_future_data_does_not_change_actual_fit_or_earlier_probabilities(self):
        state, report = self.fitted()
        changed = copy.deepcopy(self.data)
        future = changed.decision_ms >= self.phases[0]['cutoff_ms']
        changed.X[future] += 10000
        changed.y[future] = 1-changed.y[future]
        changed.information_end_ms[future] += 100000
        changed.hazards = (Hazard(EventKey(self.phases[0]['cutoff_ms'], 4, 0), 'timestamp_regression',
                                  'later', 0, 4000*MINUTE),)
        rows, audit = fit.admit(changed, self.phases[0]['cutoff_ms'])
        original_rows, original_audit = fit.admit(self.data, self.phases[0]['cutoff_ms'])
        np.testing.assert_array_equal(rows, original_rows)
        self.assertEqual(audit, original_audit)
        # A distinct temporary canonical supervisor actually fits the altered data.
        other_root = self.root/'other'; other_root.mkdir()
        other_ledger = other_root/'ledger.jsonl'; FitLedger(other_ledger).initialize(0, {'synthetic': True})
        other = Lifecycle(other_ledger)
        other.reserve(0, fingerprint(other_ledger)['sha256'], self.lifecycle.read()['files'],
                      {'synthetic': True}, fit.slots(self.phases), independent_failures=True)
        w, info = fit.training_weights(changed.entry_ms[rows], changed.information_end_ms[rows], self.clock)
        state2, report2 = fit.fit_model(changed, rows, w, info, 'logistic', PARAMETERS, other,
                                       'phase0:logistic', 'synthetic', other_root/'models')
        self.assertEqual(report['contract'], report2['contract'])
        for key in state:
            np.testing.assert_array_equal(state[key], state2[key])
        earlier = {'evaluation_start_ms': 0, 'evaluation_end_ms': self.phases[0]['cutoff_ms']}
        a, m = fit.phase_predictions(self.data, state, earlier)
        b, n = fit.phase_predictions(changed, state2, earlier)
        self.assertEqual(m, n)
        for key in a:
            np.testing.assert_array_equal(a[key], b[key])

    def test_single_class_no_floor_constant_is_available_logistic_is_not(self):
        self.data.y[:] = 0
        state, report = self.fitted('constant')
        self.assertEqual(float(state['prior']), 0.)
        state, report = self.fitted('logistic')
        self.assertIsNone(state)
        self.assertEqual(report['reason'], 'logistic_requires_two_classes')
        self.assertEqual(self.starts(), 1)
        self.data.bar_starts = np.empty(0, dtype=np.int64)
        self.data.bar_ends = np.empty(0, dtype=np.int64)
        state, report = self.fitted('constant')
        self.assertIsNone(state)
        self.assertEqual(report['reason'], 'empty_training')
        self.assertEqual(self.starts(), 1)

    def test_no_arbitrary_minimum_two_rows_logistic(self):
        self.data.information_cap_ms[2:] = self.phases[0]['cutoff_ms']
        state, report = self.fitted('logistic')
        self.assertEqual(report['support']['rows'], 2)
        self.assertEqual(report['status'], 'succeeded')
        self.assertIsNotNone(state)

    def test_cached_hash_failure_is_not_a_cache_miss_or_retry(self):
        _, report = self.fitted()
        snapshot = self.lifecycle.read()
        record = next(iter(snapshot['fits'].values()))
        path = Path(record['result']['artifacts']['model']['path'])
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.fitted(slot='phase1:logistic')
        self.assertEqual(self.starts(), 1)

    def test_convergence_failure_consumes_fit_and_alias_never_retries(self):
        with patch.object(fit.LogisticRegression, 'fit', side_effect=fit.ConvergenceWarning('fixture')):
            state, report = self.fitted()
        self.assertIsNone(state)
        self.assertEqual(report['status'], 'failed')
        with patch.object(fit.LogisticRegression, 'fit', side_effect=AssertionError('retry')):
            _, alias = self.fitted(slot='phase1:logistic')
        self.assertEqual(alias, report)
        self.assertEqual(self.starts(), 1)
        self.fitted('constant')
        self.assertEqual(self.starts(), 2)

    def test_export_failure_poison_survives_new_output(self):
        with patch.object(fit, 'durable_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.fitted()
        self.assertTrue(self.lifecycle.read()['poison'])
        with self.assertRaises(ValueError):
            self.fitted('constant')
        self.assertEqual(self.starts(), 1)

    def test_near_end_unfilled_censored_keep_probability_absence_separate(self):
        phase = self.phases[0]
        row = 7
        self.data.y[row] = -1
        self.data.information_end_ms[row] = fit.MISSING
        self.data.calendar_eligible[row] = False
        self.data.eligible[row] = False
        state = {'kind': np.asarray('constant'), 'prior': np.asarray(.75)}
        arrays, report = fit.phase_predictions(self.data, state, phase)
        self.assertEqual(arrays['source_rows'].tolist(), [row])
        self.assertEqual(arrays['probability'].tolist(), [.75])
        self.assertEqual(arrays['accepted'].tolist(), [1])
        self.assertEqual(report['metric_rows'], 0)
        missing, summary = fit.phase_predictions(self.data, None, phase)
        self.assertTrue(np.isnan(missing['probability'][0]))
        self.assertEqual(missing['accepted'].tolist(), [-1])
        self.assertEqual(missing['absence_reason'].tolist(), [fit.REASONS['model_unavailable']])
        self.data.side[row] = 0
        arrays, _ = fit.phase_predictions(self.data, state, phase)
        self.assertEqual(arrays['absence_reason'].tolist(), [fit.REASONS['no_primary_signal']])

    def test_metric_boundary_information_end_equality(self):
        state = {'kind': np.asarray('constant'), 'prior': np.asarray(.5)}
        row = 7
        self.data.information_end_ms[row] = self.phases[0]['evaluation_end_ms']
        _, report = fit.phase_predictions(self.data, state, self.phases[0])
        self.assertEqual(report['metric_rows'], 1)
        self.data.information_end_ms[row] += 1
        arrays, report = fit.phase_predictions(self.data, state, self.phases[0])
        self.assertEqual(report['metric_rows'], 0)
        self.assertEqual(arrays['accepted'].tolist(), [1])

    def test_complete_development_final_readonly_replay_ten_fits_one_open_run(self):
        report, artifacts = fit.run_phases(self.data, self.clock, self.phases, PARAMETERS, fit.runtime(),
                                          self.lifecycle, self.root/'development')
        self.assertEqual(self.starts(), 8)
        final, final_artifacts = fit.run_phases(self.data, self.clock, self.phases, PARAMETERS, fit.runtime(),
                                               self.lifecycle, self.root/'final', final=True)
        self.assertEqual(self.starts(), 10)
        before = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        with patch.object(fit.LogisticRegression, 'fit', side_effect=AssertionError('replay fit')):
            self.assertEqual(report, fit.verify_phases(self.data, self.clock, self.phases, PARAMETERS,
                             fit.runtime(), self.lifecycle, artifacts['report']))
            self.assertEqual(final, fit.verify_phases(self.data, self.clock, self.phases, PARAMETERS,
                             fit.runtime(), self.lifecycle, final_artifacts['report']))
        after = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        records = FitLedger(self.ledger).records()
        self.assertEqual(sum(r['kind'] == 'run_started' for r in records), 1)
        self.assertFalse(any(r['kind'] == 'run_finished' for r in records))
        self.assertFalse(self.lifecycle.read()['sealed'])
        self.assertEqual([c['phase'] for c in self.lifecycle.read()['checkpoints']],
                         ['DEVELOPMENT_VERIFIED', 'FINAL_MODELS_VERIFIED'])

    def test_prediction_storage_failure_poison_no_subsequent_fit(self):
        with patch.object(fit, 'durable_arrays', side_effect=OSError('prediction fsync')):
            with self.assertRaises(OSError):
                fit.run_phases(self.data, self.clock, self.phases, PARAMETERS, fit.runtime(),
                               self.lifecycle, self.root/'development')
        self.assertEqual(self.starts(), 1)
        self.assertTrue(self.lifecycle.read()['poison'])
        with self.assertRaises(ValueError):
            self.fitted('logistic')

    def test_final_report_failure_poison(self):
        original = fit.durable_json
        def fail_report(path, value):
            if Path(path).name == 'report.json':
                raise OSError('report failed')
            return original(path, value)
        with patch.object(fit, 'durable_json', side_effect=fail_report):
            with self.assertRaises(OSError):
                fit.run_phases(self.data, self.clock, self.phases, PARAMETERS, fit.runtime(),
                               self.lifecycle, self.root/'development')
        self.assertEqual(self.starts(), 8)
        self.assertTrue(self.lifecycle.read()['poison'])

    def test_checkpoint_failure_poison_retains_successful_terminals(self):
        with patch.object(self.lifecycle, 'clean_checkpoint', side_effect=OSError('checkpoint fsync')):
            with self.assertRaises(OSError):
                fit.run_phases(self.data, self.clock, self.phases, PARAMETERS, fit.runtime(),
                               self.lifecycle, self.root/'development')
        self.assertEqual(self.starts(), 8)
        self.assertTrue(self.lifecycle.read()['poison'])
        self.assertTrue(all(f['status'] == 'succeeded' for f in self.lifecycle.read()['fits'].values()))

    def test_metadata_storage_failure_keeps_orphan_unusable(self):
        original = fit.durable_json
        def metadata_failure(path, value):
            if Path(path).name == 'metadata.json':
                raise OSError('metadata fsync')
            return original(path, value)
        with patch.object(fit, 'durable_json', side_effect=metadata_failure):
            with self.assertRaises(OSError):
                self.fitted()
        self.assertEqual(len(list((self.root/'models').glob('*/model.json'))), 1)
        self.assertTrue(self.lifecycle.read()['poison'])
        with self.assertRaisesRegex(ValueError, 'Pending'):
            self.fitted(slot='phase1:logistic')
        self.assertEqual(self.starts(), 1)

    def test_scaler_numerical_failure_terminal_and_failed_cache_validated(self):
        with patch.object(fit.StandardScaler, 'fit', side_effect=ValueError('synthetic numeric')):
            _, report = self.fitted()
        self.assertEqual(report['status'], 'failed')
        # Tampering with supervisor result while maintaining envelope hash must
        # still fail against the authoritative ledger terminal.
        from fxnn.economic_lifecycle import identity
        envelope = json.loads(self.lifecycle.state_path.read_text())
        record = next(iter(envelope['state']['fits'].values()))
        record['result']['diagnostics']['reason'] = 'altered'
        envelope['sha256'] = identity(envelope['state'])
        self.lifecycle.state_path.write_text(json.dumps(envelope))
        with self.assertRaisesRegex(ValueError, 'terminal mismatch'):
            self.fitted(slot='phase1:logistic')
        self.assertEqual(self.starts(), 1)

    def test_start_and_finish_failure_poison_without_subsequent_fit(self):
        from fxnn.bound_ledger import BoundStageLedger
        # Each isolated temporary supervisor exercises a different boundary.
        for method in ('start_fit', 'finish_fit'):
            with self.subTest(method=method), tempfile.TemporaryDirectory(prefix='fit-terminal-fault-') as directory:
                root = Path(directory)
                ledger = root/'ledger.jsonl'; FitLedger(ledger).initialize(0, {'synthetic': True})
                lifecycle = Lifecycle(ledger)
                lifecycle.reserve(0, fingerprint(ledger)['sha256'], self.lifecycle.read()['files'],
                                  {'synthetic': True}, fit.slots(self.phases), independent_failures=True)
                rows, _ = fit.admit(self.data, self.phases[0]['cutoff_ms'])
                w, info = fit.training_weights(self.data.entry_ms[rows], self.data.information_end_ms[rows], self.clock)
                with patch.object(BoundStageLedger, method, side_effect=OSError('ledger fsync')):
                    with self.assertRaises(OSError):
                        fit.fit_model(self.data, rows, w, info, 'logistic', PARAMETERS, lifecycle,
                                      'phase0:logistic', 'synthetic', root/'models')
                self.assertTrue(lifecycle.read()['poison'])
                with self.assertRaises(ValueError):
                    fit.fit_model(self.data, rows, w, info, 'constant', PARAMETERS, lifecycle,
                                  'phase0:constant', 'synthetic', root/'other')

    def test_readonly_prediction_corruption_rejected_without_fit_or_state_write(self):
        _, artifacts = fit.run_phases(self.data, self.clock, self.phases, PARAMETERS, fit.runtime(),
                                     self.lifecycle, self.root/'development')
        prediction = next(value for key, value in artifacts.items() if key != 'report')
        Path(prediction['path']).write_bytes(b'corrupt')
        before = self.lifecycle.state_path.read_bytes(), self.ledger.read_bytes()
        with patch.object(fit.LogisticRegression, 'fit', side_effect=AssertionError('replay fit')):
            with self.assertRaisesRegex(ValueError, 'identity'):
                fit.verify_phases(self.data, self.clock, self.phases, PARAMETERS, fit.runtime(),
                                  self.lifecycle, artifacts['report'])
        self.assertEqual(before, (self.lifecycle.state_path.read_bytes(), self.ledger.read_bytes()))



class AdmissionAndLoaderTests(unittest.TestCase):
    def test_taint_disclosure_strict_before_clock_and_full_history(self):
        data, phases, _ = fixture()
        cutoff = phases[0]['cutoff_ms']
        original, _ = fit.admit(data, cutoff)
        data.hazards = (Hazard(EventKey(cutoff, 4, 0), 'timestamp_regression', 'source', 0, 200*MINUTE),)
        equal, _ = fit.admit(data, cutoff)
        np.testing.assert_array_equal(original, equal)
        data.hazards = (Hazard(EventKey(cutoff-1, 4, 0), 'timestamp_regression', 'source', 0, 200*MINUTE),)
        excluded, report = fit.admit(data, cutoff)
        self.assertEqual(excluded.tolist(), [4])
        self.assertEqual(report['counts']['integrity_disclosed_before_cutoff'], 4)

    def test_buffer_excludes_bar_ending_exactly_at_cutoff(self):
        data, phases, _ = fixture()
        cutoff = phases[0]['cutoff_ms']
        _, audit = fit.admit(data, cutoff)
        self.assertEqual(audit['buffer_start_ms'], (3000-1-1941)*MINUTE)
        data.information_cap_ms[0] = audit['buffer_start_ms']
        rows, _ = fit.admit(data, cutoff)
        self.assertNotIn(0, rows)
        data.information_cap_ms[0] -= 1
        rows, _ = fit.admit(data, cutoff)
        self.assertIn(0, rows)

    def test_weekend_millisecond_weights_use_scheduled_open_time(self):
        clock = SessionClockMs(0, 10000, [(0, 1000), (9000, 10000)])
        starts, ends = np.array([900, 950]), np.array([9050, 9100])
        weights, info = fit.training_weights(starts, ends, clock)
        # Both150openms; overlap100openms gives equal raw uniqueness2/3.
        np.testing.assert_array_equal(weights, [1., 1.])
        self.assertAlmostEqual(info['raw_mean'], 2/3)

    def test_loader_strict_aligned_stream_and_mutated_file_hash(self):
        with tempfile.TemporaryDirectory(prefix='economic-matrix-synthetic-') as directory:
            root = Path(directory)
            ops, labels, bars = (root/name for name in ('opportunities.jsonl', 'labels.jsonl', 'bars.jsonl'))
            op = {'id': 'economic_ticks_v1:600000', 'decision_ms': 600000, 'side': 1,
                  'X': [0.]*28, 'feature_valid': True, 'volatility_valid': True,
                  'eligible': False, 'calendar_eligible': False, 'earliest_input': 0, 'information_cap_ms': None}
            label = {'opportunity_id': op['id'], 'label': None, 'entry_ms': None,
                     'information_end_ms': None, 'information_cap_ms': None, 'earliest_input_ms': 0}
            ops.write_text(json.dumps(op)+'\n'); labels.write_text(json.dumps(label)+'\n')
            bars.write_text(json.dumps({'start': 0, 'end': 60000, 'valid': True})+'\n')
            manifest = {p.name: fingerprint(p) for p in (ops, labels, bars)}
            matrix = fit.load_matrix(ops, labels, bars, manifest, (), {'fixture': True})
            self.assertEqual(matrix.X.shape, (1, 28))
            self.assertEqual(matrix.y.tolist(), [-1])
            self.assertFalse(matrix.eligible[0])
            labels.write_text(json.dumps({**label, 'opportunity_id': 'wrong'})+'\n')
            with self.assertRaisesRegex(ValueError, 'identity'):
                fit.load_matrix(ops, labels, bars, manifest, (), {'fixture': True})
            manifest[labels.name] = fingerprint(labels)
            with self.assertRaisesRegex(ValueError, 'identities'):
                fit.load_matrix(ops, labels, bars, manifest, (), {'fixture': True})


if __name__ == "__main__":
    unittest.main()
