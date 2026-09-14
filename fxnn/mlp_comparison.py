"""One fixed MLP; verified historical controls; development-only paired research."""
import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from .cusum_continuation import paired_sensitivity, score, support, technical_reason
from .cusum_evidence import verify_ledger
from .cusum_research import identity_hash, prepare, restrict, write_new
from .data_audit import digest, load_development
from .fit_ledger import FitLedger
from .protocol import load_protocol, partition_indices
from .temporal import uniqueness_weights

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = 'mlp_cusum_v1'
SPEC = ROOT / 'configs/mlp_cusum_v1.json'
PROTOCOL = ROOT / 'docs/experiments/mlp-cusum-v1-protocol.md'
PARENT = ROOT / 'configs/multiyear_v1.json'
PHASES = (('inner', 'train', 'validation'), ('refit', 'refit', 'test'))


def load_contract():
    if digest(SPEC) != '931168489cc7f3f25b5f19f0383b152ec393caef8ff0809515e8ae10fba99f12':
        raise ValueError('MLP contract differs from preregistration')
    spec = json.loads(SPEC.read_text())
    if digest(PARENT) != spec['parent_protocol_sha256']:
        raise ValueError('Parent changed')
    return spec, load_protocol(PARENT)


def versions():
    return dict(python=platform.python_version(), numpy=np.__version__, sklearn=sklearn.__version__)


def array_hash(array):
    array = np.ascontiguousarray(array)
    header = json.dumps([array.dtype.str, array.shape]).encode()
    return hashlib.sha256(header + array.tobytes()).hexdigest()


def training_contract(data, rows, spec):
    reason = technical_reason(data, rows, False)
    if reason:
        return None, {'reason': reason.replace('logistic_requires', 'mlp_protocol_requires'),
                      'identity_sha256': identity_hash(data, rows), 'support': support(data.y[rows])}
    weights = uniqueness_weights(data.starts[rows], data.ends[rows])
    if not np.isfinite(weights).all() or np.any(weights <= 0):
        return None, {'reason': 'invalid_training_weights', 'support': support(data.y[rows])}
    params = {**spec['model'], 'batch_size': min(spec['model']['batch_size'], len(rows))}
    contract = dict(identity_sha256=identity_hash(data, rows), features=data.names,
                    arrays={name: array_hash(getattr(data, name)[rows])
                            for name in ('X', 'y', 'starts', 'ends', 'info_ends')},
                    weights_sha256=array_hash(weights), parameters=params,
                    epochs=spec['epochs'], versions=versions())
    contract['sha256'] = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    return weights, contract


class FixedMLP:
    def fit(self, X, y, weights, parameters, epochs):
        self.scaler = StandardScaler().fit(X, sample_weight=weights)
        transformed = self.scaler.transform(X)
        self.model = MLPClassifier(**parameters)
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConvergenceWarning)
            for _ in range(epochs):
                self.model.partial_fit(transformed, y, classes=[0, 1], sample_weight=weights)
                if not np.isfinite(self.model.loss_):
                    raise ValueError('Non-finite training loss')
                if not all(np.isfinite(a).all() for a in self.model.coefs_ + self.model.intercepts_):
                    raise ValueError('Non-finite neural coefficients')
        return self

    def predict(self, X):
        return self.model.predict_proba(self.scaler.transform(X))[:, 1] if len(X) else np.empty(0)


def fit_cached(data, rows, spec, ledger, fit_id, fold, hashes, cache):
    weights, contract = training_contract(data, rows, spec)
    if weights is None:
        return None, dict(contract, status='technically_unavailable', fit_id=None)
    key = contract['sha256']
    if key in cache:
        model, report = cache[key]
        return model, dict(report, reused=True, requested_fit_id=fit_id)
    report = dict(fit_id=fit_id, reused=False, contract=contract, support=support(data.y[rows]))
    ledger.start_fit(EXPERIMENT, fit_id, fold, contract['parameters'],
                     {**hashes, 'training_contract': contract})
    model = None
    try:
        model = FixedMLP().fit(data.X[rows], data.y[rows], weights,
                               contract['parameters'], spec['epochs'])
        losses = list(map(float, model.model.loss_curve_))
        if len(losses) != spec['epochs']:
            raise ValueError('Unexpected epoch count')
        stable = len(losses) > 1 and abs(losses[-1] - losses[-2]) < spec['model']['tol']
        report.update(status='succeeded', loss_curve=losses, epochs_completed=len(losses),
                      optimization_diagnostic='training_loss_stabilized' if stable else 'training_loss_not_stabilized',
                      convergence_proven=False,
                      updates=int(model.model._optimizer.t),
                      weight_min=float(weights.min()), weight_max=float(weights.max()),
                      weight_mean=float(weights.mean()),
                      scaler_mean_sha256=array_hash(model.scaler.mean_),
                      scaler_scale_sha256=array_hash(model.scaler.scale_))
    except (ValueError, ArithmeticError, RuntimeError, Warning) as error:
        model = None
        report.update(status='failed', reason=f'{type(error).__name__}: {error}')
    ledger.finish_fit(EXPERIMENT, fit_id, report['status'], report)
    cache[key] = model, report  # Failed attempts are also cached; never retry.
    return model, report


def load_controls(directory, spec, ledger_raw):
    """Validate immutable artifacts and implementation before loading predictions."""
    report_path, prediction_path = directory / 'report.json', directory / 'predictions.csv'
    if (digest(report_path) != spec['controls_report_sha256']
            or digest(ROOT/'docs/experiments/cusum-temporal-v2.json') != spec['controls_report_sha256']
            or digest(prediction_path) != spec['controls_predictions_sha256']):
        raise ValueError('Historical control artifact hash mismatch')
    report = json.loads(report_path.read_text())
    finished = [r for r in verify_ledger(ledger_raw) if r['kind'] == 'run_finished'
                and r['experiment'] == 'cusum_temporal_v2']
    if len(finished) != 1 or finished[0]['result']['report_sha256'] != digest(report_path):
        raise ValueError('Controls not linked to canonical ledger')
    if report['versions'] != versions() or report['predictions_sha256'] != digest(prediction_path):
        raise ValueError('Control versions or predictions changed')
    for name in ('cusum.py', 'cusum_continuation.py', 'cusum_research.py', 'data_audit.py',
                 'features.py', 'indexed.py', 'labeling.py', 'protocol.py', 'research.py', 'temporal.py'):
        if digest(ROOT/'fxnn'/name) != report['hashes']['source_hashes'][name]:
            raise ValueError(f'Control contract implementation changed: {name}')
    for name, path in [('config', ROOT/'configs/cusum_temporal_v2.json'),
                       ('protocol', ROOT/'docs/experiments/cusum-temporal-v2-protocol.md'),
                       ('parent_protocol', PARENT)]:
        if digest(path) != report['hashes'][name]:
            raise ValueError(f'Control protocol changed: {name}')
    grouped = defaultdict(list)
    with prediction_path.open() as stream:
        for row in csv.DictReader(stream):
            grouped[row['fold'], row['phase'], row['universe']].append(row)
    return report, grouped


def aligned_controls(data, rows, records, evaluation):
    if identity_hash(data, rows) != evaluation['identity_sha256'] or len(records) != len(rows):
        raise ValueError('Control evaluation identity mismatch')
    expected = np.column_stack((data.entry_indices[rows], data.sides[rows], data.starts[rows], data.y[rows]))
    actual = np.array([[int(r[k]) for k in ('entry_index', 'side', 'entry_epoch', 'y')]
                       for r in records], dtype=np.int64).reshape(-1, 4)
    if not np.array_equal(expected, actual):
        raise ValueError('Control identity, timestamp or label mismatch')
    predictions = {}
    for old, new in [('temporal', 'logistic_temporal'), ('constant', 'constant'), ('cusum', 'logistic_event')]:
        if old not in evaluation['scores']:
            continue
        if evaluation['scores'][old] is None:
            predictions[new] = None
            continue
        p = np.array([float(r[old]) for r in records])
        if score(data.y[rows], p) != evaluation['scores'][old]:
            raise ValueError('Control scores do not reproduce from saved probabilities')
        predictions[new] = p
    return predictions


def validate_controls(data, masks, protocol, old_report, grouped, provenance):
    if provenance != old_report['input_hashes']:
        raise ValueError('Control input data changed')
    verified = {}
    expected_keys = set()
    for fold, old in zip(protocol['folds'], old_report['folds'], strict=True):
        if fold['name'] != old['fold']:
            raise ValueError('Control fold mismatch')
        base = partition_indices(data.starts, data.info_ends, protocol, fold)
        variants = {'temporal': base, **{h: restrict(base, m) for h, m in masks.items()}}
        for phase, train, evaluation in PHASES:
            previous = old['phases'][phase]
            for method in ('constant', *variants):
                rows = variants['temporal' if method == 'constant' else method][train]
                fit = previous['fits'][method]
                if (identity_hash(data, rows) != fit['train_identity_sha256']
                        or support(data.y[rows]) != fit['support']):
                    raise ValueError('Control training identities or labels changed')
                if fit['status'] == 'succeeded':
                    weights = uniqueness_weights(data.starts[rows], data.ends[rows])
                    if float(np.average(data.y[rows], weights=weights)) != fit['prior']:
                        raise ValueError('Control training weights or prior changed')
                    for stat in ('min', 'max', 'mean'):
                        if float(getattr(weights, stat)()) != fit[f'weight_{stat}']:
                            raise ValueError('Control training transformation changed')
            for universe, parts in variants.items():
                key = fold['name'], phase, universe
                expected_keys.add(key)
                verified[key] = aligned_controls(data, parts[evaluation], grouped[key],
                                                 previous['evaluations'][universe])
    if set(grouped) != expected_keys:
        raise ValueError('Unexpected historical evaluation groups')
    return verified


def contrasts(universe):
    pairs = [('mlp_temporal', 'logistic_temporal'), ('mlp_temporal', 'constant'),
             ('logistic_temporal', 'constant')]
    if universe != 'temporal':
        pairs += [('mlp_event', 'logistic_event'), ('mlp_event', 'mlp_temporal'),
                  ('logistic_event', 'logistic_temporal'), ('mlp_event', 'constant'),
                  ('logistic_event', 'constant')]
    return pairs


def run_models(data, masks, protocol, spec, ledger, hashes, controls, old_report, output):
    reports, cache = [], {}
    fields = ['mlp_temporal', 'logistic_temporal', 'constant', 'mlp_event', 'logistic_event']
    with (output/'predictions.csv').open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['fold', 'phase', 'universe', 'entry_index', 'side', 'entry_epoch', 'y', *fields])
        for fold, old in zip(protocol['folds'], old_report['folds'], strict=True):
            base = partition_indices(data.starts, data.info_ends, protocol, fold)
            variants = {'temporal': base, **{h: restrict(base, m) for h, m in masks.items()}}
            report = dict(fold=fold['name'], phases={})
            for phase, train, evaluation in PHASES:
                models, fits = {}, {}
                for universe, parts in variants.items():
                    fit_id = f"{fold['name']}:{phase}:{universe}"
                    models[universe], fits[universe] = fit_cached(
                        data, parts[train], spec, ledger, fit_id, fold['name'], hashes, cache)
                    print(f"{fit_id}: {fits[universe]['status']} reused={fits[universe].get('reused', False)}", flush=True)
                result = dict(fits=fits, evaluations={},
                              control_fits=old['phases'][phase]['fits'],
                              diagnostics=old['phases'][phase]['diagnostics'])
                for universe, parts in variants.items():
                    rows = parts[evaluation]
                    ps = dict(controls[fold['name'], phase, universe])
                    for name, training in [('mlp_temporal', 'temporal'), *([] if universe == 'temporal' else [('mlp_event', universe)])]:
                        ps[name] = models[training].predict(data.X[rows]) if models[training] is not None else None
                    scores = {name: score(data.y[rows], p) if p is not None else None for name, p in ps.items()}
                    sensitivity = {f'{a}-vs-{b}': paired_sensitivity(data.y[rows], ps[a], ps[b], data.starts[rows])
                                   if ps[a] is not None and ps[b] is not None else {'status': 'technically_unavailable'}
                                   for a, b in contrasts(universe)}
                    result['evaluations'][universe] = dict(identity_sha256=identity_hash(data, rows),
                        support=support(data.y[rows]), distinct_openings=int(len(np.unique(data.entry_indices[rows]))),
                        scores=scores, paired_sensitivity=sensitivity)
                    for j, row in enumerate(rows):
                        writer.writerow([fold['name'], phase, universe, int(data.entry_indices[row]),
                            int(data.sides[row]), int(data.starts[row]), int(data.y[row]),
                            *[float(ps[m][j]) if ps.get(m) is not None else '' for m in fields]])
                report['phases'][phase] = result
                stream.flush()
            reports.append(report)
            write_new(output/f"{fold['name']}.json", report)
    return reports


def conclusion(reports, universes):
    results = {}
    for universe in universes:
        results[universe] = {}
        for a, b in contrasts(universe):
            scores = [r['phases']['refit']['evaluations'][universe]['scores'] for r in reports]
            if len(scores) != 3 or any(s[a] is None or s[b] is None for s in scores):
                status = 'technically_unavailable_comparison'
            elif any(s[m][k] is None for s in scores for m in (a, b) for k in ('log_loss', 'brier')):
                status = 'inconclusive_undefined_metrics'
            elif all(s[a]['log_loss'] < s[b]['log_loss'] for s in scores) and np.mean([s[a]['brier']-s[b]['brier'] for s in scores]) <= 0:
                status = 'consistent_descriptive_gain'
            else:
                status = 'mixed_or_unfavorable_predictive_result'
            results[universe][f'{a}-vs-{b}'] = status
    return dict(descriptive=results, inference='inconclusive_under_dependence_and_informed_design',
                initialization_scope='seed_0_only', active_lines=list(universes), profit_claim=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/Users/leohermoso/FXNN/data/histdata/EURUSD'))
    parser.add_argument('--controls', type=Path, default=Path('/Users/leohermoso/FXNN-cusum-exploratory/output/cusum_temporal_v2'))
    parser.add_argument('--output', type=Path, default=ROOT/'output'/EXPERIMENT)
    args = parser.parse_args()
    spec, protocol = load_contract()
    if args.output.exists():
        parser.error('Output exists; no scientific reruns')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        parser.error('Commit protocol, code and tests before real fits')
    if any(os.environ.get(k) != '1' for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')):
        parser.error('Set all four BLAS/OpenMP thread environment variables to 1')
    ledger_path = Path(spec['global_ledger'])
    raw = ledger_path.read_bytes()
    verify_ledger(raw)
    if not raw.startswith((ROOT/'docs/experiments/cusum-temporal-v2-ledger.jsonl').read_bytes()):
        raise ValueError('Published ledger history lost')
    ledger = FitLedger(ledger_path)
    before = ledger.consumed()
    old, grouped = load_controls(args.controls, spec, raw)
    print('Historical artifacts verified; preparing development data (no fits).', flush=True)
    candles, provenance = load_development(args.root, protocol)
    data, masks, observations, causal = prepare(candles, protocol, spec['thresholds'])
    del candles, observations
    controls = validate_controls(data, masks, protocol, old, grouped, provenance)
    del grouped
    print('All control training/evaluation contracts verified; reserving 12 fits.', flush=True)
    hashes = dict(code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  config=digest(SPEC), protocol=digest(PROTOCOL), parent_protocol=digest(PARENT),
                  source_hashes={p.name: digest(p) for p in sorted((ROOT/'fxnn').glob('*.py'))},
                  controls_report=digest(args.controls/'report.json'),
                  controls_predictions=digest(args.controls/'predictions.csv'), inputs=provenance)
    ledger.start_run(EXPERIMENT, spec['max_model_fits'], hashes, independent_failures=True)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(experiment=EXPERIMENT, hashes=hashes, fits_before=before,
                  confirmation_opened=False, years=[2022, 2023], versions=versions(),
                  input_hashes=provenance, causal_sampling=causal,
                  control_reuse='verified_sources_code_contracts_train_and_evaluation_identities_weights_scores',
                  features=data.names)
    try:
        report['folds'] = run_models(data, masks, protocol, spec, ledger, hashes, controls, old, args.output)
        report.update(status='completed', conclusion=conclusion(report['folds'], ['temporal', *masks]),
                      fits_consumed=ledger.consumed()-before, global_fits_consumed=ledger.consumed(),
                      predictions_sha256=digest(args.output/'predictions.csv'))
        write_new(args.output/'report.json', report)
        ledger.finish_run(EXPERIMENT, 'completed', dict(report_sha256=digest(args.output/'report.json'),
                         output=str(args.output), fits_consumed=report['fits_consumed']))
    except BaseException as error:
        write_new(args.output/'failure.json', dict(report, error=f'{type(error).__name__}: {error}'))
        ledger.finish_run(EXPERIMENT, 'failed', dict(error=f'{type(error).__name__}: {error}'))
        raise
    print(json.dumps(report['conclusion']))


if __name__ == '__main__':
    main()
