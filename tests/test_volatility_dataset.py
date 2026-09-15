import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile

import numpy as np

from fxnn.volatility_dataset import describe, regime_cutpoints, candidate_summary, build
from fxnn.session_clock import SessionClock
from fxnn.labeling import Candle
from fxnn.data_audit import digest
from fxnn.volatility import volatility_partitions


class VolatilityReportTests(unittest.TestCase):
    def test_complete_dataset_roundtrip_alignment_and_partitions(self):
        start = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp())
        stamps = start + np.arange(20000, dtype=np.int64) * 60
        prices = 1.1 + .003 * np.sin(np.arange(len(stamps)) / 211)
        candles = []
        for stamp, price in zip(stamps, prices):
            p = Decimal(str(price))
            candles.append(Candle(datetime.fromtimestamp(int(stamp), timezone.utc),
                                  p, p + Decimal('.0002'), p - Decimal('.0002'), p))
        def iso(minute):
            return datetime.fromtimestamp(start + minute * 60, timezone.utc).isoformat()
        fold = dict(name='synthetic', validation_start=iso(10000),
                    test_start=iso(15000), test_end=iso(20000))
        protocol = dict(development=[iso(0), iso(20000)], folds=[fold])
        spec = dict(thresholds=[.0005, .001],
                    volatility=dict(lag=1440, window=500, span=100, minimum=100))
        clock = SessionClock(start, np.ones(25000, dtype=bool))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports, artifacts, schema = build(candles, protocol, spec, clock, root)
            with np.load(root / 'observed.npz', allow_pickle=False) as observed:
                self.assertEqual(observed['stamps'].tolist(), stamps.tolist())
                valid = observed['causal_valid']
                self.assertTrue(valid.any())
                self.assertTrue(np.all(np.flatnonzero(valid) - observed['history_start_index'][valid] <= 1940))
                for task in ('fixed', 'dynamic'):
                    path = root / task / 'dataset.npz'
                    self.assertEqual(digest(path), artifacts[task]['dataset']['sha256'])
                    with np.load(path, allow_pickle=False) as data, np.load(root / task / 'candidates.npz', allow_pickle=False) as obs:
                        self.assertEqual(len(obs['starts']), 2 * len(stamps))
                        rows, entries, sides = data['candidate_rows'], data['observed_indices'], data['sides']
                        self.assertEqual(data['X'].shape, (len(rows), 28))
                        self.assertTrue(len(rows) > 0)
                        self.assertTrue(obs['valid'][rows].all())
                        expected = observed['X'][entries].copy()
                        expected[:, schema['directional_features']] *= sides[:, None]
                        expected[:, -1] = sides
                        np.testing.assert_array_equal(data['X'], expected)
                        np.testing.assert_array_equal(data['y'], obs['outcomes'][rows] == 'take_profit')
                        np.testing.assert_array_equal(data['entry_indices'], obs['entry_indices'][rows])
                        calculated = volatility_partitions(data['starts'], data['info_ends'], protocol,
                                                          fold, clock, stamps)
                        for part, indices in calculated.items():
                            np.testing.assert_array_equal(data[f'synthetic_{part}'], indices)
                        self.assertTrue(np.all(data['last_information_bar_end'] >= data['ends']))
                    self.assertEqual(reports[task]['all_development']['candidates'], 40000)

    def test_empty_stats_are_explicit_and_nonfinite_not_dropped(self):
        result = describe([])
        self.assertEqual(result['count'], 0)
        self.assertIsNone(result['mean'])
        self.assertEqual(result['reason'], 'empty_group')
        with self.assertRaises(ValueError):
            describe([1, np.nan])

    def test_training_only_unique_causal_timestamps_include_inconclusive(self):
        obs = dict(starts=np.array([0, 0, 60, 60, 120, 120, 180, 180]),
                   sigma=np.array([1, 1, 2, 2, 100, 100, .01, .01]),
                   valid=np.array([True] * 6 + [False] * 2))
        result = regime_cutpoints(obs, np.arange(6))
        self.assertEqual(result['unique_training_entries'], 3)
        self.assertEqual(result['cutpoints'], [1, 2])
        obs['sigma'][6:] = 1e9
        self.assertEqual(result, regime_cutpoints(obs, np.arange(6)))
        self.assertIsNone(regime_cutpoints(obs, np.arange(6, 8))['cutpoints'])

    def test_support_and_duration_do_not_drop_censored_or_ineligible(self):
        obs = dict(starts=np.array([0, 60, 120]), ends=np.array([60, 180, 120]),
                   outcomes=np.array(['take_profit', 'censored', 'causally_ineligible']),
                   valid=np.array([True, True, False]), retained=np.array([True, False, False]),
                   reason=np.array(['', '', 'insufficient_history']),
                   sigma=np.array([.1, .2, np.nan]), price_volatility=np.array([.1, .2, np.nan]),
                   tp_distance=np.array([.25, .5, np.nan]), sl_distance=np.array([.1, .2, np.nan]))
        result = candidate_summary(obs, np.arange(3), SessionClock(0, np.ones(10, dtype=bool)))
        self.assertEqual(result['candidates'], 3)
        self.assertEqual(result['causally_eligible'], 2)
        self.assertEqual(result['retained'], 1)
        self.assertEqual(result['outcomes']['censored'], 1)
        self.assertEqual(result['exclusions']['insufficient_history'], 1)
        self.assertEqual(result['durations_by_outcome']['censored']['open_minutes']['mean'], 2)
        self.assertEqual(result['barriers']['sigma']['count'], 2)
        self.assertEqual(result['prevalence_denominator'], 1)
