"""Preregistered equal-update MLP comparison; immutable historical evidence."""
import argparse
import csv
import hashlib
import inspect
import json
import os
import subprocess
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.neural_network import MLPClassifier, _multilayer_perceptron, _stochastic_optimizers
from sklearn.preprocessing import StandardScaler

from . import mlp_comparison as prior
from .mlp_comparison import (ROOT, PARENT, PHASES, array_hash, versions, load_controls,
                             validate_controls)
from .cusum_continuation import paired_sensitivity, score, support
from .cusum_evidence import verify_ledger
from .cusum_research import identity_hash, prepare, restrict, write_new
from .data_audit import digest, load_development
from .fit_ledger import FitLedger
from .protocol import partition_indices

EXPERIMENT = 'mlp_adam_budget_v1'
SPEC = ROOT/'configs/mlp_adam_budget_v1.json'
PROTOCOL = ROOT/'docs/experiments/mlp-adam-budget-v1-protocol.md'


def load_contract():
    if digest(SPEC) != '865cc0327c04123f0754536725ff776a78db65fb9a8d35b0cb569c253752f2a1':
        raise ValueError('Adam budget contract differs from preregistration')
    spec = json.loads(SPEC.read_text())
    original, protocol = prior.load_contract()
    if spec['model'] != original['model'] or spec['epochs'] != original['epochs']:
        raise ValueError('Historical MLP parameters changed')
    for module in (_multilayer_perceptron, _stochastic_optimizers):
        if digest(Path(inspect.getfile(module))) != spec['sklearn_source_sha256'][module.__name__]:
            raise ValueError('Incremental optimizer implementation changed')
    return spec, protocol


class BudgetReached(Exception):
    """Internal sentinel raised before any extra backprop or Adam update."""


class BudgetClassifier(MLPClassifier):
    def _backprop(self, X, y, sample_weight, *args):
        if self._optimizer.t == self.update_budget:
            raise BudgetReached
        result = super()._backprop(X, y, sample_weight, *args)
        if not np.isfinite(result[0]):
            raise ValueError('Non-finite minibatch loss')
        self.batch_losses.append(float(result[0]))
        self.batch_sizes.append(len(X))
        return result


class FixedUpdates:
    def fit(self, X, y, weights, parameters, updates):
        if type(updates) is not int or updates <= 0:
            raise ValueError('Positive integer update budget required')
        self.scaler = StandardScaler().fit(X, sample_weight=weights)
        transformed = self.scaler.transform(X)
        self.model = BudgetClassifier(**parameters)
        self.model.update_budget = updates
        self.model.batch_losses, self.model.batch_sizes = [], []
        self.calls = 0
        optimizer = None
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            while optimizer is None or optimizer.t < updates:
                self.calls += 1
                try:
                    self.model.partial_fit(transformed, y, classes=[0, 1], sample_weight=weights)
                except UserWarning as error:
                    if str(error) == 'Training interrupted by user.':
                        raise KeyboardInterrupt from error
                    raise
                except BudgetReached:
                    if self.model._optimizer.t != updates:
                        raise ValueError('Premature budget sentinel')
                if optimizer is not None and self.model._optimizer is not optimizer:
                    raise ValueError('Adam optimizer reset across calls')
                optimizer = self.model._optimizer
                if not all(np.isfinite(a).all() for a in
                           self.model.coefs_ + self.model.intercepts_ + optimizer.ms + optimizer.vs):
                    raise ValueError('Non-finite neural coefficients or Adam state')
        if optimizer.t != updates or len(self.model.batch_losses) != updates:
            raise ValueError('Effective Adam update count mismatch')
        return self

    def predict(self, X):
        return self.model.predict_proba(self.scaler.transform(X))[:, 1] if len(X) else np.empty(0)


def training_contract(data, rows, spec):
    weights, contract = prior.training_contract(data, rows, spec)
    if weights is not None:
        contract.pop('sha256')
        contract.update(update_budget=spec['updates'],
                        trainer_sha256=digest(Path(__file__)),
                        sklearn_source_sha256=spec['sklearn_source_sha256'])
        contract['sha256'] = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    return weights, contract


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
        model = FixedUpdates().fit(data.X[rows], data.y[rows], weights,
                                   contract['parameters'], spec['updates'])
        losses = list(map(float, model.model.loss_curve_))
        per_epoch = (len(rows) + contract['parameters']['batch_size'] - 1)//contract['parameters']['batch_size']
        complete, remainder = divmod(spec['updates'], per_epoch)
        if len(losses) != complete or model.calls != complete + bool(remainder):
            raise ValueError('Unexpected epoch/call count')
        stable = len(losses) > 1 and abs(losses[-1] - losses[-2]) < spec['model']['tol']
        diagnostic = ('undefined_fewer_than_two_complete_epochs' if len(losses) < 2 else
                      'training_loss_stabilized' if stable else 'training_loss_not_stabilized')
        partial_sizes = model.model.batch_sizes[-remainder:] if remainder else []
        partial_loss = float(np.average(model.model.batch_losses[-remainder:], weights=partial_sizes)) if remainder else None
        report.update(status='succeeded', loss_curve=losses, epochs_completed=complete,
                      partial_fit_calls=model.calls, partial_epoch_batches=remainder,
                      partial_epoch_rows=sum(partial_sizes), partial_epoch_loss=partial_loss,
                      sample_exposures=sum(model.model.batch_sizes),
                      exposures_per_candidate=sum(model.model.batch_sizes)/len(rows),
                      optimization_diagnostic=diagnostic, finite_loss_coefficients_adam=True,
                      convergence_proven=False, updates=int(model.model._optimizer.t),
                      weight_min=float(weights.min()), weight_max=float(weights.max()),
                      weight_mean=float(weights.mean()),
                      scaler_mean_sha256=array_hash(model.scaler.mean_),
                      scaler_scale_sha256=array_hash(model.scaler.scale_),
                      adam_m_sha256=[array_hash(a) for a in model.model._optimizer.ms],
                      adam_v_sha256=[array_hash(a) for a in model.model._optimizer.vs])
    except (ValueError, ArithmeticError, RuntimeError, Warning) as error:
        model = None
        report.update(status='failed', reason=f'{type(error).__name__}: {error}')
    ledger.finish_fit(EXPERIMENT, fit_id, report['status'], report)
    cache[key] = model, report
    return model, report


def load_mlp(directory, spec, ledger_raw):
    report_path, prediction_path = directory/'report.json', directory/'predictions.csv'
    if (digest(report_path) != spec['historical_mlp_report_sha256']
            or digest(ROOT/'docs/experiments/mlp-cusum-v1.json') != digest(report_path)
            or digest(prediction_path) != spec['historical_mlp_predictions_sha256']):
        raise ValueError('Historical MLP artifact hash mismatch')
    report = json.loads(report_path.read_text())
    finished = [r for r in verify_ledger(ledger_raw) if r['kind'] == 'run_finished'
                and r['experiment'] == prior.EXPERIMENT]
    if len(finished) != 1 or finished[0]['result']['report_sha256'] != digest(report_path):
        raise ValueError('MLP not linked to canonical ledger')
    if report['versions'] != versions() or report['predictions_sha256'] != digest(prediction_path):
        raise ValueError('Historical MLP versions or predictions changed')
    for name, expected in report['hashes']['source_hashes'].items():
        if digest(ROOT/'fxnn'/name) != expected:
            raise ValueError(f'Historical MLP implementation changed: {name}')
    for name, path in [('config', prior.SPEC), ('protocol', prior.PROTOCOL), ('parent_protocol', PARENT)]:
        if digest(path) != report['hashes'][name]:
            raise ValueError(f'Historical MLP protocol changed: {name}')
    grouped = defaultdict(list)
    with prediction_path.open() as stream:
        for row in csv.DictReader(stream):
            grouped[row['fold'], row['phase'], row['universe']].append(row)
    return report, grouped


def derive_budget(report):
    unique = {}
    for fold in report['folds']:
        for phase, _, _ in PHASES:
            fit = fold['phases'][phase]['fits']['temporal']
            n = fit['support']['rows']
            batch = min(1024, n)
            expected = 20*((n+batch-1)//batch)
            if (fit['updates'] != expected or fit['epochs_completed'] != 20
                    or fit['contract']['parameters']['batch_size'] != batch):
                raise ValueError('Historical update budget derivation mismatch')
            unique[fit['fit_id']] = dict(rows=n, batch_size=batch, epochs=20, updates=expected)
    if len(unique) != 4:
        raise ValueError('Expected four unique historical temporal fits')
    return max(f['updates'] for f in unique.values()), unique


def validate_mlp(data, masks, protocol, spec, report, grouped, provenance, controls):
    if report['input_hashes'] != provenance:
        raise ValueError('Historical MLP inputs changed')
    original, _ = prior.load_contract()
    verified = {}
    for fold, previous in zip(protocol['folds'], report['folds'], strict=True):
        if fold['name'] != previous['fold']:
            raise ValueError('Historical MLP folds changed')
        base = partition_indices(data.starts, data.info_ends, protocol, fold)
        variants = {'temporal': base, **{h: restrict(base, m) for h, m in masks.items()}}
        for phase, train, evaluation in PHASES:
            old = previous['phases'][phase]
            for universe, parts in variants.items():
                _, contract = prior.training_contract(data, parts[train], original)
                fit = old['fits'][universe]
                if fit.get('contract') != contract:
                    raise ValueError('Historical MLP training contract mismatch')
                key = fold['name'], phase, universe
                records = grouped[key]
                rows = parts[evaluation]
                ev = old['evaluations'][universe]
                if identity_hash(data, rows) != ev['identity_sha256'] or len(records) != len(rows):
                    raise ValueError('Historical MLP evaluation identity mismatch')
                expected = np.column_stack((data.entry_indices[rows], data.sides[rows], data.starts[rows], data.y[rows]))
                actual = np.array([[int(r[k]) for k in ('entry_index','side','entry_epoch','y')]
                                   for r in records], dtype=np.int64).reshape(-1,4)
                if not np.array_equal(expected, actual):
                    raise ValueError('Historical MLP identity/timestamp/label mismatch')
                ps = {}
                for name, metrics in ev['scores'].items():
                    p = np.array([float(r[name]) for r in records]) if metrics is not None else None
                    if p is not None and score(data.y[rows], p) != metrics:
                        raise ValueError('Historical MLP scores mismatch')
                    if name in controls[key]:
                        other = controls[key][name]
                        if (p is None) != (other is None) or (p is not None and not np.array_equal(p, other)):
                            raise ValueError('Historical logistic probabilities differ')
                    elif name in ('mlp_temporal', 'mlp_event'):
                        ps[name.replace('mlp_', 'mlp20_')] = p
                    else:
                        raise ValueError('Unexpected historical model')
                verified[key] = {**controls[key], **ps}
    if set(grouped) != set(verified):
        raise ValueError('Unexpected historical MLP evaluation groups')
    return verified


def contrasts(universe):
    pairs = [('mlp_temporal', 'mlp20_temporal'), ('mlp_temporal', 'logistic_temporal'),
             ('mlp20_temporal', 'logistic_temporal'), ('mlp_temporal', 'constant'),
             ('mlp20_temporal', 'constant'), ('logistic_temporal', 'constant')]
    if universe != 'temporal':
        pairs += [('mlp_event', 'mlp20_event'), ('mlp_event', 'mlp_temporal'),
                  ('mlp20_event', 'mlp20_temporal'), ('logistic_event', 'logistic_temporal'),
                  ('mlp_event', 'logistic_event'), ('mlp20_event', 'logistic_event'),
                  ('mlp_event', 'constant'), ('mlp20_event', 'constant'), ('logistic_event', 'constant')]
    return pairs


def run_models(data, masks, protocol, spec, ledger, hashes, controls, old_report, output):
    reports, cache = [], {}
    fields = ['mlp_temporal', 'logistic_temporal', 'constant', 'mlp_event', 'logistic_event', 'mlp20_temporal', 'mlp20_event']
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
                    if models[universe] is not None and not fits[universe]['reused']:
                        model = models[universe]
                        trajectory = dict(loss=model.model.batch_losses, rows=model.model.batch_sizes)
                        path = output/(fit_id.replace(':', '_') + '-batches.json')
                        write_new(path, trajectory)
                        fits[universe]['batch_trajectory_sha256'] = digest(path)
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


def export_evidence(report_path, ledger_path, destination, experiment=EXPERIMENT):
    if experiment != EXPERIMENT:
        raise ValueError('Unknown evidence experiment')
    stem = experiment.replace('_', '-')
    report_bytes = Path(report_path).read_bytes()
    report = json.loads(report_bytes)
    raw_lines = Path(ledger_path).read_bytes().splitlines(keepends=True)
    records = verify_ledger(b''.join(raw_lines))
    finished = [r for r in records if r['kind'] == 'run_finished'
                and r.get('experiment') == experiment]
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    if (report.get('experiment') != experiment or len(finished) != 1
            or finished[0]['result'].get('report_sha256') != report_hash
            or finished[0]['status'] != report.get('status')
            or finished[0]['consumed_total'] != report.get('global_fits_consumed')
            or finished[0]['result'].get('fits_consumed') != report.get('fits_consumed')):
        raise ValueError('Report does not match completed ledger record')
    # Export the immutable historical prefix, even if later stages append to the ledger.
    ledger_bytes = b''.join(raw_lines[:finished[0]['sequence'] + 1])
    payloads = {f'{stem}.json': report_bytes, f'{stem}-ledger.jsonl': ledger_bytes}
    manifest = {'experiment': experiment, 'files': {
        name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()}}
    payloads[f'{stem}-evidence.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    destination = Path(destination)
    for name, value in payloads.items():
        target = destination / name
        if target.exists() and target.read_bytes() != value:
            raise ValueError(f'Existing evidence differs: {target}')
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in payloads.items():
        target = destination / name
        if not target.exists():
            with target.open('xb') as stream:
                stream.write(value)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/Users/leohermoso/FXNN/data/histdata/EURUSD'))
    parser.add_argument('--controls', type=Path, default=Path('/Users/leohermoso/FXNN-cusum-exploratory/output/cusum_temporal_v2'))
    parser.add_argument('--output', type=Path, default=ROOT/'output'/EXPERIMENT)
    parser.add_argument('--mlp-controls', type=Path, default=Path('/Users/leohermoso/FXNN-mlp-exploratory/output/mlp_cusum_v1'))
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
    if not raw.startswith((ROOT/'docs/experiments/mlp-cusum-v1-ledger.jsonl').read_bytes()):
        raise ValueError('Published ledger history lost')
    ledger = FitLedger(ledger_path)
    before = ledger.consumed()
    old, grouped = load_controls(args.controls, spec, raw)
    mlp, mlp_grouped = load_mlp(args.mlp_controls, spec, raw)
    budget, derivation = derive_budget(mlp)
    if budget != spec['updates']:
        raise ValueError('Budget differs from historical derivation')
    print('Historical artifacts verified; preparing development data (no fits).', flush=True)
    candles, provenance = load_development(args.root, protocol)
    data, masks, observations, causal = prepare(candles, protocol, spec['thresholds'])
    del candles, observations
    controls = validate_controls(data, masks, protocol, old, grouped, provenance)
    del grouped
    controls = validate_mlp(data, masks, protocol, spec, mlp, mlp_grouped, provenance, controls)
    del mlp_grouped
    print('All control training/evaluation contracts verified; reserving 12 fits.', flush=True)
    hashes = dict(code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  config=digest(SPEC), protocol=digest(PROTOCOL), parent_protocol=digest(PARENT),
                  source_hashes={p.name: digest(p) for p in sorted((ROOT/'fxnn').glob('*.py'))},
                  controls_report=digest(args.controls/'report.json'),
                  controls_predictions=digest(args.controls/'predictions.csv'), inputs=provenance,
                  mlp_report=digest(args.mlp_controls/'report.json'),
                  mlp_predictions=digest(args.mlp_controls/'predictions.csv'))
    ledger.start_run(EXPERIMENT, spec['max_model_fits'], hashes, independent_failures=True)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(experiment=EXPERIMENT, hashes=hashes, fits_before=before,
                  confirmation_opened=False, years=[2022, 2023], versions=versions(),
                  input_hashes=provenance, causal_sampling=causal,
                  control_reuse='verified_sources_code_contracts_train_and_evaluation_identities_weights_scores',
                  features=data.names, update_budget=budget, budget_derivation=derivation)
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
