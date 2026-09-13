import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import numpy as np

from fxnn.data_audit import audit_candles, load_development
from fxnn.features import LOOKBACK, build_features
from fxnn.labeling import Candle, Config, label_trades, label_trades_reference
from fxnn.protocol import (class_support, load_protocol, partition_indices,
                           require_training_support, utc_epoch)

PROTOCOL = Path(__file__).resolve().parents[1] / 'configs/multiyear_v1.json'


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = load_protocol(PROTOCOL)

    def reject_config(self, protocol):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'protocol.json'
            path.write_text(json.dumps(protocol))
            with self.assertRaises(ValueError):
                load_protocol(path)

    def test_reject_wrong_config_type_reserved_year_and_overlap(self):
        for key, value in [('kind', 'optimizer'), ('confirmation_locked', False),
                           ('source_years', [2022, 2023, 2024]), ('lookback_minutes', 240),
                           ('minimum_per_class', 0)]:
            with self.subTest(key=key):
                altered = copy.deepcopy(self.protocol)
                altered[key] = value
                self.reject_config(altered)
        altered = copy.deepcopy(self.protocol)
        altered['folds'][0]['test_end'] = '2024-02-01T00:00:00+00:00'
        self.reject_config(altered)

    def test_budget_cannot_drift_from_preregistration(self):
        for key, value in [('total_model_fits', 1001), ('total_model_fits', 1000.0),
                           ('bagging_members', 21), ('bagging_seeds', [0, 1, 3]),
                           ('bagging_seeds', [False, 1, 2]), ('primary_rules', True)]:
            with self.subTest(key=key, value=value):
                altered = copy.deepcopy(self.protocol)
                altered['budget'][key] = value
                self.reject_config(altered)
        altered = copy.deepcopy(self.protocol)
        del altered['budget']
        self.reject_config(altered)

    def test_matching_local_manifest_and_csv_cannot_replace_registered_data(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root/'EURUSD_2022_m1_bid_utc.csv'
            csv_path.write_text('timestamp,open,high,low,close\n')
            manifest = dict(source='HistData.com', price_side='bid', symbol='EURUSD',
                            timeframe='M1', output_timezone='UTC',
                            source_timezone='UTC-05:00 fixed, no DST',
                            year_in_source_timezone=2022, rows=0, archive_sha256='changed',
                            csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest())
            (root/'EURUSD_2022_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'preregistered source inventory'):
                load_development(root, self.protocol)

    def test_registered_fixture_loads_without_reading_confirmation(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = {'years': []}
            for year in (2022, 2023):
                csv_path = root/f'EURUSD_{year}_m1_bid_utc.csv'
                csv_path.write_text(f'timestamp,open,high,low,close\n{year}-01-03T12:00:00+00:00,1.1,1.1,1.1,1.1\n')
                manifest = dict(source='HistData.com', price_side='bid', symbol='EURUSD',
                                timeframe='M1', output_timezone='UTC',
                                source_timezone='UTC-05:00 fixed, no DST',
                                year_in_source_timezone=year, rows=1, archive_sha256='fixture',
                                csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest())
                (root/f'EURUSD_{year}_manifest.json').write_text(json.dumps(manifest))
                inventory['years'].append(manifest)
            path = root/'sources.json'
            path.write_text(json.dumps(inventory))
            with patch('fxnn.data_audit.SOURCE_INVENTORY', path):
                candles, hashes = load_development(root, self.protocol)
            self.assertEqual([c.timestamp.year for c in candles], [2022, 2023])
            self.assertIn('versioned_source_inventory', hashes)

    def test_utc_and_year_boundary_with_horizon_and_buffer(self):
        fold = self.protocol['folds'][-1]
        outer = utc_epoch(fold['test_start'])
        end = utc_epoch(fold['test_end'])
        gap = (4320 + LOOKBACK) * 60
        starts = np.array([outer-gap-60, outer-gap, outer, end-4320*60-60,
                           end-4320*60])
        parts = partition_indices(starts, starts+4320*60, self.protocol, fold)
        self.assertEqual(parts['refit'].tolist(), [0])
        self.assertEqual(parts['test'].tolist(), [2, 3])
        with self.assertRaisesRegex(ValueError, 'Reserved'):
            partition_indices([end], [end+4320*60], self.protocol, fold)
        with self.assertRaisesRegex(ValueError, 'conservative'):
            partition_indices(starts, starts+60, self.protocol, fold)
        for stamp in ['2023-01-01T00:00:00', '2023-01-01T00:00:00-05:00']:
            with self.assertRaises(ValueError):
                utc_epoch(stamp)

    def test_support_guard_does_not_read_external_labels(self):
        labels = np.array([0]*100 + [1]*900 + [0]*200)
        parts = {name: np.arange(1000) for name in ('train', 'validation', 'refit')}
        parts['test'] = np.arange(1000, 1200)
        before = require_training_support(labels, parts, self.protocol)
        labels[1000:] = 9  # even invalid external labels are not training inputs
        self.assertEqual(before, require_training_support(labels, parts, self.protocol))
        labels[0] = 1
        with self.assertRaisesRegex(ValueError, 'abort comparison'):
            require_training_support(labels, parts, self.protocol)
        self.assertFalse(class_support([0]*2000, 1000, 100)['eligible'])
        with self.assertRaises(ValueError):
            class_support([0, float('nan')], 1, 1)

    def test_confirmation_rejected_before_labeling(self):
        candle = Candle(datetime(2024, 1, 2, tzinfo=timezone.utc), *([Decimal('1.1')]*4))
        with patch('fxnn.data_audit.build_features') as features:
            with self.assertRaisesRegex(ValueError, 'Reserved'):
                audit_candles([candle], self.protocol)
            features.assert_not_called()

    def test_manifest_source_and_hash_verified_before_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = dict(source='HistData.com', price_side='bid', symbol='EURUSD',
                            timeframe='M1', output_timezone='UTC',
                            source_timezone='UTC-05:00 fixed, no DST',
                            year_in_source_timezone=2022, csv_sha256='wrong', rows=0)
            (root/'EURUSD_2022_manifest.json').write_text(json.dumps(manifest))
            (root/'EURUSD_2022_m1_bid_utc.csv').write_text('timestamp,open,high,low,close\n')
            with self.assertRaisesRegex(ValueError, 'hash'):
                load_development(root, self.protocol)
            manifest['price_side'] = 'ask'
            (root/'EURUSD_2022_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'source'):
                load_development(root, self.protocol)

    def test_gap_censors_and_restarts_full_history_without_future_eligibility(self):
        start = datetime(2023, 1, 6, 18, tzinfo=timezone.utc)
        flat = lambda stamp: Candle(stamp, *([Decimal('1.1')]*4))
        before = [flat(start+timedelta(minutes=i)) for i in range(300)]
        for missing in [1, 48*60]:  # feed outage and weekend-size gap share conservative treatment
            after = [flat(before[-1].timestamp+timedelta(minutes=missing+1+i))
                     for i in range(LOOKBACK+2)]
            candles = before+after
            frame = build_features(candles)
            self.assertTrue(frame.valid[299])
            self.assertFalse(frame.valid[300+LOOKBACK-1])
            self.assertTrue(frame.valid[300+LOOKBACK])
            config = Config(Decimal('0.0001'))
            actual = label_trades(candles, config)
            expected = label_trades_reference(candles, config, [299])
            self.assertEqual(actual[598:600], expected)
            self.assertEqual(expected[0].outcome, 'censored')
            # A future quote changes outcomes, never earlier feature eligibility.
            changed = candles.copy()
            changed[-1] = Candle(changed[-1].timestamp, *([Decimal('1.2')]*4))
            np.testing.assert_array_equal(frame.valid[:-1], build_features(changed).valid[:-1])
            report = audit_candles(candles, self.protocol)
            monthly = report['monthly']['2023-01']
            self.assertEqual(monthly['candidates'], len(candles)*2)
            self.assertEqual(monthly['censored'], len(candles)*2)
            self.assertTrue(all(f['training_status'].startswith('abort') for f in report['folds']))
            self.assertFalse(report['confirmation_opened'])
