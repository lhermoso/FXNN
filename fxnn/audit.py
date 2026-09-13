"""Audit the existing research universe without training or changing labels."""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .features import LOOKBACK
from .labeling import Candle, Config, label_trades
from .research import epoch, load_dataset
from .temporal import split_before

CONCLUSIVE = ('take_profit', 'stop_loss', 'timeout')


def counts(rows, positives):
    return {'rows': rows, 'positives': positives, 'negatives': rows-positives,
            'positive_fraction': positives / rows if rows else None}


def monthly_audit(trades, retained_keys):
    """Count mutually exclusive label exclusions and feature warmup by entry month."""
    months = defaultdict(Counter)
    seen = set()
    for trade in trades:
        key = (trade.entry_index, 1 if trade.side == 'long' else -1)
        if key in seen:
            raise ValueError('Duplicate reconstructed candidate')
        seen.add(key)
        month = months[trade.entry_time.strftime('%Y-%m')]
        month['candidates'] += 1
        month[trade.outcome] += 1
        if key in retained_keys:
            if trade.outcome not in CONCLUSIVE:
                raise ValueError('Non-conclusive candidate retained')
            month['retained'] += 1
            month['retained_positive'] += int(trade.outcome == 'take_profit')
    if not retained_keys <= seen:
        raise ValueError('Unknown retained candidate')
    result = {}
    for name, month in sorted(months.items()):
        conclusive = sum(month[outcome] for outcome in CONCLUSIVE)
        dropped = conclusive-month['retained']
        dropped_positive = month['take_profit']-month['retained_positive']
        result[name] = {
            'candidates': month['candidates'],
            'outcomes': {outcome: month[outcome] for outcome in
                         ('take_profit', 'stop_loss', 'timeout', 'censored', 'ambiguous', 'boundary')},
            'excluded_labels': month['candidates']-conclusive,
            'conclusive': counts(conclusive, month['take_profit']),
            'excluded_feature_warmup_or_gaps': counts(dropped, dropped_positive),
            'retained': counts(month['retained'], month['retained_positive'])}
    return result


def audit(candles_path, labels_path):
    data = load_dataset(candles_path, labels_path)
    summary_path = labels_path.parent / 'summary.json'
    summary = json.loads(summary_path.read_text())
    with candles_path.open() as f:
        candles = [Candle(datetime.fromisoformat(r['timestamp']),
                          *(Decimal(r[k]) for k in ('open', 'high', 'low', 'close')))
                   for r in csv.DictReader(f)]
    trades = label_trades(candles, Config(Decimal('0.0001')))
    if dict(Counter(t.outcome for t in trades)) != summary['outcomes']:
        raise ValueError('Reconstructed outcomes disagree with original summary')
    expected = {(t.entry_index, t.side): t for t in trades if t.outcome in CONCLUSIVE}
    with labels_path.open() as f:
        for row in csv.DictReader(f):
            trade = expected.pop((int(row['entry_index']), row['side']), None)
            if (trade is None or trade.outcome != row['outcome']
                    or int(trade.entry_time.timestamp()) != epoch(row['entry_time'])
                    or int(trade.end_time.timestamp()) != epoch(row['end_time'])):
                raise ValueError('Saved label disagrees with reconstructed candidate')
    if expected:
        raise ValueError('Missing reconstructed conclusive labels')
    retained = set(zip(map(int, data.entry_indices), map(int, data.sides)))
    monthly = monthly_audit(trades, retained)
    folds = []
    for month in (7, 8, 9):
        boundary = lambda m: int(datetime(2025, m, 1, tzinfo=timezone.utc).timestamp())
        fold = {'outer_month': f'2025-{month:02}'}
        for name, start, end in (('inner', boundary(month-1), boundary(month)),
                                 ('outer', boundary(month), boundary(month+1))):
            train, test = split_before(data.starts, data.info_ends, start, end,
                                       buffer_seconds=LOOKBACK*60)
            in_month = (data.starts >= start) & (data.starts < end)
            fold[name] = {
                'training_rows': len(train),
                'training_excluded_horizon_and_buffer': int((data.starts < start).sum())-len(train),
                'evaluation_before_horizon_filter': int(in_month.sum()),
                'evaluation_excluded_right_boundary': int(in_month.sum())-len(test),
                'evaluation': counts(len(test), int(data.y[test].sum()))}
        folds.append(fold)
    return {
        'audit': 'universe_v1', 'training_performed': False,
        'reconciliation': 'All saved conclusive keys, outcomes and entry/end times match reconstruction.',
        'monthly': monthly, 'folds': folds, 'buffer_minutes': LOOKBACK,
        'hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (candles_path, labels_path, summary_path)},
        'source_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(Path(__file__).parent.glob('*.py'))},
        'limitations': [
            'Counts are descriptive; eligibility is not selected using class proportions or model scores.',
            'October–December counted only; no model training, selection or evaluation.',
            'Conclusive labels and overlapping candidates do not represent an executable portfolio.'
        ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candles', type=Path, default=Path('data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv'))
    parser.add_argument('--labels', type=Path, default=Path('output/eurusd_2025/all_trades.csv'))
    parser.add_argument('--output', type=Path, default=Path('output/universe_v1.json'))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Audit output already exists; choose a new path')
    report = audit(args.candles, args.labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f:
        f.write(json.dumps(report, indent=2) + '\n')
    print(f'Audit saved: {args.output}')


if __name__ == '__main__':
    main()
