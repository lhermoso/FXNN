"""Causal stage9 weighted models, durable terminals and read-only replay.

S0 labels are a separate diagnostic target. Probability availability uses only
side/features/volatility, never a future label, fill or evaluation-tail mask.
The supervisor owns the single fourteen-slot reservation and its open run.
"""
from collections import Counter
from dataclasses import dataclass
from itertools import zip_longest
import json
import os
from pathlib import Path
import platform
import warnings

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from fxnn.cusum_continuation import score, support
from fxnn.economic_clock import utc_ms
from fxnn.economic_labels import training_admission
from fxnn.economic_lifecycle import fingerprint, identity, verify_manifest
from fxnn.economic_opportunities import NAMES
from fxnn.mlp_comparison import array_hash
from fxnn.sequential_bootstrap import IntervalIndex
from fxnn.session_models import predict_state

EXPERIMENT = 'economic_ticks_v1'
MISSING = np.iinfo(np.int64).min
REASONS = {'available': 0, 'no_primary_signal': 1, 'features_unavailable': 2,
           'volatility_unavailable': 3, 'model_unavailable': 4}


def runtime():
    return {'python': platform.python_version(), 'numpy': np.__version__,
            'sklearn': sklearn.__version__}


def _integer(value):
    if type(value) is not int or not np.iinfo(np.int64).min < value <= np.iinfo(np.int64).max:
        raise ValueError('Finite int64 millisecond or identity required')
    return value


def _optional_ms(value):
    return MISSING if value is None else _integer(value)


def _json_rows(path):
    with Path(path).open(encoding='utf8') as stream:
        for line in stream:
            yield json.loads(line)


@dataclass
class EconomicMatrix:
    decision_ms: np.ndarray
    X: np.ndarray
    side: np.ndarray
    feature_valid: np.ndarray
    volatility_valid: np.ndarray
    eligible: np.ndarray
    calendar_eligible: np.ndarray
    y: np.ndarray
    entry_ms: np.ndarray
    information_end_ms: np.ndarray
    information_cap_ms: np.ndarray
    earliest_input_ms: np.ndarray
    bar_starts: np.ndarray
    bar_ends: np.ndarray
    hazards: tuple
    provenance: dict

    def __len__(self):
        return len(self.decision_ms)


class _AdmissionRows:
    """Array-backed views avoid a second Python object graph for every cutoff."""
    def __init__(self, data, labels):
        self.data, self.labels = data, labels

    def __len__(self):
        return len(self.data)

    def __getitem__(self, i):
        if i >= len(self):
            raise IndexError(i)
        d = self.data
        name = f'{EXPERIMENT}:{int(d.decision_ms[i])}'
        if not self.labels:
            return {'id': name, 'decision_ms': int(d.decision_ms[i])}
        return {'opportunity_id': name, 'label': None if d.y[i] < 0 else int(d.y[i]),
                'information_cap_ms': int(d.information_cap_ms[i]),
                'earliest_input_ms': int(d.earliest_input_ms[i]),
                'information_end_ms': int(d.information_end_ms[i])}


def load_matrix(opportunities, labels, bars, artifacts, hazards, provenance):
    """Stream verified files into numeric arrays; peak storage is O(rows*features).

    `artifacts` must include exact fingerprints for all three paths. The caller
    additionally binds dataset/label/index manifests and hazard content in S and
    provenance before invoking this loader. This function never reads a price
    archive or changes a historical integrity mask.
    """
    verify_manifest(artifacts)
    for path in (opportunities, labels, bars):
        if fingerprint(path) not in artifacts.values():
            raise ValueError('Input file is not bound in artifact manifest')
    with Path(opportunities).open('rb') as stream:
        n = sum(1 for _ in stream)
    integer = lambda: np.full(n, MISSING, dtype=np.int64)
    decisions, entries, ends, caps, earliest = (integer() for _ in range(5))
    X = np.full((n, len(NAMES)), np.nan)
    side, y = np.zeros(n, dtype=np.int8), np.full(n, -1, dtype=np.int8)
    flags = [np.zeros(n, dtype=bool) for _ in range(4)]
    for i, (op, label) in enumerate(zip_longest(_json_rows(opportunities), _json_rows(labels))):
        if op is None or label is None or i >= n:
            raise ValueError('Aligned opportunity and label files required')
        t = _integer(op['decision_ms'])
        name = f'{EXPERIMENT}:{t}'
        if op['id'] != name or label['opportunity_id'] != name or i and t <= decisions[i-1]:
            raise ValueError('Strictly ordered unique opportunity identities required')
        decisions[i] = t
        if op['side'] not in (-1, 0, 1):
            raise ValueError('Invalid primary side')
        side[i] = op['side']
        for target, field in zip(flags, ('feature_valid', 'volatility_valid', 'eligible', 'calendar_eligible')):
            if type(op[field]) is not bool:
                raise ValueError('Boolean causal availability required')
            target[i] = op[field]
        if op['X'] is not None:
            values = np.asarray(op['X'], dtype=np.float64)
            if values.shape != (len(NAMES),):
                raise ValueError('Feature schema mismatch')
            X[i] = values
        if flags[0][i] and not np.isfinite(X[i]).all():
            raise ValueError('Available features must be finite')
        for target, field in ((entries, 'entry_ms'), (ends, 'information_end_ms'),
                              (caps, 'information_cap_ms'), (earliest, 'earliest_input_ms')):
            target[i] = _optional_ms(label[field])
        if (caps[i] != _optional_ms(op['information_cap_ms']) or
                earliest[i] != _optional_ms(op['earliest_input'])):
            raise ValueError('Opportunity/label provenance mismatch')
        if label['label'] is not None:
            if type(label['label']) is not int or label['label'] not in (0, 1):
                raise ValueError('Binary proxy label required')
            if not (flags[0][i] and flags[1][i] and flags[2][i] and side[i]):
                raise ValueError('Observed proxy requires causal model inputs')
            if not (MISSING < earliest[i] <= t <= entries[i] < ends[i] <= caps[i]):
                raise ValueError('Invalid realized information interval')
            y[i] = label['label']
    # These two flat lists contain timestamps only, not bar dictionaries/prices.
    bar_starts, bar_ends = [], []
    previous = None
    for bar in _json_rows(bars):
        start, end = _integer(bar['start']), _integer(bar['end'])
        if end-start != 60000 or previous is not None and start <= previous:
            raise ValueError('Ordered unique observed M1 bars required')
        previous = start
        if type(bar['valid']) is not bool:
            raise ValueError('Boolean bar validity required')
        if bar['valid']:
            bar_starts.append(start)
            bar_ends.append(end)
    verify_manifest(artifacts)
    return EconomicMatrix(decisions, X, side, *flags, y, entries, ends, caps, earliest,
                          np.asarray(bar_starts, dtype=np.int64),
                          np.asarray(bar_ends, dtype=np.int64), tuple(hazards), provenance)


def admit(data, cutoff):
    """Freeze valid completed bars before the pre-clock cut, then full-cap purge."""
    bars = data.bar_starts[data.bar_ends < cutoff]
    rows, reasons = training_admission(_AdmissionRows(data, False), _AdmissionRows(data, True),
                                       data.hazards, cutoff, bars)
    rows = np.asarray(rows, dtype=np.int64)
    # Fail closed if a caller supplied an inconsistent in-memory matrix.
    if len(rows) and (not np.all((data.y[rows] == 0) | (data.y[rows] == 1)) or
                      not np.all(data.feature_valid[rows] & data.volatility_valid[rows]) or
                      not np.all(data.side[rows] != 0)):
        raise ValueError('Admitted training rows lack causal model inputs')
    codes = {name: i for i, name in enumerate(sorted({x for x in reasons if x is not None}), 1)}
    encoded = np.fromiter((0 if x is None else codes[x] for x in reasons), dtype=np.int16, count=len(data))
    return rows, {'cutoff_ms': cutoff, 'pre_clock_bar_end_strict': True,
                  'buffer_bars': 1941, 'valid_completed_bars': len(bars),
                  'buffer_start_ms': int(bars[-1941]) if len(bars) >= 1941 else None,
                  'accepted_rows_sha256': array_hash(rows), 'accepted_ids_sha256': array_hash(data.decision_ms[rows]),
                  'exclusion_codes': codes, 'exclusion_sha256': array_hash(encoded),
                  'counts': dict(Counter('admitted' if x is None else x for x in reasons))}


def training_weights(starts, ends, clock):
    """Actual-entry/information-end uniqueness in scheduled-open milliseconds.

    Endpoint difference construction is O(N+M). The frozen positive-sum tree
    provides bounded O(N log M) fallback when a prefix subtraction's certified
    error exceeds 1e-12 relative plus 1e-14 absolute. No bootstrap draw occurs.
    """
    starts, ends = np.asarray(starts), np.asarray(ends)
    if starts.shape != ends.shape or starts.ndim != 1:
        raise ValueError('Aligned realized intervals required')
    if not len(starts):
        return np.empty(0), {'rows': 0, 'raw_mean': None, 'tree_queries': 0, 'max_levels': 0}
    left = np.fromiter((clock.coordinate(int(t)) for t in starts), dtype=np.int64, count=len(starts))
    right = np.fromiter((clock.coordinate(int(t)) for t in ends), dtype=np.int64, count=len(ends))
    index = IntervalIndex(left, right)
    difference = np.zeros(len(index.c)+1, dtype=np.int64)
    np.add.at(difference, index.L, 1)
    np.add.at(difference, index.R, -1)
    index.c[:] = np.cumsum(difference[:-1])
    index.draw_count = len(left)
    raw, numerical = index.uniqueness(prospective=False)
    weights = raw/raw.mean()
    if not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError('Invalid training-local uniqueness weights')
    return weights, {'rows': len(left), 'raw_mean': float(raw.mean()),
                     'raw_min': float(raw.min()), 'raw_max': float(raw.max()),
                     'raw_sha256': array_hash(raw), 'weights_sha256': array_hash(weights),
                     'open_starts_sha256': array_hash(left), 'open_ends_sha256': array_hash(right),
                     'tree_queries': numerical['tree_queries'], 'max_levels': numerical['max_levels'],
                     'max_error_bound': float(numerical['errors'].max()),
                     'normalization': 'training_mean_one', 'clock': 'scheduled_open_milliseconds'}


def phase_plan(folds):
    phases = []
    ms = utc_ms
    for fold in folds:
        validation, test, end = (ms(fold[k]) for k in ('validation_start', 'test_start', 'test_end'))
        for name, cutoff, right in (('inner', validation, test), ('refit', test, end)):
            phases.append({'name': fold['name']+':'+name, 'cutoff_ms': cutoff,
                           'evaluation_start_ms': cutoff, 'evaluation_end_ms': right})
    if len(phases) != 6:
        raise ValueError('Exactly three inherited outer folds required')
    phases.append({'name': 'final', 'cutoff_ms': ms(folds[-1]['test_end']),
                   'evaluation_start_ms': None, 'evaluation_end_ms': None})
    return phases


def slots(phases):
    return [phase['name']+':'+family for phase in phases for family in ('constant', 'logistic')]


def model_contract(data, rows, weights, family, parameters, weight_report):
    if family not in ('constant', 'logistic'):
        raise ValueError('Unregistered model family')
    rows = np.asarray(rows, dtype=np.int64)
    if (rows.ndim != 1 or np.any(rows < 0) or np.any(rows >= len(data)) or
            len(np.unique(rows)) != len(rows) or np.any(np.diff(rows) <= 0)):
        raise ValueError('Ordered unique training rows required')
    if weights.shape != rows.shape:
        raise ValueError('Aligned training-local weights required')
    arrays = {'ids': data.decision_ms[rows], 'X': data.X[rows], 'y': data.y[rows],
              'side': data.side[rows], 'entry_ms': data.entry_ms[rows],
              'information_end_ms': data.information_end_ms[rows],
              'information_cap_ms': data.information_cap_ms[rows],
              'earliest_input_ms': data.earliest_input_ms[rows], 'weights': weights}
    return {'experiment': EXPERIMENT, 'task': 'S0_tp_first_proxy', 'family': family,
            'parameters': parameters if family == 'logistic' else {'kind': 'weighted_mean'},
            'versions': runtime(), 'features': list(NAMES), 'arrays': {k: array_hash(v) for k, v in arrays.items()},
            'support': support(data.y[rows]), 'weights': weight_report,
            'admission_rule': 'full_cap_1941_observed_bars_and_integrity_strictly_pre_clock',
            'scientific_provenance': data.provenance}


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def new_directory(path):
    """Exclusive leaf creation with durable directory entries at every level."""
    path = Path(path)
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for ancestor in reversed(missing):
        ancestor.mkdir()
        _sync_directory(ancestor.parent)
    path.mkdir(exist_ok=False)
    _sync_directory(path.parent)


def durable_json(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(Path(path).parent)
    return fingerprint(path)


def durable_arrays(path, arrays):
    with Path(path).open('xb') as stream:
        np.savez(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(Path(path).parent)
    return fingerprint(path)


def _state(value):
    kind = value.get('kind')
    expected = {'kind', 'prior'} if kind == 'constant' else {'kind', 'mean', 'scale', 'coef', 'intercept'}
    if kind not in ('constant', 'logistic') or set(value) != expected:
        raise ValueError('Invalid model export schema')
    state = {key: np.asarray(item) for key, item in value.items()}
    if kind == 'constant':
        if state['prior'].shape != () or not 0 <= float(state['prior']) <= 1:
            raise ValueError('Invalid constant export')
    else:
        if (state['mean'].shape != (len(NAMES),) or state['scale'].shape != (len(NAMES),) or
                state['coef'].shape != (1, len(NAMES)) or state['intercept'].shape != (1,) or
                np.any(state['scale'] <= 0)):
            raise ValueError('Invalid logistic export shape')
        if any(not np.isfinite(state[k]).all() for k in expected-{'kind'}):
            raise ValueError('Nonfinite model export')
    return state


def _availability(contract):
    counts = contract['support']
    if not counts['rows']:
        return 'empty_training'
    if contract['family'] == 'logistic' and not min(counts['positive'], counts['negative']):
        return 'logistic_requires_two_classes'
    return None


def verified_model(lifecycle, contract):
    """Inspect the recorded identity before lookup; never treat corruption as a miss."""
    snapshot = lifecycle.read()
    verify_manifest(snapshot['files'])
    F = identity({'S': snapshot['S'], 'contract': contract})
    matches = [fit for fit in snapshot['fits'].values() if fit['F'] == F]
    if not matches:
        reason = _availability(contract)
        if reason:
            return None, {'status': 'technically_unavailable', 'reason': reason, 'F': None,
                          'contract': contract, 'support': contract['support']}
        raise ValueError('Required model contract was never attempted')
    if len(matches) != 1 or matches[0]['status'] not in ('succeeded', 'failed'):
        raise ValueError('Pending or duplicate contract requires integrity audit')
    result = lifecycle.verified_terminal(contract, matches[0]['status'])
    if matches[0]['status'] == 'failed':
        return None, {'status': 'failed', 'F': F, 'contract': contract,
                      'support': contract['support'], 'diagnostics': result['diagnostics']}
    meta = json.loads(Path(result['artifacts']['metadata']['path']).read_text())
    if (meta.get('S') != snapshot['S'] or meta.get('F') != F or meta.get('contract') != contract or
            meta.get('model_sha256') != result['artifacts']['model']['sha256']):
        raise ValueError('Model metadata does not bind S/F/training contract')
    state = _state(json.loads(Path(result['artifacts']['model']['path']).read_text()))
    if str(state['kind'].item()) != contract['family']:
        raise ValueError('Model family differs from terminal contract')
    verify_manifest(result['artifacts'])
    return state, {'status': 'succeeded', 'F': F, 'contract': contract,
                   'support': contract['support'], 'diagnostics': result['diagnostics']}


def fit_model(data, rows, weights, weight_report, family, parameters, lifecycle, slot, fold, output):
    contract = model_contract(data, rows, weights, family, parameters, weight_report)
    snapshot = lifecycle.read()
    verify_manifest(snapshot['files'])
    F = identity({'S': snapshot['S'], 'contract': contract})
    if any(fit['F'] == F for fit in snapshot['fits'].values()) or _availability(contract):
        return verified_model(lifecycle, contract)
    if snapshot['poison'] or snapshot['terminal'] or snapshot['sealed']:
        raise ValueError('Lifecycle does not admit fitting')
    X, y = data.X[rows], data.y[rows]
    if not np.isfinite(X).all() or not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError('Finite training features and positive weights required')
    # A reserved fit encloses learned scaling, fitting and every export write.
    with lifecycle.fit(slot, contract, fold) as attempt:
        try:
            if family == 'constant':
                value = {'kind': 'constant', 'prior': float(np.average(y, weights=weights))}
                estimator_p = np.full(len(y), value['prior'])
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', ConvergenceWarning)
                    scaler = StandardScaler().fit(X, sample_weight=weights)
                    model = LogisticRegression(**parameters).fit(scaler.transform(X), y, sample_weight=weights)
                value = {'kind': 'logistic', 'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist(),
                         'coef': model.coef_.tolist(), 'intercept': model.intercept_.tolist()}
                estimator_p = model.predict_proba(scaler.transform(X))[:, 1]
            state = _state(value)
            replay_p = predict_state(state, X)
            error = float(np.max(np.abs(estimator_p-replay_p)))
            if not np.isfinite(replay_p).all() or error > 1e-12:
                raise ArithmeticError('Exported prediction differs from fitted estimator')
        except (ValueError, ArithmeticError, ConvergenceWarning) as error:
            attempt.failed({'reason': f'{type(error).__name__}: {error}', 'support': contract['support']})
        else:
            directory = Path(output)/F
            new_directory(directory)
            model_file = durable_json(directory/'model.json', value)
            metadata = durable_json(directory/'metadata.json', {'S': snapshot['S'], 'F': F,
                                    'contract': contract, 'model_sha256': model_file['sha256']})
            attempt.succeeded({'model': model_file, 'metadata': metadata},
                              {'export_max_abs_error': error, 'support': contract['support']})
    return verified_model(lifecycle, contract)


def diagnostic_metrics(y, probability):
    """Fixed-decile reliability and fixed-.5 decisions; no fitted calibration."""
    result = score(y, probability)
    result['thresholds'] = {'0.5': result['thresholds']['0.5']}
    result['undefined_reasons'] = {key: value for key, value in result['undefined_reasons'].items()
                                   if not key.startswith(('thresholds.0.3.', 'thresholds.0.4.'))}
    accepted = probability >= .5
    tp = int(np.sum(accepted & (y == 1)))
    fp = int(np.sum(accepted & (y == 0)))
    fn = int(np.sum(~accepted & (y == 1)))
    tn = int(np.sum(~accepted & (y == 0)))
    result['fixed_half_confusion'] = {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                                     'f1': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None}
    bins = np.minimum((probability*10).astype(np.int8), 9)
    result['reliability_deciles'] = []
    for i in range(10):
        selected = bins == i
        result['reliability_deciles'].append({'left': i/10, 'right': (i+1)/10,
            'right_closed': i == 9, 'rows': int(selected.sum()),
            'mean_probability': float(probability[selected].mean()) if selected.any() else None,
            'observed_positive_rate': float(y[selected].mean()) if selected.any() else None})
    return result


def phase_predictions(data, state, phase, batch_size=32768):
    left, right = phase['evaluation_start_ms'], phase['evaluation_end_ms']
    rows = np.flatnonzero((data.decision_ms >= left) & (data.decision_ms < right))
    reason = np.zeros(len(rows), dtype=np.int8)
    # Earlier conditions have priority; label/calendar/eligible never enter it.
    reason[~data.volatility_valid[rows]] = REASONS['volatility_unavailable']
    reason[~data.feature_valid[rows]] = REASONS['features_unavailable']
    reason[data.side[rows] == 0] = REASONS['no_primary_signal']
    if state is None:
        reason[reason == 0] = REASONS['model_unavailable']
    available = reason == 0
    p = np.full(len(rows), np.nan)
    selected = np.flatnonzero(available)
    for start in range(0, len(selected), batch_size):
        subset = selected[start:start+batch_size]
        values = predict_state(state, data.X[rows[subset]])
        if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
            raise ValueError('Invalid operational probability')
        p[subset] = values
    accepted = np.full(len(rows), -1, dtype=np.int8)
    accepted[available] = (p[available] >= .5).astype(np.int8)
    observed = ((data.y[rows] >= 0) & (data.information_end_ms[rows] <= right))
    metrics_mask = available & observed
    arrays = {'source_rows': rows, 'decision_ms': data.decision_ms[rows], 'side': data.side[rows],
              'probability': p, 'absence_reason': reason, 'accepted': accepted,
              'proxy_label': data.y[rows], 'metrics_mask': metrics_mask,
              'calendar_eligible': data.calendar_eligible[rows], 'operational_eligible': data.eligible[rows]}
    report = {'rows': len(rows), 'available_probabilities': int(available.sum()),
              'absence_codes': REASONS, 'absence_counts': {k: int(np.sum(reason == v)) for k, v in REASONS.items()},
              'fixed_threshold': .5, 'selection_or_calibration': False,
              'metric_mask': 'finite_probability_and_binary_proxy_label_and_information_end_ms<=evaluation_end_ms',
              'metric_rows': int(metrics_mask.sum()), 'proxy_unobserved_by_boundary': int((~observed).sum()),
              'score': diagnostic_metrics(data.y[rows][metrics_mask], p[metrics_mask]),
              'arrays': {k: array_hash(v) for k, v in arrays.items()}}
    return arrays, report


def validate_registered_phases(snapshot, phases, parameters, expected_versions):
    config=snapshot['config']
    if (config.get('model_phases')!=phases or config.get('logistic')!=parameters
            or config.get('versions')!=expected_versions or slots(phases)!=snapshot['slots']):
        raise ValueError('Phase dates, parameters or runtime differ from reserved configuration')


def run_phases(data, clock, phases, parameters, expected_versions, lifecycle, output, *, final=False):
    """Execute one development/final segment. Caller reserves and later freezes.

    Output must be new. A clean checkpoint leaves the same canonical run open.
    Resume verifies the existing segment with verify_phases; it never rewrites it.
    """
    if runtime() != expected_versions:
        raise ValueError('Registered runtime mismatch')
    chosen = [p for p in phases if (p['name'] == 'final') == final]
    if not chosen:
        raise ValueError('No registered phases in segment')
    snapshot = lifecycle.read()
    validate_registered_phases(snapshot, phases, parameters, expected_versions)
    verify_manifest(snapshot['files'])
    if slots(phases) != snapshot['slots']:
        raise ValueError('Fourteen registered slots differ from phase plan')
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    try:
        new_directory(output)
        reports = []
        artifacts = {}
        for phase in chosen:
            rows, admission = admit(data, phase['cutoff_ms'])
            weights, weight_report = training_weights(data.entry_ms[rows], data.information_end_ms[rows], clock)
            families = {}
            for family in ('constant', 'logistic'):
                name = phase['name']+':'+family
                state, fitted = fit_model(data, rows, weights, weight_report, family, parameters,
                                          lifecycle, name, phase['name'], output/'models')
                families[family] = {'fit': fitted}
                if phase['evaluation_start_ms'] is not None:
                    arrays, metrics = phase_predictions(data, state, phase)
                    artifact = durable_arrays(output/(name.replace(':', '-')+'.npz'), arrays)
                    artifacts[name] = artifact
                    families[family].update(predictions=artifact, metrics=metrics)
            reports.append({'phase': phase, 'admission': admission, 'families': families})
        report = {'experiment': EXPERIMENT, 'S': snapshot['S'], 'runtime': runtime(),
                  'segment': 'final' if final else 'development', 'phases': reports}
        artifact = durable_json(output/'report.json', report)
        artifacts['report'] = artifact
        # Exact read-only reconstruction is required before publishing a clean pause.
        verify_phases(data, clock, phases, parameters, expected_versions, lifecycle, artifact)
        lifecycle.clean_checkpoint('FINAL_MODELS_VERIFIED' if final else 'DEVELOPMENT_VERIFIED', artifacts)
        return report, artifacts
    except BaseException as error:
        lifecycle.poison(f'{type(error).__name__}: stage9 model segment publication failed')
        raise


def verify_phases(data, clock, phases, parameters, expected_versions, lifecycle, report_artifact):
    """Recompute admission, contracts, probabilities and scores; zero writes/fits."""
    if runtime() != expected_versions:
        raise ValueError('Registered runtime mismatch')
    verify_manifest({'report': report_artifact})
    report = json.loads(Path(report_artifact['path']).read_text())
    snapshot = lifecycle.read()
    validate_registered_phases(snapshot, phases, parameters, expected_versions)
    verify_manifest(snapshot['files'])
    if (report['S'] != snapshot['S'] or report['runtime'] != runtime() or
            report['experiment'] != EXPERIMENT or slots(phases) != snapshot['slots'] or
            report['segment'] not in ('final', 'development')):
        raise ValueError('Segment identity mismatch')
    chosen = [p for p in phases if (p['name'] == 'final') == (report['segment'] == 'final')]
    if len(chosen) != len(report['phases']):
        raise ValueError('Phase coverage differs from registration')
    for phase, saved in zip(chosen, report['phases']):
        rows, admission = admit(data, phase['cutoff_ms'])
        if saved['phase'] != phase or saved['admission'] != admission:
            raise ValueError('Causal training admission replay mismatch')
        weights, weight_report = training_weights(data.entry_ms[rows], data.information_end_ms[rows], clock)
        if set(saved['families']) != {'constant', 'logistic'}:
            raise ValueError('Model pair coverage mismatch')
        for family in ('constant', 'logistic'):
            contract = model_contract(data, rows, weights, family, parameters, weight_report)
            state, fitted = verified_model(lifecycle, contract)
            entry = saved['families'][family]
            if entry['fit'] != fitted:
                raise ValueError('Fit report replay mismatch')
            if phase['evaluation_start_ms'] is not None:
                arrays, metrics = phase_predictions(data, state, phase)
                verify_manifest({'predictions': entry['predictions']})
                with np.load(entry['predictions']['path'], allow_pickle=False) as archive:
                    if set(archive.files) != set(arrays):
                        raise ValueError('Prediction archive schema mismatch')
                    for key, value in arrays.items():
                        if not np.array_equal(value, archive[key], equal_nan=True):
                            raise ValueError('Prediction array replay mismatch: '+key)
                if metrics != entry['metrics']:
                    raise ValueError('Score/mask replay mismatch')
    return report
