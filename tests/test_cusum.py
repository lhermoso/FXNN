import json
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import numpy as np

from fxnn.cusum import cusum_events, interval_diagnostics, next_entries
from fxnn.cusum_research import (choose, conclusion, fit_score, inspect_internal, load_contract,
                                 main, prepare, run_models)
from fxnn.features import build_features, orient_features
from fxnn.fit_ledger import FitLedger
from fxnn.labeling import Candle, Config, label_trades
from fxnn.protocol import partition_indices, utc_epoch
from fxnn.research import Dataset


def reference(closes, stamps, h):
    # Independent segment-by-segment, with explicit positive/negative histories.
    result = []
    up, down = [], []
    for i in range(1, len(closes)):
        if stamps[i] != stamps[i-1] + 60:
            up, down = [], []
            continue
        r = math.log(closes[i]) - math.log(closes[i-1])
        up.append(r)
        down.append(r)
        if sum(up) < 0:
            up = []
        if sum(down) > 0:
            down = []
        if sum(down) < -h:
            down = []
            result.append(i)
        elif sum(up) > h:
            up = []
            result.append(i)
    return result


class CusumTests(unittest.TestCase):
    def test_reference_rises_falls_oscillation_gaps(self):
        rng = np.random.default_rng(61)
        for returns in (np.full(100, .002), np.full(100, -.002),
                        np.tile([.0009, -.0009], 50), rng.normal(0, .001, 1000)):
            closes = np.exp(np.cumsum(returns))
            stamps = np.arange(len(closes)) * 60
            stamps[50:] += 3600
            for h in (.001, .005):
                self.assertEqual(np.flatnonzero(cusum_events(closes, stamps, h)).tolist(),
                                 reference(closes, stamps, h))
        self.assertFalse(cusum_events(np.ones(100), np.arange(100)*60, .001).any())
        self.assertFalse(cusum_events(np.exp(np.tile([0, .0009], 50)),
                                     np.arange(100)*60, .001).any())

    def test_exact_threshold_strict_and_large_jump_single_reset(self):
        h = math.log(2)
        events = cusum_events([1, 2, 4, 4, 128, 128], np.arange(6)*60, h)
        self.assertEqual(np.flatnonzero(events).tolist(), [2, 4])
        events = cusum_events([4, 2, 1, 1], np.arange(4)*60, h)
        self.assertEqual(np.flatnonzero(events).tolist(), [2])

    def test_gap_drops_pending_event_and_both_accumulators(self):
        stamps = np.array([0, 60, 120, 86400, 86460, 86520])
        events = cusum_events(np.exp([0, .0007, .0014, .2, .2007, .2014]), stamps, .001)
        self.assertEqual(np.flatnonzero(events).tolist(), [2, 5])
        self.assertFalse(next_entries(events, stamps).any())
        # A subthreshold pre-gap accumulator must not produce a post-gap event.
        events = cusum_events(np.exp([0, .0007, .0008, .2, .2004, .2005]), stamps, .001)
        self.assertFalse(events.any())

    def test_future_prices_and_truncation_do_not_change_prior_entries(self):
        closes = np.exp(np.arange(500)*.0002)
        stamps = np.arange(500)*60
        baseline = next_entries(cusum_events(closes, stamps, .001), stamps)
        changed = closes.copy()
        changed[300:] *= 10
        actual = next_entries(cusum_events(changed, stamps, .001), stamps)
        np.testing.assert_array_equal(baseline[:301], actual[:301])
        short = next_entries(cusum_events(closes[:301], stamps[:301], .001), stamps[:301])
        np.testing.assert_array_equal(baseline[:301], short)

    def test_invalid_input(self):
        for close, stamps, h in [([1, 0], [0, 60], .1), ([1, 1], [0, 0], .1),
                                  ([1], [1], .1), ([1], [0], 0), ([1], [0], float('nan'))]:
            with self.assertRaises(ValueError):
                cusum_events(close, stamps, h)

    def test_raw_uniqueness_concurrency_reference(self):
        starts, ends = np.array([0, 0, 2, 10]), np.array([4, 4, 6, 12])
        raw = [np.mean([1 / ((starts <= t) & (ends > t)).sum() for t in range(a, b)])
               for a, b in zip(starts, ends)]
        report = interval_diagnostics(starts, ends)
        self.assertAlmostEqual(report['raw_uniqueness_mean'], np.mean(raw))
        self.assertAlmostEqual(report['raw_uniqueness_min'], min(raw))
        self.assertEqual(report['concurrency_max'], 3)
        self.assertEqual(report['concurrency_active_mean'], 14/8)

    def test_labels_features_identities_and_gap_warmup(self):
        spec, protocol = load_contract()
        start = datetime(2022, 1, 1, tzinfo=timezone.utc)
        candles = []
        for i in range(900):
            p = Decimal('1.1') + Decimal(i % 100) / 10000
            candles.append(Candle(start+timedelta(minutes=i+(10 if i >= 400 else 0)),
                                  p, p+Decimal('.0002'), p-Decimal('.0002'), p))
        data, masks, obs, _ = prepare(candles, protocol, spec['thresholds'])
        frame = build_features(candles)
        trades = {(t.entry_index, 1 if t.side == 'long' else -1): t
                  for t in label_trades(candles, Config(Decimal('.0001')))}
        self.assertGreater(len(data.y), 0)
        self.assertEqual(set(data.sides), {-1, 1})
        for i, (entry, side) in enumerate(zip(data.entry_indices, data.sides)):
            trade = trades[(entry, side)]
            self.assertEqual(data.y[i], int(trade.outcome == 'take_profit'))
            self.assertEqual(data.starts[i], int(trade.entry_time.timestamp()))
            np.testing.assert_array_equal(data.X[i], orient_features(frame, [entry], [side])[0])
        self.assertFalse(np.any((data.entry_indices >= 400) & (data.entry_indices < 641)))
        for h, mask in masks.items():
            stamps = [int(c.timestamp.timestamp()) for c in candles]
            expected = next_entries(cusum_events([float(c.close) for c in candles], stamps, float(h)), stamps)
            np.testing.assert_array_equal(mask, expected[data.entry_indices])
        self.assertEqual(len(obs['starts']), 2*len(candles))
        reserved = replace(candles[0], timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc))
        with patch('fxnn.cusum_research.build_features') as build:
            with self.assertRaisesRegex(ValueError, 'Reserved'):
                prepare([reserved], protocol, spec['thresholds'])
            build.assert_not_called()


class LedgerTests(unittest.TestCase):
    def test_failures_consume_budget_and_prevent_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = FitLedger(Path(tmp)/'ledger.jsonl')
            self.assertEqual(ledger.initialize(979, {'fixture': True}), 979)
            ledger.start_run('cusum_v1', 21, {'fixture': True})
            ledger.start_fit('cusum_v1', 'a', 'Q2', {}, {'fixture': True})
            ledger.finish_fit('cusum_v1', 'a', 'failed', {'error': 'fixture'})
            self.assertEqual(FitLedger(ledger.path).consumed(), 980)
            with self.assertRaises(ValueError):
                ledger.start_fit('cusum_v1', 'b', 'Q2', {}, {})
            ledger.finish_run('cusum_v1', 'failed', {})
            with self.assertRaises(ValueError):
                ledger.start_run('cusum_v1', 21, {'fixture': True})
            with self.assertRaises(ValueError):
                ledger.start_run('next', 21, {'fixture': True})

    def test_interrupted_fit_and_corrupt_ledger_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = FitLedger(Path(tmp)/'ledger.jsonl')
            ledger.initialize(0, {'fixture': True})
            ledger.start_run('cusum_v1', 1, {'fixture': True})
            ledger.start_fit('cusum_v1', 'a', 'Q2', {}, {})
            self.assertEqual(ledger.consumed(), 1)
            with self.assertRaises(ValueError):
                ledger.start_run('other', 1, {'fixture': True})
            with ledger.path.open('a') as stream:
                stream.write('{broken')
            with self.assertRaises(ValueError):
                ledger.consumed()

    def test_fit_failure_recorded_before_exception(self):
        data, _, _, _, _ = synthetic()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = new_ledger(tmp)
            with patch('fxnn.cusum_research.Baseline.fit', side_effect=RuntimeError('numerical')):
                with self.assertRaisesRegex(RuntimeError, 'numerical'):
                    fit_score(data, np.arange(100), np.arange(100, 200), False, ledger,
                              'fixture', 'Q2', {}, {'fixture': True})
            self.assertEqual(ledger.records()[-1]['status'], 'failed')
            self.assertEqual(ledger.consumed(), 1)


def synthetic():
    spec, protocol = load_contract()
    rng = np.random.default_rng(41)
    starts = np.arange(utc_epoch(protocol['development'][0]),
                       utc_epoch(protocol['development'][1]), 3600, dtype=np.int64)
    X = rng.normal(size=(len(starts), 2))
    y = (X[:, 0] + rng.normal(size=len(starts)) > 0).astype(np.int8)
    rows = np.arange(len(starts))
    data = Dataset(X, y, starts, starts+7200, starts+4320*60, rows,
                   np.where(rows % 2, -1, 1), ['x', 'z'], {'fixture': [0, 1]}, 0)
    masks = {'0.0005': rows % 5 != 0, '0.001': rows % 4 != 0}
    obs = dict(starts=starts, outcomes=np.where(y, 'take_profit', 'stop_loss'),
               valid=np.ones(len(y), bool), conclusive=np.ones(len(y), bool),
               retained=np.ones(len(y), bool), events=masks)
    return data, masks, obs, protocol, spec


def new_ledger(directory):
    ledger = FitLedger(Path(directory)/'ledger.jsonl')
    ledger.initialize(0, {'fixture': True})
    ledger.start_run('cusum_v1', 21, {'fixture': True})
    return ledger


class RunnerTests(unittest.TestCase):
    def test_three_fold_conclusion_rule(self):
        def reports(losses, briers, eligible=True):
            return [dict(selected_threshold='0.001', external_support={'eligible': eligible},
                         common_external_scores={'temporal': {'log_loss': .5, 'brier': .2},
                                                 '0.001': {'log_loss': loss, 'brier': brier}})
                    for loss, brier in zip(losses, briers)]
        self.assertEqual(conclusion(reports([.4, .4, .4], [.21, .19, .19])),
                         'consistent_exploratory_classification_gain')
        for losses, briers in [([.4, .6, .4], [.19]*3), ([.4]*3, [.21]*3),
                               ([.4, .5, .4], [.19]*3)]:
            self.assertEqual(conclusion(reports(losses, briers)),
                             'no_consistent_gain_preserve_temporal_control')
        self.assertEqual(conclusion(reports([.4]*3, [.19]*3, False)),
                         'inconclusive_external_support')

    def test_contract_and_tie_order(self):
        spec, _ = load_contract()
        self.assertEqual(spec['max_model_fits'], 21)
        scores = {name: {'log_loss': 1.0} for name in ('constant', 'temporal', '.001', '.002')}
        self.assertEqual(choose(scores, list(scores)), 'constant')
        self.assertEqual(choose(scores, ['.001', '.002']), '.001')

    def test_preflight_ignores_external_labels_and_common_support_can_stop(self):
        data, masks, obs, protocol, _ = synthetic()
        _, first, failures = inspect_internal(data, masks, obs, protocol)
        self.assertFalse(failures)
        test = partition_indices(data.starts, data.info_ends, protocol, protocol['folds'][-1])['test']
        y = data.y.copy()
        y[test] = 9
        _, second, failures = inspect_internal(replace(data, y=y), masks, obs, protocol)
        self.assertEqual(first, second)
        self.assertFalse(failures)
        masks = {'0.0005': data.entry_indices % 2 == 0, '0.001': data.entry_indices % 2 == 1}
        _, reports, failures = inspect_internal(data, masks, obs, protocol)
        self.assertTrue(any('common_validation' in f for f in failures))
        self.assertEqual(reports[0]['common_validation']['support']['rows'], 0)

    def test_same_evaluation_identities_external_invariance_and_seven_fits(self):
        data, masks, obs, protocol, spec = synthetic()
        protocol['folds'] = protocol['folds'][-1:]
        plan, _, failures = inspect_internal(data, masks, obs, protocol)
        self.assertFalse(failures)
        test = plan[0][1]['temporal']['test']
        changed = data.y.copy()
        changed[test] = 1-changed[test]
        results, predictions = [], []
        for y in (data.y, changed):
            with tempfile.TemporaryDirectory() as tmp:
                ledger = new_ledger(tmp)
                with patch('fxnn.cusum_research.uniqueness_weights', wraps=__import__(
                        'fxnn.temporal', fromlist=['uniqueness_weights']).uniqueness_weights) as weights:
                    result = run_models(replace(data, y=y), masks, obs, plan, protocol, spec,
                                        ledger, {'fixture': True}, Path(tmp))[0]
                self.assertEqual(weights.call_count, 7)
                boundary = utc_epoch(protocol['folds'][0]['test_start'])
                self.assertTrue(all(np.max(call.args[0]) < boundary for call in weights.call_args_list))
                self.assertEqual(ledger.consumed(), 7)
                records = [r for r in ledger.records() if r['kind'] == 'fit_started']
                self.assertEqual(len({r['hashes']['evaluation_identities'] for r in records[:4]}), 1)
                self.assertEqual(len({r['hashes']['evaluation_identities'] for r in records[4:]}), 1)
                results.append(result)
                predictions.append(np.loadtxt(Path(tmp)/'predictions.csv', delimiter=',', skiprows=1,
                                              usecols=(1, 2, 5, 6, 7)))
        self.assertEqual(results[0]['selected_threshold'], results[1]['selected_threshold'])
        self.assertEqual(results[0]['inner_scores'], results[1]['inner_scores'])
        np.testing.assert_array_equal(predictions[0], predictions[1])

    def test_external_empty_does_not_gate_fitting(self):
        data, masks, obs, protocol, spec = synthetic()
        protocol['folds'] = protocol['folds'][-1:]
        test = partition_indices(data.starts, data.info_ends, protocol, protocol['folds'][0])['test']
        for mask in masks.values():
            mask[test] = False
        plan, _, failures = inspect_internal(data, masks, obs, protocol)
        self.assertFalse(failures)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = new_ledger(tmp)
            report = run_models(data, masks, obs, plan, protocol, spec, ledger, {}, Path(tmp))[0]
            self.assertEqual(ledger.consumed(), 7)
            self.assertFalse(report['external_support']['eligible'])
            self.assertIsNone(report['common_external_scores']['temporal']['log_loss'])

    def test_main_support_stop_persists_zero_fits_and_blocks_rerun(self):
        data, masks, obs, protocol, spec = synthetic()
        masks['0.001'][:] = False
        with tempfile.TemporaryDirectory() as tmp:
            spec['global_ledger'] = str(Path(tmp)/'ledger.jsonl')
            output = Path(tmp)/'result'
            argv = ['cusum', '--initialize-ledger', '--output', str(output)]
            with patch('sys.argv', argv), patch('fxnn.cusum_research.load_contract', return_value=(spec, protocol)), \
                    patch('fxnn.cusum_research.subprocess.check_output', side_effect=['', 'fixture']), \
                    patch('fxnn.cusum_research.load_development', return_value=([], {})), \
                    patch('fxnn.cusum_research.prepare', return_value=(data, masks, obs, {})), \
                    patch('fxnn.cusum_research.Baseline.fit') as fit:
                main()
                fit.assert_not_called()
            report = json.loads((output/'report.json').read_text())
            self.assertEqual(report['fits_consumed'], 0)
            self.assertNotIn('folds', report)
            ledger = FitLedger(spec['global_ledger'])
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                ledger.start_run('cusum_v1', 21, {'fixture': True})


if __name__ == '__main__':
    unittest.main()
