"""Preregistered descriptive stability diagnostics. No training or relabeling."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

from .cusum_evidence import verify_ledger
from .cusum_research import identity_hash
from .data_audit import digest, load_development
from .features import orient_features
from .mlp_comparison import array_hash, versions, PHASES
from .protocol import utc_epoch
from .session_data import session_features, session_events
from .session_models import load_data, open_weights, predict_state

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT/'configs/session_stability_v1.json'
PROTOCOL = ROOT/'docs/experiments/session-stability-v1-protocol.md'
EXPERIMENT = 'session_stability_v1'
OUTCOMES = ('take_profit', 'stop_loss', 'timeout', 'censored', 'ambiguous', 'boundary')


def check(value, message):
    if not value:
        raise ValueError(message)


@contextmanager
def no_training(protected=()):
    """Fail before Python training/relabeling calls or protected write opens."""
    protected = {str(Path(p).resolve()) for p in protected}
    active = [True]
    forbidden = {'fit', 'partial_fit', 'fit_transform', 'start_fit', 'finish_fit',
                 'start_run', 'finish_run', 'session_labels', 'label_trades'}
    previous = sys.getprofile()

    def profile(frame, event, arg):
        if event == 'call' and frame.f_code.co_name in forbidden:
            raise RuntimeError('Training/label/ledger mutation forbidden')

    def audit(event, args):
        if active[0] and event == 'open':
            path, mode, flags = args
            if isinstance(path, (str, bytes, os.PathLike)):
                writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
                if writing and str(Path(os.fsdecode(path)).resolve()) in protected:
                    raise RuntimeError('Protected input write forbidden')

    sys.addaudithook(audit)
    sys.setprofile(profile)
    try:
        yield
    finally:
        active[0] = False
        sys.setprofile(previous)


def quantiles(x, w, probabilities=(.05, .5, .95)):
    order = np.argsort(x, kind='stable')
    cdf = np.cumsum(w[order])
    indices = np.searchsorted(cdf, np.asarray(probabilities)*cdf[-1], side='left')
    return x[order[np.minimum(indices, len(x)-1)]]


def summary(x, w=None):
    x = np.asarray(x, dtype=float)
    if not len(x):
        return dict(n=0, weight_sum=0., mean=None, std=None, quantiles=None, reason='empty')
    w = np.ones(len(x)) if w is None else np.asarray(w, dtype=float)
    check(w.shape == x.shape and np.isfinite(x).all() and np.isfinite(w).all()
          and np.all(w > 0), 'Invalid descriptive inputs')
    mean = float(np.average(x, weights=w))
    return dict(n=len(x), weight_sum=float(w.sum()), mean=mean,
                std=float(np.sqrt(np.average((x-mean)**2, weights=w))),
                quantiles=quantiles(x, w).tolist())


def reference(X, w):
    result = []
    for col in X.T:
        s = summary(col, w)
        q = s['quantiles']
        s['outside_fraction'] = float(np.average((col < q[0]) | (col > q[2]), weights=w))
        result.append(s)
    return result


def compare(X, refs):
    result = []
    for col, ref in zip(X.T, refs, strict=True):
        s = summary(col)
        valid = len(col) and ref['std'] > 0
        s.update(standardized_mean_shift=(s['mean']-ref['mean'])/ref['std'] if valid else None,
                 std_ratio=s['std']/ref['std'] if valid else None,
                 outside_fraction=float(np.mean((col < ref['quantiles'][0]) |
                                                (col > ref['quantiles'][2]))) if len(col) else None,
                 normalization_reason=None if valid else 'empty' if not len(col) else 'zero_train_std')
        result.append(s)
    return result


def contributions(X, state, groups):
    indices = [j for cols in groups.values() for j in cols]
    check(sorted(indices) == list(range(X.shape[1])), 'Families must partition all features exactly once')
    check(str(state['kind'].item()) == 'logistic', 'Only frozen logistic states')
    check(np.all(state['scale'] > 0), 'Invalid frozen scale')
    z = (X-state['mean'])/state['scale']
    products = z*state['coef'].ravel()
    grouped = np.column_stack([products[:, cols].sum(axis=1) for cols in groups.values()])
    direct = (z @ state['coef'].T + state['intercept']).ravel()
    reconstructed = grouped.sum(axis=1)+float(state['intercept'].item())
    np.testing.assert_allclose(reconstructed, direct, rtol=1e-12, atol=1e-12)
    return grouped, direct, float(np.max(np.abs(reconstructed-direct), initial=0.))


def class_summaries(values, y, weights=None):
    check(len(values) == len(y) and np.isin(y, [0, 1]).all(), 'Observed classes required')
    out = {}
    for label, mask in [('all', np.ones(len(y), dtype=bool)), ('0', y == 0), ('1', y == 1)]:
        out[label] = summary(values[mask], None if weights is None else weights[mask])
    out['class1_minus_class0_mean'] = (out['1']['mean']-out['0']['mean']
                                      if out['1']['n'] and out['0']['n'] else None)
    return out


def losses(y, logits):
    if not len(y):
        return dict(log_loss=None, brier=None)
    p = 1/(1+np.exp(-np.clip(logits, -709, 709)))
    return dict(log_loss=float(np.mean(np.logaddexp(0., logits)-y*logits)),
                brier=float(np.mean((p-y)**2)))


def removal(y, logits, group):
    base, removed = losses(y, logits), losses(y, logits-group)
    return dict(scores=removed, delta={k: removed[k]-base[k] if base[k] is not None else None for k in base})


def paired_rows(data, rows, prediction):
    np.testing.assert_array_equal(rows, prediction['rows'])
    for field in ('starts', 'entry_indices', 'sides', 'y'):
        np.testing.assert_array_equal(getattr(data, field)[rows], prediction[field])


def horizon_mask(candidates, start, end):
    return ((candidates['starts'] >= start) & (candidates['starts'] < end) &
            (candidates['info_ends'] < end))


def candidate_X(frame, indices, sides):
    valid = frame.valid[indices]
    X = np.full((len(indices), len(frame.names)), np.nan)
    X[valid] = orient_features(frame, indices[valid], sides[valid])
    return X


def immutable(spec):
    for name, expected in spec['frozen_files'].items():
        check(digest(ROOT/name) == expected, f'Frozen input changed: {name}')
    for name, expected in spec['source_hashes'].items():
        path = ROOT/'docs/experiments/multiyear-v1-sources.json' if name == 'versioned_source_inventory' else Path(spec['source_root'])/name
        check(digest(path) == expected, f'Source changed: {name}')
    check(digest(Path(spec['global_ledger'])) == spec['ledger_sha256'], 'Ledger bytes changed')


def read_json(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    check(read_json(path) == value, 'JSON round-trip mismatch')


def calculate(spec):
    """Deterministic full replay also used to verify the persisted report."""
    immutable(spec)
    raw = Path(spec['global_ledger']).read_bytes()
    records = verify_ledger(raw)
    consumed = records[0]['prior_fits']+sum(r['kind'] == 'fit_started' for r in records)
    check(consumed == spec['expected_prior_fits'] == 103 and spec['max_model_fits'] == 0, 'Zero fit contract')
    check(spec['versions'] == versions(), 'Runtime versions changed')
    data, masks, parts, protocol, clock, manifest = load_data(ROOT/'output/session_dataset_v1', spec)
    check(protocol['source_years'] == [2022, 2023], 'Reserved years')
    check(data.names == spec['feature_names'] and data.groups == spec['families'], 'Feature schema changed')
    masks = {'temporal': np.ones(len(data.y), dtype=bool), **masks}
    models = read_json(ROOT/'output/session_models_v1/report.json')
    controls = read_json(ROOT/'output/session_controls_v1/report.json')
    refs, train_cache, state_cache, train_summaries = {}, {}, {}, {}
    distribution, model_results = [], []
    probability_values, max_logit_error, max_probability_error = 0, 0., 0.

    def training(rows, universe):
        key = identity_hash(data, rows)
        if key not in train_cache:
            w = open_weights(data, rows, clock)
            check(np.isfinite(w).all() and np.all(w > 0), 'Training weights invalid')
            train_cache[key] = w
            refs[key] = dict(universe=universe, identity_sha256=key, n=len(rows),
                             weights_sha256=array_hash(w),
                             uniqueness=reference(data.X[rows], w),
                             uniform=reference(data.X[rows], np.ones(len(rows))))
        return key, train_cache[key]

    def state_for(fit, origin, rows, universe):
        key, w = training(rows, universe)
        contract = fit['contract']
        check(fit['status'] == 'succeeded' and contract['identities'] == key, 'Training identity mismatch')
        check(contract['weights_sha256'] == array_hash(w), 'Training weights mismatch')
        model_key = f"{origin}:{fit['model_sha256']}"
        if model_key not in state_cache:
            check(hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest() == fit['contract_sha256'], 'Contract hash mismatch')
            for field, expected in contract['arrays'].items():
                check(array_hash(getattr(data, field)[rows]) == expected, f'Training {field} mismatch')
            path = ROOT/'output'/origin/fit['model_file']
            check(digest(path) == fit['model_sha256'], 'Model hash mismatch')
            starts = [r for r in records if r['kind'] == 'fit_started' and r.get('experiment') == origin and r['fit_id'] == fit['fit_id']]
            ends = [r for r in records if r['kind'] == 'fit_finished' and r.get('experiment') == origin and r['fit_id'] == fit['fit_id']]
            check(len(starts) == len(ends) == 1 and starts[0]['sequence'] < ends[0]['sequence'] and
                  starts[0]['hashes']['training_contract_sha256'] == fit['contract_sha256'] and
                  ends[0]['status'] == 'succeeded' and ends[0]['result']['model_sha256'] == fit['model_sha256'], 'Ledger linkage mismatch')
            with np.load(path, allow_pickle=False) as archive:
                state = {k: archive[k] for k in archive.files}
            np.testing.assert_allclose(state['mean'], [s['mean'] for s in refs[key]['uniqueness']], rtol=1e-9, atol=1e-12)
            scale = np.array([s['std'] for s in refs[key]['uniqueness']]); scale[scale == 0] = 1
            np.testing.assert_allclose(state['scale'], scale, rtol=1e-9, atol=1e-12)
            c, _, err = contributions(data.X[rows], state, data.groups)
            train_summaries[model_key] = dict(reference=key, model_sha256=fit['model_sha256'],
                intercept=float(state['intercept'].item()), max_logit_error=err,
                families={g: dict(uniqueness=class_summaries(c[:, j], data.y[rows], w),
                                  uniform=class_summaries(c[:, j], data.y[rows]))
                          for j, g in enumerate(data.groups)})
            state_cache[model_key] = state
        return state_cache[model_key], model_key

    for old_fold, ctrl_fold in zip(models['folds'], controls['folds'], strict=True):
        name = old_fold['fold']; check(name == ctrl_fold['fold'], 'Fold pairing')
        for phase, train, test in PHASES:
            old_phase = old_fold['phases'][phase]
            for universe, mask in masks.items():
                tr = parts[name][train]; tr = tr[mask[tr]]
                rows = parts[name][test]; rows = rows[mask[rows]]
                ref_key, _ = training(tr, universe)
                distribution.append(dict(fold=name, phase=phase, universe=universe,
                    reference=ref_key, identity_sha256=identity_hash(data, rows), n=len(rows),
                    evaluation={weighting: compare(data.X[rows], refs[ref_key][weighting])
                                for weighting in ('uniqueness', 'uniform')}))
                ev = old_phase['evaluations'][universe] if universe == 'temporal' else ctrl_fold['phases'][phase][universe]
                origin = 'session_models_v1' if universe == 'temporal' else 'session_controls_v1'
                check(ev['identity_sha256'] == identity_hash(data, rows), 'Evaluation hash mismatch')
                check(digest(ROOT/'output'/origin/ev['predictions_file']) == ev['predictions_sha256'], 'Prediction hash mismatch')
                requests = {'logistic_temporal': old_phase['fits']['logistic:temporal']} if universe == 'temporal' else {
                    k: ev['fits'][k] for k in ('logistic_temporal', 'logistic_event', 'logistic_equal')}
                with np.load(ROOT/'output'/origin/ev['predictions_file'], allow_pickle=False) as pred:
                    paired_rows(data, rows, pred)
                    for model, fit in requests.items():
                        train_universe = 'temporal' if model == 'logistic_temporal' else universe
                        model_rows = parts[name][train]; model_rows = model_rows[masks[train_universe][model_rows]]
                        model_origin = 'session_controls_v1' if model == 'logistic_equal' else 'session_models_v1'
                        state, model_key = state_for(fit, model_origin, model_rows, train_universe)
                        c, logits, err = contributions(data.X[rows], state, data.groups)
                        p = predict_state(state, data.X[rows])
                        reconstructed_p = 1/(1+np.exp(-np.clip(c.sum(axis=1)+float(state['intercept'].item()), -709, 709)))
                        np.testing.assert_allclose(reconstructed_p, pred[model], rtol=1e-12, atol=1e-12)
                        np.testing.assert_array_equal(p, pred[model])
                        prob_err = float(np.max(np.abs(reconstructed_p-p), initial=0.))
                        max_logit_error = max(max_logit_error, err); max_probability_error = max(max_probability_error, prob_err)
                        probability_values += len(rows)
                        base = losses(data.y[rows], logits)
                        for metric in base:
                            np.testing.assert_allclose(base[metric], ev['scores'][model][metric], rtol=1e-12, atol=1e-12)
                        model_results.append(dict(fold=name, phase=phase, universe=universe, model=model,
                            training_summary=model_key, n=len(rows), positives=int(data.y[rows].sum()),
                            identity_sha256=identity_hash(data, rows), intercept=float(state['intercept'].item()),
                            scores=base, max_logit_error=err, max_probability_error=prob_err,
                            families={g: dict(summary=class_summaries(c[:, j], data.y[rows]),
                                              removal=removal(data.y[rows], logits, c[:, j]))
                                      for j, g in enumerate(data.groups)}))
            print(f'{name} {phase}: distribution and frozen contributions complete', flush=True)

    selection, reconstruction = censor_diagnostics(data, masks, parts, protocol, clock, manifest, spec, refs, training)
    check(Path(spec['global_ledger']).read_bytes() == raw, 'Ledger changed during diagnostics')
    immutable(spec)
    return dict(experiment=EXPERIMENT, new_fits=0, ledger_consumed=consumed, ledger_sha256=spec['ledger_sha256'],
                config_sha256=digest(SPEC), protocol_sha256=digest(PROTOCOL), runner_sha256=digest(Path(__file__)),
                feature_names=data.names, families=data.groups, references=refs,
                training_contributions=train_summaries, distribution=distribution,
                model_evaluations=model_results, selection=selection, reconstruction=reconstruction,
                verification=dict(reproduced_probabilities_exact=probability_values,
                                  max_logit_error=max_logit_error, max_probability_error=max_probability_error,
                                  unique_models=len(state_cache), unique_training_sets=len(refs),
                                  training_guard=True, inputs_unchanged=True, ledger_byte_equal=True),
                aliases=['2023Q3 inner = 2023Q2 refit', '2023Q4 inner = 2023Q3 refit'],
                confirmation_opened=False, profit_claim=False)


def censor_diagnostics(data, masks, parts, protocol, clock, manifest, spec, refs, training):
    with np.load(ROOT/'output/session_dataset_v1/candidates.npz', allow_pickle=False) as archive:
        candidates = {k: archive[k] for k in ('starts', 'info_ends', 'entry_indices', 'sides', 'valid',
                      'outcomes', 'conclusive', 'retained', 'cusum_0.0005', 'cusum_0.001')}
    check(set(np.unique(candidates['outcomes'])) <= set(OUTCOMES), 'Unexpected candidate outcome')
    candles, provenance = load_development(Path(spec['source_root']), protocol)
    check(provenance == spec['source_hashes'] == manifest['input_hashes'], 'Source provenance mismatch')
    raw_stamps = np.array([int(c.timestamp.timestamp()) for c in candles])
    active = np.flatnonzero(clock.active[clock.indices(raw_stamps)])
    stamps = raw_stamps[active]; candles = [candles[i] for i in active]
    breaks = clock.gap_breaks(stamps)
    frame = session_features(candles, breaks)
    entries = np.searchsorted(stamps, candidates['starts'])
    np.testing.assert_array_equal(stamps[entries], candidates['starts'])
    np.testing.assert_array_equal(active[entries], candidates['entry_indices'])
    np.testing.assert_array_equal(frame.valid[entries], candidates['valid'])
    np.testing.assert_array_equal(np.isin(candidates['outcomes'], OUTCOMES[:3]), candidates['conclusive'])
    np.testing.assert_array_equal(candidates['retained'], candidates['valid'] & candidates['conclusive'])
    X = candidate_X(frame, entries, candidates['sides'])
    kept = np.flatnonzero(candidates['retained'])
    kept = kept[np.lexsort((candidates['sides'][kept], candidates['starts'][kept]))]
    for field in ('starts', 'info_ends', 'entry_indices', 'sides'):
        np.testing.assert_array_equal(getattr(data, field), candidates[field][kept])
    np.testing.assert_array_equal(X[kept], data.X)
    np.testing.assert_array_equal(data.y, candidates['outcomes'][kept] == 'take_profit')
    candidate_masks = {'temporal': np.ones(len(entries), dtype=bool)}
    for h in ('0.0005', '0.001'):
        events = session_events(candles, breaks, float(h))
        np.testing.assert_array_equal(events[entries], candidates[f'cusum_{h}'])
        np.testing.assert_array_equal(events[entries[kept]], masks[h])
        candidate_masks[h] = candidates[f'cusum_{h}']
    results = []
    for quarter in spec['selection_quarters']:
        q = int(quarter[-1]); start = utc_epoch(f'2023-{1+3*(q-1):02d}-01T00:00:00+00:00')
        end = utc_epoch('2024-01-01T00:00:00+00:00' if q == 4 else f'2023-{1+3*q:02d}-01T00:00:00+00:00')
        fold, train, test = ('2023Q2', 'train', 'validation') if q == 1 else (quarter, 'refit', 'test')
        for universe, mask in candidate_masks.items():
            before = mask & (candidates['starts'] >= start) & (candidates['starts'] < end)
            eligible = mask & horizon_mask(candidates, start, end)
            conclusive = eligible & candidates['valid'] & candidates['conclusive']
            censored = eligible & candidates['valid'] & (candidates['outcomes'] == 'censored')
            rows = parts[fold][test]; rows = rows[masks[universe][rows]]
            ci = np.flatnonzero(conclusive); ci = ci[np.lexsort((candidates['sides'][ci], candidates['starts'][ci]))]
            for field in ('starts', 'sides', 'entry_indices'):
                np.testing.assert_array_equal(candidates[field][ci], getattr(data, field)[rows])
            tr = parts[fold][train]; tr = tr[masks[universe][tr]]
            key, _ = training(tr, universe)
            counts = {outcome: {label: int((eligible & (candidates['outcomes'] == outcome) &
                                                (candidates['valid'] == valid)).sum())
                                for label, valid in [('valid_history', True), ('invalid_history', False)]}
                      for outcome in OUTCOMES}
            n = int(eligible.sum()); cc = int(censored.sum()); nc = int(conclusive.sum())
            check(sum(sum(c.values()) for c in counts.values()) == n, 'Candidate count conservation')
            comparisons = {}
            for weighting in ('uniqueness', 'uniform'):
                ref = refs[key][weighting]
                a, b = compare(X[conclusive], ref), compare(X[censored], ref)
                comparisons[weighting] = dict(conclusive=a, censored=b,
                    censored_minus_conclusive_train_std=[(sb['mean']-sa['mean'])/r['std']
                        if nc and cc and r['std'] > 0 else None for sa, sb, r in zip(a, b, ref, strict=True)])
            results.append(dict(quarter=quarter, universe=universe, reference=key,
                candidates_before_horizon=int(before.sum()), excluded_horizon=int(before.sum())-n,
                candidates_after_horizon=n, counts=counts, retained=nc, valid_censored=cc,
                valid_conclusive_or_censored=nc+cc,
                censor_fraction_all=sum(counts['censored'].values())/n if n else None,
                censor_fraction_valid_pair=cc/(nc+cc) if nc+cc else None,
                comparison=comparisons))
        print(f'{quarter}: causal observability comparison complete', flush=True)
    return results, dict(exact_retained_rows=len(kept), features=28, candidate_rows=len(entries),
                         invalid_history=int((~candidates['valid']).sum()),
                         invalid_features_all_nan=bool(np.isnan(X[~candidates['valid']]).all()),
                         masks_exact=True, no_labels_recalculated=True, source_hashes=provenance)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'output'/EXPERIMENT)
    parser.add_argument('--verify', action='store_true', help='Recompute frozen diagnostics and compare saved report')
    args = parser.parse_args()
    spec = read_json(SPEC)
    check(spec['experiment'] == EXPERIMENT and spec['kind'] == 'frozen_diagnostic_no_fits', 'Diagnostic config type')
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        check(os.environ.get(key) == '1', f'Set {key}=1 before startup')
    if not args.verify:
        check(not args.output.exists(), 'Output exists')
        check(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip(), 'Commit preregistration/code first')
    protected = [ROOT/name for name in spec['frozen_files']] + [Path(spec['global_ledger'])]
    protected += [Path(spec['source_root'])/name for name in spec['source_hashes'] if name != 'versioned_source_inventory']
    with no_training(protected):
        raw = Path(spec['global_ledger']).read_bytes()
        if not args.verify:
            args.output.mkdir(parents=True, exist_ok=False)
            dump(args.output/'run.json', dict(code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                config_sha256=digest(SPEC), protocol_sha256=digest(PROTOCOL),
                executed_utc=datetime.now(timezone.utc).isoformat()))
        try:
            result = calculate(spec)
        except BaseException as error:
            if not args.verify:
                dump(args.output/'failure.json', dict(error=f'{type(error).__name__}: {error}',
                     ledger_byte_equal=Path(spec['global_ledger']).read_bytes() == raw))
            raise
        if args.verify:
            check(result == read_json(args.output/'report.json'), 'Persisted diagnostics do not reproduce')
            verification = dict(status='verified', report_sha256=digest(args.output/'report.json'),
                                ledger_sha256=spec['ledger_sha256'], complete_aggregate_replay=True,
                                new_fits=0, **result['verification'])
            dump(args.output/'verification.json', verification)
        else:
            dump(args.output/'report.json', result)
        check(Path(spec['global_ledger']).read_bytes() == raw, 'Ledger changed')
        immutable(spec)
    print(json.dumps(dict(status='verified' if args.verify else 'completed', new_fits=0,
                          ledger_consumed=103, report_sha256=digest(args.output/'report.json'))), flush=True)


if __name__ == '__main__':
    main()
