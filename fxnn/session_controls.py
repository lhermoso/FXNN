"""Preregistered paired prior/regularization controls; session artifacts only."""
import argparse
import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression, _logistic
from sklearn.preprocessing import StandardScaler

from .cusum_continuation import paired_sensitivity, score, support, technical_reason
from .cusum_evidence import verify_ledger
from .cusum_research import identity_hash
from .data_audit import digest
from .fit_ledger import FitLedger
from .mlp_comparison import array_hash, versions, PHASES
from .session_dataset import save_arrays, write_json
from .session_models import load_data, open_weights, predict_state

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = 'session_controls_v1'
SPEC = ROOT/'configs/session_controls_v1.json'
PROTOCOL = ROOT/'docs/experiments/session-controls-v1-protocol.md'
PAIRS = [('logistic_event', 'constant_event'),
         ('logistic_equal', 'logistic_event'),
         ('logistic_equal', 'logistic_temporal'),
         ('logistic_equal', 'constant_event'),
         ('constant_event', 'constant_temporal')]
CONTROL_NAMES = {'constant_temporal': 'constant:temporal',
                 'logistic_temporal': 'logistic:temporal',
                 'logistic_event': 'logistic:{h}'}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def contract_hash(contract):
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()


def equal_c(n_temporal, n_event):
    check(type(n_temporal) is int and type(n_event) is int
          and 0 < n_event <= n_temporal, 'Invalid training support for C')
    return n_temporal / n_event


def training_contract(data, rows, weights):
    return dict(identities=identity_hash(data, rows), features=data.names,
                arrays={k: array_hash(getattr(data, k)[rows])
                        for k in ('X', 'y', 'starts', 'ends', 'info_ends')},
                weights_sha256=array_hash(weights), versions=versions(),
                weights_clock='scheduled_open_minutes')


def verify_fit(data, rows, clock, fit, source, records, memo):
    """Verify old fit against exact local training inputs and append-only ledger."""
    check(fit['status'] == 'succeeded', 'Unavailable source control')
    contract = fit['contract']; key = contract_hash(contract)
    check(key == fit['contract_sha256'], 'Control contract hash changed')
    # Recheck row identities even for aliases. Dataset arrays are frozen upstream.
    check(identity_hash(data, rows) == contract['identities'], 'Control train identities changed')
    if key in memo:
        return memo[key]
    weights = open_weights(data, rows, clock)
    for field, value in training_contract(data, rows, weights).items():
        check(contract[field] == value, f'Control training changed: {field}')
    check(digest(source/fit['model_file']) == fit['model_sha256'], 'Control model bytes changed')
    starts = [r for r in records if r['kind'] == 'fit_started'
              and r.get('experiment') == 'session_models_v1' and r['fit_id'] == fit['fit_id']]
    ends = [r for r in records if r['kind'] == 'fit_finished'
            and r.get('experiment') == 'session_models_v1' and r['fit_id'] == fit['fit_id']]
    check(len(starts) == len(ends) == 1, 'Control ledger linkage')
    check(starts[0]['hashes']['training_contract_sha256'] == key
          and starts[0]['sequence'] < ends[0]['sequence']
          and ends[0]['status'] == 'succeeded'
          and ends[0]['result']['model_sha256'] == fit['model_sha256'], 'Control ledger result')
    with np.load(source/fit['model_file'], allow_pickle=False) as archive:
        state = {k: archive[k] for k in archive.files}
    if contract['family'] == 'constant':
        np.testing.assert_allclose(state['prior'], np.average(data.y[rows], weights=weights), rtol=1e-12)
    else:
        mean = np.average(data.X[rows], weights=weights, axis=0)
        scale = np.sqrt(np.average((data.X[rows]-mean)**2, weights=weights, axis=0))
        scale[scale == 0] = 1
        np.testing.assert_allclose(state['mean'], mean, rtol=1e-9, atol=1e-12)
        np.testing.assert_allclose(state['scale'], scale, rtol=1e-9, atol=1e-12)
    memo[key] = state
    return state


def verify_sources(data, masks, parts, clock, old, source, raw):
    """Read-only preflight: all reused controls and paired predictions, before fits."""
    records = verify_ledger(raw); memo = {}; values = 0
    for fold in old['folds']:
        name = fold['fold']
        for phase, train, test in PHASES:
            result = fold['phases'][phase]
            for h, mask in masks.items():
                rows = parts[name][test]; rows = rows[mask[rows]]
                ev = result['evaluations'][h]
                check(identity_hash(data, rows) == ev['identity_sha256'], 'Control evaluation identities')
                check(digest(source/ev['predictions_file']) == ev['predictions_sha256'], 'Control prediction bytes')
                with np.load(source/ev['predictions_file'], allow_pickle=False) as pred:
                    np.testing.assert_array_equal(pred['rows'], rows)
                    for field in ('entry_indices', 'sides', 'starts', 'y'):
                        np.testing.assert_array_equal(pred[field], getattr(data, field)[rows])
                    for model, request in CONTROL_NAMES.items():
                        fit = result['fits'][request.format(h=h)]
                        tr = parts[name][train]
                        if model == 'logistic_event':
                            tr = tr[mask[tr]]
                        state = verify_fit(data, tr, clock, fit, source, records, memo)
                        old_name = 'constant' if model == 'constant_temporal' else model
                        p = predict_state(state, data.X[rows])
                        np.testing.assert_array_equal(p, pred[old_name])
                        check(score(data.y[rows], p) == ev['scores'][old_name], 'Control metrics changed')
                        values += len(rows)
    return dict(unique_controls=len(memo), reproduced_probabilities=values)


def fit_new(data, rows, temporal_rows, family, spec, clock, ledger, fit_id, fold,
            hashes, cache, output):
    check(family in ('constant', 'logistic'), 'Unsupported control family')
    reason = technical_reason(data, rows, family == 'constant')
    if reason:
        return None, dict(status='technically_unavailable', reason=reason, fit_id=None)
    weights = open_weights(data, rows, clock)
    check(np.isfinite(weights).all() and np.all(weights > 0), 'Invalid training weights')
    np.testing.assert_allclose(weights.mean(), 1., rtol=1e-12)
    c = equal_c(len(temporal_rows), len(rows))
    params = dict(spec['logistic'], C=c) if family == 'logistic' else {}
    contract = dict(training_contract(data, rows, weights), family=family, parameters=params,
                    temporal_identities=identity_hash(data, temporal_rows), n_temporal=len(temporal_rows),
                    n_event=len(rows), runner_sha256=digest(Path(__file__)),
                    logistic_source_sha256=spec['logistic_source_sha256'])
    key = contract_hash(contract)
    if key in cache:
        state, report = cache[key]
        return state, dict(report, reused=True, requested_fit_id=fit_id)
    report = dict(fit_id=fit_id, status='started', reused=False, contract=contract,
                  contract_sha256=key, support=support(data.y[rows]),
                  weight_sum=float(weights.sum()), weight_mean=float(weights.mean()),
                  C=c if family == 'logistic' else None,
                  relative_l2=1/(c*weights.sum()) if family == 'logistic' else None)
    ledger.start_fit(EXPERIMENT, fit_id, fold, params, dict(hashes, training_contract_sha256=key))
    state = None
    try:
        X, y = data.X[rows], data.y[rows]
        if family == 'constant':
            state = dict(kind=np.array('constant'), prior=np.array(np.average(y, weights=weights)))
            expected = np.full(min(257, len(rows)), float(state['prior']))
        else:
            scaler = StandardScaler().fit(X, sample_weight=weights)
            model = LogisticRegression(**params)
            with warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                model.fit(scaler.transform(X), y, sample_weight=weights)
            state = dict(kind=np.array('logistic'), mean=scaler.mean_, scale=scaler.scale_,
                         coef=model.coef_, intercept=model.intercept_)
            report['iterations'] = model.n_iter_.tolist()
            expected = model.predict_proba(scaler.transform(X[:257]))[:, 1]
        check(all(np.isfinite(v).all() for k,v in state.items() if k != 'kind'), 'Nonfinite model')
        np.testing.assert_allclose(predict_state(state, X[:257]), expected, rtol=1e-12, atol=1e-12)
        file = output/'models'/f'{key}.npz'; artifact = save_arrays(file, state)
        with np.load(file, allow_pickle=False) as saved:
            np.testing.assert_allclose(predict_state(saved, X[:257]), expected, rtol=1e-12, atol=1e-12)
        report.update(status='succeeded', model_file=str(file.relative_to(output)), model_sha256=artifact['sha256'])
    except BaseException as error:
        state = None; report.update(status='failed', reason=f'{type(error).__name__}: {error}')
        ledger.finish_fit(EXPERIMENT, fit_id, 'failed', report)
        write_json(output/'models'/f'{key}.json', report); cache[key] = state, report
        if not isinstance(error, (ValueError, ArithmeticError, RuntimeError, Warning)):
            raise
        return state, report
    ledger.finish_fit(EXPERIMENT, fit_id, 'succeeded', report)
    write_json(output/'models'/f'{key}.json', report); cache[key] = state, report
    return state, report


def diagnostics(p):
    if not len(p):
        return dict(mean=None, std=None, min=None, max=None, quantiles=None)
    return dict(mean=float(p.mean()), std=float(p.std()), min=float(p.min()), max=float(p.max()),
                quantiles=np.quantile(p, [.05, .25, .5, .75, .95]).tolist())


def run_controls(data, masks, parts, clock, spec, old, source, ledger, hashes, output):
    reports, cache = [], {}
    for old_fold in old['folds']:
        name = old_fold['fold']; fold = dict(fold=name, phases={})
        for phase, train, test in PHASES:
            result = {}
            for h, mask in masks.items():
                temporal = parts[name][train]; tr = temporal[mask[temporal]]
                rows = parts[name][test]; rows = rows[mask[rows]]
                states, fits = {}, {}
                for model, request in CONTROL_NAMES.items():
                    fit = old_fold['phases'][phase]['fits'][request.format(h=h)]
                    with np.load(source/fit['model_file'], allow_pickle=False) as saved:
                        states[model] = {k: saved[k] for k in saved.files}
                    fits[model] = dict(fit, source='session_models_v1')
                for model, family in [('constant_event', 'constant'), ('logistic_equal', 'logistic')]:
                    fit_id = f'{name}:{phase}:{h}:{model}'
                    states[model], fits[model] = fit_new(data, tr, temporal, family, spec, clock,
                        ledger, fit_id, name, hashes, cache, output)
                    print(f"{fit_id}: {fits[model]['status']} reused={fits[model].get('reused', False)}", flush=True)
                predictions = {k: predict_state(s, data.X[rows]) for k,s in states.items() if s is not None}
                scores = {k: score(data.y[rows], predictions[k]) if k in predictions else None for k in states}
                sensitivity = {f'{a}_minus_{b}': paired_sensitivity(data.y[rows], predictions[a], predictions[b], data.starts[rows])
                               for a,b in PAIRS if a in predictions and b in predictions}
                file = output/f'{name}_{phase}_{h}.npz'
                artifact = save_arrays(file, dict(rows=rows, y=data.y[rows], starts=data.starts[rows],
                    sides=data.sides[rows], entry_indices=data.entry_indices[rows], **predictions))
                result[h] = dict(fits=fits, scores=scores, support=support(data.y[rows]),
                    identity_sha256=identity_hash(data, rows), predictions_file=file.name,
                    predictions_sha256=artifact['sha256'], paired_sensitivity=sensitivity,
                    probability_diagnostics={k: diagnostics(p) for k,p in predictions.items()})
            fold['phases'][phase] = result
            write_json(output/f'{name}_{phase}.json', result)
        reports.append(fold)
    return reports


def conclude(folds, thresholds):
    result = {}
    for h in map(str, thresholds):
        result[h] = {}
        for a,b in PAIRS:
            scores = [f['phases']['refit'][h]['scores'] for f in folds]
            if len(scores) != 3 or any(s.get(a) is None or s.get(b) is None for s in scores):
                value = dict(status='technically_unavailable')
            elif any(s[m][k] is None for s in scores for m in (a,b) for k in ('log_loss', 'brier')):
                value = dict(status='undefined_empty_evaluation')
            else:
                ll = [s[a]['log_loss']-s[b]['log_loss'] for s in scores]
                bs = [s[a]['brier']-s[b]['brier'] for s in scores]
                value = dict(status='consistent_descriptive_gain' if all(v < 0 for v in ll) and np.mean(bs)<=0
                             else 'mixed_or_unfavorable', delta_log_loss=ll, delta_brier=bs,
                             mean_delta_brier=float(np.mean(bs)))
            result[h][f'{a}_minus_{b}'] = value
    return result


def verify_output(output, source, data, masks, parts, clock, raw):
    """No fits: reopen all arrays, verify train contracts, prior/scaler and metrics."""
    report = json.loads((output/'report.json').read_text())
    records = verify_ledger(raw); count = 0; unique = set(); probability_values = 0
    for fold in report['folds']:
        for phase, train, test in PHASES:
            for h, ev in fold['phases'][phase].items():
                rows = parts[fold['fold']][test]; rows = rows[masks[h][rows]]
                check(identity_hash(data, rows) == ev['identity_sha256'], 'Output identities changed')
                file = output/ev['predictions_file']
                check(digest(file) == ev['predictions_sha256'], 'Output predictions changed')
                with np.load(file, allow_pickle=False) as pred:
                    np.testing.assert_array_equal(pred['rows'], rows)
                    for k in ('y','starts','sides','entry_indices'):
                        np.testing.assert_array_equal(pred[k], getattr(data,k)[rows])
                    for model, fit in ev['fits'].items():
                        if fit['status'] != 'succeeded':
                            check(ev['scores'][model] is None and model not in pred, 'Failed fit has predictions')
                            continue
                        origin = source if fit.get('source') else output
                        check(digest(origin/fit['model_file']) == fit['model_sha256'], 'Export hash mismatch')
                        with np.load(origin/fit['model_file'], allow_pickle=False) as state:
                            p = predict_state(state, data.X[rows])
                            np.testing.assert_array_equal(p, pred[model])
                            check(score(data.y[rows], p) == ev['scores'][model], 'Output score mismatch')
                            check(diagnostics(p) == ev['probability_diagnostics'][model], 'Output diagnostics mismatch')
                            probability_values += len(p)
                            if fit.get('source'):
                                continue
                            c = fit['contract']; key = contract_hash(c)
                            check(key == fit['contract_sha256'], 'New contract hash')
                            temporal = parts[fold['fold']][train]; tr = temporal[masks[h][temporal]]
                            check(c['temporal_identities'] == identity_hash(data, temporal), 'Temporal support identity')
                            check(c['n_temporal'] == len(temporal) and c['n_event'] == len(tr), 'C support mismatch')
                            w = open_weights(data, tr, clock)
                            for k,v in training_contract(data,tr,w).items():
                                check(c[k] == v, f'New training contract mismatch: {k}')
                            if model == 'constant_event':
                                np.testing.assert_allclose(state['prior'], np.average(data.y[tr],weights=w), rtol=1e-12)
                            else:
                                check(c['parameters']['C'] == equal_c(len(temporal),len(tr)), 'C formula mismatch')
                                wt = open_weights(data,temporal,clock)
                                np.testing.assert_allclose(1/(c['parameters']['C']*w.sum()),1/wt.sum(),rtol=1e-12)
                                mean = np.average(data.X[tr],weights=w,axis=0)
                                scale = np.sqrt(np.average((data.X[tr]-mean)**2,weights=w,axis=0));scale[scale==0]=1
                                np.testing.assert_allclose(state['mean'],mean,rtol=1e-9,atol=1e-12)
                                np.testing.assert_allclose(state['scale'],scale,rtol=1e-9,atol=1e-12)
                            started = [r for r in records if r['kind']=='fit_started' and r.get('experiment')==EXPERIMENT and r['fit_id']==fit['fit_id']]
                            finished = [r for r in records if r['kind']=='fit_finished' and r.get('experiment')==EXPERIMENT and r['fit_id']==fit['fit_id']]
                            check(len(started)==len(finished)==1, 'New ledger linkage')
                            check(started[0]['hashes']['training_contract_sha256']==key and finished[0]['status']=='succeeded'
                                  and finished[0]['result']['model_sha256']==fit['model_sha256'], 'New ledger result')
                            unique.add(key)
                    for a,b in PAIRS:
                        if a in pred and b in pred:
                            check(paired_sensitivity(data.y[rows],pred[a],pred[b],data.starts[rows])
                                  ==ev['paired_sensitivity'][f'{a}_minus_{b}'], 'Paired sensitivity mismatch')
                count += 1
    attempted = [r for r in records if r['kind']=='fit_started' and r.get('experiment')==EXPERIMENT]
    check(len(attempted)==report['new_fits']<=16, 'Fit budget mismatch')
    check(conclude(report['folds'],[.0005,.001]) == report['conclusion'], 'Conclusion mismatch')
    return dict(status='verified', report_sha256=digest(output/'report.json'),
                unique_successful_new_models=len(unique), new_fits=len(attempted),
                prediction_archives=count, reproduced_probabilities=probability_values,
                ledger_after_sha256=hashlib.sha256(raw).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'output'/EXPERIMENT)
    args = parser.parse_args()
    check(not args.output.exists(), 'Output exists; no scientific reruns')
    check(not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(), 'Commit protocol/config/code before fits')
    spec = json.loads(SPEC.read_text())
    check(spec['experiment']==EXPERIMENT and spec['kind']=='paired_session_prior_regularization'
          and spec['max_model_fits']==16 and spec['versions']==versions(), 'Invalid config/budget/versions')
    check(spec['thresholds']==[.0005,.001] and spec['C_rule']=='N_temporal / N_event', 'Frozen control rule changed')
    check(digest(Path(inspect.getfile(_logistic)))==spec['logistic_source_sha256'], 'Logistic implementation changed')
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
        check(os.environ.get(key)=='1', f'Set {key}=1 before Python startup')
    for name,expected in spec['frozen_files'].items():
        check(digest(ROOT/name)==expected, f'Frozen input changed: {name}')
    source = ROOT/'output/session_models_v1'; dataset = ROOT/'output/session_dataset_v1'
    old = json.loads((source/'report.json').read_text())
    # Verify executed sources by Git object; the sole historical whitespace delta is accepted by AST.
    for name,expected in old['hashes']['source_hashes'].items():
        executed = subprocess.check_output(['git','show',f"{old['hashes']['code_sha']}:fxnn/{name}"],cwd=ROOT)
        check(hashlib.sha256(executed).hexdigest()==expected, 'Executed source mismatch')
        if digest(ROOT/'fxnn'/name)!=expected:
            check(name=='session_neural.py' and ast.dump(ast.parse(executed))==ast.dump(ast.parse((ROOT/'fxnn'/name).read_text())), 'Unexpected historical code change')
    ledger_path=Path(spec['global_ledger']);raw=ledger_path.read_bytes();verify_ledger(raw)
    check(hashlib.sha256(raw).hexdigest()==spec['ledger_before_sha256'], 'Ledger changed since preregistration')
    ledger=FitLedger(ledger_path);check(ledger.consumed()==spec['expected_prior_fits'], 'Budget changed')
    data,masks,parts,protocol,clock,manifest=load_data(dataset,spec)
    check(protocol['source_years']==[2022,2023], 'Reserved years')
    check(digest(dataset/'candidates.npz')==manifest['artifacts']['candidates']['sha256'], 'Candidates changed')
    preflight=verify_sources(data,masks,parts,clock,old,source,raw)
    unique={identity_hash(data,p[t]) for p in parts.values() for t in ('train','refit')}
    check(len(unique)==4, 'Expected four unique pasts')
    hashes=dict(code_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                config=digest(SPEC),protocol=digest(PROTOCOL),ledger_before=spec['ledger_before_sha256'],
                dataset=spec['dataset_sha256'],source_report=spec['frozen_files']['output/session_models_v1/report.json'],
                source_hashes={p.name:digest(p) for p in sorted((ROOT/'fxnn').glob('*.py'))})
    args.output.mkdir(parents=True,exist_ok=False);(args.output/'models').mkdir()
    (args.output/'ledger-before.jsonl').write_bytes(raw)
    write_json(args.output/'run.json',dict(spec=spec,hashes=hashes,preflight=preflight))
    ledger.start_run(EXPERIMENT,16,hashes,independent_failures=True)
    try:
        folds=run_controls(data,masks,parts,clock,spec,old,source,ledger,hashes,args.output)
        after=ledger_path.read_bytes();verify_ledger(after);check(after.startswith(raw),'Ledger prefix changed')
        report=dict(experiment=EXPERIMENT,status='completed',hashes=hashes,preflight=preflight,folds=folds,
                    conclusion=conclude(folds,spec['thresholds']),fits_before=spec['expected_prior_fits'],
                    fits_after=ledger.consumed(),new_fits=ledger.consumed()-spec['expected_prior_fits'],
                    confirmation_opened=False,profit_claim=False)
        write_json(args.output/'report.json',report)
        verification=verify_output(args.output,source,data,masks,parts,clock,after)
        for name,expected in spec['frozen_files'].items():
            check(digest(ROOT/name)==expected,f'Frozen input mutated: {name}')
        ledger.finish_run(EXPERIMENT,'completed',dict(report_sha256=digest(args.output/'report.json'),new_fits=report['new_fits']))
    except BaseException as error:
        write_json(args.output/'failure.json',dict(error=f'{type(error).__name__}: {error}',hashes=hashes))
        ledger.finish_run(EXPERIMENT,'aborted',dict(error=f'{type(error).__name__}: {error}'))
        raise
    after=ledger_path.read_bytes();verify_ledger(after);check(after.startswith(raw),'Ledger prefix changed')
    (args.output/'ledger-after.jsonl').write_bytes(after)
    verification['ledger_after_sha256']=hashlib.sha256(after).hexdigest()
    write_json(args.output/'verification.json',verification)
    print(json.dumps(dict(status='completed',new_fits=report['new_fits'],fits_after=report['fits_after'],verification=verification)),flush=True)


if __name__ == '__main__':
    main()
