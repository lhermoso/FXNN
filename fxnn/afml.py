"""Pre-registered afml_v1: fixed logistic model, common candidates, inner selection."""
import argparse
import csv
import hashlib
import json
import platform
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
from statsmodels.tsa.stattools import adfuller

from .audit import counts
from .features import LOOKBACK
from .fracdiff import fractional_features
from .research import Baseline, Dataset, group_importance, load_dataset, metrics
from .temporal import split_before, uniqueness_weights

ORDERS = (.25, .5, .75)
PROTOCOL = Path('docs/experiments/afml-v1-protocol.md')


@dataclass
class Prepared:
    data: Dataset
    extras: dict
    frames: dict
    logs: np.ndarray
    stamps: np.ndarray
    lookback: int
    eligibility: dict


def prepare(data, logs, stamps):
    frames = {str(d): fractional_features(logs, stamps, d) for d in ORDERS}
    keep = np.ones(len(data.y), dtype=bool)
    for frame in frames.values():
        keep &= frame.valid[data.entry_indices]
    fields = ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides')
    common = replace(data, **{field: getattr(data, field)[keep] for field in fields})
    extras = {key: frame.values[common.entry_indices] * common.sides
              for key, frame in frames.items()}
    eligibility = {}
    for month in range(1, 10):
        start = int(datetime(2025, month, 1, tzinfo=timezone.utc).timestamp())
        end = int(datetime(2025, month+1, 1, tzinfo=timezone.utc).timestamp())
        before = (data.starts >= start) & (data.starts < end)
        after = before & keep
        excluded = before & ~keep
        eligibility[f'2025-{month:02}'] = {
            'baseline': counts(int(before.sum()), int(data.y[before].sum())),
            'common': counts(int(after.sum()), int(data.y[after].sum())),
            'extra_warmup_excluded': counts(int(excluded.sum()), int(data.y[excluded].sum()))}
    return Prepared(common, extras, frames, np.asarray(logs), np.asarray(stamps),
                    max(LOOKBACK, *(f.lookback for f in frames.values())), eligibility)


def correlation(x, y):
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def diagnostic_rows(data, train):
    """Longest contiguous run of unique training entries; never join gaps."""
    rows = []
    for row in train:
        if not rows or data.entry_indices[row] != data.entry_indices[rows[-1]]:
            rows.append(int(row))
    runs = []
    for row in rows:
        if (not runs or data.entry_indices[row] != data.entry_indices[runs[-1][-1]]+1
                or data.starts[row] != data.starts[runs[-1][-1]]+60):
            runs.append([])
        runs[-1].append(row)
    return np.asarray(max(runs, key=len)[:5000] if runs else [], dtype=int)


def adf(values):
    if len(values) < 100 or np.std(values) == 0:
        return {'available': False, 'reason': 'Insufficient or constant contiguous training series'}
    stat, p, lag, n, critical = adfuller(values, maxlag=1, regression='c', autolag=None)
    return {'available': True, 'statistic': float(stat), 'pvalue': float(p),
            'lag': int(lag), 'nobs': int(n), 'critical': critical}


def diagnostics(prepared, train):
    data = prepared.data
    rows = diagnostic_rows(data, train)
    indices = data.entry_indices[rows]
    raw = prepared.logs[indices-1]
    report = {'rows': len(rows), 'first_entry_index': int(indices[0]) if len(rows) else None,
              'last_entry_index': int(indices[-1]) if len(rows) else None,
              'raw_log_price_adf': adf(raw), 'orders': {}}
    for key, frame in prepared.frames.items():
        values = frame.values[indices]
        correlations = {name: correlation(prepared.extras[key][train], data.X[train, i])
                        for i, name in enumerate(data.names)}
        usable = {name: value for name, value in correlations.items() if value is not None}
        strongest = max(usable, key=lambda name: abs(usable[name])) if usable else None
        report['orders'][key] = {
            'adf': adf(values), 'memory_correlation': correlation(raw, values) if len(rows) >= 100 else None,
            'redundancy_correlations': correlations, 'most_correlated_feature': strongest,
            'most_correlated_value': usable[strongest] if strongest else None}
    return report


def model_state(model):
    result = {'prior': model.prior}
    if model.model is not None:
        result.update(scaler_mean=model.scaler.mean_.tolist(),
                      scaler_scale=model.scaler.scale_.tolist(),
                      coefficients=model.model.coef_.tolist(),
                      intercept=model.model.intercept_.tolist(),
                      iterations=model.model.n_iter_.tolist())
    return result


def partition_state(data, rows, weights=None):
    identities = [[int(data.entry_indices[i]), int(data.sides[i])] for i in rows]
    result = counts(len(rows), int(data.y[rows].sum()))
    result['identity_sha256'] = hashlib.sha256(json.dumps(identities).encode()).hexdigest()
    if weights is not None:
        result.update(weight_min=float(weights.min()), weight_max=float(weights.max()),
                      weight_sum=float(weights.sum()))
    return result


def run_fold(prepared, month):
    data = prepared.data
    boundary = lambda m: int(datetime(2025, m, 1, tzinfo=timezone.utc).timestamp())
    inner, outer, end = boundary(month-1), boundary(month), boundary(month+1)
    train, validation = split_before(data.starts, data.info_ends, inner, outer,
                                     buffer_seconds=prepared.lookback*60)
    refit, test = split_before(data.starts, data.info_ends, outer, end,
                              buffer_seconds=prepared.lookback*60)
    if min(map(len, (train, validation, refit, test))) < 100:
        raise ValueError('Fold lacks at least 100 examples per partition')
    weights = uniqueness_weights(data.starts[train], data.ends[train])
    refit_weights = uniqueness_weights(data.starts[refit], data.ends[refit])
    matrices = {'control': data.X}
    matrices.update({key: np.column_stack((data.X, extra)) for key, extra in prepared.extras.items()})
    internal = {}
    prior = None
    for key, X in matrices.items():
        model = Baseline().fit(X[train], data.y[train], weights)
        prior = model.prior
        groups = dict(data.groups)
        if key != 'control':
            groups['fractional'] = [data.X.shape[1]]
        internal[key] = {
            'metrics': metrics(data.y[validation], model.predict(X[validation])),
            'permutation': group_importance(model, X[validation], data.y[validation], groups, seed=month),
            'model': model_state(model)}
    best = min(prepared.extras, key=lambda k: (internal[k]['metrics']['log_loss'], float(k)))
    chosen = best if internal[best]['metrics']['log_loss'] < internal['control']['metrics']['log_loss'] else 'control'
    constant_inner = metrics(data.y[validation], np.full(len(validation), prior))
    # All single-feature diagnostics have identical train and validation rows.
    singles = {name: data.X[:, i] for i, name in enumerate(data.names)}
    singles.update({f'ffd_{key}': values for key, values in prepared.extras.items()})
    sfi = {}
    for name, column in singles.items():
        X = column[:, None]
        model = Baseline().fit(X[train], data.y[train], weights)
        scores = metrics(data.y[validation], model.predict(X[validation]))
        sfi[name] = {'metrics': scores, 'model': model_state(model),
                     'log_loss_gain_over_constant': constant_inner['log_loss']-scores['log_loss']}
    diagnostic = diagnostics(prepared, train)
    external_models = {}
    predictions = {}
    for key in ('control', best):
        X = matrices[key]
        model = Baseline().fit(X[refit], data.y[refit], refit_weights)
        predictions[key] = model.predict(X[test])
        external_models[key] = model_state(model)
    predictions['constant'] = np.full(len(test), external_models['control']['prior'])
    predictions['adaptive'] = predictions[chosen]
    predictions['fractional'] = predictions.pop(best)
    report = {
        'outer_month': f'2025-{month:02}', 'best_d': float(best), 'adaptive_choice': chosen,
        'buffer_minutes': prepared.lookback,
        'inner': internal, 'inner_constant': constant_inner, 'sfi': sfi,
        'training_diagnostics': diagnostic, 'external_models': external_models,
        'partitions': {name: partition_state(data, rows, w) for name, rows, w in
                       [('train', train, weights), ('validation', validation, None),
                        ('refit', refit, refit_weights), ('test', test, None)]},
        'exclusions': {
            'inner_training_horizon_buffer': int((data.starts < inner).sum())-len(train),
            'refit_horizon_buffer': int((data.starts < outer).sum())-len(refit),
            'inner_right_boundary': int(((data.starts >= inner) & (data.starts < outer)).sum())-len(validation),
            'outer_right_boundary': int(((data.starts >= outer) & (data.starts < end)).sum())-len(test)},
        'last_train_information_epoch': int(data.info_ends[train].max()),
        'last_refit_information_epoch': int(data.info_ends[refit].max()),
        'external': {name: metrics(data.y[test], p) for name, p in predictions.items()},
        'fit_count': len(matrices)+len(singles)+2}
    return report, test, predictions, (train, weights, refit, refit_weights)


def stability(folds):
    result = {'sfi': {}, 'permutation': {}}
    for name in folds[0]['sfi']:
        values = [fold['sfi'][name]['log_loss_gain_over_constant'] for fold in folds]
        result['sfi'][name] = {'gains': values, 'positive_folds': sum(v > 0 for v in values)}
    for key in folds[0]['inner']:
        result['permutation'][key] = {}
        for name in folds[0]['inner'][key]['permutation']:
            values = [f['inner'][key]['permutation'][name]['mean_log_loss_increase'] for f in folds]
            result['permutation'][key][name] = {'increases': values, 'positive_folds': sum(v > 0 for v in values)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candles', type=Path, default=Path('data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv'))
    parser.add_argument('--labels', type=Path, default=Path('output/eurusd_2025/all_trades.csv'))
    parser.add_argument('--output', type=Path, default=Path('output/afml_v1'))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Experiment output already exists; preserve it and do not repeat statistical search')
    protocol = PROTOCOL.read_bytes()
    committed = subprocess.check_output(['git', 'show', f'HEAD:{PROTOCOL}'])
    if protocol != committed:
        parser.error('Protocol must be committed before training')
    args.output.mkdir(parents=True)
    started = time.perf_counter()
    manifest = {
        'experiment': 'afml_v1', 'started_utc': datetime.now(timezone.utc).isoformat(),
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'versions': {'python': platform.python_version(), **{p: version(p) for p in
                     ('numpy', 'scikit-learn', 'scipy', 'statsmodels', 'pandas')}},
        'hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                   (args.candles, args.labels, PROTOCOL, Path('requirements-lock.txt'))},
        'source_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(Path(__file__).parent.glob('*.py'))}}
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    data = load_dataset(args.candles, args.labels)
    with args.candles.open() as stream:
        rows = list(csv.DictReader(stream))
    logs = np.log([float(row['close']) for row in rows])
    stamps = np.asarray([int(datetime.fromisoformat(row['timestamp']).timestamp()) for row in rows])
    prepared = prepare(data, logs, stamps)
    folds = []
    with (args.output/'predictions.csv').open('w', newline='') as stream, (args.output/'weights.csv').open('w', newline='') as ws:
        writer = csv.writer(stream)
        writer.writerow(['fold', 'entry_index', 'side', 'label', 'control', 'fractional', 'constant', 'adaptive'])
        weight_writer = csv.writer(ws)
        weight_writer.writerow(['fold', 'partition', 'entry_index', 'side', 'weight'])
        for month in (7, 8, 9):
            report, test, predictions, weight_data = run_fold(prepared, month)
            folds.append(report)
            (args.output/f'fold-{month}.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
            for j, row in enumerate(test):
                writer.writerow([month, prepared.data.entry_indices[row], prepared.data.sides[row], prepared.data.y[row],
                                 *(predictions[name][j] for name in ('control', 'fractional', 'constant', 'adaptive'))])
            for name, indices, weights in (('train', *weight_data[:2]), ('refit', *weight_data[2:])):
                for row, weight in zip(indices, weights):
                    weight_writer.writerow([month, name, prepared.data.entry_indices[row], prepared.data.sides[row], weight])
            stream.flush()
            ws.flush()
            print(f"{report['outer_month']}: d={report['best_d']}, adaptive={report['adaptive_choice']}", flush=True)
    report = {**manifest, 'folds': folds, 'eligibility': prepared.eligibility,
              'weights': {key: frame.weights.tolist() for key, frame in prepared.frames.items()},
              'lookbacks': {key: frame.lookback for key, frame in prepared.frames.items()},
              'stability': stability(folds), 'fit_count': sum(f['fit_count'] for f in folds),
              'consistent_log_loss_gain': all(f['external']['fractional']['log_loss'] < f['external']['control']['log_loss'] for f in folds),
              'seconds': time.perf_counter()-started,
              'limitations': 'Exploratory overlapping conclusive labels; no profit claim; October–December not modeled.'}
    (args.output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(f"Completed {report['fit_count']} fits in {report['seconds']:.1f}s", flush=True)


if __name__ == '__main__':
    main()
