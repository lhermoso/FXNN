"""Preregistered development-only datasets and full candidate diagnostics."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from .data_audit import digest, load_development
from .features import orient_features
from .fit_ledger import FitLedger
from .mlp_comparison import versions
from .protocol import load_protocol, utc_epoch
from .research import Dataset
from .session_clock import weekly_fx_clock
from .session_data import session_events, session_features
from .session_dataset import save_arrays, write_json
from .volatility import barrier_labels, volatility_partitions
from .volatility_estimator import causal_volatility

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'configs/volatility_barriers_v1.json'
CONTRACT = ROOT / 'docs/experiments/volatility-barriers-v1-protocol.md'
TASKS = ('fixed', 'dynamic')
OUTCOMES = ('take_profit', 'stop_loss', 'timeout', 'ambiguous', 'boundary',
            'censored', 'causally_ineligible')


def describe(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError('Descriptive samples must be finite; no silent dropping')
    names = ('mean', 'std', 'min', 'q05', 'q50', 'q95', 'max')
    if not len(values):
        return dict(count=0, reason='empty_group', **dict.fromkeys(names))
    q = np.quantile(values, [.05, .5, .95])
    return dict(count=len(values), reason=None, mean=float(values.mean()),
                std=float(values.std()), min=float(values.min()),
                q05=float(q[0]), q50=float(q[1]), q95=float(q[2]), max=float(values.max()))


def candidate_summary(obs, rows, clock):
    rows = np.asarray(rows, dtype=np.int64)
    outcome = obs['outcomes'][rows]
    valid, retained = obs['valid'][rows], obs['retained'][rows]
    positives = int((retained & (outcome == 'take_profit')).sum())
    exclusions = Counter(obs['reason'][rows][~valid].tolist())
    for name in ('ambiguous', 'boundary', 'censored'):
        exclusions[f'eligible_{name}'] = int((valid & (outcome == name)).sum())
    durations = {}
    for name in OUTCOMES:
        selected = rows[outcome == name] if name != 'causally_ineligible' else rows[:0]
        durations[name] = dict(
            open_minutes=describe(clock.elapsed(obs['starts'][selected], obs['ends'][selected])),
            wall_hours=describe((obs['ends'][selected] - obs['starts'][selected]) / 3600),
        )
    causal = rows[valid]
    barriers = {key: describe(obs[key][causal]) for key in
                ('tp_distance', 'sl_distance', 'sigma', 'price_volatility')}
    barriers.update({f'{key}_pips': describe(obs[key][causal] / .0001)
                     for key in ('tp_distance', 'sl_distance')})
    return dict(candidates=len(rows), causally_eligible=int(valid.sum()),
                causal_eligibility_denominator=len(rows), retained=int(retained.sum()),
                positive=positives, negative=int(retained.sum()) - positives,
                prevalence=positives / int(retained.sum()) if retained.sum() else None,
                prevalence_denominator=int(retained.sum()),
                outcomes={name: int((outcome == name).sum()) for name in OUTCOMES},
                exclusions=dict(exclusions), durations_by_outcome=durations, barriers=barriers)


def regime_cutpoints(obs, training_rows):
    """Inverse empirical CDF of unique causal TRAINING candidate timestamps."""
    rows = np.asarray(training_rows, dtype=np.int64)
    rows = rows[obs['valid'][rows]]
    _, first = np.unique(obs['starts'][rows], return_index=True)
    sigma = obs['sigma'][rows[first]]
    if not len(sigma):
        return dict(unique_training_entries=0, cutpoints=None, tied=None,
                    reason='empty_causal_training_population')
    if not np.isfinite(sigma).all() or np.any(sigma <= 0):
        raise ValueError('Invalid causal regime input')
    cut = np.quantile(sigma, [1 / 3, 2 / 3], method='inverted_cdf').tolist()
    return dict(unique_training_entries=len(sigma), cutpoints=cut, tied=cut[0] == cut[1], reason=None)


def partition_report(obs, rows, clock, cutpoints):
    report = candidate_summary(obs, rows, clock)
    sigma, valid = obs['sigma'][rows], obs['valid'][rows]
    cut = cutpoints['cutpoints']
    bands = {'ineligible': ~valid}
    if cut is None:
        bands.update(low=np.zeros(len(rows), dtype=bool), middle=np.zeros(len(rows), dtype=bool),
                     high=np.zeros(len(rows), dtype=bool), unavailable=valid)
    else:
        bands.update(low=valid & (sigma <= cut[0]), middle=valid & (sigma > cut[0]) & (sigma <= cut[1]),
                     high=valid & (sigma > cut[1]))
    report['regimes'] = {name: candidate_summary(obs, rows[mask], clock) for name, mask in bands.items()}
    report['calendar_quarters'] = {}
    for year in (2022, 2023):
        for quarter in range(1, 5):
            month = 1 + (quarter - 1) * 3
            begin = utc_epoch(f'{year}-{month:02d}-01T00:00:00+00:00')
            end = utc_epoch(f'{year + 1 if quarter == 4 else year}-{1 if quarter == 4 else month + 3:02d}-01T00:00:00+00:00')
            selected = rows[(obs['starts'][rows] >= begin) & (obs['starts'][rows] < end)]
            report['calendar_quarters'][f'{year}Q{quarter}'] = candidate_summary(obs, selected, clock)
    return report


def prepare_volatility(candles, protocol, spec, clock):
    begin, end = map(utc_epoch, protocol['development'])
    raw_stamps = np.asarray([int(c.timestamp.timestamp()) for c in candles], dtype=np.int64)
    if not len(raw_stamps) or np.any((raw_stamps < begin) | (raw_stamps >= end)):
        raise ValueError('Empty or reserved source quotes')
    active = clock.active[clock.indices(raw_stamps)]
    original = np.flatnonzero(active)
    candles = [candles[i] for i in original]
    stamps = raw_stamps[active]
    breaks = clock.gap_breaks(stamps, 15)
    frame = session_features(candles, breaks)
    closes = np.asarray([float(c.close) for c in candles])
    opens = np.asarray([float(c.open) for c in candles])
    volatility = causal_volatility(closes, stamps, clock, breaks, **spec['volatility'])
    price_vol = volatility['price_volatility']
    # Common causal eligibility across both tasks and both directions.
    bounds_valid = (opens > .005) & (opens > 2.5 * price_vol)
    label_eligible = volatility['valid'] & bounds_valid
    reason = volatility['reason'].copy()
    reason[volatility['valid'] & ~bounds_valid] = 'nonpositive_barrier'
    reason[label_eligible & ~frame.valid] = 'feature_history'
    causal = label_eligible & frame.valid
    events = {str(h): session_events(candles, breaks, h) for h in spec['thresholds']}
    observed = dict(stamps=stamps, original_indices=original, X=frame.values, feature_valid=frame.valid,
                    closes=np.asarray([str(c.close) for c in candles]), breaks=breaks,
                    causal_valid=causal, **volatility)
    # Keep volatility validity and full eligibility distinct in the archive.
    observed['volatility_valid'] = observed.pop('valid')
    observed['eligibility_reason'] = reason
    for h, mask in events.items():
        observed[f'cusum_{h}'] = mask
    tasks = {}
    for task in TASKS:
        tp, sl = ((np.full(len(stamps), .005), np.full(len(stamps), .002)) if task == 'fixed'
                  else (2.5 * price_vol, price_vol))
        print(f'Labeling task {task}.', flush=True)
        obs = barrier_labels(candles, clock, tp, sl, eligible=label_eligible)
        entry = obs['entry_local']
        obs.update(entry_indices=original[entry], valid=causal[entry], feature_valid=frame.valid[entry],
                   volatility_valid=volatility['valid'][entry], sigma=volatility['sigma'][entry],
                   price_volatility=price_vol[entry], reason=reason[entry],
                   vol_history_start_index=volatility['history_start_index'][entry])
        conclusive = np.isin(obs['outcomes'], ('take_profit', 'stop_loss', 'timeout'))
        obs['conclusive'] = conclusive
        obs['retained'] = conclusive & obs['valid']
        rows = np.flatnonzero(obs['retained'])
        rows = rows[np.lexsort((obs['sides'][rows], obs['starts'][rows]))]
        selected, sides = entry[rows], obs['sides'][rows]
        data = Dataset(orient_features(frame, selected, sides),
                       (obs['outcomes'][rows] == 'take_profit').astype(np.int8),
                       stamps[selected], obs['ends'][rows], obs['info_ends'][rows], original[selected],
                       sides, frame.names, frame.groups, int((conclusive & ~obs['valid']).sum()))
        for h, mask in events.items():
            obs[f'cusum_{h}'] = mask[entry]
        tasks[task] = (data, obs, rows)
    return tasks, observed, dict(feature_names=frame.names, feature_groups=frame.groups,
                                 directional_features=frame.directional,
                                 raw_candles=len(raw_stamps), outside_session=int((~active).sum()))


def build(candles, protocol, spec, clock, output):
    tasks, observed, schema = prepare_volatility(candles, protocol, spec, clock)
    artifacts = {'observed': save_arrays(output / 'observed.npz', observed)}
    reports = {}
    for task, (data, obs, selected) in tasks.items():
        directory = output / task
        directory.mkdir()
        arrays = {name: getattr(data, name) for name in
                  ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides')}
        arrays.update(feature_names=np.asarray(data.names), candidate_rows=selected,
                      observed_indices=obs['entry_local'][selected],
                      last_information_bar_end=obs['last_information_bar_end'][selected])
        for h in map(str, spec['thresholds']):
            arrays[f'cusum_{h}'] = obs[f'cusum_{h}'][selected]
        report = dict(all_development=candidate_summary(obs, np.arange(len(obs['starts'])), clock), folds=[])
        for fold in protocol['folds']:
            parts = volatility_partitions(data.starts, data.info_ends, protocol, fold, clock, observed['stamps'])
            rawparts = volatility_partitions(obs['starts'], obs['info_ends'], protocol, fold, clock, observed['stamps'])
            for part, rows in parts.items():
                arrays[f"{fold['name']}_{part}"] = rows
            phases = {}
            for phase, train, evaluate in (('inner', 'train', 'validation'), ('refit', 'refit', 'test')):
                populations = {}
                for population in ('temporal', *map(str, spec['thresholds'])):
                    mask = np.ones(len(obs['starts']), dtype=bool) if population == 'temporal' else obs[f'cusum_{population}']
                    train_rows, eval_rows = (rawparts[p][mask[rawparts[p]]] for p in (train, evaluate))
                    cutpoints = regime_cutpoints(obs, train_rows)
                    populations[population] = dict(cutpoints=cutpoints,
                        training=partition_report(obs, train_rows, clock, cutpoints),
                        evaluation=partition_report(obs, eval_rows, clock, cutpoints))
                phases[phase] = populations
            report['folds'].append(dict(name=fold['name'], phases=phases))
        artifacts[task] = dict(dataset=save_arrays(directory / 'dataset.npz', arrays),
                               candidates=save_arrays(directory / 'candidates.npz', obs))
        reports[task] = report
    return reports, artifacts, schema


def load_contract():
    spec = json.loads(SPEC.read_text())
    parent = ROOT / 'configs/multiyear_v1.json'
    if (spec['experiment'] != 'volatility_barriers_v1' or spec['kind'] != 'causal_volatility_tasks'
            or spec['source_years'] != [2022, 2023] or spec['max_model_fits'] != 48
            or spec['thresholds'] != [.0005, .001] or spec['versions'] != versions()
            or spec['volatility'] != dict(lag=1440, window=500, span=100, minimum=100)
            or spec['history_buffer'] != 1941 or spec['horizon_open_minutes'] != 4320
            or spec['censor_from_missing_minutes'] != 15
            or spec['tasks'] != dict(fixed=dict(tp_price=.005, sl_price=.002),
                                     dynamic=dict(tp_multiple=2.5, sl_multiple=1.0))
            or spec['daily_return'] != 'close_endpoint / close_exact_1440_open_minute_anchor - 1'
            or spec['next_stage_task'] != 'dynamic' or spec['confirmation_opened'] is not False
            or digest(parent) != spec['parent_protocol_sha256']):
        raise ValueError('Unregistered volatility contract or runtime')
    return spec, load_protocol(parent)


def verify_dataset(directory, source_root):
    """Rebuild frozen labels/features/reports in temporary storage, without fits."""
    directory, source_root = Path(directory), Path(source_root)
    spec, protocol = load_contract()
    manifest = json.loads((directory / 'manifest.json').read_text())
    hashes = manifest['hashes']
    if (manifest['config'] != spec or digest(SPEC) != hashes['config']
            or digest(CONTRACT) != hashes['protocol']
            or digest(directory / 'report.json') != manifest['report_sha256']):
        raise ValueError('Dataset contract/report changed')
    for name, expected in hashes['sources'].items():
        if digest(ROOT / 'fxnn' / name) != expected:
            raise ValueError(f'Frozen source changed: {name}')
    ledger = Path(spec['global_ledger'])
    before = ledger.read_bytes()
    prefix = (directory / 'ledger-before.jsonl').read_bytes()
    if not before.startswith(prefix) or hashlib.sha256(prefix).hexdigest() != hashes['ledger']:
        raise ValueError('Historical ledger prefix changed')
    FitLedger(ledger).records()
    candles, provenance = load_development(source_root, protocol)
    if provenance != manifest['input_hashes']:
        raise ValueError('Source inputs changed')
    begin, end = map(utc_epoch, protocol['development'])
    clock = weekly_fx_clock(begin, end + 10 * 86400)
    checked = 0
    with tempfile.TemporaryDirectory(prefix='fxnn-volatility-replay-') as temporary:
        rebuilt = Path(temporary)
        reports, _, schema = build(candles, protocol, spec, clock, rebuilt)
        expected_report = dict(status='completed', tasks=reports, model_fits=0,
                               confirmation_opened=False, ledger_unchanged=True)
        if expected_report != json.loads((directory / 'report.json').read_text()) or schema != manifest['schema']:
            raise ValueError('Rebuilt dataset report/schema differs')
        files = [('observed.npz', manifest['artifacts']['observed'])]
        files += [(f'{task}/{kind}.npz', manifest['artifacts'][task][kind])
                  for task in TASKS for kind in ('dataset', 'candidates')]
        for name, artifact in files:
            if digest(directory / name) != artifact['sha256']:
                raise ValueError(f'Artifact changed: {name}')
            with np.load(directory / name, allow_pickle=False) as saved, np.load(rebuilt / name, allow_pickle=False) as replay:
                if set(saved.files) != set(replay.files):
                    raise ValueError('Artifact array schema changed')
                for field in saved.files:
                    np.testing.assert_array_equal(saved[field], replay[field])
                    checked += 1
    if ledger.read_bytes() != before:
        raise ValueError('Ledger changed during no-fit verification')
    return dict(status='verified', arrays_exact=checked, report_exact=True, new_fits=0,
                manifest_sha256=digest(directory / 'manifest.json'),
                ledger_sha256=hashlib.sha256(before).hexdigest(), confirmation_opened=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/Users/leohermoso/FXNN/data/histdata/EURUSD'))
    parser.add_argument('--output', type=Path, default=ROOT / 'output/volatility_dataset_v1')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_dataset(args.output, args.root)), flush=True)
        return
    if args.output.exists():
        parser.error('Output exists; preserve every attempt')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        parser.error('Commit protocol and code before labels')
    spec, protocol = load_contract()
    ledger = Path(spec['global_ledger'])
    before = ledger.read_bytes()
    if (FitLedger(ledger).consumed() != spec['expected_prior_fits']
            or hashlib.sha256(before).hexdigest() != spec['ledger_before_sha256']):
        raise ValueError('Canonical budget differs from preregistration')
    hashes = dict(config=digest(SPEC), protocol=digest(CONTRACT),
                  parent=digest(ROOT / 'configs/multiyear_v1.json'),
                  code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  sources={p.name: digest(p) for p in sorted((ROOT / 'fxnn').glob('*.py'))},
                  ledger=hashlib.sha256(before).hexdigest())
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'ledger-before.jsonl').write_bytes(before)
    write_json(args.output / 'run.json', dict(hashes=hashes, config=spec))
    try:
        candles, provenance = load_development(args.root, protocol)
        begin, end = map(utc_epoch, protocol['development'])
        clock = weekly_fx_clock(begin, end + 10 * 86400)
        report, artifacts, schema = build(candles, protocol, spec, clock, args.output)
        if ledger.read_bytes() != before:
            raise ValueError('Ledger changed during no-fit labeling')
        write_json(args.output / 'report.json', dict(status='completed', tasks=report,
                   model_fits=0, confirmation_opened=False, ledger_unchanged=True))
        write_json(args.output / 'manifest.json', dict(hashes=hashes, config=spec, artifacts=artifacts,
                   input_hashes=provenance, schema=schema, report_sha256=digest(args.output / 'report.json')))
    except BaseException as error:
        write_json(args.output / 'failure.json', dict(error=f'{type(error).__name__}: {error}', hashes=hashes))
        raise


if __name__ == '__main__':
    main()
