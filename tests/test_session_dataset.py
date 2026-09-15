import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np

from fxnn.labeling import Candle
from fxnn.protocol import load_protocol, utc_epoch
from fxnn.session_clock import SessionClock
from fxnn.session_dataset import build, historical_months, save_arrays

ROOT = Path(__file__).resolve().parents[1]


class SessionDatasetTests(unittest.TestCase):
    def test_export_identity_labels_features_and_masks(self):
        protocol = load_protocol(ROOT/'configs/multiyear_v1.json')
        spec = json.loads((ROOT/'configs/session_dataset_v1.json').read_text())
        start = utc_epoch(protocol['development'][0])
        clock = SessionClock(start, np.ones(1100000, dtype=bool))
        candles = []
        for i in range(900):
            if i in (310, 311) or 600 <= i < 615:
                continue
            price = Decimal('1.10') + Decimal(i % 100)*Decimal('.0001')
            candles.append(Candle(datetime.fromtimestamp(start+i*60, timezone.utc),
                                  price, price+Decimal('.0001'), price-Decimal('.0001'), price))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report, artifacts, schema = build(candles, protocol, spec, clock, output)
            self.assertGreater(report['all_development']['retained'], 0)
            self.assertEqual(report['diagnostics']['synthetic_candles'], 0)
            with np.load(output/'dataset.npz', allow_pickle=False) as data, np.load(output/'candidates.npz', allow_pickle=False) as obs:
                lookup = {(int(t), int(s)): i for i, (t, s) in enumerate(zip(obs['starts'], obs['sides']))}
                indices = np.asarray([lookup[int(t), int(s)] for t, s in zip(data['starts'], data['sides'])])
                np.testing.assert_array_equal(data['y'], (obs['outcomes'][indices] == 'take_profit').astype(np.int8))
                np.testing.assert_array_equal(data['entry_indices'], obs['entry_indices'][indices])
                np.testing.assert_array_equal(data['cusum_0.0005'], obs['cusum_0.0005'][indices])
                self.assertTrue(np.all(obs['retained'][indices]))
                self.assertEqual(data['X'].shape[1], 28)
                self.assertEqual(schema['feature_windows_unit'], 'observed_candles')
                self.assertNotIn('outcomes', data.files)
            self.assertGreater(artifacts['dataset']['bytes'], 0)

    def test_reserved_quotes_rejected_before_build(self):
        protocol = load_protocol(ROOT/'configs/multiyear_v1.json')
        spec = json.loads((ROOT/'configs/session_dataset_v1.json').read_text())
        start = utc_epoch(protocol['development'][0])
        clock = SessionClock(start, np.ones(1100000, dtype=bool))
        price = Decimal('1.1')
        c = Candle(datetime(2024, 1, 1, tzinfo=timezone.utc), price, price, price, price)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, 'Reserved'):
            build([c], protocol, spec, clock, Path(directory))

    def test_serialization_rejects_objects_and_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'data.npz'
            with self.assertRaises(ValueError):
                save_arrays(path, {'bad': np.array([{}], dtype=object)})
            save_arrays(path, {'x': np.array([1., np.nan])})
            with self.assertRaises(FileExistsError):
                save_arrays(path, {'x': np.array([2.])})

    def test_historical_comparison_totals(self):
        months = historical_months(ROOT/'docs/experiments/multiyear-v1-data.md')
        self.assertEqual(sum(m['retained'] for m in months.values()), 558224)
        self.assertEqual(sum(m['candidates'] for m in months.values()), 1390526)
