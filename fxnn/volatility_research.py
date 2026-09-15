"""Fixed task-specific models and read-only replay for volatility_barriers_v1."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np

from .cusum_continuation import paired_sensitivity, score, support, technical_reason
from .cusum_research import identity_hash, restrict
from .data_audit import digest, SOURCE_INVENTORY
from .experiment_fit import StageLedger, abort_run, fit_cached, verified_model
from .mlp_comparison import array_hash, versions, PHASES
from .protocol import utc_epoch
from .research import Dataset
from .session_clock import weekly_fx_clock
from .session_dataset import save_arrays, write_json
from .session_models import open_weights, predict_state
from .volatility import volatility_partitions
from .volatility_dataset import ROOT, SPEC, CONTRACT, TASKS, load_contract

EXPERIMENT = 'volatility_barriers_v1'
SOURCE_ROOT = Path('/Users/leohermoso/FXNN/data/histdata/EURUSD')
THREAD_VARIABLES = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                    'VECLIB_MAXIMUM_THREADS')


def read_json(path):
    return json.loads(Path(path).read_text())


def check_hash(path, expected):
    if digest(path) != expected:
        raise ValueError(f'Artifact changed: {path}')


def source_hashes():
    return {p.name: digest(p) for p in sorted((ROOT/'fxnn').glob('*.py'))}


def verify_sources(expected):
    # Later stages may add modules; every module frozen in this run must match.
    # Any change to an import in a frozen module still changes its own hash.
    for name, value in expected.items():
        if Path(name).name != name:
            raise ValueError('Invalid frozen module name')
        check_hash(ROOT / 'fxnn' / name, value)


def load_data(directory, spec, protocol, ledger, source_root=SOURCE_ROOT):
    """Verify every input artifact and recompute the conservative partitions."""
    directory = Path(directory)
    manifest = read_json(directory/'manifest.json')
    hashes = manifest['hashes']
    if (manifest['config'] != spec or hashes['config'] != digest(SPEC)
            or hashes['protocol'] != digest(CONTRACT)
            or hashes['parent'] != digest(ROOT/'configs/multiyear_v1.json')):
        raise ValueError('Dataset contract or implementation changed')
    verify_sources(hashes['sources'])
    prefix = (directory/'ledger-before.jsonl').read_bytes()
    if hashlib.sha256(prefix).hexdigest() != hashes['ledger'] or not ledger.path.read_bytes().startswith(prefix):
        raise ValueError('Dataset ledger prefix changed')
    ledger.records()  # Validate full current hash chain, not only its byte prefix.
    check_hash(directory/'report.json', manifest['report_sha256'])
    if read_json(directory/'report.json')['status'] != 'completed':
        raise ValueError('Dataset build did not complete')
    for name, expected in manifest['input_hashes'].items():
        path = SOURCE_INVENTORY if name == 'versioned_source_inventory' else Path(source_root)/name
        allowed = {f'EURUSD_{year}_{suffix}' for year in (2022, 2023)
                   for suffix in ('m1_bid_utc.csv', 'manifest.json')}
        if name != 'versioned_source_inventory' and name not in allowed:
            raise ValueError('Reserved or invalid source artifact')
        check_hash(path, expected)
    check_hash(directory/'observed.npz', manifest['artifacts']['observed']['sha256'])
    with np.load(directory/'observed.npz', allow_pickle=False) as archive:
        stamps = archive['stamps']
    begin, end = map(utc_epoch, protocol['development'])
    if stamps.ndim != 1 or np.any(np.diff(stamps) <= 0) or np.any((stamps < begin) | (stamps >= end)):
        raise ValueError('Invalid observed development timestamps')
    clock = weekly_fx_clock(begin, end+10*86400)
    tasks = {}
    for task in TASKS:
        for name in ('dataset', 'candidates'):
            check_hash(directory/task/f'{name}.npz', manifest['artifacts'][task][name]['sha256'])
        with np.load(directory/task/'dataset.npz', allow_pickle=False) as archive:
            fields = {name: archive[name] for name in
                      ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides')}
            data = Dataset(**fields, names=archive['feature_names'].tolist(),
                           groups=manifest['schema']['feature_groups'], dropped_warmup=0)
            if data.X.shape != (len(data.y), 28) or not np.isfinite(data.X).all():
                raise ValueError('Invalid task feature matrix')
            support(data.y)
            if np.any(data.ends <= data.starts) or np.any(data.ends > data.info_ends):
                raise ValueError('Invalid task realized intervals')
            if (np.any(archive['last_information_bar_end'] < data.ends)
                    or np.any(archive['last_information_bar_end'] > data.info_ends)):
                raise ValueError('Invalid downstream information intervals')
            observed = archive['observed_indices']
            if np.any(observed < 0) or np.any(observed >= len(stamps)):
                raise ValueError('Invalid observed identity')
            np.testing.assert_array_equal(stamps[observed], data.starts)
            masks = {str(h): archive[f'cusum_{h}'] for h in spec['thresholds']}
            if any(mask.dtype != np.bool_ or mask.shape != data.y.shape for mask in masks.values()):
                raise ValueError('Invalid population mask')
            partitions = {}
            for fold in protocol['folds']:
                parts = volatility_partitions(data.starts, data.info_ends, protocol, fold, clock, stamps)
                for name, rows in parts.items():
                    np.testing.assert_array_equal(rows, archive[f"{fold['name']}_{name}"])
                partitions[fold['name']] = parts
            tasks[task] = dict(data=data, masks=masks, partitions=partitions)
    return tasks, clock, manifest


def evaluate(data, rows, models):
    predictions = {name: predict_state(state, data.X[rows])
                   for name, state in models.items() if state is not None}
    scores = {name: score(data.y[rows], predictions[name]) if name in predictions else None
              for name in ('constant', 'logistic')}
    sensitivity = (paired_sensitivity(data.y[rows], predictions['logistic'], predictions['constant'],
                                     data.starts[rows]) if len(predictions) == 2 else None)
    arrays = dict(rows=rows, entry_indices=data.entry_indices[rows], sides=data.sides[rows],
                  starts=data.starts[rows], y=data.y[rows], **predictions)
    result = dict(identity_sha256=identity_hash(data, rows), support=support(data.y[rows]),
                  scores=scores, paired_sensitivity=sensitivity)
    return arrays, result


def run_models(tasks, protocol, spec, clock, ledger, hashes, output):
    reports, cache = {}, {}
    for task in TASKS:
        bundle = tasks[task]
        data = bundle['data']
        reports[task] = []
        for fold in protocol['folds']:
            parts = bundle['partitions'][fold['name']]
            populations = {'temporal': parts, **{h: restrict(parts, mask) for h, mask in bundle['masks'].items()}}
            fold_report = dict(fold=fold['name'], phases={})
            for phase, train, evaluation in PHASES:
                result = {}
                for population, selected in populations.items():
                    models, fits = {}, {}
                    for family in ('constant', 'logistic'):
                        fit_id = f"{task}:{fold['name']}:{phase}:{population}:{family}"
                        print(f'Starting {fit_id}', flush=True)
                        models[family], fits[family] = fit_cached(data, selected[train], family,
                            spec['logistic'] if family == 'logistic' else {}, clock, ledger,
                            EXPERIMENT, task, fit_id, fold['name'], hashes, cache, output)
                        print(f"{fit_id}: {fits[family]['status']}, reused={fits[family].get('reused', False)}", flush=True)
                    arrays, evaluation_report = evaluate(data, selected[evaluation], models)
                    path = output/f"{task}_{fold['name']}_{phase}_{population}.npz"
                    artifact = save_arrays(path, arrays)
                    result[population] = dict(fits=fits, evaluation={**evaluation_report,
                        'predictions_file': path.name, 'predictions_sha256': artifact['sha256']})
                fold_report['phases'][phase] = result
                write_json(output/f"{task}_{fold['name']}_{phase}.json", result)
            reports[task].append(fold_report)
    return reports


def conclude(reports, thresholds):
    result = {}
    for task in TASKS:
        result[task] = {}
        for population in ('temporal', *map(str, thresholds)):
            scores = [r['phases']['refit'][population]['evaluation']['scores'] for r in reports[task]]
            delta = None
            if len(scores) != 3 or any(s[m] is None for s in scores for m in ('constant', 'logistic')):
                status = 'technically_unavailable_comparison'
            elif any(s[m][metric] is None for s in scores for m in ('constant', 'logistic')
                     for metric in ('log_loss', 'brier')):
                status = 'inconclusive_empty_evaluation'
            else:
                delta = float(np.mean([s['logistic']['brier']-s['constant']['brier'] for s in scores]))
                gain = all(s['logistic']['log_loss'] < s['constant']['log_loss'] for s in scores)
                status = 'consistent_descriptive_gain' if gain and delta <= 0 else 'mixed_or_unfavorable_predictive_result'
            result[task][population] = dict(status=status, mean_brier_delta=delta)
    return dict(descriptive=result, inference='inconclusive_under_dependence_and_informed_design',
                task_ranking_performed=False, profit_claim=False,
                next_stage_task='dynamic', next_stage_rule='preregistered_mechanistic_continuation_not_score_selection')


def execute(tasks, protocol, spec, clock, ledger, hashes, output, manifest):
    """Global lifecycle: any post-fit storage error ends this scientific run."""
    output = Path(output)
    before = ledger.path.read_bytes()
    if ('ledger_before_sha256' in spec
            and hashlib.sha256(before).hexdigest() != spec['ledger_before_sha256']):
        raise ValueError('Canonical ledger bytes differ from preregistration')
    if ledger.consumed() != spec['expected_prior_fits']:
        raise ValueError('Canonical budget changed before fit reservation')
    output.mkdir(parents=True, exist_ok=False)
    try:
        (output/'ledger-before.jsonl').write_bytes(before)
        write_json(output/'run.json', dict(hashes=hashes, spec=spec))
        ledger.start_run(EXPERIMENT, spec['max_model_fits'], hashes, independent_failures=True)
        reports = run_models(tasks, protocol, spec, clock, ledger, hashes, output)
        after_count = ledger.consumed()
        report = dict(experiment=EXPERIMENT, status='completed', hashes=hashes, versions=versions(),
                      tasks=reports, conclusion=conclude(reports, spec['thresholds']),
                      fits_before=spec['expected_prior_fits'], fits_after=after_count,
                      new_fits=after_count-spec['expected_prior_fits'], confirmation_opened=False,
                      dataset_input_hashes=manifest['input_hashes'])
        if not ledger.path.read_bytes().startswith(before):
            raise ValueError('Canonical ledger prefix changed')
        write_json(output/'report.json', report)
        ledger.finish_run(EXPERIMENT, 'completed', dict(report_sha256=digest(output/'report.json'),
                          new_fits=report['new_fits']))
        after = ledger.path.read_bytes()
        ledger.records()
        if not after.startswith(before):
            raise ValueError('Canonical ledger prefix changed')
        with (output/'ledger-after.jsonl').open('xb') as stream:
            stream.write(after)
        return report
    except BaseException as error:
        abort_run(ledger, EXPERIMENT, output, error)
        raise


def canonical_fit(report):
    result = dict(report)
    result.pop('requested_fit_id', None)
    result['reused'] = False
    return result


def verify_training(data, rows, family, fit, task, spec, clock, hashes):
    reason = technical_reason(data, rows, family == 'constant')
    if fit['status'] == 'technically_unavailable':
        if fit.get('reason') != reason or reason is None or fit['fit_id'] is not None:
            raise ValueError('Unavailable fit does not match technical support')
        return
    if reason is not None:
        raise ValueError('Attempted fit has invalid training support')
    contract = fit['contract']
    expected = dict(experiment=EXPERIMENT, stage=6, task=task, family=family,
                    parameters=spec['logistic'] if family == 'logistic' else {},
                    identities=identity_hash(data, rows), features=data.names, groups=data.groups,
                    arrays={name: array_hash(getattr(data, name)[rows]) for name in
                            ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides')},
                    weights_sha256=array_hash(open_weights(data, rows, clock)), versions=versions(),
                    source_hashes=hashes, weights_clock='scheduled_open_minutes_realized_ends')
    if contract != expected:
        raise ValueError('Saved model training contract does not match fold')


def replay_reports(tasks, protocol, spec, clock, ledger, hashes, output, reports, prefix):
    """Reconstruct saved predictions, identity, scores and weekly sensitivities."""
    count = 0
    for task in TASKS:
        bundle = tasks[task]
        data = bundle['data']
        if [r['fold'] for r in reports[task]] != [f['name'] for f in protocol['folds']]:
            raise ValueError('Fold report topology changed')
        for fold, saved in zip(protocol['folds'], reports[task], strict=True):
            parts = bundle['partitions'][fold['name']]
            populations = {'temporal': parts, **{h: restrict(parts, m) for h, m in bundle['masks'].items()}}
            for phase, train, evaluation in PHASES:
                if read_json(output/f"{task}_{fold['name']}_{phase}.json") != saved['phases'][phase]:
                    raise ValueError('Phase report changed')
                for population, selected in populations.items():
                    item = saved['phases'][phase][population]
                    models = {}
                    for family in ('constant', 'logistic'):
                        fit = item['fits'][family]
                        verify_training(data, selected[train], family, fit, task, spec, clock, hashes)
                        if fit['status'] == 'succeeded':
                            models[family] = verified_model(canonical_fit(fit), output, ledger, EXPERIMENT,
                                hashes=hashes, ledger_prefix=prefix)
                        elif fit['status'] == 'failed':
                            matching = [r for r in ledger.records() if r['kind'] == 'fit_finished'
                                        and r.get('experiment') == EXPERIMENT and r.get('fit_id') == fit['fit_id']]
                            if len(matching) != 1 or matching[0]['status'] != 'failed' or matching[0]['result'] != canonical_fit(fit):
                                raise ValueError('Failed fit lacks authoritative ledger record')
                            models[family] = None
                        elif fit['status'] == 'technically_unavailable':
                            models[family] = None
                        else:
                            raise ValueError('Incomplete fit cannot be replayed as completed')
                    arrays, expected = evaluate(data, selected[evaluation], models)
                    recorded = item['evaluation']
                    path = output/f"{task}_{fold['name']}_{phase}_{population}.npz"
                    if recorded['predictions_file'] != path.name:
                        raise ValueError('Unexpected prediction archive path')
                    check_hash(path, recorded['predictions_sha256'])
                    with np.load(path, allow_pickle=False) as archive:
                        if set(archive.files) != set(arrays):
                            raise ValueError('Prediction archive fields changed')
                        for name, values in arrays.items():
                            np.testing.assert_array_equal(archive[name], values)
                            if name in ('constant', 'logistic'):
                                count += len(values)
                    actual = {k: v for k, v in recorded.items() if not k.startswith('predictions_')}
                    if actual != expected:
                        raise ValueError('Scores or paired sensitivity changed')
    return count


def verify(output, dataset, source_root=SOURCE_ROOT):
    output, dataset = Path(output), Path(dataset)
    spec, protocol = load_contract()
    ledger = StageLedger(spec['global_ledger'])
    raw = ledger.path.read_bytes()
    report, run = read_json(output/'report.json'), read_json(output/'run.json')
    hashes = run['hashes']
    if (run['spec'] != spec or report['hashes'] != hashes or report['versions'] != versions()
            or hashes['config'] != digest(SPEC) or hashes['protocol'] != digest(CONTRACT)
            or hashes['dataset_manifest'] != digest(dataset/'manifest.json')):
        raise ValueError('Frozen experiment inputs changed')
    verify_sources(hashes['source_hashes'])
    prefix = (output/'ledger-before.jsonl').read_bytes()
    after = (output/'ledger-after.jsonl').read_bytes()
    if hashlib.sha256(prefix).hexdigest() != hashes['ledger_before'] or not after.startswith(prefix) or not raw.startswith(after):
        raise ValueError('Run ledger prefix or final snapshot changed')
    records = ledger.records()
    matching = [r for r in records if r['kind'] == 'run_finished' and r.get('experiment') == EXPERIMENT]
    starts = [r for r in records if r['kind'] == 'run_started' and r.get('experiment') == EXPERIMENT]
    attempts = [r for r in records if r['kind'] == 'fit_started' and r.get('experiment') == EXPERIMENT]
    if (report['experiment'] != EXPERIMENT or report['status'] != 'completed'
            or report['confirmation_opened'] is not False
            or report['fits_before'] != spec['expected_prior_fits']
            or report['new_fits'] != len(attempts) or not 0 <= len(attempts) <= spec['max_model_fits']
            or report['fits_after'] != report['fits_before']+report['new_fits']
            or len(starts) != 1 or starts[0]['hashes'] != hashes
            or starts[0]['max_fits'] != spec['max_model_fits'] or len(matching) != 1
            or matching[0]['status'] != 'completed'
            or matching[0]['result']['report_sha256'] != digest(output/'report.json')
            or matching[0]['consumed_total'] != report['fits_after']
            or matching[0]['result']['new_fits'] != report['new_fits']):
        raise ValueError('Report lacks authoritative completed run')
    if json.loads(after.splitlines()[-1]) != matching[0]:
        raise ValueError('Final ledger snapshot does not end at completed run')
    tasks, clock, manifest = load_data(dataset, spec, protocol, ledger, source_root)
    if report['dataset_input_hashes'] != manifest['input_hashes']:
        raise ValueError('Reported source provenance changed')
    count = replay_reports(tasks, protocol, spec, clock, ledger, hashes, output, report['tasks'], prefix)
    if report['conclusion'] != conclude(report['tasks'], spec['thresholds']):
        raise ValueError('Conclusion changed')
    if ledger.path.read_bytes() != raw:
        raise ValueError('Read-only verification changed ledger')
    return dict(status='verified', predictions_replayed=count, model_fits=0,
                ledger_unchanged=True, report_sha256=digest(output/'report.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT/'output/volatility_dataset_v1')
    parser.add_argument('--output', type=Path, default=ROOT/'output'/EXPERIMENT)
    parser.add_argument('--source-root', type=Path, default=SOURCE_ROOT)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    for name in THREAD_VARIABLES:
        if os.environ.get(name) != '1':
            raise ValueError(f'Set {name}=1 before Python startup')
    if args.verify:
        print(json.dumps(verify(args.output, args.dataset, args.source_root)), flush=True)
        return
    if args.output.exists():
        parser.error('Output exists; no scientific reruns')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        parser.error('Commit protocol and code before fitting')
    spec, protocol = load_contract()
    ledger = StageLedger(spec['global_ledger'])
    tasks, clock, manifest = load_data(args.dataset, spec, protocol, ledger, args.source_root)
    raw = ledger.path.read_bytes()
    hashes = dict(code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  config=digest(SPEC), protocol=digest(CONTRACT), source_hashes=source_hashes(),
                  dataset_manifest=digest(args.dataset/'manifest.json'),
                  ledger_before=hashlib.sha256(raw).hexdigest())
    report = execute(tasks, protocol, spec, clock, ledger, hashes, args.output, manifest)
    print(json.dumps(dict(status='completed', new_fits=report['new_fits'], total_fits=report['fits_after'])), flush=True)


if __name__ == '__main__':
    main()
