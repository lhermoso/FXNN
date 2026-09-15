"""Versioned fitting with terminal caches and fail-closed artifact persistence."""
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .cusum_continuation import support, technical_reason
from .cusum_research import identity_hash
from .data_audit import digest
from .fit_ledger import FitLedger
from .mlp_comparison import array_hash, versions
from .session_dataset import save_arrays, write_json
from .session_models import open_weights, predict_state

_ABORT = '__run_aborted__'


def contract_hash(contract):
    return hashlib.sha256(json.dumps(contract, sort_keys=True, allow_nan=False).encode()).hexdigest()


class StageLedger(FitLedger):
    """Change metadata before hashing, preserving every inherited transaction guard."""
    def __init__(self, path, stage=6):
        super().__init__(path)
        if type(stage) is not int or stage <= 0:
            raise ValueError('Stage must be a positive integer')
        self.stage = stage

    def _append(self, stream, records, kind, **values):
        if kind == 'run_started':
            finished = {(r['experiment'], r['fit_id']) for r in records if r['kind'] == 'fit_finished'}
            if any((r['experiment'], r['fit_id']) not in finished
                   for r in records if r['kind'] == 'fit_started'):
                raise ValueError('Unfinished fit requires integrity audit before new research')
        if kind == 'fit_started':
            params = values['parameters']
            seed = params.get('parameters', params).get('random_state')
            if seed is not None and type(seed) is not int:
                raise ValueError('Registered random_state must be an integer or None')
            values.update(stage=self.stage, seed=seed)
        return super()._append(stream, records, kind, **values)


def fit_cached(data, rows, family, parameters, clock, ledger, experiment, task,
               fit_id, fold, hashes, cache, output):
    """Fit a new contract once. Storage faults poison this cache for the whole run."""
    if _ABORT in cache or getattr(ledger, '_experiment_aborted', False):
        raise RuntimeError('Run aborted; no further scientific fits permitted')
    if family not in ('constant', 'logistic'):
        raise ValueError('Only weighted constant and logistic are registered')
    rows = np.asarray(rows)
    reason = technical_reason(data, rows, family == 'constant')
    if reason:
        return None, dict(status='technically_unavailable', reason=reason,
                          fit_id=None, support=support(data.y[rows]))
    weights = open_weights(data, rows, clock)
    if not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError('Invalid training-local uniqueness weights')
    contract = dict(experiment=experiment, stage=ledger.stage, task=task, family=family,
                    parameters=parameters, identities=identity_hash(data, rows),
                    features=data.names, groups=data.groups,
                    arrays={name: array_hash(getattr(data, name)[rows]) for name in
                            ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides')},
                    weights_sha256=array_hash(weights), versions=versions(),
                    source_hashes=hashes, weights_clock='scheduled_open_minutes_realized_ends')
    key = contract_hash(contract)
    if key in cache:
        state, report = cache[key]
        return state, dict(report, reused=True, requested_fit_id=fit_id)
    report = dict(fit_id=fit_id, reused=False, contract_sha256=key, contract=contract,
                  support=support(data.y[rows]), status='in_progress',
                  weight_min=float(weights.min()), weight_max=float(weights.max()),
                  weight_mean=float(weights.mean()))
    try:
        ledger.start_fit(experiment, fit_id, fold,
                         dict(family=family, task=task, parameters=parameters),
                         {**hashes, 'training_contract_sha256': key})
    except BaseException:
        # A failed fsync may still have left an authoritative start record.
        ledger._experiment_aborted = True
        cache[_ABORT] = 'Fit start transaction failed'
        raise
    cache[key] = None, report
    output = Path(output)
    terminal = False
    persistence = False
    try:
        X, y = data.X[rows], data.y[rows]
        if family == 'constant':
            state = dict(kind=np.array(family), prior=np.array(np.average(y, weights=weights)))
            expected = np.full(min(len(rows), 257), float(state['prior']))
        else:
            scaler = StandardScaler().fit(X, sample_weight=weights)
            model = LogisticRegression(**parameters)
            with warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                model.fit(scaler.transform(X), y, sample_weight=weights)
            state = dict(kind=np.array(family), mean=scaler.mean_, scale=scaler.scale_,
                         coef=model.coef_, intercept=model.intercept_)
            expected = model.predict_proba(scaler.transform(X[:257]))[:, 1]
            report['iterations'] = model.n_iter_.tolist()
        for name, value in state.items():
            if name != 'kind' and not np.isfinite(value).all():
                raise ValueError('Nonfinite exported model')
        np.testing.assert_allclose(predict_state(state, X[:257]), expected, rtol=1e-12, atol=1e-12)
        persistence = True
        (output/'models').mkdir(parents=True, exist_ok=True)
        artifact = output/'models'/f'{key}.npz'
        info = save_arrays(artifact, state)
        with np.load(artifact, allow_pickle=False) as saved:
            np.testing.assert_array_equal(predict_state(saved, X[:257]), predict_state(state, X[:257]))
        report.update(status='succeeded', model_file=str(artifact.relative_to(output)),
                      model_sha256=info['sha256'])
        write_json(output/'models'/f'{key}.json', report)
        ledger.finish_fit(experiment, fit_id, 'succeeded', report)
        terminal = True
        cache[key] = state, report
        return state, report
    except BaseException as error:
        report = dict(report, status='failed', reason=f'{type(error).__name__}: {error}')
        cache[key] = None, report
        secondary = []
        if not terminal:
            try:
                # An I/O error may occur after the record became durable.
                records = ledger.records()
                if not any(r['kind'] == 'fit_finished' and r.get('experiment') == experiment
                           and r.get('fit_id') == fit_id for r in records):
                    ledger.finish_fit(experiment, fit_id, 'failed', report)
                else:
                    persistence = True
            except BaseException as failure:
                secondary.append(f'{type(failure).__name__}: {failure}')
        recoverable = isinstance(error, (ValueError, ArithmeticError, RuntimeError, Warning))
        if persistence or secondary or not recoverable:
            cache[_ABORT] = str(error)
            ledger._experiment_aborted = True
            for detail in secondary:
                error.add_note(detail)
            raise
        try:
            (output/'models').mkdir(parents=True, exist_ok=True)
            write_json(output/'models'/f'{key}.json', report)
        except BaseException:
            cache[_ABORT] = 'Failed-fit report persistence failed'
            ledger._experiment_aborted = True
            raise
        return None, report


def abort_run(ledger, experiment, output, error):
    """Preserve original caller exception; return secondary errors for diagnostics."""
    ledger._experiment_aborted = True
    failures = []
    try:
        write_json(Path(output)/'failure.json', dict(status='aborted',
                   reason=f'{type(error).__name__}: {error}'))
    except BaseException as failure:
        failures.append(f'failure.json: {type(failure).__name__}: {failure}')
    finally:
        try:
            records = ledger.records()
            started = any(r['kind'] == 'run_started' and r.get('experiment') == experiment for r in records)
            closed = any(r['kind'] == 'run_finished' and r.get('experiment') == experiment for r in records)
            if started and not closed:
                ledger.finish_run(experiment, 'aborted', dict(reason=str(error), secondary=failures.copy()))
        except BaseException as failure:
            failures.append(f'finish_run: {type(failure).__name__}: {failure}')
    for detail in failures:
        error.add_note(detail)
    return failures


def verified_model(report, output, ledger, experiment, *, hashes,
                   expected_contract=None, ledger_prefix=None, allow_partial=False):
    """Load only hash-bound succeeded fits; caller verifies prediction/report manifests."""
    records = ledger.records()
    if ledger_prefix is not None:
        prefix = bytes(ledger_prefix)
        if not ledger.path.read_bytes().startswith(prefix):
            raise ValueError('Canonical ledger prefix changed')
    contract = report['contract']
    key = contract_hash(contract)
    if (report['status'] != 'succeeded' or report['contract_sha256'] != key
            or contract['experiment'] != experiment or contract['source_hashes'] != hashes
            or contract['versions'] != versions()
            or (expected_contract is not None and contract != expected_contract)):
        raise ValueError('Model contract verification failed')
    starts = [r for r in records if r['kind'] == 'fit_started' and r.get('experiment') == experiment
              and r.get('fit_id') == report['fit_id']]
    finishes = [r for r in records if r['kind'] == 'fit_finished' and r.get('experiment') == experiment
                and r.get('fit_id') == report['fit_id']]
    if (len(starts) != 1 or len(finishes) != 1 or finishes[0]['status'] != 'succeeded'
            or starts[0]['hashes'] != {**hashes, 'training_contract_sha256': key}
            or finishes[0]['result'] != report):
        raise ValueError('No authoritative succeeded fit for artifact')
    runs = [r for r in records if r['kind'] == 'run_finished' and r.get('experiment') == experiment]
    if len(runs) != 1 or (runs[0]['status'] != 'completed'
                         and not (allow_partial and runs[0]['status'] == 'aborted')):
        raise ValueError('Run is not completed; partial replay requires explicit aborted status')
    output = Path(output)
    path = output/report['model_file']
    if path.resolve().parent != (output/'models').resolve() or path.name != f'{key}.npz':
        raise ValueError('Invalid model artifact path')
    if digest(path) != report['model_sha256']:
        raise ValueError('Model artifact bytes changed')
    companion = json.loads((output/'models'/f'{key}.json').read_text())
    if companion != report:
        raise ValueError('Model report changed')
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}
