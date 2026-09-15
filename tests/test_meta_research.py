from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from fxnn import meta_research as runner
from fxnn.experiment_fit import StageLedger
from fxnn.meta_dataset import project
from fxnn.meta_primary import choose_threshold
from fxnn.protocol import utc_epoch
from fxnn.research import Dataset
from fxnn.session_clock import weekly_fx_clock
from test_meta_dataset import source_fixture


class MetaOpportunityTests(unittest.TestCase):
    def test_all_opportunities_and_missing_calibration_keep_probabilities(self):
        observed, candidates, schema, selected = source_fixture()
        _, op, _ = project(observed, candidates, schema)
        state = dict(kind=np.array('constant'), prior=np.array(.6))
        models = dict(constant=state, logistic=state)
        metric_openings = selected[:1]  # Near-end G remains operational, not diagnostic.
        missing = choose_threshold(np.zeros(3, int), np.array([.2, .4, .6]), 'Q2')
        saved, report = runner.phase_evaluation(op, selected, metric_openings, '0.0005', models,
                                               {name: missing for name in models})
        np.testing.assert_array_equal(saved['operational_eligible'], [1, 1, 0, 0, 0, 1, 1, 1])
        self.assertEqual(saved['logistic_probability_available'].sum(), 5)
        np.testing.assert_array_equal(saved['logistic_accepted'], np.full(8, -1))
        self.assertIsNone(report['coverage']['models']['logistic']['accepted'])
        self.assertEqual(report['coverage']['primary_accepted'], 5)
        self.assertFalse(report['selected_decision_scores']['logistic']['available'])
        self.assertEqual(report['support']['rows'], 1)
        self.assertEqual(report['threshold_diagnostics']['logistic']['0.5']['f1'], 1.)
        self.assertIsNone(report['selections']['logistic']['threshold'])
        changed = dict(op, outcomes=np.full(len(op['starts']), 'stop_loss'))
        other, _ = runner.phase_evaluation(changed, selected, metric_openings, '0.0005', models,
                                           {name: missing for name in models})
        np.testing.assert_array_equal(saved['logistic_probability'], other['logistic_probability'])
        np.testing.assert_array_equal(saved['logistic_accepted'], other['logistic_accepted'])
        available = choose_threshold(np.array([1, 0]), np.array([.8, .1]), 'Q1')
        active, _ = runner.phase_evaluation(op, selected, metric_openings, '0.0005', models,
                                           {name: available for name in models})
        np.testing.assert_array_equal(active['logistic_accepted'], [1, 1, -1, -1, -1, 1, 1, 1])


class MetaRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.output = self.root/'result'
        self.path = self.root/'ledger'
        self.ledger = StageLedger(self.path, 7); self.ledger.initialize(0, 'synthetic')
        self.before = self.path.read_bytes()
        begin = utc_epoch('2023-01-02T00:00:00+00:00')
        starts = begin+np.arange(80)*60
        self.clock = weekly_fx_clock(begin-86400, begin+86400)
        X = np.column_stack((np.sin(np.arange(80)), np.ones(80)))
        y = np.arange(80) % 2
        op = dict(X=X, starts=starts, entry_indices=np.arange(80), side=np.ones(80, np.int8),
                  causal_valid=np.ones(80, bool), primary_reason=np.full(80, 'signal'), causal_reason=np.full(80, 'eligible'),
                  outcomes=np.where(y, 'take_profit', 'stop_loss'), **{f'cusum_{h}': np.ones(80, bool) for h in (.0005, .001)})
        data = Dataset(X, y, starts, starts+60, starts+120, np.arange(80), np.ones(80, np.int8), ['a', 'direction'], {'a': [0]}, 0)
        def date(index):
            from datetime import datetime, timezone
            return datetime.fromtimestamp(int(starts[index]), timezone.utc).isoformat()
        self.protocol = {'folds': [dict(name=f'Q{i}', validation_start=date(35), test_start=date(45), test_end=date(75)) for i in (2, 3, 4)]}
        parts = {f'Q{i}': dict(train=np.arange(20), refit=np.arange(30), validation=np.arange(35, 43), test=np.arange(45, 73)) for i in (2, 3, 4)}
        self.bundle = dict(data=data, opportunities=op, opening_rows=np.arange(80), partitions=parts,
                           masks={str(h): np.ones(80, bool) for h in (.0005, .001)})
        self.spec = dict(global_ledger=str(self.path), expected_prior_fits=0,
            ledger_before_sha256=hashlib.sha256(self.before).hexdigest(), max_model_fits=24,
            thresholds=[.0005, .001], logistic={'C': 1., 'random_state': 0, 'max_iter': 1000})
        self.hashes = {'fixture': 'synthetic'}

    def execute(self):
        with redirect_stdout(io.StringIO()):
            return runner.execute(self.bundle, self.protocol, self.spec, self.clock, self.hashes, self.output)

    def test_execute_and_exact_replay_with_no_fit(self):
        report = self.execute()
        self.assertEqual(report['new_fits'], 4)
        raw = self.path.read_bytes()
        with patch.object(runner, 'fit_cached', side_effect=AssertionError('Replay must not fit')):
            replay = runner.run_models(self.bundle, self.protocol, self.spec, self.clock, self.ledger,
                                       self.hashes, self.output, replay=report['folds'], prefix=self.before)
        self.assertEqual(replay, report['folds'])
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual({r['stage'] for r in self.ledger.records() if r['kind'] == 'fit_started'}, {7})
        path = self.output/'Q2_inner_temporal.json'
        value = json.loads(path.read_text())
        value['evaluation']['selections']['logistic']['threshold'] = .3
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'Thresholds'):
            runner.run_models(self.bundle, self.protocol, self.spec, self.clock, self.ledger,
                              self.hashes, self.output, replay=report['folds'], prefix=self.before)

    def test_external_mutation_preserves_fitted_states_and_inner_selection(self):
        first = self.execute()
        first_output = self.output
        # Only external values change. Training/refit and inner validation are
        # untouched; this exercises actual fit orchestration, not fixed-model inference.
        self.bundle['data'].X[45:] *= 17
        self.bundle['data'].y[45:] = 1-self.bundle['data'].y[45:]
        self.bundle['opportunities']['outcomes'][45:] = np.where(
            self.bundle['data'].y[45:], 'take_profit', 'stop_loss')
        self.path = self.root/'second-ledger'
        self.ledger = StageLedger(self.path, 7); self.ledger.initialize(0, 'synthetic mutation')
        self.spec = dict(self.spec, global_ledger=str(self.path),
            ledger_before_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.output = self.root/'second-result'
        second = self.execute()
        for a, b in zip(first['folds'], second['folds']):
            for phase in ('inner', 'refit'):
                for population in ('temporal', '0.0005', '0.001'):
                    left, right = a['phases'][phase][population], b['phases'][phase][population]
                    self.assertEqual(left['evaluation']['selections'], right['evaluation']['selections'])
                    for family in ('constant', 'logistic'):
                        lf, rf = left['fits'][family], right['fits'][family]
                        self.assertEqual(lf['contract'], rf['contract'])
                        with np.load(first_output/lf['model_file'], allow_pickle=False) as old, \
                                np.load(self.output/rf['model_file'], allow_pickle=False) as new:
                            for key in old.files:
                                np.testing.assert_array_equal(old[key], new[key])
                    if phase == 'inner':
                        self.assertEqual(left['evaluation'], right['evaluation'])

    def test_atomic_execute_wiring_rejects_intervening_zero_fit_run(self):
        original = runner.write_json
        def race(path, value):
            original(path, value)
            if path.name == 'run.json':
                other = StageLedger(self.path, 9)
                other.start_run('intervening', 1, {'fixture': 1})
                other.finish_run('intervening', 'completed', {})
        with patch.object(runner, 'write_json', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'Frozen ledger'):
                self.execute()
        self.assertFalse(any(r.get('experiment') == runner.EXPERIMENT for r in self.ledger.records()))
        self.assertEqual(self.ledger.consumed(), 0)

    def test_opportunity_and_final_report_failures_abort(self):
        with patch.object(runner, 'save_arrays', side_effect=OSError('opportunity disk')):
            with self.assertRaisesRegex(OSError, 'opportunity disk'):
                self.execute()
        self.assertEqual(self.ledger.consumed(), 2)
        self.assertEqual(self.ledger.records()[-1]['status'], 'aborted')

    def test_threshold_json_failure_aborts_before_refit(self):
        original = runner.write_json
        def fail(path, value):
            if path.name == 'Q2_inner_temporal.json':
                raise OSError('threshold archive disk')
            original(path, value)
        with patch.object(runner, 'write_json', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'threshold archive disk'):
                self.execute()
        self.assertEqual(self.ledger.consumed(), 2)
        self.assertEqual(self.ledger.records()[-1]['status'], 'aborted')

    def test_final_report_and_failure_json_errors_still_close(self):
        original = runner.write_json
        def fail(path, value):
            if path.name == 'report.json':
                raise OSError('final report disk')
            original(path, value)
        with patch.object(runner, 'write_json', side_effect=fail):
            with patch('fxnn.experiment_fit.write_json', side_effect=lambda p, v: (_ for _ in ()).throw(OSError('failure disk')) if p.name == 'failure.json' else original(p, v)):
                with self.assertRaisesRegex(OSError, 'final report disk'):
                    self.execute()
        self.assertEqual(self.ledger.consumed(), 4)
        self.assertEqual(self.ledger.records()[-1]['status'], 'aborted')

    def test_finish_run_failure_preserves_orphan_report(self):
        from fxnn.bound_ledger import BoundStageLedger
        original = BoundStageLedger.finish_run
        def fail(ledger, experiment, status, result):
            if status == 'completed':
                raise OSError('finish run disk')
            return original(ledger, experiment, status, result)
        with patch.object(BoundStageLedger, 'finish_run', fail):
            with self.assertRaisesRegex(OSError, 'finish run disk'):
                self.execute()
        self.assertTrue((self.output/'report.json').exists())
        self.assertFalse((self.output/'ledger-after.jsonl').exists())
        self.assertEqual(self.ledger.records()[-1]['status'], 'aborted')

    def test_source_subset_allows_later_modules_but_not_frozen_edits(self):
        folder = self.root/'fxnn'; folder.mkdir()
        frozen = folder/'frozen.py'; frozen.write_text('original')
        expected = {'frozen.py': runner.digest(frozen)}
        with patch.object(runner, 'ROOT', self.root):
            runner.verify_sources(expected)
            (folder/'future.py').write_text('new stage')
            runner.verify_sources(expected)
            frozen.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'artifact changed'):
                runner.verify_sources(expected)
            with self.assertRaisesRegex(ValueError, 'module path'):
                runner.verify_sources({'../bad.py': 'a'*64})

    def test_complete_verify_and_terminal_report_binding(self):
        dataset = self.root/'dataset'; dataset.mkdir()
        (dataset/'manifest.json').write_text('{}')
        config, protocol = self.root/'config.json', self.root/'protocol.md'
        config.write_text('{}'); protocol.write_text('fixture protocol')
        self.hashes = dict(config=runner.digest(config), protocol=runner.digest(protocol),
                           source_hashes={}, dataset_manifest=runner.digest(dataset/'manifest.json'))
        self.execute()
        raw = self.path.read_bytes()
        with patch.object(runner, 'SPEC', config), patch.object(runner, 'CONTRACT', protocol), \
                patch.object(runner, 'load_bundle', return_value=(self.bundle, self.clock, {})), \
                patch.object(runner, 'fit_cached', side_effect=AssertionError('must not fit')):
            result = runner.verify(self.output, dataset, self.root/'unused', self.spec, self.protocol)
            self.assertEqual(result['model_fits'], 0)
            self.assertEqual(self.path.read_bytes(), raw)
            report_path = self.output/'report.json'
            report = json.loads(report_path.read_text()); report['new_fits'] += 1
            report_path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'authoritative completed'):
                runner.verify(self.output, dataset, self.root/'unused', self.spec, self.protocol)
