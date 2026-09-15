"""Fixed-model retraining on a verified session dataset, without relabeling."""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import _multilayer_perceptron, _stochastic_optimizers
from sklearn.preprocessing import StandardScaler

from .cusum_continuation import paired_sensitivity, score, support, technical_reason
from .cusum_evidence import verify_ledger
from .cusum_research import identity_hash, restrict
from .data_audit import digest
from .fit_ledger import FitLedger
from .mlp_comparison import array_hash, versions, PHASES
from .protocol import load_protocol, utc_epoch
from .research import Dataset
from .session_clock import weekly_fx_clock
from .session_data import session_partitions
from .session_dataset import write_json, save_arrays
from .session_neural import FixedUpdates
from .temporal import uniqueness_weights

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = 'session_models_v1'
SPEC = ROOT/'configs/session_models_v1.json'
PROTOCOL = ROOT/'docs/experiments/session-models-v1-protocol.md'


def load_data(directory, spec):
    manifest_path = directory/'manifest.json'
    if digest(manifest_path) != spec['dataset_manifest_sha256']:
        raise ValueError('Dataset manifest changed')
    manifest = json.loads(manifest_path.read_text())
    path = directory/'dataset.npz'
    if digest(path) != spec['dataset_sha256'] or digest(path) != manifest['artifacts']['dataset']['sha256']:
        raise ValueError('Dataset bytes changed')
    if digest(directory/'report.json') != manifest['report_sha256']:
        raise ValueError('Coverage evidence changed')
    for name, expected in manifest['hashes']['sources'].items():
        if digest(ROOT/'fxnn'/name) != expected:
            raise ValueError(f'Dataset implementation changed: {name}')
    parent = ROOT/'configs/multiyear_v1.json'
    if digest(parent) != spec['parent_protocol_sha256']:
        raise ValueError('Temporal reservation changed')
    protocol = load_protocol(parent)
    begin, end = map(utc_epoch, protocol['development'])
    clock = weekly_fx_clock(begin, end+10*86400)
    with np.load(path, allow_pickle=False) as archive:
        fields = {k: archive[k] for k in ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides')}
        data = Dataset(**fields, names=archive['feature_names'].tolist(),
                       groups=manifest['schema']['feature_groups'], dropped_warmup=0)
        if data.X.shape != (len(data.y), 28) or not np.isfinite(data.X).all():
            raise ValueError('Invalid feature matrix')
        if np.any(data.starts < begin) or np.any(data.starts >= end):
            raise ValueError('Reserved entries rejected')
        if np.any(data.ends <= data.starts) or np.any(data.ends > data.info_ends):
            raise ValueError('Invalid event intervals')
        support(data.y)
        masks = {str(h): archive[f'cusum_{h}'] for h in spec['thresholds']}
        partitions = {}
        for fold in protocol['folds']:
            calculated = session_partitions(data.starts, data.info_ends, protocol, fold,
                                            clock, archive['observed_stamps'])
            for part, rows in calculated.items():
                np.testing.assert_array_equal(rows, archive[f"{fold['name']}_{part}"])
            partitions[fold['name']] = calculated
    return data, masks, partitions, protocol, clock, manifest


def open_weights(data, rows, clock):
    starts = clock.prefix[clock.indices(data.starts[rows])]
    ends = clock.prefix[clock.indices(data.ends[rows], endpoint=True)]
    return uniqueness_weights(starts, ends)


def common_budget(partitions, batch=1024, epochs=20):
    counts = [len(p[part]) for p in partitions.values() for part in ('train', 'refit')]
    if not counts or min(counts) <= 0:
        raise ValueError('Temporal training support unavailable')
    return epochs*max((n+min(batch, n)-1)//min(batch, n) for n in counts)


def predict_state(state, X):
    """Inference from exported arrays; no estimator unpickling required."""
    kind = str(state['kind'].item())
    if kind == 'constant':
        return np.full(len(X), float(state['prior'].item()))
    z = (X-state['mean'])/state['scale']
    if kind == 'logistic':
        logits = (z @ state['coef'].T + state['intercept']).ravel()
    elif kind == 'mlp':
        hidden = np.maximum(0., z @ state['coef_0'] + state['intercept_0'])
        logits = (hidden @ state['coef_1'] + state['intercept_1']).ravel()
    else:
        raise ValueError('Unknown exported model type')
    return 1/(1+np.exp(-np.clip(logits, -709, 709)))


def fit_cached(data, rows, family, updates, spec, clock, ledger, fit_id, fold,
               hashes, cache, output):
    reason = technical_reason(data, rows, family == 'constant')
    if reason:
        return None, dict(status='technically_unavailable', reason=reason, fit_id=None)
    weights = open_weights(data, rows, clock)
    if not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError('Invalid session uniqueness weights')
    params = (dict(spec['model'], batch_size=min(spec['model']['batch_size'], len(rows)))
              if family == 'mlp' else spec['logistic'] if family == 'logistic' else {})
    contract = dict(family=family, parameters=params, updates=updates,
                    identities=identity_hash(data, rows), features=data.names,
                    arrays={k: array_hash(getattr(data, k)[rows])
                            for k in ('X', 'y', 'starts', 'ends', 'info_ends')},
                    weights_sha256=array_hash(weights), versions=versions(),
                    trainer_sha256=digest(ROOT/'fxnn/session_neural.py'),
                    weights_clock=spec['weights_clock'])
    key = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    if key in cache:
        state, report = cache[key]
        return state, dict(report, reused=True, requested_fit_id=fit_id)
    report = dict(fit_id=fit_id, reused=False, contract_sha256=key, contract=contract,
                  support=support(data.y[rows]),
                  weight_min=float(weights.min()), weight_max=float(weights.max()),
                  weight_mean=float(weights.mean()))
    ledger.start_fit(EXPERIMENT, fit_id, fold, dict(family=family, parameters=params, updates=updates),
                     {**hashes, 'training_contract_sha256': key})
    state = None
    try:
        X, y = data.X[rows], data.y[rows]
        if family == 'constant':
            state = dict(kind=np.array(family), prior=np.array(np.average(y, weights=weights)))
            expected = np.full(min(len(rows), 257), float(state['prior']))
        elif family == 'logistic':
            scaler = StandardScaler().fit(X, sample_weight=weights)
            model = LogisticRegression(**params)
            with warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                model.fit(scaler.transform(X), y, sample_weight=weights)
            state = dict(kind=np.array(family), mean=scaler.mean_, scale=scaler.scale_,
                         coef=model.coef_, intercept=model.intercept_)
            expected = model.predict_proba(scaler.transform(X[:257]))[:, 1]
            report['iterations'] = model.n_iter_.tolist()
        else:
            fitted = FixedUpdates().fit(X, y, weights, params, updates)
            model, scaler = fitted.model, fitted.scaler
            state = dict(kind=np.array(family), mean=scaler.mean_, scale=scaler.scale_,
                         coef_0=model.coefs_[0], coef_1=model.coefs_[1],
                         intercept_0=model.intercepts_[0], intercept_1=model.intercepts_[1])
            expected = fitted.predict(X[:257])
            losses = list(map(float, model.loss_curve_))
            per_epoch = (len(rows)+params['batch_size']-1)//params['batch_size']
            complete, remainder = divmod(updates, per_epoch)
            if len(losses) != complete or fitted.calls != complete+bool(remainder):
                raise ValueError('Unexpected completed epochs/calls')
            report.update(updates=int(model._optimizer.t), epochs_completed=complete,
                          partial_epoch_batches=remainder, loss_curve=losses,
                          sample_exposures=sum(model.batch_sizes),
                          optimization_diagnostic=('undefined_fewer_than_two_complete_epochs' if len(losses)<2
                            else 'training_loss_stabilized' if abs(losses[-1]-losses[-2])<1e-4
                            else 'training_loss_not_stabilized'), convergence_proven=False)
        for name, value in state.items():
            if name != 'kind' and not np.isfinite(value).all():
                raise ValueError('Nonfinite exported model')
        np.testing.assert_allclose(predict_state(state, X[:257]), expected, rtol=1e-12, atol=1e-12)
        artifact = output/'models'/f'{key}.npz'
        artifact_info = save_arrays(artifact, state)
        with np.load(artifact, allow_pickle=False) as saved:
            np.testing.assert_allclose(predict_state(saved, X[:257]), expected, rtol=1e-12, atol=1e-12)
        report.update(status='succeeded', model_file=str(artifact.relative_to(output)),
                      model_sha256=artifact_info['sha256'])
    except BaseException as error:
        state = None
        report.update(status='failed', reason=f'{type(error).__name__}: {error}')
        ledger.finish_fit(EXPERIMENT, fit_id, 'failed', report)
        write_json(output/'models'/f'{key}.json', report)
        cache[key] = state, report
        if not isinstance(error, (ValueError, ArithmeticError, RuntimeError, Warning)):
            raise
        return state, report
    ledger.finish_fit(EXPERIMENT, fit_id, 'succeeded', report)
    write_json(output/'models'/f'{key}.json', report)
    cache[key] = state, report
    return state, report


def contrasts(universe):
    pairs = [(m, 'constant') for m in ('logistic_temporal', 'mlp20_temporal', 'mlpbudget_temporal')]
    pairs += [('mlp20_temporal', 'logistic_temporal'), ('mlpbudget_temporal', 'logistic_temporal'),
              ('mlpbudget_temporal', 'mlp20_temporal')]
    if universe != 'temporal':
        pairs += [(f'{m}_event', 'constant') for m in ('logistic', 'mlp20', 'mlpbudget')]
        pairs += [(f'{m}_event', f'{m}_temporal') for m in ('logistic', 'mlp20', 'mlpbudget')]
        pairs += [('mlp20_event', 'logistic_event'), ('mlpbudget_event', 'logistic_event'),
                  ('mlpbudget_event', 'mlp20_event')]
    return pairs


def run_models(data, masks, partitions, protocol, spec, clock, ledger, hashes, output):
    budget = common_budget(partitions)
    reports, cache = [], {}
    for fold in protocol['folds']:
        variants = {'temporal': partitions[fold['name']],
                    **{h: restrict(partitions[fold['name']], m) for h, m in masks.items()}}
        report = dict(fold=fold['name'], phases={})
        for phase, train, evaluation in PHASES:
            models, fits = {}, {}
            requests = [('constant', 'temporal', 'constant', None)]
            for universe, parts in variants.items():
                n = len(parts[train]); batch = min(1024, n)
                local_updates = 20*((n+batch-1)//batch) if n else 0
                requests += [(method, universe, family, updates) for method, family, updates in
                             [('logistic', 'logistic', None), ('mlp20', 'mlp', local_updates), ('mlpbudget', 'mlp', budget)]]
            for method, universe, family, updates in requests:
                name = f'{method}:{universe}'
                fit_id = f"{fold['name']}:{phase}:{name}"
                print(f'Starting {fit_id}', flush=True)
                models[name], fits[name] = fit_cached(data, variants[universe][train], family, updates,
                    spec, clock, ledger, fit_id, fold['name'], hashes, cache, output)
                print(f"{fit_id}: {fits[name]['status']} reused={fits[name].get('reused',False)}", flush=True)
            result = dict(fits=fits, evaluations={})
            for universe, parts in variants.items():
                rows = parts[evaluation]
                selected = {'constant': models['constant:temporal'],
                            **{f'{m}_temporal': models[f'{m}:temporal'] for m in ('logistic', 'mlp20', 'mlpbudget')}}
                if universe != 'temporal':
                    selected.update({f'{m}_event': models[f'{m}:{universe}'] for m in ('logistic', 'mlp20', 'mlpbudget')})
                predictions = {m: predict_state(state, data.X[rows]) for m, state in selected.items() if state is not None}
                scores = {m: score(data.y[rows], predictions[m]) if m in predictions else None for m in selected}
                sensitivity = {f'{a}_minus_{b}': paired_sensitivity(data.y[rows], predictions[a], predictions[b], data.starts[rows])
                               for a, b in contrasts(universe) if a in predictions and b in predictions}
                archive = dict(rows=rows, entry_indices=data.entry_indices[rows], sides=data.sides[rows],
                               starts=data.starts[rows], y=data.y[rows], **predictions)
                file = output/f"{fold['name']}_{phase}_{universe}.npz"
                artifact = save_arrays(file, archive)
                result['evaluations'][universe] = dict(identity_sha256=identity_hash(data, rows),
                    support=support(data.y[rows]), scores=scores, paired_sensitivity=sensitivity,
                    predictions_file=file.name, predictions_sha256=artifact['sha256'])
            report['phases'][phase] = result
            write_json(output/f"{fold['name']}_{phase}.json", result)
        reports.append(report)
    return reports, budget


def conclude(reports, thresholds):
    result = {}
    for universe in ('temporal', *map(str, thresholds)):
        result[universe] = {}
        for a, b in contrasts(universe):
            scores = [r['phases']['refit']['evaluations'][universe]['scores'] for r in reports]
            if len(scores) != 3 or any(s[a] is None or s[b] is None for s in scores):
                status = 'technically_unavailable_comparison'
            elif any(s[m][metric] is None for s in scores for m in (a,b) for metric in ('log_loss','brier')):
                status = 'inconclusive_empty_evaluation'
            else:
                gain = all(s[a]['log_loss'] < s[b]['log_loss'] for s in scores)
                brier = np.mean([s[a]['brier']-s[b]['brier'] for s in scores])
                status = 'consistent_descriptive_gain' if gain and brier <= 0 else 'mixed_or_unfavorable_predictive_result'
            result[universe][f'{a}_minus_{b}'] = status
    return dict(descriptive=result, inference='inconclusive_under_dependence_and_informed_design', profit_claim=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT/'output/session_dataset_v1')
    parser.add_argument('--output', type=Path, default=ROOT/'output'/EXPERIMENT)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; no scientific reruns')
    if subprocess.check_output(['git','status','--porcelain'], cwd=ROOT, text=True).strip():
        parser.error('Commit code and protocol before fits')
    if digest(SPEC) != 'a35934e87dfa0ceb005629f61adc5fb5b09ee865d365be8604b20a00d71855d1':
        raise ValueError('Model config differs from preregistration')
    spec = json.loads(SPEC.read_text())
    if (spec['experiment'] != EXPERIMENT or spec['kind'] != 'fixed_models_session_dataset'
            or spec['max_model_fits'] != 40 or spec['versions'] != versions()):
        raise ValueError('Wrong config type, budget or versions')
    for module in (_multilayer_perceptron, _stochastic_optimizers):
        if digest(Path(inspect.getfile(module))) != spec['sklearn_source_sha256'][module.__name__]:
            raise ValueError('Optimizer implementation changed')
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
        if os.environ.get(key) != '1':
            raise ValueError(f'Set {key}=1 before Python startup')
    ledger_path = Path(spec['global_ledger']); raw = ledger_path.read_bytes(); verify_ledger(raw)
    ledger = FitLedger(ledger_path)
    if ledger.consumed() != spec['expected_prior_fits']:
        raise ValueError('Canonical budget changed since preregistration')
    data, masks, parts, protocol, clock, manifest = load_data(args.dataset, spec)
    hashes = dict(code_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  config=digest(SPEC), protocol=digest(PROTOCOL), dataset=spec['dataset_sha256'],
                  dataset_manifest=spec['dataset_manifest_sha256'], ledger_before=hashlib.sha256(raw).hexdigest(),
                  source_hashes={p.name:digest(p) for p in sorted((ROOT/'fxnn').glob('*.py'))})
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'models').mkdir()
    (args.output/'ledger-before.jsonl').write_bytes(raw)
    write_json(args.output/'run.json', dict(hashes=hashes, spec=spec, common_updates=common_budget(parts)))
    ledger.start_run(EXPERIMENT, spec['max_model_fits'], hashes, independent_failures=True)
    try:
        reports, budget = run_models(data,masks,parts,protocol,spec,clock,ledger,hashes,args.output)
        report = dict(experiment=EXPERIMENT, status='completed', hashes=hashes, versions=versions(),
                      common_updates=budget, folds=reports, conclusion=conclude(reports,spec['thresholds']),
                      fits_before=spec['expected_prior_fits'], fits_after=ledger.consumed(),
                      new_fits=ledger.consumed()-spec['expected_prior_fits'], confirmation_opened=False,
                      dataset_input_hashes=manifest['input_hashes'])
        write_json(args.output/'report.json', report)
        ledger.finish_run(EXPERIMENT,'completed',dict(report_sha256=digest(args.output/'report.json'),
                          new_fits=report['new_fits']))
    except BaseException as error:
        write_json(args.output/'failure.json',dict(hashes=hashes,error=f'{type(error).__name__}: {error}'))
        ledger.finish_run(EXPERIMENT,'aborted',dict(error=f'{type(error).__name__}: {error}'))
        raise
    after = ledger_path.read_bytes(); verify_ledger(after)
    if not after.startswith(raw):
        raise ValueError('Ledger prefix changed')
    (args.output/'ledger-after.jsonl').write_bytes(after)
    print(json.dumps(dict(status='completed',new_fits=report['new_fits'],total_fits=report['fits_after'])),flush=True)


if __name__ == '__main__':
    main()
