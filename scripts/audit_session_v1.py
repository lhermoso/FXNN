"""Read-only audit of frozen session v1 artifacts. No estimator fits or ledger writes.

Run from repository root: .venv/bin/python -m scripts.audit_session_v1
Only aggregate JSON is emitted to stdout. Sources are restricted to 2022–2023.
"""
import hashlib
import json
import ast
import subprocess
from pathlib import Path

import numpy as np

from fxnn.cusum_continuation import score
from fxnn.cusum_evidence import verify_ledger
from fxnn.cusum_research import identity_hash
from fxnn.data_audit import digest, load_development
from fxnn.features import orient_features
from fxnn.mlp_comparison import array_hash
from fxnn.session_data import session_events, session_features
from fxnn.session_models import load_data, open_weights, predict_state


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / 'output/session_models_v1'
DATA = ROOT / 'output/session_dataset_v1'
LEDGER = Path('/Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl')


def check(value, message):
    if not value:
        raise ValueError(message)


def minute_weights(data, rows, clock):
    """Independent dense minute implementation, versus compressed interval code."""
    starts = clock.prefix[clock.indices(data.starts[rows])]
    ends = clock.prefix[clock.indices(data.ends[rows], endpoint=True)]
    delta = np.bincount(starts, minlength=len(clock.prefix))
    delta -= np.bincount(ends, minlength=len(clock.prefix))
    concurrency = np.cumsum(delta)
    area = np.concatenate(([0.], np.cumsum(1 / np.maximum(concurrency, 1))))
    weights = (area[ends] - area[starts]) / (ends - starts)
    return weights / weights.mean()


def scalar_label(candles, stamps, clock, entry, direction, deadline):
    """Minute-by-minute Decimal oracle; no barrier tree or future-gap array."""
    from decimal import Decimal
    start = int(stamps[entry])
    target = candles[entry].open + direction * Decimal('.0050')
    stop = candles[entry].open - direction * Decimal('.0020')
    next_quote, missing = entry, 0
    for minute in range(start, min(deadline, int(stamps[-1]) + 60), 60):
        if not clock.active[(minute - clock.first_epoch) // 60]:
            continue
        if next_quote >= len(stamps) or stamps[next_quote] != minute:
            missing += 1
            if missing == 15:
                return 'censored', minute + 60
        else:
            missing = 0
            bar = candles[next_quote]
            next_quote += 1
            if direction * (bar.open - stop) <= 0:
                return 'stop_loss', minute
            if direction * (bar.open - target) >= 0:
                return 'take_profit', minute
            tp = bar.high >= target if direction == 1 else bar.low <= target
            sl = bar.low <= stop if direction == 1 else bar.high >= stop
            if tp and sl:
                return 'ambiguous', minute + 60
            if sl:
                return 'stop_loss', minute + 60
            if tp:
                return ('take_profit' if minute + 60 < deadline else 'boundary'), minute + 60
        if minute + 60 == deadline:
            return 'timeout', deadline
    return 'censored', int(stamps[-1]) + 60


def main():
    before = LEDGER.read_bytes()
    records = verify_ledger(before)
    consumed = records[0]['prior_fits'] + sum(r['kind'] == 'fit_started' for r in records)
    check(consumed == 87, 'Unexpected ledger consumption')
    check(before == (MODELS / 'ledger-after.jsonl').read_bytes(), 'Ledger snapshot mismatch')
    check(before.startswith((MODELS / 'ledger-before.jsonl').read_bytes()), 'Historical prefix changed')
    report = json.loads((MODELS / 'report.json').read_text())
    check(digest(MODELS / 'report.json') == json.loads((MODELS / 'verification.json').read_text())['report_sha256'], 'Report hash')
    spec = json.loads((ROOT / 'configs/session_models_v1.json').read_text())
    data, masks, parts, protocol, clock, manifest = load_data(DATA, spec)
    check(protocol['source_years'] == [2022, 2023], 'Reserved source years')
    source_differences = []
    for name, expected in report['hashes']['source_hashes'].items():
        current = ROOT / 'fxnn' / name
        executed = subprocess.check_output(['git', 'show', f"{report['hashes']['code_sha']}:fxnn/{name}"], cwd=ROOT)
        check(hashlib.sha256(executed).hexdigest() == expected, f'Executed source hash: {name}')
        if digest(current) != expected:
            check(ast.dump(ast.parse(current.read_text())) == ast.dump(ast.parse(executed)), f'Semantic source change: {name}')
            source_differences.append(dict(file=name, executed_sha256=expected,
                                           current_sha256=digest(current), identical_ast=True))
    check(digest(DATA / 'candidates.npz') == manifest['artifacts']['candidates']['sha256'], 'Candidates hash')
    with np.load(DATA / 'candidates.npz', allow_pickle=False) as archive:
        candidates = {k: archive[k] for k in archive.files}
    retained = np.flatnonzero(candidates['retained'])
    retained = retained[np.lexsort((candidates['sides'][retained], candidates['starts'][retained]))]
    for field in ('starts', 'ends', 'info_ends', 'entry_indices', 'sides'):
        np.testing.assert_array_equal(getattr(data, field), candidates[field][retained])
    np.testing.assert_array_equal(data.y, candidates['outcomes'][retained] == 'take_profit')
    np.testing.assert_array_equal(candidates['retained'], candidates['conclusive'] & candidates['valid'])

    candles, provenance = load_development(Path('/Users/leohermoso/FXNN/data/histdata/EURUSD'), protocol)
    check(provenance == manifest['input_hashes'], 'Source provenance mismatch')
    raw_stamps = np.array([int(c.timestamp.timestamp()) for c in candles])
    active_indices = np.flatnonzero(clock.active[clock.indices(raw_stamps)])
    candles = [candles[i] for i in active_indices]
    stamps = raw_stamps[active_indices]
    breaks = clock.gap_breaks(stamps)
    frame = session_features(candles, breaks)
    entries = np.searchsorted(stamps, data.starts)
    np.testing.assert_array_equal(orient_features(frame, entries, data.sides), data.X)
    for h, mask in masks.items():
        events = session_events(candles, breaks, float(h))
        np.testing.assert_array_equal(events[entries], mask)
        np.testing.assert_array_equal(mask, candidates[f'cusum_{h}'][retained])
    # Truncate exactly at entry, replace its OHLC: prices at t cannot enter X[t].
    from dataclasses import replace
    causal_entries = np.unique(entries[np.linspace(0, len(entries) - 1, 12, dtype=int)])
    for i in causal_entries:
        original = candles[i]
        changed = replace(original, open=original.open * 2, high=original.high * 2,
                          low=original.low * 2, close=original.close * 2)
        truncated = session_features(candles[:i] + [changed], breaks[:i+1])
        np.testing.assert_array_equal(truncated.values[-1], frame.values[i])

    sample = set(np.linspace(0, len(candidates['starts']) - 1, 80, dtype=int).tolist())
    for outcome in np.unique(candidates['outcomes']):
        group = np.flatnonzero(candidates['outcomes'] == outcome)
        sample.update(group[np.linspace(0, len(group) - 1, min(10, len(group)), dtype=int)].tolist())
    for row in sorted(sample):
        i = int(np.searchsorted(stamps, candidates['starts'][row]))
        actual = scalar_label(candles, stamps, clock, i, int(candidates['sides'][row]), int(candidates['info_ends'][row]))
        check(actual == (candidates['outcomes'][row], int(candidates['ends'][row])), f'Scalar label row {row}')

    verified_models, training_sets, probabilities, archives = set(), {}, 0, 0
    external = []
    for fold in report['folds']:
        name = fold['fold']
        for phase, train, test in (('inner', 'train', 'validation'), ('refit', 'refit', 'test')):
            result = fold['phases'][phase]
            for request, fit in result['fits'].items():
                _, universe = request.split(':')
                rows = parts[name][train]
                if universe != 'temporal':
                    rows = rows[masks[universe][rows]]
                contract = fit['contract']
                key = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
                check(key == fit['contract_sha256'], 'Cache key mismatch')
                check(identity_hash(data, rows) == contract['identities'], 'Training identities')
                for field, expected in contract['arrays'].items():
                    check(array_hash(getattr(data, field)[rows]) == expected, f'Training array {field}')
                training_key = contract['identities']
                if training_key not in training_sets:
                    w = open_weights(data, rows, clock)
                    np.testing.assert_allclose(w, minute_weights(data, rows, clock), rtol=2e-7, atol=1e-8)
                    mean = np.average(data.X[rows], weights=w, axis=0)
                    scale = np.sqrt(np.average((data.X[rows] - mean)**2, weights=w, axis=0))
                    scale[scale == 0] = 1
                    training_sets[training_key] = (w, mean, scale)
                w, mean, scale = training_sets[training_key]
                check(array_hash(w) == contract['weights_sha256'], 'Weight hash')
                check(digest(MODELS / fit['model_file']) == fit['model_sha256'], 'Model hash')
                if key not in verified_models:
                    started = [r for r in records if r['kind'] == 'fit_started' and r.get('experiment') == 'session_models_v1' and r['fit_id'] == fit['fit_id']]
                    finished = [r for r in records if r['kind'] == 'fit_finished' and r.get('experiment') == 'session_models_v1' and r['fit_id'] == fit['fit_id']]
                    check(len(started) == len(finished) == 1, 'Ledger fit linkage')
                    check(started[0]['sequence'] < finished[0]['sequence'], 'Ledger fit order')
                    check(started[0]['hashes']['training_contract_sha256'] == key, 'Ledger contract')
                    check(finished[0]['status'] == 'succeeded' and finished[0]['result']['model_sha256'] == fit['model_sha256'], 'Ledger result')
                    with np.load(MODELS / fit['model_file'], allow_pickle=False) as state:
                        if contract['family'] == 'constant':
                            np.testing.assert_allclose(state['prior'], np.average(data.y[rows], weights=w), rtol=1e-12)
                        else:
                            np.testing.assert_allclose(state['mean'], mean, rtol=1e-9, atol=1e-12)
                            np.testing.assert_allclose(state['scale'], scale, rtol=1e-9, atol=1e-12)
                    verified_models.add(key)
            for universe, evaluation in result['evaluations'].items():
                file = MODELS / evaluation['predictions_file']
                check(digest(file) == evaluation['predictions_sha256'], 'Prediction hash')
                rows = parts[name][test]
                if universe != 'temporal':
                    rows = rows[masks[universe][rows]]
                check(identity_hash(data, rows) == evaluation['identity_sha256'], 'Evaluation identity hash')
                with np.load(file, allow_pickle=False) as pred:
                    np.testing.assert_array_equal(pred['rows'], rows)
                    for field in ('entry_indices', 'sides', 'starts', 'y'):
                        np.testing.assert_array_equal(pred[field], getattr(data, field)[rows])
                    summary = dict(fold=name, universe=universe, prevalence=float(data.y[rows].mean()),
                                   constant_probability=float(pred['constant'][0]), models={})
                    for model, metrics in evaluation['scores'].items():
                        method, training = ('constant', 'temporal') if model == 'constant' else model.rsplit('_', 1)
                        source = universe if training == 'event' else 'temporal'
                        fit = result['fits'][f'{method}:{source}']
                        with np.load(MODELS / fit['model_file'], allow_pickle=False) as state:
                            replay = predict_state(state, data.X[rows])
                        np.testing.assert_array_equal(replay, pred[model])
                        check(score(data.y[rows], replay) == metrics, 'Metrics mismatch')
                        probabilities += len(rows)
                        summary['models'][model] = {k: metrics[k] for k in ('log_loss', 'brier', 'roc_auc', 'average_precision')}
                    if phase == 'refit':
                        external.append(summary)
                archives += 1
    check(len(verified_models) == 39, 'Unique model count')
    check(LEDGER.read_bytes() == before, 'Ledger changed during audit')
    print(json.dumps(dict(status='verified', new_fits=0, ledger_consumed=consumed,
                         ledger_sha256=hashlib.sha256(before).hexdigest(),
                         source_implementation='d496120', audit_script_sha256=digest(Path(__file__)),
                         source_differences=source_differences,
                         full_feature_rows=len(data.y), causal_entry_checks=len(causal_entries),
                         scalar_label_checks=len(sample), unique_training_sets=len(training_sets),
                         unique_models=len(verified_models), probability_values=probabilities,
                         prediction_archives=archives, external=external), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
