"""Exploratory fixed-threshold paired comparisons; no cross-universe selection."""
import argparse
import csv
import json
import platform
import subprocess
from pathlib import Path

import numpy as np
import sklearn

from .cusum import interval_diagnostics
from .cusum_evidence import verify_ledger
from .cusum_research import coverage, identity_hash, prepare, restrict, write_new
from .data_audit import digest, load_development
from .fit_ledger import FitLedger
from .protocol import load_protocol, partition_indices
from .research import Baseline, metrics
from .temporal import uniqueness_weights

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = 'cusum_temporal_v2'
SPEC = ROOT / 'configs/cusum_temporal_v2.json'
PARENT = ROOT / 'configs/multiyear_v1.json'
PROTOCOL = ROOT / 'docs/experiments/cusum-temporal-v2-protocol.md'


def load_contract():
    spec = json.loads(SPEC.read_text())
    expected = dict(experiment=EXPERIMENT, kind='exploratory_paired_cusum_temporal',
                    parent_protocol_sha256='ad288bd306d53ae07faff867ffed78c1490df9d4fc7f9b137204594bdaf191c8',
                    thresholds=[0.0005, 0.001], max_model_fits=24,
                    global_ledger='/Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl')
    if spec != expected or digest(PARENT) != spec['parent_protocol_sha256']:
        raise ValueError('Continuation or parent differs from preregistration')
    return spec, load_protocol(PARENT)


def support(y):
    y = np.asarray(y)
    if y.ndim != 1 or not np.all((y == 0) | (y == 1)):
        raise ValueError('Expected binary labels')
    return dict(rows=len(y), positive=int(y.sum()), negative=int(len(y) - y.sum()))


def technical_reason(data, rows, constant):
    counts = support(data.y[rows])
    if not counts['rows']:
        return 'empty_training'
    if not constant and not min(counts['positive'], counts['negative']):
        return 'logistic_requires_two_classes'
    if not constant and (not data.X.shape[1] or not np.isfinite(data.X[rows]).all()):
        return 'invalid_training_features'
    if (not np.isfinite(data.starts[rows]).all() or not np.isfinite(data.ends[rows]).all()
            or np.any(data.ends[rows] <= data.starts[rows])):
        return 'invalid_training_intervals'
    return None


def score(y, p):
    counts = support(y)
    p = np.asarray(p)
    if p.shape != np.asarray(y).shape or not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError('Invalid or misaligned probabilities')
    reasons = {}
    if not len(y):
        result = {k: None for k in ('log_loss', 'brier', 'average_precision', 'roc_auc')}
        reasons.update({k: 'empty_evaluation' for k in result})
        result.update(rows=0, positives=0, thresholds={str(t): dict(
            signals=0, true_positives=0, false_positives=0, precision=None, recall=None)
            for t in (.3, .4, .5)})
    else:
        result = metrics(y, p)
        if not counts['positive']:
            reasons['average_precision'] = 'no_positives'
        if not min(counts['positive'], counts['negative']):
            reasons['roc_auc'] = 'requires_two_classes'
    for t, values in result['thresholds'].items():
        if values['precision'] is None:
            reasons[f'thresholds.{t}.precision'] = 'no_signals'
        if values['recall'] is None:
            reasons[f'thresholds.{t}.recall'] = 'no_positives'
    return {**result, 'support': counts, 'undefined_reasons': reasons}


def fit_once(data, rows, constant, ledger, fit_id, fold, hashes):
    reason = technical_reason(data, rows, constant)
    report = dict(support=support(data.y[rows]), train_identity_sha256=identity_hash(data, rows))
    if reason:
        return None, dict(report, status='technically_unavailable', reason=reason)
    ledger.start_fit(EXPERIMENT, fit_id, fold,
                     dict(constant=constant, C=1, max_iter=1000),
                     {**hashes, 'train_identities': report['train_identity_sha256']})
    try:
        weights = uniqueness_weights(data.starts[rows], data.ends[rows])
        if not np.isfinite(weights).all() or np.any(weights <= 0):
            raise ValueError('Invalid training weights')
        X = data.X[rows, :0] if constant else data.X[rows]
        model = Baseline().fit(X, data.y[rows], weights)
        report.update(status='succeeded', prior=model.prior,
                      weight_min=float(weights.min()), weight_max=float(weights.max()),
                      weight_mean=float(weights.mean()))
    except (ValueError, ArithmeticError, RuntimeError, Warning) as error:
        report.update(status='failed', reason=f'{type(error).__name__}: {error}')
        ledger.finish_fit(EXPERIMENT, fit_id, 'failed', report)
        return None, report
    ledger.finish_fit(EXPERIMENT, fit_id, 'succeeded', report)
    return model, report


def paired_sensitivity(y, event, control, starts):
    """Delete one entry-week, no refits: descriptive sensitivity, never a CI."""
    if not len(y):
        return dict(status='empty_evaluation', weeks=0, log_loss=None, brier=None)
    # Unix epoch is Thursday; subtract Monday 1969-12-29 for UTC week buckets.
    weeks = (starts + 3 * 86400) // (7 * 86400)
    unique = np.unique(weeks)
    eps = np.finfo(np.float64).eps
    def losses(p):
        p = np.clip(p, eps, 1 - eps)
        return -(y * np.log(p) + (1-y) * np.log1p(-p))
    deltas = dict(log_loss=losses(event)-losses(control), brier=(event-y)**2-(control-y)**2)
    result = dict(status='descriptive_not_confidence_interval', weeks=len(unique))
    for name, delta in deltas.items():
        leave = [float(delta[weeks != week].mean()) for week in unique] if len(unique) > 1 else []
        result[name] = dict(delta=float(delta.mean()),
                            delete_week_min=min(leave) if leave else None,
                            delete_week_max=max(leave) if leave else None)
    result['weekly_support'] = [dict(week_start_epoch=int(week*7*86400 - 3*86400),
                                     **support(y[weeks == week])) for week in unique]
    return result


def evaluate(data, rows, models):
    predictions, scores = {}, {}
    for method, model in models.items():
        if model is None:
            scores[method] = None
            continue
        p = model.predict(data.X[rows, :0] if method == 'constant' else data.X[rows]) if len(rows) else np.empty(0)
        scores[method] = score(data.y[rows], p)
        predictions[method] = p
    return predictions, dict(identity_sha256=identity_hash(data, rows),
                             support=support(data.y[rows]),
                             distinct_openings=int(len(np.unique(data.entry_indices[rows]))), scores=scores)


def run_models(data, masks, observations, protocol, ledger, hashes, output):
    reports = []
    with (output / 'predictions.csv').open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['fold', 'phase', 'universe', 'entry_index', 'side', 'entry_epoch',
                         'y', 'temporal', 'constant', 'cusum'])
        for fold in protocol['folds']:
            base = partition_indices(data.starts, data.info_ends, protocol, fold)
            variants = {'temporal': base, **{h: restrict(base, mask) for h, mask in masks.items()}}
            starts = observations['starts']
            obs_parts = partition_indices(starts, starts + protocol['horizon_minutes']*60, protocol, fold)
            report = dict(fold=fold['name'], phases={})
            for phase, train_part, eval_part in [('inner', 'train', 'validation'), ('refit', 'refit', 'test')]:
                models, fits = {}, {}
                for method in ('constant', 'temporal', *masks):
                    train = variants['temporal' if method == 'constant' else method][train_part]
                    models[method], fits[method] = fit_once(
                        data, train, method == 'constant', ledger,
                        f"{fold['name']}:{phase}:{method}", fold['name'], hashes)
                result = dict(fits=fits, evaluations={}, diagnostics={})
                for universe, parts in variants.items():
                    rows = parts[eval_part]
                    selected = {m: models[m] for m in ('temporal', 'constant')}
                    if universe != 'temporal':
                        selected['cusum'] = models[universe]
                    predictions, evaluation = evaluate(data, rows, selected)
                    if 'cusum' in predictions:
                        evaluation['paired_sensitivity'] = {
                            m: paired_sensitivity(data.y[rows], predictions['cusum'], predictions[m], data.starts[rows])
                            for m in ('temporal', 'constant') if m in predictions}
                    result['evaluations'][universe] = evaluation
                    result['diagnostics'][universe] = {
                        part: dict(support=support(data.y[parts[part]]),
                                   distinct_openings=int(len(np.unique(data.entry_indices[parts[part]]))),
                                   overlap=interval_diagnostics(data.starts[parts[part]], data.ends[parts[part]]),
                                   coverage=coverage(observations, obs_parts[part], observations['events'].get(universe)))
                        for part in (train_part, eval_part)}
                    for j, row in enumerate(rows):
                        writer.writerow([fold['name'], phase, universe, int(data.entry_indices[row]),
                                         int(data.sides[row]), int(data.starts[row]), int(data.y[row]),
                                         *[float(predictions[m][j]) if m in predictions else ''
                                           for m in ('temporal', 'constant', 'cusum')]])
                report['phases'][phase] = result
                stream.flush()
                print(f"{fold['name']}:{phase} completed", flush=True)
            write_new(output / f"{fold['name']}.json", report)
            reports.append(report)
    return reports


def conclusion(reports, thresholds):
    result = {}
    for h in thresholds:
        result[h] = {}
        for control in ('temporal', 'constant'):
            scores = [r['phases']['refit']['evaluations'][h]['scores'] for r in reports]
            if len(scores) != 3 or any(s['cusum'] is None or s[control] is None for s in scores):
                status = 'technically_unavailable_comparison'
            elif any(s[m][k] is None for s in scores for m in ('cusum', control) for k in ('log_loss', 'brier')):
                status = 'inconclusive_empty_evaluation'
            else:
                gain = all(s['cusum']['log_loss'] < s[control]['log_loss'] for s in scores)
                brier = np.mean([s['cusum']['brier'] - s[control]['brier'] for s in scores])
                status = 'consistent_descriptive_gain' if gain and brier <= 0 else 'mixed_or_unfavorable_predictive_result'
            result[h][control] = status
    return dict(descriptive=result, inference='inconclusive_under_dependence_and_informed_design',
                active_lines=['temporal', *thresholds], profit_claim=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/Users/leohermoso/FXNN/data/histdata/EURUSD'))
    parser.add_argument('--output', type=Path, default=ROOT / 'output' / EXPERIMENT)
    args = parser.parse_args()
    spec, protocol = load_contract()
    if args.output.exists():
        parser.error('Output exists; no scientific reruns')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        parser.error('Commit code and protocol before real fits')
    ledger_path = Path(spec['global_ledger'])
    raw = ledger_path.read_bytes()  # Never initialize or create missing canonical ledger.
    verify_ledger(raw)
    historical = (ROOT / 'docs/experiments/cusum-v1-ledger.jsonl').read_bytes()
    if not raw.startswith(historical):
        raise ValueError('Canonical ledger lost published history')
    ledger = FitLedger(ledger_path)
    before = ledger.consumed()
    hashes = dict(code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  config=digest(SPEC), protocol=digest(PROTOCOL), parent_protocol=digest(PARENT),
                  source_hashes={p.name: digest(p) for p in sorted((ROOT / 'fxnn').glob('*.py'))})
    ledger.start_run(EXPERIMENT, spec['max_model_fits'], hashes, independent_failures=True)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(experiment=EXPERIMENT, hashes=hashes, fits_before=before,
                  confirmation_opened=False, years=[2022, 2023],
                  versions=dict(python=platform.python_version(), numpy=np.__version__, sklearn=sklearn.__version__))
    try:
        candles, provenance = load_development(args.root, protocol)
        report['input_hashes'] = provenance
        data, masks, observations, causal = prepare(candles, protocol, spec['thresholds'])
        report['causal_sampling'] = causal
        report['folds'] = run_models(data, masks, observations, protocol, ledger,
                                     {**hashes, 'inputs': provenance}, args.output)
        report.update(status='completed', conclusion=conclusion(report['folds'], list(masks)),
                      fits_consumed=ledger.consumed()-before, global_fits_consumed=ledger.consumed(),
                      predictions_sha256=digest(args.output / 'predictions.csv'))
        write_new(args.output / 'report.json', report)
        ledger.finish_run(EXPERIMENT, report['status'], dict(
            report_sha256=digest(args.output / 'report.json'), output=str(args.output),
            fits_consumed=report['fits_consumed']))
    except BaseException as error:
        write_new(args.output / 'failure.json', dict(report, error=f'{type(error).__name__}: {error}',
                                                    global_fits_consumed=ledger.consumed()))
        ledger.finish_run(EXPERIMENT, 'failed', {'error': f'{type(error).__name__}: {error}'})
        raise
    print(json.dumps({k: report[k] for k in ('status', 'fits_consumed', 'conclusion')}))


if __name__ == '__main__':
    main()
