import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from fxnn.cusum_continuation import (EXPERIMENT, conclusion, fit_once, load_contract,
                                     paired_sensitivity, run_models, score, technical_reason)
from fxnn.cusum_research import identity_hash
from fxnn.fit_ledger import FitLedger
from fxnn.protocol import partition_indices, utc_epoch
from test_cusum import synthetic


def ledger_at(root):
    ledger = FitLedger(Path(root) / 'ledger.jsonl')
    ledger.initialize(0, {'synthetic': True})
    ledger.start_run(EXPERIMENT, 24, {'synthetic': True}, independent_failures=True)
    return ledger


class ContinuationTests(unittest.TestCase):
    def test_contract_and_undefined_metrics(self):
        spec, _ = load_contract()
        self.assertEqual(spec['max_model_fits'], 24)
        for y, p in [(np.array([], int), np.array([])), (np.zeros(3, int), np.zeros(3)),
                     (np.ones(3, int), np.ones(3))]:
            result = score(y, p)
            json.dumps(result, allow_nan=False)
            self.assertIsNone(result['roc_auc'])
            self.assertIsNone(result['thresholds']['0.3']['recall'] if not y.sum() else result['roc_auc'])
        self.assertIsNone(score(np.zeros(2, int), np.zeros(2))['average_precision'])
        self.assertEqual(score(np.ones(2, int), np.ones(2))['average_precision'], 1)
        for p in (np.array([.2]), np.array([np.nan, .2]), np.array([1.1, .2])):
            with self.assertRaises(ValueError):
                score(np.array([0, 1]), p)

    def test_low_support_not_arbitrary_veto_and_no_silent_constant(self):
        data, _, _, _, _ = synthetic()
        rows = np.array([np.flatnonzero(data.y == 0)[0], np.flatnonzero(data.y == 1)[0]])
        self.assertIsNone(technical_reason(data, rows, False))
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ledger_at(tmp)
            model, result = fit_once(data, rows, False, ledger, 'two', 'Q2', {})
            self.assertEqual(result['status'], 'succeeded')
            self.assertIsNotNone(model.model)
            one = rows[:1]
            model, result = fit_once(data, one, False, ledger, 'single', 'Q2', {})
            self.assertIsNone(model)
            self.assertEqual(result['reason'], 'logistic_requires_two_classes')
            model, result = fit_once(data, one, True, ledger, 'constant', 'Q2', {})
            self.assertEqual(result['status'], 'succeeded')
            self.assertEqual(model.prior, 0)
            self.assertEqual(ledger.consumed(), 2)

    def test_failure_consumed_no_retry_other_ids_continue_pending_blocks(self):
        data, _, _, _, _ = synthetic()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ledger_at(tmp)
            def fail(*args):
                self.assertEqual(ledger.records()[-1]['kind'], 'fit_started')
                raise RuntimeError('numerical')
            with patch('fxnn.cusum_continuation.Baseline.fit', side_effect=fail):
                model, result = fit_once(data, np.arange(100), False, ledger, 'failed', 'Q2', {})
            self.assertIsNone(model)
            self.assertEqual(result['status'], 'failed')
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                ledger.start_fit(EXPERIMENT, 'failed', 'Q2', {}, {})
            fit_once(data, np.arange(100), True, ledger, 'next', 'Q2', {})
            ledger.start_fit(EXPERIMENT, 'pending', 'Q2', {}, {})
            with self.assertRaisesRegex(ValueError, 'unfinished'):
                ledger.start_fit(EXPERIMENT, 'blocked', 'Q2', {}, {})
            self.assertEqual(ledger.consumed(), 3)

    def test_train_only_weights_scaler_and_future_invariance(self):
        data, _, _, protocol, _ = synthetic()
        parts = partition_indices(data.starts, data.info_ends, protocol, protocol['folds'][0])
        rows = parts['train']
        boundary = utc_epoch(protocol['folds'][0]['validation_start'])
        self.assertTrue(np.all(data.info_ends[rows] < boundary - 241*60))
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ledger_at(tmp)
            first, _ = fit_once(data, rows, False, ledger, 'first', 'Q2', {})
            data.X[parts['test']] += 1e6
            data.y[parts['test']] = 1-data.y[parts['test']]
            data.ends[parts['test']] += 1000000
            second, _ = fit_once(data, rows, False, ledger, 'second', 'Q2', {})
            np.testing.assert_array_equal(first.scaler.mean_, second.scaler.mean_)
            np.testing.assert_array_equal(first.model.coef_, second.model.coef_)

    def test_disjoint_thresholds_all_folds_24_fits_paired_identity_and_full_control(self):
        data, masks, obs, protocol, _ = synthetic()
        # Sparse, mutually disjoint masks: intersection empty, all partitions still run.
        ix = np.arange(len(data.y))
        masks['0.0005'][:] = ix % 40 == 0
        masks['0.001'][:] = ix % 40 == 1
        self.assertFalse((masks['0.0005'] & masks['0.001']).any())
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ledger_at(tmp)
            reports = run_models(data, masks, obs, protocol, ledger, {}, Path(tmp))
            self.assertEqual(ledger.consumed(), 24)
            with (Path(tmp)/'predictions.csv').open() as stream:
                records = list(csv.DictReader(stream))
            for fold, report in zip(protocol['folds'], reports):
                base = partition_indices(data.starts, data.info_ends, protocol, fold)
                for phase, part in [('inner', 'validation'), ('refit', 'test')]:
                    evaluations = report['phases'][phase]['evaluations']
                    for h in masks:
                        rows = base[part][masks[h][base[part]]]
                        self.assertEqual(evaluations[h]['identity_sha256'], identity_hash(data, rows))
                        self.assertLess(evaluations[h]['support']['rows'], 1000)
                        for metric in evaluations[h]['scores'].values():
                            self.assertEqual(metric['support']['rows'], len(rows))
                        subset = [r for r in records if r['fold'] == fold['name'] and r['phase'] == phase and r['universe'] == h]
                        self.assertEqual(len(subset), len(rows))
                        self.assertTrue(all(r['temporal'] and r['constant'] and r['cusum'] for r in subset))
                    self.assertEqual(evaluations['temporal']['support']['rows'], len(base[part]))
            json.dumps(reports, allow_nan=False)

    def test_infeasible_threshold_does_not_cancel_other_comparisons(self):
        data, masks, obs, protocol, _ = synthetic()
        masks['0.001'][:] = False
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ledger_at(tmp)
            reports = run_models(data, masks, obs, protocol, ledger, {}, Path(tmp))
            self.assertEqual(ledger.consumed(), 18)
            result = conclusion(reports, list(masks))
            self.assertEqual(result['descriptive']['0.001']['temporal'], 'technically_unavailable_comparison')
            self.assertNotEqual(result['descriptive']['0.0005']['temporal'], 'technically_unavailable_comparison')

    def test_week_sensitivity_is_paired_and_no_iid_interval(self):
        y = np.array([0, 1, 0, 1])
        a, b = np.array([.1, .8, .2, .9]), np.full(4, .5)
        starts = np.array([0, 60, 7*86400, 7*86400+60])
        result = paired_sensitivity(y, a, b, starts)
        self.assertEqual(result['weeks'], 2)
        self.assertAlmostEqual(result['log_loss']['delta'], score(y, a)['log_loss'] - score(y, b)['log_loss'])
        self.assertEqual(result['status'], 'descriptive_not_confidence_interval')
        self.assertIsNone(paired_sensitivity(y, a, b, np.arange(4))['brier']['delete_week_min'])

    def test_conclusion_strict_three_fold_rule_and_missing_metrics(self):
        def reports(losses, briers):
            return [{'phases': {'refit': {'evaluations': {'h': {'scores': {
                'cusum': {'log_loss': loss, 'brier': brier},
                'temporal': {'log_loss': .5, 'brier': .2},
                'constant': {'log_loss': .5, 'brier': .2}}}}}}}
                    for loss, brier in zip(losses, briers)]
        def verdict(rows):
            return conclusion(rows, ['h'])['descriptive']['h']['temporal']
        self.assertEqual(verdict(reports([.4]*3, [.21, .19, .19])), 'consistent_descriptive_gain')
        for loss, brier in [([.4, .5, .4], [.19]*3), ([.4]*3, [.21]*3)]:
            self.assertEqual(verdict(reports(loss, brier)), 'mixed_or_unfavorable_predictive_result')
        self.assertEqual(verdict(reports([None, .4, .4], [.2]*3)), 'inconclusive_empty_evaluation')
        rows = reports([.4]*3, [.19]*3)
        rows[0]['phases']['refit']['evaluations']['h']['scores']['cusum'] = None
        self.assertEqual(verdict(rows), 'technically_unavailable_comparison')

    def test_published_continuation_evidence_and_budget(self):
        from fxnn.cusum_evidence import export_evidence, verify_ledger
        from fxnn.data_audit import digest
        root = Path(__file__).resolve().parents[1] / 'docs/experiments'
        manifest = json.loads((root/'cusum-temporal-v2-evidence.json').read_text())
        for name, expected in manifest['files'].items():
            self.assertEqual(digest(root/name), expected)
        raw = (root/'cusum-temporal-v2-ledger.jsonl').read_bytes()
        self.assertTrue(raw.startswith((root/'cusum-v1-ledger.jsonl').read_bytes()))
        records = verify_ledger(raw)
        fits = [r for r in records if r['kind'] == 'fit_started']
        self.assertEqual(len(fits), 24)
        self.assertEqual(len({r['fit_id'] for r in fits}), 24)
        self.assertTrue(all(r['experiment'] == EXPERIMENT for r in fits))
        self.assertEqual(sum(r['kind'] == 'fit_finished' and r['status'] == 'succeeded' for r in records), 24)
        self.assertEqual(records[-1]['consumed_total'], 24)
        report = json.loads((root/'cusum-temporal-v2.json').read_text())
        self.assertEqual(report['conclusion'], conclusion(report['folds'], ['0.0005', '0.001']))
        self.assertEqual(report['years'], [2022, 2023])
        self.assertFalse(report['confirmation_opened'])
        with tempfile.TemporaryDirectory() as tmp:
            actual = export_evidence(root/'cusum-temporal-v2.json',
                                     root/'cusum-temporal-v2-ledger.jsonl', tmp, EXPERIMENT)
            self.assertEqual(actual, manifest)
            self.assertEqual((Path(tmp)/'cusum-temporal-v2.json').read_bytes(),
                             (root/'cusum-temporal-v2.json').read_bytes())
