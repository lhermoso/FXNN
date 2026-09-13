"""Fixed MLP experiment with epoch selection confined to inner temporal validation."""
import argparse
import csv
import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
from sklearn.metrics import log_loss
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from .features import LOOKBACK
from .research import Baseline, load_dataset, metrics
from .temporal import split_before, uniqueness_weights

SEEDS = (11, 29, 47)
CHECKPOINTS = (5, 10, 20)


def make_model(seed):
    return MLPClassifier(hidden_layer_sizes=(32, 16), activation='relu',
                         solver='adam', alpha=0.01, batch_size=1024,
                         learning_rate_init=0.001, early_stopping=False,
                         shuffle=True, random_state=seed)


def choose_epochs(X, y, weights, validation_X, validation_y,
                  seeds=SEEDS, checkpoints=CHECKPOINTS):
    if not checkpoints or min(checkpoints) < 1 or tuple(sorted(set(checkpoints))) != tuple(checkpoints):
        raise ValueError('Checkpoints must be positive, unique and increasing')
    if not seeds:
        raise ValueError('At least one seed required')
    scaler = StandardScaler().fit(X, sample_weight=weights)
    train_X = scaler.transform(X)
    valid_X = scaler.transform(validation_X)
    losses = {epoch: [] for epoch in checkpoints}
    for seed in seeds:
        model = make_model(seed)
        for epoch in range(1, max(checkpoints)+1):
            model.partial_fit(train_X, y, classes=[0, 1], sample_weight=weights)
            if epoch in losses:
                losses[epoch].append(float(log_loss(validation_y, model.predict_proba(valid_X)[:, 1], labels=[0, 1])))
    chosen = min(checkpoints, key=lambda e: (np.mean(losses[e]), e))
    return chosen, {str(e): {'seed_log_losses': values, 'mean_log_loss': float(np.mean(values))}
                    for e, values in losses.items()}


def refit_predict(X, y, weights, test_X, epochs, seeds=SEEDS):
    scaler = StandardScaler().fit(X, sample_weight=weights)
    train_X = scaler.transform(X)
    transformed_test = scaler.transform(test_X)
    predictions = []
    for seed in seeds:
        model = make_model(seed)
        for _ in range(epochs):
            model.partial_fit(train_X, y, classes=[0, 1], sample_weight=weights)
        predictions.append(model.predict_proba(transformed_test)[:, 1])
    return np.asarray(predictions)


def run_fold(data, year, month, seeds=SEEDS, checkpoints=CHECKPOINTS):
    def boundary(m):
        y, zero_month = divmod(year*12+m-1, 12)
        return int(datetime(y, zero_month+1, 1, tzinfo=timezone.utc).timestamp())
    start, end = boundary(month), boundary(month+1)
    inner_start = boundary(month-1)
    train, validation = split_before(data.starts, data.info_ends, inner_start, start,
                                     buffer_seconds=LOOKBACK*60)
    refit, test = split_before(data.starts, data.info_ends, start, end,
                              buffer_seconds=LOOKBACK*60)
    if min(map(len, (train, validation, refit, test))) < 100:
        raise ValueError('Insufficient examples per temporal partition')
    weights = uniqueness_weights(data.starts[train], data.ends[train])
    epochs, internal = choose_epochs(data.X[train], data.y[train], weights,
                                    data.X[validation], data.y[validation], seeds, checkpoints)
    refit_weights = uniqueness_weights(data.starts[refit], data.ends[refit])
    predictions = refit_predict(data.X[refit], data.y[refit], refit_weights,
                                data.X[test], epochs, seeds)
    logistic = Baseline().fit(data.X[refit], data.y[refit], refit_weights)
    p = predictions.mean(axis=0)
    report = {'outer_month': datetime.fromtimestamp(start, timezone.utc).strftime('%Y-%m'),
              'train_rows': len(train), 'validation_rows': len(validation), 'refit_rows': len(refit),
              'last_train_information_time': int(data.info_ends[refit].max()),
              'test_start': start, 'selected_epochs': epochs, 'inner_selection': internal,
              'constant': metrics(data.y[test], np.full(len(test), logistic.prior)),
              'logistic': metrics(data.y[test], logistic.predict(data.X[test])),
              'neural_ensemble': metrics(data.y[test], p),
              'individual_seeds': {str(seed): metrics(data.y[test], prediction)
                                   for seed, prediction in zip(seeds, predictions)}}
    return report, test, predictions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candles', type=Path, default=Path('data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv'))
    parser.add_argument('--labels', type=Path, default=Path('output/eurusd_2025/all_trades.csv'))
    parser.add_argument('--output', type=Path, default=Path('output/neural_v1'))
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output must be empty; preserve prior experiments')
    started = time.perf_counter()
    data = load_dataset(args.candles, args.labels)
    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    with (args.output/'predictions.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['fold', 'entry_index', 'side', 'entry_epoch_utc', 'label', 'probability', *[f'seed_{s}' for s in SEEDS]])
        for month in (7, 8, 9):
            report, test, predictions = run_fold(data, 2025, month)
            reports.append(report)
            for i, ps in zip(test, predictions.T):
                writer.writerow([report['outer_month'], data.entry_indices[i], data.sides[i], data.starts[i], data.y[i], ps.mean(), *ps])
            print(f"{report['outer_month']}: epochs={report['selected_epochs']}; "
                  f"logistic={report['logistic']['log_loss']:.5f}; neural={report['neural_ensemble']['log_loss']:.5f}", flush=True)
    protocol = Path('docs/experiments/neural-v1-protocol.md')
    report = {'experiment': 'neural_v1', 'features': data.names, 'folds': reports,
              'architecture': [len(data.names), 32, 16, 1], 'seeds': SEEDS, 'checkpoints': CHECKPOINTS,
              'estimator_parameters': make_model(SEEDS[0]).get_params(),
              'rows_after_warmup': len(data.y), 'warmup_dropped': data.dropped_warmup,
              'versions': {'python': platform.python_version(), 'numpy': np.__version__, 'sklearn': sklearn.__version__},
              'hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.candles, args.labels, protocol, Path('requirements-lock.txt'))},
              'source_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))},
              'seconds': round(time.perf_counter()-started, 3),
              'interpretation': 'Exploratory comparison on previously examined months; conclusive overlapping labels only. No PnL. Q4 not modeled.'}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
