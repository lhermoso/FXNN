"""Frozen-source unilateral projection with a complete causal opening stream."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from .cusum_continuation import support
from .data_audit import digest
from .experiment_fit import StageLedger
from .meta_primary import primary_signals, join_candidates
from .mlp_comparison import versions
from .protocol import load_protocol, utc_epoch
from .research import Dataset
from .session_clock import weekly_fx_clock
from .session_dataset import save_arrays, write_json
from .volatility import volatility_partitions

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT/'configs/meta_primary_v1.json'
CONTRACT = ROOT/'docs/experiments/meta-primary-v1-protocol.md'
SOURCE = Path('/Users/leohermoso/FXNN-issue6/output/volatility_dataset_v1')
EXPERIMENT = 'meta_primary_v1'
FIELDS = ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides')


def read_json(path):
    return json.loads(Path(path).read_text())


def check_hash(path, expected):
    if digest(Path(path)) != expected:
        raise ValueError(f'Frozen artifact changed: {path}')


def arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key] for key in archive.files}


def sources():
    return {path.name: digest(path) for path in sorted((ROOT/'fxnn').glob('*.py'))}


def load_contract():
    spec = read_json(SPEC)
    source = read_json(ROOT/'configs/volatility_barriers_v1.json')
    if (spec['experiment'] != EXPERIMENT or spec['kind'] != 'deterministic_primary_meta_filter'
            or spec['source_years'] != [2022, 2023] or spec['max_model_fits'] != 24
            or spec['expected_prior_fits'] != 141 or spec['history_buffer'] != 1941
            or spec['primary_observed_history'] != 61 or spec['source_task'] != 'dynamic'
            or spec['thresholds'] != [.0005, .001] or spec['acceptance_thresholds'] != [.3, .4, .5]
            or spec['logistic'] != source['logistic'] or spec['versions'] != versions()
            or spec['confirmation_opened'] is not False):
        raise ValueError('Unregistered meta-labeling contract')
    check_hash(ROOT/'configs/multiyear_v1.json', spec['parent_protocol_sha256'])
    check_hash(ROOT/'configs/volatility_barriers_v1.json', spec['source_config_sha256'])
    check_hash(ROOT/'docs/experiments/volatility-barriers-v1-protocol.md', spec['source_protocol_sha256'])
    return spec, load_protocol(ROOT/'configs/multiyear_v1.json')


def load_source(directory, spec, protocol, ledger):
    directory = Path(directory)
    check_hash(directory/'manifest.json', spec['source_dataset_manifest_sha256'])
    manifest = read_json(directory/'manifest.json')
    if manifest['config'] != read_json(ROOT/'configs/volatility_barriers_v1.json'):
        raise ValueError('Frozen source configuration changed')
    for name, expected in manifest['hashes']['sources'].items():
        if Path(name).name != name:
            raise ValueError('Invalid source module path')
        check_hash(ROOT/'fxnn'/name, expected)
    if (manifest['hashes']['config'] != spec['source_config_sha256']
            or manifest['hashes']['protocol'] != spec['source_protocol_sha256']):
        raise ValueError('Source protocol binding changed')
    check_hash(directory/'report.json', spec['source_dataset_report_sha256'])
    if manifest['report_sha256'] != spec['source_dataset_report_sha256']:
        raise ValueError('Source dataset report binding changed')
    raw = ledger.path.read_bytes()
    prefix = (directory/'ledger-before.jsonl').read_bytes()
    if not raw.startswith(prefix) or hashlib.sha256(prefix).hexdigest() != manifest['hashes']['ledger']:
        raise ValueError('Source ledger prefix changed')
    check_hash(directory.parent/'volatility_barriers_v1/report.json', spec['source_models_report_sha256'])
    records = ledger.records()
    completed = [r for r in records if r['kind'] == 'run_finished'
                 and r.get('experiment') == 'volatility_barriers_v1']
    if (len(completed) != 1 or completed[0]['status'] != 'completed'
            or completed[0]['result']['report_sha256'] != spec['source_models_report_sha256']):
        raise ValueError('Source models lack verified completion binding')
    paths = {'observed': directory/'observed.npz', 'dataset': directory/'dynamic/dataset.npz',
             'candidates': directory/'dynamic/candidates.npz'}
    expected = {'observed': spec['source_observed_sha256'], 'dataset': spec['source_dynamic_dataset_sha256'],
                'candidates': spec['source_dynamic_candidates_sha256']}
    for name, path in paths.items():
        check_hash(path, expected[name])
        registered = manifest['artifacts']['observed'] if name == 'observed' else manifest['artifacts']['dynamic'][name]
        if registered['sha256'] != expected[name]:
            raise ValueError('Source manifest array binding changed')
    observed, candidates, source_data = (arrays(paths[name]) for name in ('observed', 'candidates', 'dataset'))
    begin, end = map(utc_epoch, protocol['development'])
    stamps = observed['stamps']
    if stamps.ndim != 1 or np.any(np.diff(stamps) <= 0) or np.any((stamps < begin) | (stamps >= end)):
        raise ValueError('Invalid or reserved observed source timestamps')
    clock = weekly_fx_clock(begin, end+10*86400)
    # Verify selected bilateral data identities without importing source6's bound loader.
    chosen = source_data['candidate_rows']
    for name in ('starts', 'ends', 'info_ends', 'entry_indices', 'sides', 'last_information_bar_end'):
        np.testing.assert_array_equal(source_data[name], candidates[name][chosen])
    return observed, candidates, source_data, manifest, clock


def project(observed, candidates, schema):
    stamps, original = observed['stamps'], observed['original_indices']
    n = len(stamps)
    primary = primary_signals(observed['closes'], observed['breaks'])
    chosen = join_candidates(primary['side'], candidates)
    selected = np.flatnonzero(chosen >= 0)
    if observed['X'].shape != (n, len(schema['feature_names'])):
        raise ValueError('Source feature schema mismatch')
    if candidates['entry_indices'].shape != candidates['entry_local'].shape:
        raise ValueError('Invalid source original identities')
    np.testing.assert_array_equal(candidates['entry_indices'], original[candidates['entry_local']])
    np.testing.assert_array_equal(candidates['starts'], stamps[candidates['entry_local']])
    X = observed['X'].copy()
    X[:, schema['directional_features']] *= primary['side'][:, None]
    X[:, -1] = primary['side']
    causal = np.asarray(observed['causal_valid'])
    if causal.dtype != np.bool_ or causal.shape != (n,):
        raise ValueError('Invalid pre-entry eligibility mask')
    operational = (primary['side'] != 0) & causal
    if not np.isfinite(X[operational]).all():
        raise ValueError('Nonfinite causally eligible primary features')
    opportunities = dict(starts=stamps.copy(), entry_indices=original.copy(),
        observed_indices=np.arange(n, dtype=np.int64), candidate_rows=chosen, X=X,
        causal_valid=causal.copy(), causal_reason=observed['eligibility_reason'].copy(), **primary)
    for key in observed:
        if key.startswith('cusum_'):
            if observed[key].shape != (n,) or observed[key].dtype != np.bool_:
                raise ValueError('Invalid source event mask')
            opportunities[key] = observed[key].copy()
    # Outcomes are joined only after all causal fields and operational features exist.
    opportunities['outcomes'] = np.full(n, 'no_primary_signal', dtype='<U24')
    for name in ('ends', 'info_ends', 'last_information_bar_end'):
        opportunities[name] = stamps.copy()
    for name in ('outcomes', 'ends', 'info_ends', 'last_information_bar_end'):
        opportunities[name][selected] = candidates[name][chosen[selected]]
    conclusive = np.isin(opportunities['outcomes'], ('take_profit', 'stop_loss', 'timeout'))
    retained = np.flatnonzero(operational & conclusive)
    if np.any(opportunities['ends'][retained] <= stamps[retained]):
        raise ValueError('Invalid retained realized interval')
    opportunities['conclusive'] = conclusive
    data = Dataset(X[retained], (opportunities['outcomes'][retained] == 'take_profit').astype(np.int8),
                   stamps[retained], opportunities['ends'][retained], opportunities['info_ends'][retained],
                   original[retained], primary['side'][retained], schema['feature_names'],
                   schema['feature_groups'], 0)
    return data, opportunities, retained


def summary(opportunities):
    side, causal = opportunities['side'], opportunities['causal_valid']
    return dict(openings=len(side), primary_signals=int((side != 0).sum()),
        primary_reasons=dict(Counter(opportunities['primary_reason'].tolist())),
        causal_primary=int(((side != 0) & causal).sum()),
        outcomes=dict(Counter(opportunities['outcomes'].tolist())),
        causal_reasons=dict(Counter(opportunities['causal_reason'].tolist())),
        retained=int(((side != 0) & causal & opportunities['conclusive']).sum()))


def make_bundle(observed, candidates, schema, protocol, clock):
    data, opportunities, opening_rows = project(observed, candidates, schema)
    partitions = {fold['name']: volatility_partitions(data.starts, data.info_ends, protocol, fold,
                   clock, observed['stamps']) for fold in protocol['folds']}
    masks = {key.removeprefix('cusum_'): value[opening_rows] for key, value in opportunities.items()
             if key.startswith('cusum_')}
    return dict(data=data, opportunities=opportunities, opening_rows=opening_rows,
                observed_stamps=observed['stamps'], partitions=partitions, masks=masks)


def verify_projection_source(bundle, source_data):
    """Independent agreement with frozen bilateral X/y for selected identities."""
    chosen = bundle['opportunities']['candidate_rows'][bundle['opening_rows']]
    source_rows = source_data['candidate_rows']
    order = np.argsort(source_rows)
    positions = np.searchsorted(source_rows[order], chosen)
    if np.any(positions >= len(order)):
        raise ValueError('Selected primary row absent from frozen bilateral dataset')
    rows = order[positions]
    np.testing.assert_array_equal(source_rows[rows], chosen)
    for name in FIELDS:
        np.testing.assert_array_equal(getattr(bundle['data'], name), source_data[name][rows])


def dataset_arrays(bundle):
    data = bundle['data']
    result = {name: getattr(data, name) for name in FIELDS}
    result.update(feature_names=np.asarray(data.names), opening_rows=bundle['opening_rows'],
                  last_information_bar_end=bundle['opportunities']['last_information_bar_end'][bundle['opening_rows']])
    for h, mask in bundle['masks'].items():
        result[f'cusum_{h}'] = mask
    for fold, parts in bundle['partitions'].items():
        for name, rows in parts.items():
            result[f'{fold}_{name}'] = rows
    return result


def build(source, output, spec, protocol):
    output = Path(output)
    ledger = StageLedger(spec['global_ledger'], 7)
    before = ledger.path.read_bytes()
    if ledger.consumed() != spec['expected_prior_fits'] or hashlib.sha256(before).hexdigest() != spec['ledger_before_sha256']:
        raise ValueError('Frozen prior ledger changed')
    observed, candidates, source_data, manifest, clock = load_source(source, spec, protocol, ledger)
    output.mkdir(parents=True, exist_ok=False)
    try:
        bundle = make_bundle(observed, candidates, manifest['schema'], protocol, clock)
        verify_projection_source(bundle, source_data)
        artifacts = dict(dataset=save_arrays(output/'dataset.npz', dataset_arrays(bundle)),
                         opportunities=save_arrays(output/'opportunities.npz', bundle['opportunities']))
        report = dict(status='completed', model_fits=0, confirmation_opened=False,
                      coverage=summary(bundle['opportunities']), training_support=support(bundle['data'].y))
        write_json(output/'report.json', report)
        hashes = dict(config=digest(SPEC), protocol=digest(CONTRACT), sources=sources(),
                      source_manifest=digest(Path(source)/'manifest.json'),
                      code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                      ledger_before=hashlib.sha256(before).hexdigest())
        (output/'ledger-before.jsonl').write_bytes(before)
        if ledger.path.read_bytes() != before:
            raise ValueError('Ledger changed during no-fit projection')
        write_json(output/'manifest.json', dict(config=spec, hashes=hashes, artifacts=artifacts,
                   schema=manifest['schema'], report_sha256=digest(output/'report.json')))
        return report
    except BaseException as error:
        write_json(output/'failure.json', dict(error=f'{type(error).__name__}: {error}'))
        raise


def load_bundle(directory, source, spec, protocol, ledger):
    directory = Path(directory)
    manifest = read_json(directory/'manifest.json')
    if manifest['config'] != spec or manifest['hashes']['config'] != digest(SPEC) or manifest['hashes']['protocol'] != digest(CONTRACT):
        raise ValueError('Meta dataset contract changed')
    for name, expected in manifest['hashes']['sources'].items():
        if Path(name).name != name:
            raise ValueError('Invalid source module path')
        check_hash(ROOT/'fxnn'/name, expected)
    prefix = (directory/'ledger-before.jsonl').read_bytes()
    if hashlib.sha256(prefix).hexdigest() != manifest['hashes']['ledger_before'] or not ledger.path.read_bytes().startswith(prefix):
        raise ValueError('Meta dataset ledger prefix changed')
    check_hash(directory/'report.json', manifest['report_sha256'])
    observed, candidates, source_data, source_manifest, clock = load_source(source, spec, protocol, ledger)
    if manifest['hashes']['source_manifest'] != spec['source_dataset_manifest_sha256'] or manifest['schema'] != source_manifest['schema']:
        raise ValueError('Source projection schema changed')
    bundle = make_bundle(observed, candidates, source_manifest['schema'], protocol, clock)
    verify_projection_source(bundle, source_data)
    for name, expected_arrays in (('dataset', dataset_arrays(bundle)), ('opportunities', bundle['opportunities'])):
        path = directory/f'{name}.npz'
        check_hash(path, manifest['artifacts'][name]['sha256'])
        saved = arrays(path)
        if set(saved) != set(expected_arrays):
            raise ValueError('Projection fields changed')
        for key, value in expected_arrays.items():
            np.testing.assert_array_equal(saved[key], value)
    expected_report = dict(status='completed', model_fits=0, confirmation_opened=False,
                          coverage=summary(bundle['opportunities']), training_support=support(bundle['data'].y))
    if read_json(directory/'report.json') != expected_report:
        raise ValueError('Projection coverage changed')
    return bundle, clock, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=ROOT/'output/meta_dataset_v1')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    spec, protocol = load_contract()
    if args.verify:
        ledger = StageLedger(spec['global_ledger'], 7)
        before = ledger.path.read_bytes()
        bundle, _, _ = load_bundle(args.output, args.source, spec, protocol, ledger)
        if ledger.path.read_bytes() != before:
            raise ValueError('Read-only projection verification changed ledger')
        print(json.dumps(dict(status='verified', openings=len(bundle['opportunities']['starts']), model_fits=0)), flush=True)
    else:
        if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
            parser.error('Commit protocol and code before projection')
        print(json.dumps(build(args.source, args.output, spec, protocol)), flush=True)


if __name__ == '__main__':
    main()
