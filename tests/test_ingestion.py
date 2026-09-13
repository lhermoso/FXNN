"""Synthetic CSV fixtures exercise the real ingestion path."""
import csv
import hashlib
import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fxnn.research import load_dataset


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.candles = root / 'candles.csv'
        self.labels = root / 'all_trades.csv'
        self.summary_path = root / 'summary.json'
        base = datetime(2025, 1, 31, 18, tzinfo=timezone.utc)
        self.times = [base + timedelta(minutes=i + (10 if i >= 400 else 0))
                      for i in range(900)]
        self.prices = [1.1 + i * .000001 + (i % 7) * .000002 for i in range(900)]
        with self.candles.open('w') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'open', 'high', 'low', 'close'])
            for time, price in zip(self.times, self.prices):
                writer.writerow([time.isoformat(), price, price+.0002, price-.0002, price])
        # Deliberately unsorted, opposite labels at the same entry, warmup and gap rows.
        self.rows = [self.row(i, side, y) for i, side, y in
                     [(700, 'long', 0), (300, 'long', 1), (20, 'short', 1),
                      (641, 'short', 1), (300, 'short', 0), (400, 'long', 1),
                      (640, 'short', 0), (241, 'long', 0)]]
        self.summary = {
            'input_sha256': hashlib.sha256(self.candles.read_bytes()).hexdigest(),
            'usable_labels': len(self.rows),
            'config': {'pip_size': '0.0001', 'take_profit_pips': '50',
                       'stop_loss_pips': '20', 'max_hold': '3 days, 0:00:00',
                       'bar_duration': '0:01:00'}}
        self.write()

    def row(self, i, side, y):
        return dict(entry_index=i, side=side, label=y,
                    outcome='take_profit' if y else 'stop_loss',
                    entry_time=self.times[i].isoformat(),
                    end_time=(self.times[i] + timedelta(minutes=1)).isoformat())

    def write(self):
        with self.labels.open('w') as f:
            writer = csv.DictWriter(f, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)
        self.summary_path.write_text(json.dumps(self.summary))

    def load(self):
        return load_dataset(self.candles, self.labels)

    def test_alignment_sort_direction_and_gap_exclusions(self):
        data = self.load()
        expected = [(241, 1, 0), (300, -1, 0), (300, 1, 1), (641, -1, 1), (700, 1, 0)]
        self.assertEqual(list(zip(data.entry_indices, data.sides, data.y)), expected)
        self.assertEqual(data.dropped_warmup, 3)
        for row, (i, side, _) in enumerate(expected):
            # Independent closed-form oracle, not orient_features called a second time.
            for window in (5, 15, 60, 240):
                value = side * math.log(self.prices[i-1] / self.prices[i-window-1])
                self.assertAlmostEqual(data.X[row, data.names.index(f'return_{window}')], value, places=12)
            self.assertEqual(data.X[row, data.names.index('direction')], side)
            self.assertEqual(data.starts[row], int(self.times[i].timestamp()))
            self.assertEqual(data.ends[row], data.starts[row] + 60)
            self.assertEqual(data.info_ends[row], data.starts[row] + 72*3600)

    def test_input_order_does_not_change_any_aligned_array(self):
        before = self.load()
        self.rows.reverse()
        self.write()
        after = self.load()
        for name in ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides'):
            self.assertEqual(getattr(before, name).tolist(), getattr(after, name).tolist())

    def test_rejects_inconsistent_rows_even_when_excluded_by_warmup(self):
        mutations = [
            {'entry_index': -1}, {'entry_index': 900}, {'side': 'flat'},
            {'label': 0, 'outcome': 'take_profit'}, {'outcome': 'censored'},
            {'entry_time': self.times[21].isoformat()},
            {'entry_time': self.times[20].replace(tzinfo=None).isoformat()},
            {'end_time': self.times[20].isoformat()},
            {'end_time': (self.times[20] + timedelta(hours=73)).isoformat()},
        ]
        original = dict(self.rows[2])
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.rows[2] = original | mutation
                self.write()
                with self.assertRaises(ValueError):
                    self.load()
        self.rows[2] = original

    def test_rejects_duplicate_and_selected_subset(self):
        self.rows.append(dict(self.rows[2]))
        self.write()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.load()
        self.rows = self.rows[:-2]
        self.write()
        with self.assertRaisesRegex(ValueError, 'entire'):
            self.load()

    def test_rejects_hash_and_config_mismatch(self):
        for change in ({'input_sha256': 'wrong'}, {'config': {}}):
            with self.subTest(change=change):
                original = dict(self.summary)
                self.summary.update(change)
                self.write()
                with self.assertRaises(ValueError):
                    self.load()
                self.summary = original
