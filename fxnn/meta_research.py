"""Stage7 fixed-model meta-filter with full opportunity decisions and exact replay."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np

from .bound_ledger import BoundStageLedger
from .cusum_continuation import score, support, technical_reason, paired_sensitivity
from .cusum_research import identity_hash, restrict
from .data_audit import digest
from .experiment_fit import StageLedger, fit_cached, verified_model, abort_run, contract_hash
from .meta_dataset import ROOT, SPEC, CONTRACT, SOURCE, EXPERIMENT, FIELDS
from .meta_dataset import load_contract, load_bundle, read_json, check_hash, sources
from .meta_primary import choose_threshold, decisions, decision_metrics, threshold_grid
from .mlp_comparison import versions, array_hash, PHASES
from .protocol import utc_epoch
from .session_dataset import save_arrays, write_json
from .session_models import predict_state, open_weights

THREAD_VARIABLES = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')


def inference(preentry, rows, population, models):
    """This function receives no outcome, duration, label or information horizon."""
    rows = np.asarray(rows, dtype=np.int64)
    signal = preentry['side'][rows] != 0
    event = np.ones(len(rows), dtype=bool) if population == 'temporal' else preentry[f'cusum_{population}'][rows]
    causal = preentry['causal_valid'][rows]
    eligible = signal & event & causal
    if not np.isfinite(preentry['X'][rows[eligible]]).all():
        raise ValueError('Nonfinite eligible inference features')
    result = dict(opening_rows=rows, starts=preentry['starts'][rows],
                  entry_indices=preentry['entry_indices'][rows], sides=preentry['side'][rows],
                  primary_signal=signal, event_match=event, causal_valid=causal, operational_eligible=eligible)
    for family, state in models.items():
        available = eligible & (state is not None)
        p = np.full(len(rows), np.nan)
        if state is not None:
            p[available] = predict_state(state, preentry['X'][rows[available]])
        result[f'{family}_probability'] = p
        result[f'{family}_probability_available'] = available
    return result


def opening_identity(opportunities, rows):
    return array_hash(np.column_stack((opportunities['entry_indices'][rows], opportunities['side'][rows])))


def phase_evaluation(opportunities, rows, metric_openings, population, models, selections=None):
    preentry = {k: opportunities[k] for k in ('X', 'side', 'causal_valid', 'starts', 'entry_indices')}
    preentry.update({k: v for k, v in opportunities.items() if k.startswith('cusum_')})
    archive = inference(preentry, rows, population, models)
    # Only after causal inference, attach diagnostic outcomes/horizon membership.
    metric = np.isin(rows, metric_openings)
    if np.any(metric & ~archive['operational_eligible']):
        raise ValueError('Diagnostic metric rows exceed causal opportunity mask')
    y = (opportunities['outcomes'][rows[metric]] == 'take_profit').astype(np.int8)
    archive['metric_mask'] = metric
    archive['outcomes'] = opportunities['outcomes'][rows]
    archive['y'] = np.where(metric, opportunities['outcomes'][rows] == 'take_profit', -1).astype(np.int8)
    source_id = opening_identity(opportunities, rows[metric])
    selected, scores, decision_scores, coverage, grids = {}, {}, {}, {}, {}
    for family, state in models.items():
        p = archive[f'{family}_probability']
        if selections is None:
            selection = (choose_threshold(y, p[metric], source_id) if state is not None else
                         dict(available=False, threshold=None, reason='model_unavailable', grid=None,
                              source_identity_sha256=source_id, rule='maximum_inner_f1_highest_threshold_tie'))
        else:
            selection = selections[family]
        selected[family] = selection
        decision = decisions(p, archive[f'{family}_probability_available'], selection)
        archive.update({f'{family}_{name}': value for name, value in decision.items()})
        scores[family] = score(y, p[metric]) if state is not None else None
        grids[family] = threshold_grid(y, p[metric]) if state is not None else None
        usable = state is not None and selection['available']
        decision_scores[family] = (dict(available=True, reason=None, **decision_metrics(y, decision['accepted'][metric]))
                                   if usable else dict(available=False, reason='model_unavailable' if state is None else selection['reason'],
                                                       metrics=None))
        coverage[family] = dict(probability_available=int(archive[f'{family}_probability_available'].sum()),
            acceptance_available=int(decision['acceptance_available'].sum()),
            accepted=int((decision['accepted'] == 1).sum()) if usable else None,
            rejected=int((decision['accepted'] == 0).sum()) if usable else None,
            unavailable=int((~decision['acceptance_available']).sum()),
            unavailable_reasons=dict(Counter(decision['acceptance_reason'][~decision['acceptance_available']].tolist())))
    archive['primary_acceptance_available'] = archive['operational_eligible'].copy()
    archive['primary_accepted'] = np.where(archive['operational_eligible'], 1, -1).astype(np.int8)
    sensitivity = (paired_sensitivity(y, archive['logistic_probability'][metric], archive['constant_probability'][metric],
                                     archive['starts'][metric]) if all(state is not None for state in models.values()) else None)
    report = dict(identity_sha256=opening_identity(opportunities, rows), metric_identity_sha256=source_id,
        support=support(y), selections=selected, scores=scores, threshold_diagnostics=grids, selected_decision_scores=decision_scores,
        primary_decision_scores=decision_metrics(y, np.ones(len(y), dtype=np.int8)), paired_sensitivity=sensitivity,
        coverage=dict(openings=len(rows), primary_signals=int(archive['primary_signal'].sum()),
            primary_event_matches=int((archive['primary_signal'] & archive['event_match']).sum()),
            causal_primary_event=int(archive['operational_eligible'].sum()), metric_rows=int(metric.sum()),
            primary_accepted=int(archive['operational_eligible'].sum()), models=coverage,
            all_opening_outcomes=dict(Counter(archive['outcomes'].tolist())),
            eligible_outcomes=dict(Counter(archive['outcomes'][archive['operational_eligible']].tolist())),
            primary_reasons=dict(Counter(opportunities['primary_reason'][rows].tolist())),
            causal_reasons=dict(Counter(opportunities['causal_reason'][rows].tolist()))))
    return archive, report


def canonical_fit(fit):
    result = dict(fit)
    result.pop('requested_fit_id', None)
    result['reused'] = False
    return result


def replay_fit(data, rows, family, fit, spec, clock, ledger, hashes, output, prefix):
    reason = technical_reason(data, rows, family == 'constant')
    if fit['status'] == 'technically_unavailable':
        expected = dict(status='technically_unavailable', reason=reason, fit_id=None, support=support(data.y[rows]))
        if reason is None or fit != expected:
            raise ValueError('Technical unavailability changed')
        return None
    if reason is not None:
        raise ValueError('Attempted fit has invalid training support')
    contract = dict(experiment=EXPERIMENT, stage=7, task='dynamic', family=family,
        parameters=spec['logistic'] if family == 'logistic' else {}, identities=identity_hash(data, rows),
        features=data.names, groups=data.groups,
        arrays={name: array_hash(getattr(data, name)[rows]) for name in FIELDS},
        weights_sha256=array_hash(open_weights(data, rows, clock)), versions=versions(),
        source_hashes=hashes, weights_clock='scheduled_open_minutes_realized_ends')
    if fit['contract'] != contract or fit['contract_sha256'] != contract_hash(contract):
        raise ValueError('Training contract changed')
    normalized = canonical_fit(fit)
    if fit['status'] == 'succeeded':
        return verified_model(normalized, output, ledger, EXPERIMENT, hashes=hashes,
                              expected_contract=contract, ledger_prefix=prefix)
    if fit['status'] != 'failed':
        raise ValueError('Incomplete fit cannot be replayed')
    records = ledger.records()
    matching = [r for r in records if r['kind'] == 'fit_finished' and r.get('experiment') == EXPERIMENT
                and r.get('fit_id') == fit['fit_id']]
    starts = [r for r in records if r['kind'] == 'fit_started' and r.get('experiment') == EXPERIMENT
              and r.get('fit_id') == fit['fit_id']]
    if (len(matching) != 1 or matching[0]['status'] != 'failed' or matching[0]['result'] != normalized
            or len(starts) != 1 or starts[0]['hashes'] != {**hashes, 'training_contract_sha256': contract_hash(contract)}):
        raise ValueError('Failed fit lacks authoritative record')
    return None


def persist_phase(output, name, archive, report, saved=None):
    path = output/f'{name}.npz'
    if saved is None:
        artifact = save_arrays(path, archive)
        result = {**report, 'predictions_file': path.name, 'predictions_sha256': artifact['sha256']}
        write_json(output/f'{name}.json', result)
        return result
    if saved['predictions_file'] != path.name:
        raise ValueError('Prediction path changed')
    check_hash(path, saved['predictions_sha256'])
    with np.load(path, allow_pickle=False) as loaded:
        if set(loaded.files) != set(archive):
            raise ValueError('Opportunity archive fields changed')
        for key, value in archive.items():
            np.testing.assert_array_equal(loaded[key], value)
    result = {**report, 'predictions_file': path.name, 'predictions_sha256': saved['predictions_sha256']}
    if result != saved or read_json(output/f'{name}.json') != result:
        raise ValueError('Thresholds, opportunity coverage or metrics changed')
    return result


def run_models(bundle, protocol, spec, clock, ledger, hashes, output, replay=None, prefix=None):
    data, op = bundle['data'], bundle['opportunities']
    reports, cache = [], {}
    for index, fold in enumerate(protocol['folds']):
        parts = bundle['partitions'][fold['name']]
        variants = {'temporal': parts, **{h: restrict(parts, mask) for h, mask in bundle['masks'].items()}}
        report = dict(fold=fold['name'], phases={})
        inner_selections = {}
        if replay is not None and replay[index]['fold'] != fold['name']:
            raise ValueError('Fold topology changed')
        for phase, train, evaluate in PHASES:
            begin = utc_epoch(fold['validation_start'] if phase == 'inner' else fold['test_start'])
            end = utc_epoch(fold['test_start'] if phase == 'inner' else fold['test_end'])
            opening_rows = np.flatnonzero((op['starts'] >= begin) & (op['starts'] < end))
            report['phases'][phase] = {}
            for universe, selected in variants.items():
                models, fits = {}, {}
                saved = None if replay is None else replay[index]['phases'][phase][universe]
                for family in ('constant', 'logistic'):
                    fit_id = f"{fold['name']}:{phase}:{universe}:{family}"
                    if saved is None:
                        print(f'Starting {fit_id}', flush=True)
                        models[family], fits[family] = fit_cached(data, selected[train], family,
                            spec['logistic'] if family == 'logistic' else {}, clock, ledger,
                            EXPERIMENT, 'dynamic', fit_id, fold['name'], hashes, cache, output)
                    else:
                        fits[family] = saved['fits'][family]
                        models[family] = replay_fit(data, selected[train], family, fits[family], spec,
                                                   clock, ledger, hashes, output, prefix)
                metric_openings = bundle['opening_rows'][selected[evaluate]]
                archive, evaluation = phase_evaluation(op, opening_rows, metric_openings, universe, models,
                                                       None if phase == 'inner' else inner_selections[universe])
                if phase == 'inner':
                    inner_selections[universe] = evaluation['selections']
                entry = dict(fits=fits, evaluation=evaluation)
                report['phases'][phase][universe] = persist_phase(output, f"{fold['name']}_{phase}_{universe}",
                                                                  archive, entry, saved)
        reports.append(report)
    return reports


def conclude(reports, thresholds):
    comparisons = {}
    for universe in ('temporal', *map(str, thresholds)):
        items = [r['phases']['refit'][universe]['evaluation'] for r in reports]
        scores = [r['scores'] for r in items]
        brier = None
        if len(scores) != 3 or any(s[name] is None for s in scores for name in ('constant', 'logistic')):
            status = 'technically_unavailable_comparison'
        elif any(s[name][metric] is None for s in scores for name in ('constant', 'logistic') for metric in ('log_loss', 'brier')):
            status = 'inconclusive_empty_evaluation'
        else:
            brier = float(np.mean([s['logistic']['brier']-s['constant']['brier'] for s in scores]))
            gain = all(s['logistic']['log_loss'] < s['constant']['log_loss'] for s in scores)
            status = 'consistent_descriptive_gain' if gain and brier <= 0 else 'mixed_or_unfavorable_predictive_result'
        comparisons[universe] = dict(probability_comparison=status, mean_brier_delta=brier,
            selected_filter_available_by_fold={r['fold']: {name: r['phases']['refit'][universe]['evaluation']['selected_decision_scores'][name]['available']
                                                         for name in ('constant', 'logistic')} for r in reports})
    return dict(populations=comparisons, inference='inconclusive_under_dependence_and_informed_design',
                profit_claim=False, task_selection='dynamic_preregistered_mechanistic_continuation',
                no_threshold_borrowing=True)


def execute(bundle, protocol, spec, clock, hashes, output):
    """Instantiate the bound ledger here so callers cannot bypass atomic reservation."""
    ledger = BoundStageLedger(spec['global_ledger'], 7, spec['expected_prior_fits'], spec['ledger_before_sha256'])
    before = ledger.path.read_bytes()
    if ledger.consumed() != spec['expected_prior_fits'] or hashlib.sha256(before).hexdigest() != spec['ledger_before_sha256']:
        raise ValueError('Frozen ledger preflight changed')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    try:
        (output/'ledger-before.jsonl').write_bytes(before)
        write_json(output/'run.json', dict(spec=spec, hashes=hashes))
        ledger.start_run(EXPERIMENT, spec['max_model_fits'], hashes, independent_failures=True)
        folds = run_models(bundle, protocol, spec, clock, ledger, hashes, output)
        count = ledger.consumed()
        report = dict(experiment=EXPERIMENT, status='completed', hashes=hashes, versions=versions(),
            folds=folds, conclusion=conclude(folds, spec['thresholds']), fits_before=spec['expected_prior_fits'],
            fits_after=count, new_fits=count-spec['expected_prior_fits'], confirmation_opened=False)
        write_json(output/'report.json', report)
        if not ledger.path.read_bytes().startswith(before):
            raise ValueError('Ledger prefix changed')
        ledger.finish_run(EXPERIMENT, 'completed', dict(report_sha256=digest(output/'report.json'), new_fits=report['new_fits']))
        after = ledger.path.read_bytes()
        ledger.records()
        if not after.startswith(before):
            raise ValueError('Ledger prefix changed after completion')
        with (output/'ledger-after.jsonl').open('xb') as stream:
            stream.write(after)
        return report
    except BaseException as error:
        abort_run(ledger, EXPERIMENT, output, error)
        raise


def verify_sources(expected):
    for name, value in expected.items():
        if Path(name).name != name:
            raise ValueError('Invalid frozen source module path')
        check_hash(ROOT/'fxnn'/name, value)


def verify(output, dataset, source, spec, protocol):
    output = Path(output)
    ledger = StageLedger(spec['global_ledger'], 7)
    raw = ledger.path.read_bytes()
    records = ledger.records()
    report, run = read_json(output/'report.json'), read_json(output/'run.json')
    hashes = run['hashes']
    if (run['spec'] != spec or report['hashes'] != hashes or report['versions'] != versions()
            or hashes['config'] != digest(SPEC) or hashes['protocol'] != digest(CONTRACT)
            or hashes['dataset_manifest'] != digest(Path(dataset)/'manifest.json')):
        raise ValueError('Meta research input binding changed')
    verify_sources(hashes['source_hashes'])
    before = (output/'ledger-before.jsonl').read_bytes()
    after = (output/'ledger-after.jsonl').read_bytes()
    if not raw.startswith(after) or not after.startswith(before) or hashlib.sha256(before).hexdigest() != spec['ledger_before_sha256']:
        raise ValueError('Meta research ledger snapshot changed')
    starts = [r for r in records if r['kind'] == 'run_started' and r.get('experiment') == EXPERIMENT]
    finished = [r for r in records if r['kind'] == 'run_finished' and r.get('experiment') == EXPERIMENT]
    fits = [r for r in records if r['kind'] == 'fit_started' and r.get('experiment') == EXPERIMENT]
    if (len(starts) != 1 or starts[0]['hashes'] != hashes or starts[0]['max_fits'] != spec['max_model_fits']
            or len(finished) != 1 or finished[0]['status'] != 'completed'
            or finished[0]['result'] != dict(report_sha256=digest(output/'report.json'), new_fits=len(fits))
            or json.loads(after.splitlines()[-1]) != finished[0]
            or report['status'] != 'completed' or report['experiment'] != EXPERIMENT
            or report['confirmation_opened'] is not False or report['new_fits'] != len(fits)
            or report['fits_before'] != spec['expected_prior_fits']
            or report['fits_after'] != spec['expected_prior_fits']+len(fits)
            or finished[0]['consumed_total'] != report['fits_after'] or len(fits) > spec['max_model_fits']):
        raise ValueError('Meta report lacks authoritative completed ledger binding')
    bundle, clock, _ = load_bundle(dataset, source, spec, protocol, ledger)
    replayed = run_models(bundle, protocol, spec, clock, ledger, hashes, output, replay=report['folds'], prefix=before)
    if replayed != report['folds'] or conclude(replayed, spec['thresholds']) != report['conclusion']:
        raise ValueError('Meta conclusions or fold reports changed')
    if ledger.path.read_bytes() != raw:
        raise ValueError('Read-only replay changed ledger')
    return dict(status='verified', model_fits=0, folds_replayed=len(replayed), ledger_unchanged=True,
                report_sha256=digest(output/'report.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT/'output/meta_dataset_v1')
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=ROOT/'output'/EXPERIMENT)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    for name in THREAD_VARIABLES:
        if os.environ.get(name) != '1':
            raise ValueError(f'Set {name}=1 before Python startup')
    spec, protocol = load_contract()
    if args.verify:
        print(json.dumps(verify(args.output, args.dataset, args.source, spec, protocol)), flush=True)
        return
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        parser.error('Commit protocol and code before fitting')
    ledger = StageLedger(spec['global_ledger'], 7)
    bundle, clock, _ = load_bundle(args.dataset, args.source, spec, protocol, ledger)
    hashes = dict(config=digest(SPEC), protocol=digest(CONTRACT), source_hashes=sources(),
                  dataset_manifest=digest(args.dataset/'manifest.json'), ledger_before=spec['ledger_before_sha256'],
                  code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
    report = execute(bundle, protocol, spec, clock, hashes, args.output)
    print(json.dumps(dict(status='completed', new_fits=report['new_fits'], total_fits=report['fits_after'])), flush=True)


if __name__ == '__main__':
    main()
