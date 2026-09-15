"""Unit-occurrence-weight fits with durable artifacts and terminal attempt caches."""
import json
import math
import os
from pathlib import Path
import shutil
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .cusum_continuation import support, technical_reason
from .data_audit import digest
from .experiment_fit import contract_hash, verified_model
from .mlp_comparison import array_hash, versions
from .session_models import predict_state

EXPERIMENT = 'sequential_bagging_v1'
FIELDS = ('X','y','starts','ends','info_ends','entry_indices','sides')


class ArtifactStore:
    """Free-space checks are not a physical reservation against other processes."""
    def __init__(self, root, estimate, *, minimum_safety=16*1024**3):
        self.root = Path(root)
        if type(estimate) is not int or estimate < 0:
            raise ValueError('Nonnegative output estimate required')
        self.estimate = estimate
        self.remaining = estimate
        self.safety = max(minimum_safety,math.ceil(.2*estimate))
        self.written = 0

    def check(self):
        parent = self.root
        while not parent.exists(): parent = parent.parent
        if shutil.disk_usage(parent).free <= self.remaining+self.safety:
            raise OSError('Insufficient free disk for remaining artifacts and safety margin')

    def complete(self, path):
        size = Path(path).stat().st_size
        self.written += size; self.remaining = max(0,self.remaining-size)
        return dict(sha256=digest(Path(path)),bytes=size)

    def json(self, path, value):
        self.check()
        with Path(path).open('x') as stream:
            json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        return self.complete(path)

    def arrays(self, path, values):
        self.check()
        if any(np.asarray(v).dtype.hasobject for v in values.values()):
            raise ValueError('Object arrays forbidden')
        with Path(path).open('xb') as stream:
            np.savez_compressed(stream,**values)
            stream.flush(); os.fsync(stream.fileno())
        with np.load(path,allow_pickle=False) as archive:
            if set(archive.files) != set(values): raise ValueError('Array archive schema changed')
            for k,v in values.items(): np.testing.assert_array_equal(archive[k],v)
        return self.complete(path)

    def bytes(self,path,value):
        self.check()
        with Path(path).open('xb') as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        return self.complete(path)


def training_contract(data, rows, parameters, hashes, sampler):
    return dict(experiment=EXPERIMENT,stage=8,task='dynamic',family='logistic',parameters=parameters,
                features=data.names,groups=data.groups,arrays={k:array_hash(getattr(data,k)[rows]) for k in FIELDS},
                identities=array_hash(np.column_stack((data.entry_indices[rows],data.sides[rows]))),
                weighting='unit_per_occurrence_including_duplicates',sampler=sampler,
                source_hashes=hashes,versions=versions())


def fit_unit(data, rows, parameters, ledger, fit_id, fold, hashes, sampler, cache, output, store):
    if getattr(ledger,'_experiment_aborted',False):
        raise RuntimeError('Run aborted; no later fit permitted')
    rows = np.asarray(rows,dtype=np.int64)
    contract = training_contract(data,rows,parameters,hashes,sampler)
    key = contract_hash(contract)
    if key in cache:
        state,report = cache[key]
        return state,dict(report,reused=True,requested_fit_id=fit_id)
    reason = technical_reason(data,rows,False)
    report = dict(fit_id=None if reason else fit_id,reused=False,contract=contract,contract_sha256=key,
                  support=support(data.y[rows]),status='technically_unavailable' if reason else 'in_progress')
    if reason:
        report['reason'] = reason; cache[key] = None,report
        return None,report
    try:
        ledger.start_fit(EXPERIMENT,fit_id,fold,dict(parameters=parameters,weighting=contract['weighting']),
                         {**hashes,'training_contract_sha256':key})
    except BaseException:
        ledger._experiment_aborted = True
        cache[key] = None,report
        raise
    cache[key] = None,report
    persistence = False
    output = Path(output)
    try:
        X,y = data.X[rows],data.y[rows]
        scaler = StandardScaler().fit(X)
        model = LogisticRegression(**parameters)
        with warnings.catch_warnings():
            warnings.simplefilter('error',ConvergenceWarning)
            model.fit(scaler.transform(X),y)
        state = dict(kind=np.array('logistic'),mean=scaler.mean_,scale=scaler.scale_,coef=model.coef_,intercept=model.intercept_)
        if any(not np.isfinite(v).all() for k,v in state.items() if k!='kind'):
            raise ValueError('Nonfinite exported model')
        expected = model.predict_proba(scaler.transform(X[:257]))[:,1]
        np.testing.assert_allclose(predict_state(state,X[:257]),expected,rtol=1e-12,atol=1e-12)
        persistence = True
        directory = output/'models'; directory.mkdir(exist_ok=True)
        artifact = store.arrays(directory/f'{key}.npz',state)
        report.update(status='succeeded',model_file=f'models/{key}.npz',model_sha256=artifact['sha256'],iterations=model.n_iter_.tolist())
        store.json(directory/f'{key}.json',report)
        ledger.finish_fit(EXPERIMENT,fit_id,'succeeded',report)
        cache[key] = state,report
        return state,report
    except BaseException as error:
        report = dict(report,status='failed',reason=f'{type(error).__name__}: {error}')
        cache[key] = None,report
        try:
            records = ledger.records()
            if not any(r['kind']=='fit_finished' and r.get('experiment')==EXPERIMENT and r.get('fit_id')==fit_id for r in records):
                ledger.finish_fit(EXPERIMENT,fit_id,'failed',report)
            else:
                persistence = True
        except BaseException as secondary:
            error.add_note(str(secondary)); persistence = True
        if persistence or not isinstance(error,(ValueError,ArithmeticError,RuntimeError,Warning)):
            ledger._experiment_aborted = True
            raise
        try:
            (output/'models').mkdir(exist_ok=True)
            store.json(output/'models'/f'{key}.json',report)
        except BaseException:
            ledger._experiment_aborted = True
            raise
        return None,report


def replay_unit(data, rows, parameters, ledger, hashes, sampler, report, output, prefix):
    contract = training_contract(data,rows,parameters,hashes,sampler)
    if report['contract'] != contract or report['contract_sha256'] != contract_hash(contract):
        raise ValueError('Unit-weight training contract changed')
    normalized = dict(report,reused=False); normalized.pop('requested_fit_id',None)
    reason = technical_reason(data,rows,False)
    if report['status']=='technically_unavailable':
        expected=dict(fit_id=None,reused=False,contract=contract,contract_sha256=contract_hash(contract),
                      support=support(data.y[rows]),status='technically_unavailable',reason=reason)
        if normalized!=expected or reason is None:
            raise ValueError('Unavailable member support changed')
        return None
    if reason: raise ValueError('Attempted member has invalid training support')
    starts=[r for r in ledger.records() if r['kind']=='fit_started' and r.get('experiment')==EXPERIMENT and r.get('fit_id')==report['fit_id']]
    if (len(starts)!=1 or starts[0]['stage']!=8 or starts[0]['seed']!=parameters.get('random_state')
            or starts[0]['hashes']!={**hashes,'training_contract_sha256':contract_hash(contract)}
            or starts[0]['parameters']!=dict(parameters=parameters,weighting=contract['weighting'])):
        raise ValueError('Unit-weight fit start contract changed')
    if report['status']=='succeeded':
        return verified_model(normalized,output,ledger,EXPERIMENT,hashes=hashes,expected_contract=contract,ledger_prefix=prefix)
    matches = [r for r in ledger.records() if r['kind']=='fit_finished' and r.get('experiment')==EXPERIMENT and r.get('fit_id')==report['fit_id']]
    if report['status']!='failed' or len(matches)!=1 or matches[0]['status']!='failed' or matches[0]['result']!=normalized:
        raise ValueError('No authoritative failed fit')
    return None


def abort(ledger, output, error, store):
    ledger._experiment_aborted = True
    try:
        store.json(Path(output)/'failure.json',dict(status='aborted',error=f'{type(error).__name__}: {error}'))
    except BaseException as secondary:
        error.add_note(f'failure.json: {secondary}')
    finally:
        try:
            records = ledger.records()
            started = any(r['kind']=='run_started' and r.get('experiment')==EXPERIMENT for r in records)
            closed = any(r['kind']=='run_finished' and r.get('experiment')==EXPERIMENT for r in records)
            if started and not closed: ledger.finish_run(EXPERIMENT,'aborted',dict(error=str(error)))
        except BaseException as secondary:
            error.add_note(f'finish_run: {secondary}')
