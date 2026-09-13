"""Audit development support without fitting models or opening confirmation labels."""
import argparse
import csv
import hashlib
import json
import platform
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import numpy as np

from .features import LOOKBACK, build_features
from .labeling import Candle, Config, label_trades, validate_candles
from .protocol import (class_support, load_protocol, partition_indices,
                       require_training_support, utc_epoch)

CONCLUSIVE = ('take_profit', 'stop_loss', 'timeout')
SOURCE_INVENTORY = Path(__file__).resolve().parents[1] / 'docs/experiments/multiyear-v1-sources.json'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_development(root, protocol):
    inventory = json.loads(SOURCE_INVENTORY.read_text())
    sources = {item['year_in_source_timezone']: item for item in inventory['years']}
    candles, provenance = [], {'versioned_source_inventory': digest(SOURCE_INVENTORY)}
    begin, end = map(utc_epoch, protocol['development'])
    for year in protocol['source_years']:
        path = root / f'EURUSD_{year}_m1_bid_utc.csv'
        manifest_path = root / f'EURUSD_{year}_manifest.json'
        manifest = json.loads(manifest_path.read_text())
        if (manifest['source'] != 'HistData.com' or manifest['price_side'] != 'bid'
                or manifest['symbol'] != 'EURUSD' or manifest['timeframe'] != 'M1'
                or manifest['output_timezone'] != 'UTC'
                or manifest['source_timezone'] != 'UTC-05:00 fixed, no DST'
                or manifest['year_in_source_timezone'] != year):
            raise ValueError('Unexpected data source or normalization')
        actual = digest(path)
        if actual != manifest['csv_sha256']:
            raise ValueError('Candle hash disagrees with manifest')
        registered = sources[year]
        if any(manifest.get(key) != registered[key]
               for key in ('csv_sha256', 'archive_sha256', 'rows')):
            raise ValueError('Data version differs from preregistered source inventory')
        rows = 0
        with path.open() as stream:
            for row in csv.DictReader(stream):
                rows += 1
                stamp = datetime.fromisoformat(row['timestamp'])
                epoch = utc_epoch(row['timestamp'])
                if begin <= epoch < end:
                    candles.append(Candle(stamp, *(Decimal(row[k]) for k in
                                                  ('open', 'high', 'low', 'close'))))
        if rows != manifest['rows']:
            raise ValueError('Candle count disagrees with manifest')
        provenance[path.name] = actual
        provenance[manifest_path.name] = digest(manifest_path)
    validate_candles(candles, Config(Decimal('0.0001')))
    return candles, provenance


def audit_candles(candles, protocol):
    if protocol['lookback_minutes'] != LOOKBACK:
        raise ValueError('Audit feature history must match registered lookback')
    begin, end = map(utc_epoch, protocol['development'])
    if any(not begin <= int(c.timestamp.timestamp()) < end for c in candles):
        raise ValueError('Reserved candles rejected before features or labeling')
    frame = build_features(candles)
    trades = label_trades(candles, Config(Decimal('0.0001')))
    monthly = defaultdict(Counter)
    starts, labels = [], []
    for trade in trades:
        counts = monthly[trade.entry_time.strftime('%Y-%m')]
        counts['candidates'] += 1
        counts[trade.outcome] += 1
        if not frame.valid[trade.entry_index]:
            counts['ineligible_history_all_outcomes'] += 1
        if trade.outcome in CONCLUSIVE:
            if frame.valid[trade.entry_index]:
                positive = int(trade.outcome == 'take_profit')
                counts['retained'] += 1
                counts['retained_positive' if positive else 'retained_negative'] += 1
                starts.append(int(trade.entry_time.timestamp()))
                labels.append(positive)
            else:
                counts['conclusive_excluded_history'] += 1
    starts, labels = np.asarray(starts, dtype=np.int64), np.asarray(labels, dtype=np.int8)
    info_ends = starts + protocol['horizon_minutes'] * 60
    folds = []
    for fold in protocol['folds']:
        parts = partition_indices(starts, info_ends, protocol, fold)
        support = {name: class_support(labels[indices], protocol['minimum_rows'],
                                      protocol['minimum_per_class'])
                   for name, indices in parts.items()}
        try:
            require_training_support(labels, parts, protocol)
            training_status = 'eligible'
        except ValueError:
            training_status = 'abort_insufficient_support'
        folds.append({**fold, 'support': support, 'training_status': training_status,
                      'external_status': 'descriptive_only' if support['test']['eligible']
                                         else 'inconclusive_insufficient_support',
                      'excluded_before_refit_boundary': int((starts < utc_epoch(fold['test_start'])).sum())
                                                       - len(parts['refit'])})
    return {'monthly': {month: dict(counts) for month, counts in sorted(monthly.items())},
            'folds': folds, 'development_rows': len(candles),
            'training_performed': False, 'confirmation_opened': False,
            'gap_policy': protocol['gap_policy'],
            'economic_status': 'blocked_missing_complete_bid_ask_and_provider_calendar'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('data/histdata/EURUSD'))
    parser.add_argument('--protocol', type=Path, default=Path('configs/multiyear_v1.json'))
    parser.add_argument('--output', type=Path, default=Path('output/multiyear_v1/data_audit.json'))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Audit output exists; preserve previous attempts')
    protocol = load_protocol(args.protocol)
    candles, provenance = load_development(args.root, protocol)
    report = audit_candles(candles, protocol)
    report.update(experiment=protocol['experiment'], input_hashes=provenance,
                  protocol_sha256=digest(args.protocol),
                  source_hashes={p.name: digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
                  versions={'python': platform.python_version(), 'numpy': np.__version__})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(f'Development audit saved: {args.output}')


if __name__ == '__main__':
    main()
