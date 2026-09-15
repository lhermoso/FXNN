"""Build and verify a versioned development dataset; never fit a model."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import subprocess

import numpy as np

from .cusum_evidence import verify_ledger
from .data_audit import digest, load_development
from .protocol import load_protocol, utc_epoch
from .session_clock import weekly_fx_clock
from .session_data import prepare_session, session_partitions

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'configs/session_dataset_v1.json'
CONTRACT = ROOT / 'docs/experiments/session-dataset-v1-protocol.md'


def summarize(obs, rows):
    outcomes = obs['outcomes'][rows]
    kept = obs['retained'][rows]
    return dict(candidates=len(rows), outcomes=dict(Counter(outcomes.tolist())),
                feature_eligible=int(obs['valid'][rows].sum()),
                retained=int(kept.sum()),
                positive=int((kept & (outcomes == 'take_profit')).sum()),
                negative=int((kept & (outcomes != 'take_profit')).sum()),
                censored_fraction=float((outcomes == 'censored').mean()) if len(rows) else None)


def historical_months(path):
    """Read the already versioned monthly audit, without recomputing old labels."""
    result = {}
    for line in path.read_text().splitlines():
        fields = [v.strip() for v in line.split('|')]
        if len(fields) == 9 and len(fields[1]) == 7 and fields[1][:4] in ('2022', '2023'):
            result[fields[1]] = dict(zip(
                ('candidates', 'censored', 'ambiguous', 'conclusive_without_history', 'retained', 'positive'),
                map(int, fields[2:8])))
    if len(result) != 24:
        raise ValueError('Historical monthly audit not recognized')
    return result


def write_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def save_arrays(path, arrays):
    """No object arrays/pickle; verify every serialized array before hashing."""
    if any(np.asarray(value).dtype.hasobject for value in arrays.values()):
        raise ValueError('Object arrays forbidden')
    with path.open('xb') as stream:
        np.savez_compressed(stream, **arrays)
    with np.load(path, allow_pickle=False) as loaded:
        if set(loaded.files) != set(arrays):
            raise ValueError('Serialized fields changed')
        for name, expected in arrays.items():
            np.testing.assert_array_equal(loaded[name], expected)
    return dict(sha256=digest(path), bytes=path.stat().st_size,
                arrays={k: dict(shape=list(v.shape), dtype=str(v.dtype)) for k, v in arrays.items()})


def build(candles, protocol, spec, clock, output):
    data, masks, obs, diagnostics, stamps = prepare_session(candles, protocol, spec, clock)
    if not np.isfinite(data.X).all() or data.X.shape != (len(data.y), 28):
        raise ValueError('Invalid feature matrix')
    if not np.all(np.isin(data.y, [0, 1])) or np.any(data.ends > data.info_ends):
        raise ValueError('Invalid labels or information intervals')
    np.testing.assert_array_equal(clock.elapsed(data.starts, data.info_ends), 4320)
    arrays = {name: getattr(data, name) for name in
              ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides')}
    arrays['feature_names'] = np.asarray(data.names)
    arrays['observed_stamps'] = stamps
    for h, mask in masks.items():
        arrays[f'cusum_{h}'] = mask
    report = dict(diagnostics=diagnostics, all_development=summarize(obs, np.arange(len(obs['starts']))),
                  monthly={}, folds=[], timeout_stale_open_minutes_max=int(obs['timeout_stale_open_minutes'].max(initial=0)),
                  timeout_with_stale_price=int((obs['timeout_stale_open_minutes'] > 0).sum()))
    for year in (2022, 2023):
        for month in range(1, 13):
            begin = utc_epoch(f'{year}-{month:02d}-01T00:00:00+00:00')
            end = utc_epoch(f'{year+1 if month == 12 else year}-{1 if month == 12 else month+1:02d}-01T00:00:00+00:00')
            rows = np.flatnonzero((obs['starts'] >= begin) & (obs['starts'] < end))
            report['monthly'][f'{year}-{month:02d}'] = summarize(obs, rows)
    for fold in protocol['folds']:
        parts = session_partitions(data.starts, data.info_ends, protocol, fold, clock, stamps)
        rawparts = session_partitions(obs['starts'], obs['info_ends'], protocol, fold, clock, stamps)
        support = {}
        for name, rows in parts.items():
            arrays[f"{fold['name']}_{name}"] = rows
            support[name] = dict(rows=len(rows), positive=int(data.y[rows].sum()),
                                 negative=int(len(rows)-data.y[rows].sum()),
                                 cusum={h: int(mask[rows].sum()) for h, mask in masks.items()})
        for train, evaluate in (('train', 'validation'), ('refit', 'test')):
            a, b = parts[train], parts[evaluate]
            if len(a) and len(b) and data.info_ends[a].max() >= data.starts[b].min():
                raise ValueError('Training label overlaps evaluation')
        report['folds'].append(dict(name=fold['name'], support=support,
                                    external_candidates=summarize(obs, rawparts['test'])))
    candidate_arrays = {k: v for k, v in obs.items() if k != 'events'}
    for h, mask in obs['events'].items():
        candidate_arrays[f'cusum_{h}'] = mask
    print(f'Saving {len(data.y):,} rows and {len(obs["starts"]):,} candidates.', flush=True)
    artifacts = dict(dataset=save_arrays(output/'dataset.npz', arrays),
                     candidates=save_arrays(output/'candidates.npz', candidate_arrays))
    return report, artifacts, dict(feature_names=data.names, feature_groups=data.groups,
                                   feature_windows_unit='observed_candles', timestamps='UTC epoch seconds')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/Users/leohermoso/FXNN/data/histdata/EURUSD'))
    parser.add_argument('--output', type=Path, default=ROOT/'output/session_dataset_v1')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; preserve prior run')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        parser.error('Commit contract and code before labeling')
    spec = json.loads(SPEC.read_text())
    parent = ROOT/'configs/multiyear_v1.json'
    if digest(parent) != spec['parent_protocol_sha256']:
        raise ValueError('Parent protocol changed')
    protocol = load_protocol(parent)
    if (spec['kind'] != 'dataset_rebuild_no_fits' or spec['new_model_fits'] != 0
            or spec['source_years'] != [2022, 2023] or protocol['source_years'] != [2022, 2023]
            or spec['horizon_open_minutes'] != 4320 or spec['censor_from_missing_minutes'] != 15
            or spec['thresholds'] != [0.0005, 0.001]):
        raise ValueError('Unregistered dataset configuration')
    ledger = Path(spec['global_ledger'])
    before = ledger.read_bytes()
    records = verify_ledger(before)
    consumed = records[0]['prior_fits'] + sum(r['kind'] == 'fit_started' for r in records)
    args.output.mkdir(parents=True, exist_ok=False)
    hashes = dict(config=digest(SPEC), contract=digest(CONTRACT), parent=digest(parent),
                  code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  sources={p.name: digest(p) for p in sorted((ROOT/'fxnn').glob('*.py'))},
                  ledger=hashlib.sha256(before).hexdigest())
    try:
        candles, provenance = load_development(args.root, protocol)
        start, end = map(utc_epoch, protocol['development'])
        # Calendar-only extension covers deadlines, never reads confirmation prices.
        clock = weekly_fx_clock(start, end+10*86400)
        print('Building observed-only session dataset for 2022–2023.', flush=True)
        report, artifacts, schema = build(candles, protocol, spec, clock, args.output)
        historical = ROOT/'docs/experiments/multiyear-v1-data.md'
        report['historical_monthly'] = historical_months(historical)
        hashes['historical_audit'] = digest(historical)
        if ledger.read_bytes() != before:
            raise ValueError('Ledger changed during no-fit rebuild')
        report.update(status='completed', experiment=spec['experiment'], model_fits=0,
                      global_fits_consumed=consumed, ledger_unchanged=True, confirmation_opened=False)
        write_json(args.output/'report.json', report)
        write_json(args.output/'manifest.json', dict(config=spec, hashes=hashes, input_hashes=provenance,
                   artifacts=artifacts, report_sha256=digest(args.output/'report.json'), schema=schema,
                   versions=dict(python=platform.python_version(), numpy=np.__version__)))
    except BaseException as error:
        write_json(args.output/'failure.json', dict(hashes=hashes, error=f'{type(error).__name__}: {error}'))
        raise
    print(json.dumps(report['all_development']), flush=True)


if __name__ == '__main__':
    main()
