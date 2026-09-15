"""Synthetic lifecycle fault injection; no research data or canonical ledger."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from fxnn.experiment_fit import StageLedger, abort_run, fit_cached, verified_model
from fxnn.fit_ledger import FitLedger
from fxnn.research import Dataset
from fxnn.session_clock import weekly_fx_clock
from fxnn.session_models import predict_state


class ExperimentFitTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.ledger = StageLedger(self.output/'ledger.jsonl')
        self.ledger.initialize(0, 'synthetic fixture')
        self.prefix = self.ledger.path.read_bytes()
        self.ledger.start_run('synthetic', 5, {'source': 'fixture'}, independent_failures=True)
        starts = np.arange(1641214800, 1641214800+60*40, 60, dtype=np.int64)
        self.clock = weekly_fx_clock(int(starts[0])-86400, int(starts[-1])+86400)
        self.data = Dataset(X=np.column_stack((np.sin(np.arange(40)), np.arange(40)/40)),
                            y=np.arange(40) % 2, starts=starts, ends=starts+180,
                            info_ends=starts+240, entry_indices=np.arange(40),
                            sides=np.ones(40, dtype=int), names=['a', 'b'],
                            groups={'fixture': [0, 1]}, dropped_warmup=0)
        self.cache = {}

    def fit(self, family='logistic', fit_id='fit', rows=None, task='dynamic'):
        return fit_cached(self.data, np.arange(30) if rows is None else rows, family,
                          {'random_state': 7, 'max_iter': 1000} if family == 'logistic' else {},
                          self.clock, self.ledger, 'synthetic', task, fit_id, 'fold',
                          {'source': 'fixture'}, self.cache, self.output)

    def replay(self, report, **kwargs):
        return verified_model(report, self.output, self.ledger, 'synthetic',
                              hashes={'source': 'fixture'}, ledger_prefix=self.prefix, **kwargs)

    def test_success_cache_stage_and_prediction_replay(self):
        state, report = self.fit()
        alias, reuse = self.fit(fit_id='alias')
        self.assertIs(state, alias)
        self.assertTrue(reuse['reused'])
        self.assertEqual(self.ledger.consumed(), 1)
        record = next(r for r in self.ledger.records() if r['kind'] == 'fit_started')
        self.assertEqual((record['stage'], record['seed']), (6, 7))
        self.assertTrue(self.ledger.path.read_bytes().startswith(self.prefix))
        self.ledger.finish_run('synthetic', 'completed', {})
        loaded = self.replay(report)
        np.testing.assert_array_equal(predict_state(state, self.data.X), predict_state(loaded, self.data.X))
        (self.output/report['model_file']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            self.replay(report)

    def test_constant_single_class_and_training_local_scaler(self):
        self.data.X[30:] = 1e6
        state, _ = self.fit()
        self.assertTrue(np.all(state['mean'] < 1))
        self.data.y[:] = 1
        state, report = self.fit('constant', 'constant')
        self.assertEqual(float(state['prior']), 1.)
        self.assertEqual(report['support']['positive'], 30)
        before = self.ledger.consumed()
        self.assertEqual(self.fit(fit_id='single')[1]['reason'], 'logistic_requires_two_classes')
        self.assertEqual(self.ledger.consumed(), before)

    def test_scaler_and_model_failures_are_terminal_but_independent_allowed(self):
        for target in ('StandardScaler.fit', 'LogisticRegression.fit'):
            with self.subTest(target=target):
                self.cache.clear()
                with patch('fxnn.experiment_fit.'+target, side_effect=ValueError('numerical')):
                    state, report = self.fit(fit_id=target, task=target)
                self.assertIsNone(state)
                count = self.ledger.consumed()
                self.assertIsNone(self.fit(fit_id='alias', task=target)[0])
                self.assertEqual(self.ledger.consumed(), count)
                self.assertEqual(report['status'], 'failed')
        self.assertIsNotNone(self.fit('constant', 'independent')[0])

    def test_export_and_report_faults_poison_run(self):
        for target in ('save_arrays', 'write_json'):
            with self.subTest(target=target):
                # Different contracts ensure this fault gets a fresh fit.
                self.cache = {}
                self.ledger._experiment_aborted = False  # Independent synthetic fault fixture.
                with patch('fxnn.experiment_fit.'+target, side_effect=OSError('disk')):
                    with self.assertRaises(OSError):
                        self.fit(fit_id=target, task=target)
                count = self.ledger.consumed()
                with self.assertRaisesRegex(RuntimeError, 'aborted'):
                    self.fit('constant', 'later')
                self.assertEqual(self.ledger.consumed(), count)
                self.cache = {}
                with self.assertRaisesRegex(RuntimeError, 'aborted'):
                    self.fit('constant', 'fresh-cache')

    def test_finish_fit_fault_preserves_start_and_rejects_orphan(self):
        with patch.object(self.ledger, 'finish_fit', side_effect=OSError('ledger disk')):
            with self.assertRaises(OSError):
                self.fit()
        reports = list((self.output/'models').glob('*.json'))
        report = json.loads(reports[0].read_text())
        self.assertEqual(report['status'], 'succeeded')
        with self.assertRaisesRegex(ValueError, 'authoritative'):
            self.replay(report)
        with self.assertRaisesRegex(RuntimeError, 'aborted'):
            self.fit('constant', 'later')
        self.assertEqual(self.ledger.consumed(), 1)

    def test_start_fault_after_durable_record_aborts_without_training(self):
        original = self.ledger.start_fit

        def start_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('fsync failed after write')

        with patch.object(self.ledger, 'start_fit', side_effect=start_then_fail):
            with patch('fxnn.experiment_fit.StandardScaler.fit') as scaler:
                with self.assertRaises(OSError):
                    self.fit()
                scaler.assert_not_called()
        self.assertEqual(self.ledger.consumed(), 1)
        self.cache.clear()
        with self.assertRaisesRegex(RuntimeError, 'aborted'):
            self.fit('constant', 'later')

    def test_abort_finally_even_failure_file_cannot_write(self):
        state, report = self.fit()
        error = OSError('prediction or final-report export')
        with patch('fxnn.experiment_fit.write_json', side_effect=OSError('disk full')):
            secondary = abort_run(self.ledger, 'synthetic', self.output, error)
        self.assertEqual(len(secondary), 1)
        self.assertEqual(self.ledger.records()[-1]['status'], 'aborted')
        with self.assertRaises(ValueError):
            self.replay(report)
        np.testing.assert_array_equal(predict_state(state, self.data.X),
                                      predict_state(self.replay(report, allow_partial=True), self.data.X))
        before = len(self.ledger.records())
        abort_run(self.ledger, 'synthetic', self.output, error)
        self.assertEqual(len(self.ledger.records()), before)

    def test_abort_finish_run_failure_is_reported(self):
        with patch.object(self.ledger, 'finish_run', side_effect=OSError('unavailable')):
            errors = abort_run(self.ledger, 'synthetic', self.output, RuntimeError('original'))
        self.assertIn('finish_run', errors[0])
        with self.assertRaisesRegex(ValueError, 'Unfinished'):
            self.ledger.start_run('next', 1, {'source': 'fixture'})

    def test_fresh_stage_ledger_rejects_aborted_unfinished_fit(self):
        self.ledger.start_fit('synthetic', 'unfinished', 'fold', {}, {'h': 'fixture'})
        self.ledger.finish_run('synthetic', 'aborted', {})
        fresh = StageLedger(self.ledger.path, stage=7)
        with self.assertRaisesRegex(ValueError, 'integrity audit'):
            fresh.start_run('next_stage', 1, {'h': 'fixture'})
        self.assertEqual(self.ledger.consumed(), 1)

    def test_inherited_guards_and_historical_stage(self):
        self.ledger.start_fit('synthetic', 'first', 'fold', {'random_state': 13}, {'h': 'x'})
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            self.ledger.start_fit('synthetic', 'second', 'fold', {}, {'h': 'x'})
        self.ledger.finish_fit('synthetic', 'first', 'succeeded', {})
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            self.ledger.start_fit('synthetic', 'first', 'fold', {}, {'h': 'x'})
        self.ledger.finish_run('synthetic', 'completed', {})
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            self.ledger.start_run('synthetic', 1, {'h': 'x'})
        old = FitLedger(self.output/'old.jsonl')
        old.initialize(999, 'synthetic')
        with self.assertRaisesRegex(ValueError, 'Insufficient'):
            old.start_run('too_many', 2, {'h': 'x'})
        old.start_run('last', 1, {'h': 'x'})
        self.assertEqual(old.start_fit('last', 'f', 'q', {}, {'h': 'x'})['stage'], 5)
        old.finish_fit('last', 'f', 'succeeded', {})
        with self.assertRaisesRegex(ValueError, 'exhausted'):
            old.start_fit('last', 'g', 'q', {}, {'h': 'x'})
        for stage in (0, -1, True, 6.0):
            with self.assertRaises(ValueError):
                StageLedger(self.output/'bad', stage)

    def test_full_contract_separates_task_information_and_sources(self):
        _, first = self.fit('constant')
        self.data.info_ends = self.data.info_ends+60
        _, second = self.fit('constant', 'changed')
        _, third = self.fit('constant', 'task', task='fixed')
        self.assertEqual(len({r['contract_sha256'] for r in (first, second, third)}), 3)
        self.ledger.finish_run('synthetic', 'completed', {})
        with self.assertRaisesRegex(ValueError, 'contract'):
            verified_model(first, self.output, self.ledger, 'synthetic', hashes={'source': 'changed'})
        with self.assertRaisesRegex(ValueError, 'prefix'):
            verified_model(first, self.output, self.ledger, 'synthetic', hashes={'source': 'fixture'},
                           ledger_prefix=b'wrong')


if __name__ == '__main__':
    unittest.main()
