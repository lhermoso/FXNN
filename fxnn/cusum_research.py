"""Preregistered development-only CUSUM experiment; deterministic stop is a result."""
import argparse
import csv
import hashlib
import json
import platform
import subprocess
from collections import Counter
from decimal import Decimal
from pathlib import Path

import numpy as np
import sklearn

from .cusum import cusum_events, interval_diagnostics, next_entries
from .data_audit import CONCLUSIVE, digest, load_development
from .features import build_features, orient_features
from .fit_ledger import FitLedger
from .labeling import Config, label_trades
from .protocol import (class_support, load_protocol, partition_indices,
                       require_training_support, utc_epoch)
from .research import Baseline, Dataset, metrics
from .temporal import uniqueness_weights

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'configs/cusum_v1.json'
PARENT = ROOT / 'configs/multiyear_v1.json'


def load_contract():
    spec = json.loads(SPEC.read_text())
    expected = dict(experiment='cusum_v1', kind='causal_cusum_comparison',
                    parent_protocol_sha256='ad288bd306d53ae07faff867ffed78c1490df9d4fc7f9b137204594bdaf191c8',
                    thresholds=[0.0005, 0.001], crossing='strict_reset_triggered',
                    internal_evaluation='intersection', max_model_fits=21, seed=0,
                    tie_tolerance=1e-12,
                    global_ledger='/Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl')
    if spec != expected or digest(PARENT) != spec['parent_protocol_sha256']:
        raise ValueError('CUSUM or parent contract differs from preregistration')
    return spec, load_protocol(PARENT)


def identity_hash(data, rows):
    identities = np.column_stack((data.entry_indices[rows], data.sides[rows]))
    return hashlib.sha256(identities.astype('<i8').tobytes()).hexdigest()


def prepare(candles, protocol, thresholds):
    begin, end = map(utc_epoch, protocol['development'])
    stamps = np.asarray([int(c.timestamp.timestamp()) for c in candles], dtype=np.int64)
    if np.any((stamps < begin) | (stamps >= end)):
        raise ValueError('Reserved candles rejected before features or labeling')
    frame = build_features(candles)
    closes = [float(c.close) for c in candles]
    close_events = {str(h): cusum_events(closes, stamps, h) for h in thresholds}
    entry_events = {h: next_entries(events, stamps) for h, events in close_events.items()}
    trades = label_trades(candles, Config(Decimal('0.0001')))
    indices = np.asarray([t.entry_index for t in trades], dtype=np.int64)
    sides = np.asarray([1 if t.side == 'long' else -1 for t in trades], dtype=np.int8)
    starts = stamps[indices]
    ends = np.asarray([int(t.end_time.timestamp()) for t in trades], dtype=np.int64)
    outcomes = np.asarray([t.outcome for t in trades])
    conclusive = np.isin(outcomes, CONCLUSIVE)
    retained = conclusive & frame.valid[indices]
    # Same row order for every array: association survives two sides and dropped labels.
    rows = np.flatnonzero(retained)
    rows = rows[np.lexsort((sides[rows], starts[rows]))]
    entry, side = indices[rows], sides[rows]
    data = Dataset(orient_features(frame, entry, side),
                   (outcomes[rows] == 'take_profit').astype(np.int8), starts[rows], ends[rows],
                   starts[rows] + protocol['horizon_minutes'] * 60, entry, side,
                   frame.names, frame.groups, int((conclusive & ~frame.valid[indices]).sum()))
    masks = {h: entries[data.entry_indices] for h, entries in entry_events.items()}
    observations = dict(starts=starts, outcomes=outcomes, valid=frame.valid[indices],
                        conclusive=conclusive, retained=retained,
                        events={h: entries[indices] for h, entries in entry_events.items()})
    causal = {'candles': len(candles), 'feature_eligible_openings': int(frame.valid.sum()),
              'gap_resets': int((np.diff(stamps) != 60).sum()), 'thresholds': {}}
    for h, events in close_events.items():
        entries = entry_events[h]
        causal['thresholds'][h] = dict(closed_events=int(events.sum()),
                                      next_continuous_openings=int(entries.sum()),
                                      lost_next_opening=int(events.sum() - entries.sum()),
                                      warmup_excluded=int((entries & ~frame.valid).sum()),
                                      eligible_openings=int((entries & frame.valid).sum()),
                                      density_per_eligible_opening=float((entries & frame.valid).sum()
                                                                         / max(1, frame.valid.sum())))
    return data, masks, observations, causal


def restrict(parts, mask):
    return {name: rows[mask[rows]] for name, rows in parts.items()}


def coverage(observations, rows, mask=None):
    selected = rows if mask is None else rows[mask[rows]]
    valid = observations['valid'][selected]
    conclusive = observations['conclusive'][selected]
    counts = Counter(observations['outcomes'][selected].tolist())
    retained = int((valid & conclusive).sum())
    return dict(observed_side_candidates=len(rows), sampled_side_candidates=len(selected),
                density=len(selected) / max(1, len(rows)), outcomes=dict(counts),
                warmup_excluded_all_outcomes=int((~valid).sum()),
                conclusive_excluded_history=int((~valid & conclusive).sum()),
                feature_eligible=int(valid.sum()), retained=retained,
                retained_coverage=retained / max(1, len(rows)),
                censored_fraction=counts['censored'] / max(1, len(selected)))


def inspect_internal(data, masks, observations, protocol):
    """Inspect all preregistered internal supports before any fit, never test y."""
    plan, reports, failures = [], [], []
    common = np.logical_and.reduce(list(masks.values()))
    obs_starts = observations['starts']
    for fold in protocol['folds']:
        base = partition_indices(data.starts, data.info_ends, protocol, fold)
        variants = {'temporal': base, **{h: restrict(base, m) for h, m in masks.items()}}
        obs_parts = partition_indices(obs_starts, obs_starts + protocol['horizon_minutes'] * 60,
                                      protocol, fold)
        report = {'fold': fold['name'], 'support': {}, 'coverage': {}, 'overlap': {}}
        for name, parts in variants.items():
            report['support'][name] = {
                part: class_support(data.y[parts[part]], protocol['minimum_rows'],
                                    protocol['minimum_per_class'])
                for part in ('train', 'validation', 'refit')}
            try:
                require_training_support(data.y, parts, protocol)
            except ValueError:
                failures.append(f"{fold['name']}:{name}")
            report['coverage'][name] = {
                part: coverage(observations, obs_parts[part], observations['events'].get(name))
                for part in ('train', 'validation', 'refit')}
            report['overlap'][name] = {
                part: interval_diagnostics(data.starts[parts[part]], data.ends[parts[part]])
                for part in ('train', 'validation', 'refit')}
        validation = base['validation'][common[base['validation']]]
        support = class_support(data.y[validation], protocol['minimum_rows'], protocol['minimum_per_class'])
        report['common_validation'] = {
            'support': support, 'identity_sha256': identity_hash(data, validation),
            'cost': {h: {'before': len(parts['validation']), 'retained': len(validation),
                         'excluded': len(parts['validation']) - len(validation)}
                     for h, parts in variants.items() if h != 'temporal'}}
        if not support['eligible']:
            failures.append(f"{fold['name']}:common_validation")
        reports.append(report)
        plan.append((fold, variants, validation, obs_parts))
    return plan, reports, failures


def choose(scores, order, tolerance=1e-12):
    best = min(scores[name]['log_loss'] for name in order)
    return next(name for name in order if scores[name]['log_loss'] <= best + tolerance)


def safe_metrics(y, p):
    if not len(y):
        return dict(rows=0, positives=0, log_loss=None, brier=None,
                    average_precision=None, roc_auc=None, thresholds={})
    return metrics(y, p)


def fit_score(data, train, evaluation, constant, ledger, fit_id, fold, parameters, hashes):
    ledger.start_fit('cusum_v1', fit_id, fold, parameters,
                     {**hashes, 'train_identities': identity_hash(data, train),
                      'evaluation_identities': identity_hash(data, evaluation)})
    try:
        weights = uniqueness_weights(data.starts[train], data.ends[train])
        X = data.X[:, :0] if constant else data.X
        model = Baseline().fit(X[train], data.y[train], weights)
        prediction = model.predict(X[evaluation]) if len(evaluation) else np.empty(0)
        score = safe_metrics(data.y[evaluation], prediction)
        ledger.finish_fit('cusum_v1', fit_id, 'succeeded',
                          dict(metrics=score, prior=model.prior, train_rows=len(train),
                               weight_min=float(weights.min()), weight_max=float(weights.max())))
        return model, prediction, score
    except BaseException as error:
        ledger.finish_fit('cusum_v1', fit_id, 'failed',
                          {'error': f'{type(error).__name__}: {error}'})
        raise


def run_models(data, masks, observations, plan, protocol, spec, ledger, hashes, output):
    reports = []
    with (output / 'predictions.csv').open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['fold', 'entry_index', 'side', 'entry_epoch', 'y',
                         'temporal', 'constant', 'cusum'])
        for fold, variants, common, obs_parts in plan:
            name = fold['name']
            scores = {}
            order = ['constant', 'temporal', *masks]
            for method in order:
                train = variants['temporal' if method == 'constant' else method]['train']
                _, _, scores[method] = fit_score(
                    data, train, common, method == 'constant', ledger, f'{name}:inner:{method}',
                    name, {'phase': 'inner', 'method': method, 'C': 1.0, 'max_iter': 1000}, hashes)
            selected = choose(scores, list(masks), spec['tie_tolerance'])
            recommendation = choose(scores, order, spec['tie_tolerance'])
            test = variants[selected]['test']
            predictions, external, models = {}, {}, {}
            for method in ('constant', 'temporal', selected):
                train = variants['temporal' if method == 'constant' else method]['refit']
                models[method], predictions[method], external[method] = fit_score(
                    data, train, test, method == 'constant', ledger, f'{name}:refit:{method}',
                    name, {'phase': 'refit', 'method': method, 'C': 1.0, 'max_iter': 1000}, hashes)
            # External support is descriptive only, after all external predictions exist.
            support = class_support(data.y[test], protocol['minimum_rows'], protocol['minimum_per_class'])
            full = variants['temporal']['test']
            separate = {method: safe_metrics(data.y[full], models[method].predict(
                data.X[full, :0] if method == 'constant' else data.X[full])) if len(full)
                else safe_metrics(data.y[full], np.empty(0)) for method in ('constant', 'temporal')}
            report = dict(fold=name, inner_scores=scores, selected_threshold=selected,
                          inner_recommendation=recommendation, common_external_scores=external,
                          external_support=support, external_identity_sha256=identity_hash(data, test),
                          temporal_universe_separate=separate,
                          external_coverage={method: coverage(observations, obs_parts['test'],
                                                             observations['events'].get(method))
                                             for method in ('temporal', selected)},
                          external_overlap={method: interval_diagnostics(data.starts[variants[method]['test']],
                                                                         data.ends[variants[method]['test']])
                                            for method in ('temporal', selected)})
            for j, row in enumerate(test):
                writer.writerow([name, int(data.entry_indices[row]), int(data.sides[row]),
                                 int(data.starts[row]), int(data.y[row]), predictions['temporal'][j],
                                 predictions['constant'][j], predictions[selected][j]])
            stream.flush()
            write_new(output / f'{name}.json', report)
            reports.append(report)
            print(f'{name}: completed; selected h={selected}', flush=True)
    return reports


def conclusion(reports):
    if not all(r['external_support']['eligible'] for r in reports):
        return 'inconclusive_external_support'
    losses, briers = [], []
    for report in reports:
        score = report['common_external_scores']
        event, temporal = score[report['selected_threshold']], score['temporal']
        losses.append(event['log_loss'] < temporal['log_loss'])
        briers.append(event['brier'] - temporal['brier'])
    return ('consistent_exploratory_classification_gain' if all(losses) and np.mean(briers) <= 0
            else 'no_consistent_gain_preserve_temporal_control')


def write_new(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/Users/leohermoso/FXNN/data/histdata/EURUSD'))
    parser.add_argument('--output', type=Path, default=ROOT / 'output/cusum_v1')
    parser.add_argument('--initialize-ledger', action='store_true',
                        help='Explicitly initialize canonical ledger from verified #4 zero-fit audit')
    args = parser.parse_args()
    spec, protocol = load_contract()
    if args.output.exists():
        parser.error('Output exists; preserve scientific attempt')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        parser.error('Commit code and preregistration before real experiment')
    hashes = {'code_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'cusum_protocol': digest(SPEC), 'parent_protocol': digest(PARENT),
              'source_hashes': {p.name: digest(p) for p in sorted((ROOT / 'fxnn').glob('*.py'))}}
    ledger = FitLedger(spec['global_ledger'])
    if args.initialize_ledger:
        ledger.initialize(0, {'report': 'docs/experiments/multiyear-v1-data.md',
                              'report_sha256': digest(ROOT / 'docs/experiments/multiyear-v1-data.md'),
                              'inspection': 'No prior #5-#9 attempts in existing result worktrees; #4 fit count zero'})
    before = ledger.consumed()
    ledger.start_run(spec['experiment'], spec['max_model_fits'], hashes)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(experiment=spec['experiment'], hashes=hashes, fits_before=before,
                  confirmation_opened=False, years=[2022, 2023],
                  versions=dict(python=platform.python_version(), numpy=np.__version__, sklearn=sklearn.__version__))
    try:
        candles, provenance = load_development(args.root, protocol)
        report['input_hashes'] = provenance
        data, masks, observations, causal = prepare(candles, protocol, spec['thresholds'])
        report['causal_sampling'] = causal
        plan, preflight, failures = inspect_internal(data, masks, observations, protocol)
        report.update(internal_preflight=preflight, support_failures=failures)
        write_new(args.output / 'preflight.json', report)
        if failures:
            report['status'] = 'stopped_insufficient_internal_support'
            report['conclusion'] = 'Inconclusive predictability; no models fitted and no external metrics. No profit inference.'
        else:
            report['folds'] = run_models(data, masks, observations, plan, protocol, spec, ledger,
                                        {**hashes, 'inputs': provenance}, args.output)
            report['status'] = 'completed'
            report['conclusion'] = conclusion(report['folds'])
        report.update(fits_consumed=ledger.consumed() - before, global_fits_consumed=ledger.consumed())
        write_new(args.output / 'report.json', report)
        ledger.finish_run(spec['experiment'], report['status'],
                          dict(report_sha256=digest(args.output / 'report.json'),
                               output=str(args.output), fits_consumed=report['fits_consumed']))
    except BaseException as error:
        write_new(args.output / 'failure.json', {**report, 'error': f'{type(error).__name__}: {error}',
                                                'global_fits_consumed': ledger.consumed()})
        ledger.finish_run(spec['experiment'], 'failed', {'error': f'{type(error).__name__}: {error}'})
        raise
    print(json.dumps({k: report[k] for k in ('status', 'fits_consumed', 'global_fits_consumed', 'conclusion')}))


if __name__ == '__main__':
    main()
