"""Preregistered uniform/sequential bagging with durable traces and exact replay."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np

from .bootstrap_fit import ArtifactStore, EXPERIMENT, FIELDS, fit_unit, replay_unit, abort
from .bound_ledger import BoundStageLedger
from .cusum_continuation import score, support, paired_sensitivity
from .cusum_research import restrict
from .data_audit import digest
from .experiment_fit import StageLedger, contract_hash
from .meta_primary import choose_threshold, threshold_grid, decisions, decision_metrics
from .meta_research import replay_fit as replay_source_fit
from .mlp_comparison import versions, array_hash, PHASES
from .protocol import load_protocol, utc_epoch
from .research import Dataset
from .session_clock import weekly_fx_clock
from .session_models import predict_state
from .sequential_bootstrap import IntervalIndex, canonical_order, seed_for, sample
from .volatility import volatility_partitions

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT/'configs/sequential_bagging_v1.json'
PROTOCOL = ROOT/'docs/experiments/sequential-bagging-v1-protocol.md'
SOURCE = Path('/Users/leohermoso/FXNN-issue7/output/meta_dataset_v1')
SOURCE_MODELS = Path('/Users/leohermoso/FXNN-issue7/output/meta_primary_v1')
SCHEMES = ('uniform','sequential')
MASTERS = (0,1)
MEMBERS = 3
K = 512


def read_json(path): return json.loads(Path(path).read_text())


def check_hash(path, expected):
    if digest(Path(path))!=expected: raise ValueError(f'Frozen artifact changed: {path}')


def sources(): return {p.name:digest(p) for p in sorted((ROOT/'fxnn').glob('*.py'))}


def verify_sources(expected):
    for name,value in expected.items():
        if Path(name).name!=name: raise ValueError('Invalid frozen module path')
        check_hash(ROOT/'fxnn'/name,value)


def load_contract():
    spec = read_json(SPEC); old = read_json(ROOT/'configs/meta_primary_v1.json')
    if (spec['experiment']!=EXPERIMENT or spec['kind']!='paired_unit_weight_bagging'
            or spec['source_years']!=[2022,2023] or spec['draw_count']!=K or spec['members']!=MEMBERS
            or spec['master_seeds']!=list(MASTERS) or spec['schemes']!=list(SCHEMES)
            or spec['max_model_fits']!=156 or spec['expected_prior_fits']!=161
            or spec['versions']!=versions() or spec['logistic']!=old['logistic']
            or spec['thresholds']!=[.0005,.001] or spec['history_buffer']!=1941):
        raise ValueError('Unregistered bagging contract')
    check_hash(ROOT/'configs/meta_primary_v1.json',spec['source']['source_config_sha256'])
    check_hash(ROOT/'docs/experiments/meta-primary-v1-protocol.md',spec['source']['source_protocol_sha256'])
    check_hash(ROOT/'configs/multiyear_v1.json',old['parent_protocol_sha256'])
    return spec,load_protocol(ROOT/'configs/multiyear_v1.json')


def load_source(directory, models_directory, spec, protocol, ledger):
    directory,models_directory = Path(directory),Path(models_directory)
    binding = spec['source']
    check_hash(directory/'manifest.json',binding['source_dataset_manifest_sha256'])
    manifest = read_json(directory/'manifest.json')
    oldspec = read_json(ROOT/'configs/meta_primary_v1.json')
    check_hash(ROOT/'configs/meta_primary_v1.json',binding['source_config_sha256'])
    check_hash(ROOT/'docs/experiments/meta-primary-v1-protocol.md',binding['source_protocol_sha256'])
    if manifest['config']!=oldspec: raise ValueError('Source7 configuration changed')
    verify_sources(manifest['hashes']['sources'])
    check_hash(directory/'report.json',binding['source_dataset_report_sha256'])
    check_hash(models_directory/'report.json',binding['source_models_report_sha256'])
    model_report = read_json(models_directory/'report.json')
    if (model_report['versions']!=versions() or oldspec['versions']!=versions()
            or manifest['hashes']['config']!=binding['source_config_sha256']
            or manifest['hashes']['protocol']!=binding['source_protocol_sha256']
            or model_report['hashes']['config']!=binding['source_config_sha256']
            or model_report['hashes']['protocol']!=binding['source_protocol_sha256']):
        raise ValueError('Frozen source7 runtime/protocol binding changed')
    verify_sources(model_report['hashes']['source_hashes'])
    before = (models_directory/'ledger-before.jsonl').read_bytes()
    after = (models_directory/'ledger-after.jsonl').read_bytes()
    raw = ledger.path.read_bytes(); records=ledger.records()
    if not after.startswith(before) or not raw.startswith(after): raise ValueError('Source7 ledger prefix changed')
    completed=[r for r in records if r['kind']=='run_finished' and r.get('experiment')=='meta_primary_v1']
    if (len(completed)!=1 or completed[0]['status']!='completed'
            or completed[0]['result']['report_sha256']!=binding['source_models_report_sha256']
            or json.loads(after.splitlines()[-1])!=completed[0]):
        raise ValueError('Source7 lacks authoritative completion')
    loaded={}
    for name in ('dataset','opportunities'):
        path=directory/f'{name}.npz'
        check_hash(path,binding['source_artifacts'][name]['sha256'])
        if manifest['artifacts'][name]['sha256']!=binding['source_artifacts'][name]['sha256']:
            raise ValueError('Source7 manifest array binding changed')
        with np.load(path,allow_pickle=False) as archive: loaded[name]={k:archive[k] for k in archive.files}
    fields,op=loaded['dataset'],loaded['opportunities']
    data=Dataset(**{k:fields[k] for k in FIELDS},names=fields['feature_names'].tolist(),groups=manifest['schema']['feature_groups'],dropped_warmup=0)
    begin,end=map(utc_epoch,protocol['development']); stamps=op['starts']
    if np.any(np.diff(stamps)<=0) or np.any((stamps<begin)|(stamps>=end)): raise ValueError('Invalid or reserved opening timestamps')
    clock=weekly_fx_clock(begin,end+10*86400)
    opening=fields['opening_rows']
    if np.any((opening<0)|(opening>=len(stamps))): raise ValueError('Invalid primary opening mapping')
    for name in ('X','starts','entry_indices','ends','info_ends','last_information_bar_end'):
        np.testing.assert_array_equal(fields[name],op[name][opening])
    np.testing.assert_array_equal(data.sides,op['side'][opening])
    np.testing.assert_array_equal(data.y,(op['outcomes'][opening]=='take_profit').astype(np.int8))
    if data.X.shape!=(len(data.y),28) or not np.isfinite(data.X).all(): raise ValueError('Invalid source feature matrix')
    if np.any(fields['last_information_bar_end']<data.ends) or np.any(fields['last_information_bar_end']>data.info_ends):
        raise ValueError('Invalid conservative sampling interval')
    canonical_order(data.entry_indices)
    parts={}
    for fold in protocol['folds']:
        parts[fold['name']]=volatility_partitions(data.starts,data.info_ends,protocol,fold,clock,stamps)
        for name,rows in parts[fold['name']].items(): np.testing.assert_array_equal(rows,fields[f"{fold['name']}_{name}"])
    masks={str(h):fields[f'cusum_{h}'] for h in spec['thresholds']}
    for h,mask in masks.items(): np.testing.assert_array_equal(mask,op[f'cusum_{h}'][opening])
    return dict(data=data,opportunities=op,opening_rows=opening,partitions=parts,masks=masks,
                sampling_ends=fields['last_information_bar_end'],source_report=model_report,source_spec=oldspec,
                source_prefix=before,source_models=models_directory),clock


def validate_references(bundle,protocol,clock,ledger):
    """Audit all frozen references before reserving any stage8 fit budget."""
    data,op=bundle['data'],bundle['opportunities']
    directory=bundle['source_models']; report=bundle['source_report']
    states={}
    for fi,fold in enumerate(protocol['folds']):
        parts=bundle['partitions'][fold['name']]
        variants={'temporal':parts,**{h:restrict(parts,m) for h,m in bundle['masks'].items()}}
        for phase,train,_ in PHASES:
            begin=utc_epoch(fold['validation_start'] if phase=='inner' else fold['test_start'])
            end=utc_epoch(fold['test_start'] if phase=='inner' else fold['test_end'])
            openings=np.flatnonzero((op['starts']>=begin)&(op['starts']<end))
            for pop,selected in variants.items():
                entry=report['folds'][fi]['phases'][phase][pop]
                path=directory/entry['predictions_file']
                if path.name!=f"{fold['name']}_{phase}_{pop}.npz" or path.parent!=directory:
                    raise ValueError('Unexpected frozen reference prediction path')
                check_hash(path,entry['predictions_sha256'])
                if read_json(path.with_suffix('.json'))!=entry: raise ValueError('Frozen reference phase report changed')
                eligible=(op['side'][openings]!=0)&op['causal_valid'][openings]
                if pop!='temporal': eligible &= op[f'cusum_{pop}'][openings]
                with np.load(path,allow_pickle=False) as archive:
                    np.testing.assert_array_equal(archive['opening_rows'],openings)
                    np.testing.assert_array_equal(archive['entry_indices'],op['entry_indices'][openings])
                    for family in ('constant','logistic'):
                        state=replay_source_fit(data,selected[train],family,entry['fits'][family],bundle['source_spec'],clock,ledger,
                                                report['hashes'],directory,bundle['source_prefix'])
                        states[(fi,phase,pop,family)]=state
                        p=np.full(len(openings),np.nan)
                        if state is not None: p[eligible]=predict_state(state,op['X'][openings[eligible]])
                        np.testing.assert_array_equal(archive[f'{family}_probability'],p)
    bundle['reference_states']=states


def sampling_contract(bundle, rows, clock, population):
    data=bundle['data']; order,inverse=canonical_order(data.entry_indices[rows]); ordered=rows[order]
    starts=clock.prefix[clock.indices(data.starts[ordered])]
    ends=clock.prefix[clock.indices(bundle['sampling_ends'][ordered],endpoint=True)]
    contract=dict(task='dynamic',population=population,identities=array_hash(data.entry_indices[ordered]),
                  starts=array_hash(starts),ends=array_hash(ends),clock='scheduled_open_minutes',versions=versions())
    return ordered,starts,ends,order,inverse,contract


def sampling_trace(starts,ends,contract,population,master,member,scheme,output,store,replay=None,identities=None,source_rows=None):
    training_hash=contract_hash(contract)
    seed=seed_for(training_hash,population,master,member)
    config=dict(training=contract,training_sha256=training_hash,master_seed=master,member=member,
                derived_seed=seed,generator='PCG64',scheme=scheme,draw_count=K,
                implementation_sha256=digest(ROOT/'fxnn/sequential_bootstrap.py'),
                protocol_sha256=digest(PROTOCOL),
                numerical_policy=dict(version='positive_tree_v1',absolute_tolerance=1e-14,relative_tolerance=1e-12,
                                      direct_interval_fallback=False))
    key=contract_hash(config); directory=output/'samples'
    if replay is None: directory.mkdir(exist_ok=True)
    path=directory/f'{key}.probabilities.f64'
    uniforms=np.random.Generator(np.random.PCG64(seed)).random(K)
    started=time.perf_counter()
    stream=None
    try:
        if scheme=='sequential':
            if replay is None:
                store.check(); stream=path.open('xb')
            else:
                check_hash(path,replay['probabilities_sha256']); stream=path.open('rb')
        def consume(step,p):
            if scheme=='sequential':
                payload=np.asarray(p,dtype='<f8').tobytes()
                if replay is None: stream.write(payload)
                elif stream.read(len(payload))!=payload: raise ValueError('Sequential probability trace changed')
        result=sample(starts,ends,uniforms,scheme,consume)
        if stream is not None:
            if replay is None: stream.flush(); os.fsync(stream.fileno())
            elif stream.read(1): raise ValueError('Extra probability trace bytes')
    finally:
        if stream is not None: stream.close()
    elapsed=time.perf_counter()-started
    probability_hash=None
    if scheme=='sequential':
        if path.stat().st_size!=K*len(starts)*8: raise ValueError('Incomplete probability trace')
        probability_hash=digest(path)
        if replay is None: store.complete(path)
    arrays={k:result[k] for k in ('draws','uniforms','chosen_probabilities')}
    ids=np.arange(len(starts)) if identities is None else identities
    source_rows=np.arange(len(starts)) if source_rows is None else source_rows
    arrays.update(canonical_original_ids=ids,canonical_source_rows=source_rows,
                  draw_original_ids=ids[result['draws']],draw_source_rows=source_rows[result['draws']])
    arraypath=directory/f'{key}.npz'
    record=dict(contract=config,contract_sha256=key,draws_file=str(arraypath.relative_to(output)),
                probabilities_file=str(path.relative_to(output)) if scheme=='sequential' else None,
                probabilities_sha256=probability_hash,probabilities_shape=[K,len(starts)],
                probability_dtype='<f8' if scheme=='sequential' else 'analytic_1/N',
                diagnostics=result['diagnostics'],tree_queries=result['tree_queries'],max_query_levels=result['max_query_levels'])
    if replay is None:
        artifact=store.arrays(arraypath,arrays)
        record.update(draws_sha256=artifact['sha256'],sampling_seconds=elapsed,
                      probability_bytes=K*len(starts)*8 if scheme=='sequential' else 0)
        store.json(directory/f'{key}.json',record)
    else:
        check_hash(arraypath,replay['draws_sha256'])
        with np.load(arraypath,allow_pickle=False) as archive:
            for name,value in arrays.items(): np.testing.assert_array_equal(archive[name],value)
        record.update(draws_sha256=replay['draws_sha256'],sampling_seconds=replay['sampling_seconds'],probability_bytes=replay['probability_bytes'])
        if record!=replay or read_json(directory/f'{key}.json')!=record: raise ValueError('Sampling report changed')
    return result['draws'],record


def ensemble_predictions(states, X):
    member=[predict_state(state,X) if state is not None else None for state in states]
    result=None if any(p is None for p in member) else np.mean(np.stack(member),axis=0)
    return result,member


def diversity(member):
    pairs={}
    for i in range(len(member)):
        for j in range(i+1,len(member)):
            a,b=member[i],member[j]
            if a is None or b is None: pairs[f'{i}-{j}']=dict(reason='member_unavailable',mean_absolute_difference=None,correlation=None)
            elif not len(a): pairs[f'{i}-{j}']=dict(reason='empty_evaluation',mean_absolute_difference=None,correlation=None)
            else:
                valid=len(a)>1 and np.std(a)>0 and np.std(b)>0
                pairs[f'{i}-{j}']=dict(reason=None if valid else 'constant_or_insufficient_predictions',
                    mean_absolute_difference=float(np.mean(abs(a-b))),correlation=float(np.corrcoef(a,b)[0,1]) if valid else None)
    return pairs


def evaluate(op,rows,metric_openings,population,predictions,inner=None):
    signal=op['side'][rows]!=0
    event=np.ones(len(rows),bool) if population=='temporal' else op[f'cusum_{population}'][rows]
    eligible=signal&event&op['causal_valid'][rows]
    metric=np.isin(rows,metric_openings)
    if np.any(metric&~eligible): raise ValueError('Metric universe exceeds causal inference')
    y=(op['outcomes'][rows[metric]]=='take_profit').astype(np.int8)
    archive=dict(opening_rows=rows,entry_indices=op['entry_indices'][rows],sides=op['side'][rows],starts=op['starts'][rows],
                 primary_signal=signal,event_match=event,causal_valid=op['causal_valid'][rows],
                 primary_reason=op['primary_reason'][rows],causal_reason=op['causal_reason'][rows],
                 operational_eligible=eligible,metric_mask=metric,outcomes=op['outcomes'][rows],
                 primary_accepted=np.where(eligible,1,-1).astype(np.int8))
    result={}; selected={}
    identity=array_hash(np.column_stack((op['entry_indices'][rows[metric]],op['side'][rows[metric]])))
    for name,values in predictions.items():
        p=np.full(len(rows),np.nan); available=eligible&(values is not None)
        if values is not None: p[eligible]=values
        selection=(choose_threshold(y,p[metric],identity) if values is not None else
                   dict(available=False,threshold=None,reason='model_unavailable',grid=None,source_identity_sha256=identity,rule='maximum_inner_f1_highest_threshold_tie')) if inner is None else inner[name]
        decision=decisions(p,available,selection); usable=values is not None and selection['available']
        archive[f'{name}_probability']=p; archive[f'{name}_probability_available']=available
        archive.update({f'{name}_{k}':v for k,v in decision.items()})
        result[name]=dict(scores=score(y,p[metric]) if values is not None else None,
            threshold_grid=threshold_grid(y,p[metric]) if values is not None else None,selection=selection,
            selected_decision_metrics=decision_metrics(y,decision['accepted'][metric]) if usable else None,
            decision_unavailable_reason=None if usable else 'model_unavailable' if values is None else selection['reason'],
            probability_available=int(available.sum()),acceptance_available=int(decision['acceptance_available'].sum()),
            accepted=int((decision['accepted']==1).sum()) if usable else None,rejected=int((decision['accepted']==0).sum()) if usable else None)
        selected[name]=selection
    pairs={}
    for master in MASTERS:
        sequential=f'sequential_{master}'; uniform=f'uniform_{master}'
        for a,b in ((sequential,uniform),(sequential,'full'),(uniform,'full'),(sequential,'weighted_logistic'),(uniform,'weighted_logistic'),(sequential,'weighted_constant'),(uniform,'weighted_constant')):
            if predictions[a] is not None and predictions[b] is not None:
                pairs[f'{a}_minus_{b}']=paired_sensitivity(y,archive[f'{a}_probability'][metric],archive[f'{b}_probability'][metric],op['starts'][rows[metric]])
            else: pairs[f'{a}_minus_{b}']=None
    return archive,dict(models=result,paired_sensitivity=pairs,support=support(y),
        coverage=dict(openings=len(rows),primary_signals=int(signal.sum()),primary_event=int((signal&event).sum()),
                      causal_eligible=int(eligible.sum()),metric_rows=int(metric.sum()),primary_accepted=int(eligible.sum()),
                      primary_reasons=dict(Counter(archive['primary_reason'].tolist())),
                      causal_reasons=dict(Counter(archive['causal_reason'].tolist())),
                      all_outcomes=dict(Counter(op['outcomes'][rows].tolist())),
                      eligible_outcomes=dict(Counter(op['outcomes'][rows[eligible]].tolist()))),
        primary_metrics=decision_metrics(y,np.ones(len(y),np.int8))),selected


def estimate_output(bundle,protocol):
    # Conservative: all phase contracts counted even when cache may later reuse them.
    trace=0; draws=0; training_metadata=0
    for fold in protocol['folds']:
        parts=bundle['partitions'][fold['name']]
        for rows in (parts['train'],parts['refit']):
            counts=[len(rows),*[int(mask[rows].sum()) for mask in bundle['masks'].values()]]
            trace+=sum(K*n*8*MEMBERS*len(MASTERS) for n in counts)
            # Both canonical identity/source arrays plus up to eight K-length
            # draw/diagnostic arrays; all schemes and aliases counted conservatively.
            draws+=sum((n*16+K*64+65536)*MEMBERS*len(MASTERS)*len(SCHEMES) for n in counts)
            # Phase mapping arrays and full-population uniqueness/multiplicities.
            training_metadata+=sum(n*64+65536 for n in counts)
    # 7 predictors: p, p availability, acceptance availability/int8, reason U48;
    # 12 member probability vectors plus identities/masks/outcomes and container overhead.
    opportunities=len(bundle['opportunities']['starts'])*3*2*3*(7*(8+1+1+1+192)+12*8+512)
    return int(trace+draws+training_metadata+156*64*1024**2+opportunities+16*1024**2)


def run_models(bundle,protocol,spec,clock,ledger,hashes,output,store,replay=None,prefix=None):
    reports=[]; fit_cache={}; sampling_cache={}; replay_samples={}
    data,op=bundle['data'],bundle['opportunities']
    for fi,fold in enumerate(protocol['folds']):
        parts=bundle['partitions'][fold['name']]
        variants={'temporal':parts,**{h:restrict(parts,m) for h,m in bundle['masks'].items()}}
        report=dict(fold=fold['name'],phases={}); selections={}
        for phase,train,evalpart in PHASES:
            begin=utc_epoch(fold['validation_start'] if phase=='inner' else fold['test_start']); end=utc_epoch(fold['test_start'] if phase=='inner' else fold['test_end'])
            openings=np.flatnonzero((op['starts']>=begin)&(op['starts']<end)); report['phases'][phase]={}
            for pop,selected in variants.items():
                saved=None if replay is None else replay[fi]['phases'][phase][pop]
                ordered,starts,ends,order,inverse,contract=sampling_contract(bundle,selected[train],clock,pop)
                event=np.ones(len(openings),bool) if pop=='temporal' else op[f'cusum_{pop}'][openings]
                eligible=(op['side'][openings]!=0)&op['causal_valid'][openings]&event
                X=op['X'][openings[eligible]]
                if not np.isfinite(X).all(): raise ValueError('Nonfinite causal opportunity X')
                fits={}; traces={}; predictions={}; members={}; diversities={}
                fullsampler=dict(kind='full_unit_weight',population=pop,training=contract)
                fid=f"{fold['name']}:{phase}:{pop}:full"
                if saved is None:
                    state,fits['full']=fit_unit(data,ordered,spec['logistic'],ledger,fid,fold['name'],hashes,fullsampler,fit_cache,output,store)
                else:
                    fits['full']=saved['fits']['full']; state=replay_unit(data,ordered,spec['logistic'],ledger,hashes,fullsampler,fits['full'],output,prefix)
                predictions['full']=None if state is None else predict_state(state,X)
                for master in MASTERS:
                    for scheme in SCHEMES:
                        name=f'{scheme}_{master}'; states=[]; fits[name]=[]; traces[name]=[]
                        for member in range(MEMBERS):
                            fid=f"{fold['name']}:{phase}:{pop}:{name}:{member}"
                            if len(ordered):
                                cachekey=(contract_hash(contract),master,member,scheme)
                                if saved is None:
                                    if cachekey not in sampling_cache:
                                        sampling_cache[cachekey]=sampling_trace(starts,ends,contract,pop,master,member,scheme,output,store,identities=data.entry_indices[ordered],source_rows=ordered)
                                    draws,trace=sampling_cache[cachekey]
                                else:
                                    trace=saved['traces'][name][member]
                                    if cachekey not in replay_samples:
                                        replay_samples[cachekey]=sampling_trace(starts,ends,contract,pop,master,member,scheme,output,store,replay=trace,identities=data.entry_indices[ordered],source_rows=ordered)
                                    draws,checked=replay_samples[cachekey]
                                    if checked!=trace: raise ValueError('Sampling alias changed')
                                sampler=dict(kind='bootstrap',trace=trace['contract'],trace_sha256=trace['contract_sha256'],draws_sha256=trace['draws_sha256'],
                                             canonical_ids=array_hash(data.entry_indices[ordered]),draw_original_ids=array_hash(data.entry_indices[ordered[draws]]))
                                drawrows=ordered[draws]
                            else:
                                trace=dict(status='empty_training',contract=contract); drawrows=ordered
                                sampler=dict(kind='empty_bootstrap',master=master,member=member,scheme=scheme,training=contract)
                            if saved is None:
                                state,fit=fit_unit(data,drawrows,spec['logistic'],ledger,fid,fold['name'],hashes,sampler,fit_cache,output,store)
                            else:
                                fit=saved['fits'][name][member]; state=replay_unit(data,drawrows,spec['logistic'],ledger,hashes,sampler,fit,output,prefix)
                            states.append(state); fits[name].append(fit); traces[name].append(trace)
                        predictions[name],members[name]=ensemble_predictions(states,X)
                        diversities[name]=diversity(members[name])
                source_entry=bundle['source_report']['folds'][fi]['phases'][phase][pop]
                for family in ('constant','logistic'):
                    source_fit=source_entry['fits'][family]
                    state=(bundle['reference_states'][(fi,phase,pop,family)] if 'reference_states' in bundle else
                           replay_source_fit(data,selected[train],family,source_fit,bundle['source_spec'],clock,ledger,
                                             bundle['source_report']['hashes'],bundle['source_models'],bundle['source_prefix']))
                    predictions[f'weighted_{family}']=None if state is None else predict_state(state,X)
                archive,evaluation,chosen=evaluate(op,openings,bundle['opening_rows'][selected[evalpart]],pop,predictions,
                                                 None if phase=='inner' else selections[pop])
                if phase=='inner': selections[pop]=chosen
                for family in ('constant','logistic'):
                    if chosen[f'weighted_{family}']!=source_entry['evaluation']['selections'][family]:
                        raise ValueError('Frozen reference threshold changed')
                for name,values in members.items():
                    for index,value in enumerate(values):
                        memberp=np.full(len(openings),np.nan)
                        if value is not None: memberp[eligible]=value
                        archive[f'{name}_member_{index}']=memberp
                archive.update(selected_source_rows=selected[train],canonical_to_selected=order,selected_to_canonical=inverse,
                               canonical_source_rows=ordered,canonical_original_ids=data.entry_indices[ordered])
                full_index=IntervalIndex(starts,ends) if len(starts) else None
                full_diag=None
                if full_index is not None:
                    delta=np.zeros(len(full_index.d)+1,dtype=np.int64)
                    np.add.at(delta,full_index.L,1); np.add.at(delta,full_index.R,-1)
                    full_index.c=np.cumsum(delta[:-1]); full_index.draw_count=len(starts)
                    full_diag=full_index.diagnostics(np.arange(len(starts)))
                    archive['full_training_raw_uniqueness']=np.asarray(full_diag.pop('raw_uniqueness'))
                    archive['full_training_distinct_event_indices']=np.asarray(full_diag.pop('distinct_event_indices'),dtype=np.int64)
                    archive['full_training_multiplicities']=np.asarray(full_diag.pop('multiplicities'),dtype=np.int64)
                path=output/f"{fold['name']}_{phase}_{pop}.npz"
                item=dict(fits=fits,traces=traces,evaluation=evaluation,diversity=diversities,
                          full_training_uniqueness=full_diag,ensemble_members=3,ensemble_divisor=3)
                if saved is None:
                    artifact=store.arrays(path,archive); item.update(predictions_file=path.name,predictions_sha256=artifact['sha256'])
                    store.json(path.with_suffix('.json'),item)
                else:
                    check_hash(path,saved['predictions_sha256'])
                    with np.load(path,allow_pickle=False) as checked:
                        if set(checked.files)!=set(archive): raise ValueError('Prediction schema changed')
                        for name,value in archive.items(): np.testing.assert_array_equal(checked[name],value)
                    item.update(predictions_file=path.name,predictions_sha256=saved['predictions_sha256'])
                    if saved!=item or read_json(path.with_suffix('.json'))!=item: raise ValueError('Bagging phase report changed')
                report['phases'][phase][pop]=item
        reports.append(report)
    return reports


def conclusion(reports,thresholds):
    result={}
    for pop in ('temporal',*map(str,thresholds)):
        result[pop]={}
        for master in MASTERS:
            name=f'sequential_{master}'; control=f'uniform_{master}'
            scores=[r['phases']['refit'][pop]['evaluation']['models'] for r in reports]
            if len(scores)!=3 or any(s[n]['scores'] is None or s[n]['scores']['log_loss'] is None for s in scores for n in (name,control)):
                status='technically_unavailable_or_empty_comparison'; delta=None
            else:
                delta=float(np.mean([s[name]['scores']['brier']-s[control]['scores']['brier'] for s in scores]))
                good=all(s[name]['scores']['log_loss']<s[control]['scores']['log_loss'] for s in scores)
                status='consistent_descriptive_gain' if good and delta<=0 else 'mixed_or_unfavorable'
            result[pop][str(master)]=dict(status=status,mean_brier_delta=delta)
    return dict(per_seed=result,both_seeds_required=True,seed_selection=False,profit_claim=False,
                inference='inconclusive_under_dependence_and_informed_design')


def execute(bundle,protocol,spec,clock,hashes,output):
    output=Path(output); estimate=estimate_output(bundle,protocol); store=ArtifactStore(output,estimate); store.check()
    ledger=BoundStageLedger(spec['global_ledger'],8,spec['expected_prior_fits'],spec['ledger_before_sha256'])
    before=ledger.path.read_bytes()
    if hashlib.sha256(before).hexdigest()!=spec['ledger_before_sha256']: raise ValueError('Frozen ledger changed')
    validate_references(bundle,protocol,clock,ledger)
    output.mkdir(parents=True,exist_ok=False)
    try:
        store.bytes(output/'ledger-before.jsonl',before)
        store.json(output/'run.json',dict(spec=spec,hashes=hashes,storage=dict(estimate=estimate,safety=store.safety,physical_reservation=False)))
        ledger.start_run(EXPERIMENT,spec['max_model_fits'],hashes,independent_failures=True)
        reports=run_models(bundle,protocol,spec,clock,ledger,hashes,output,store)
        report=dict(experiment=EXPERIMENT,status='completed',hashes=hashes,versions=versions(),folds=reports,
                    conclusion=conclusion(reports,spec['thresholds']),fits_before=spec['expected_prior_fits'],fits_after=ledger.consumed(),
                    new_fits=ledger.consumed()-spec['expected_prior_fits'],confirmation_opened=False)
        store.json(output/'report.json',report)
        if not ledger.path.read_bytes().startswith(before): raise ValueError('Ledger prefix changed')
        ledger.finish_run(EXPERIMENT,'completed',dict(report_sha256=digest(output/'report.json'),new_fits=report['new_fits']))
        after=ledger.path.read_bytes(); ledger.records()
        store.bytes(output/'ledger-after.jsonl',after)
        return report
    except BaseException as error:
        abort(ledger,output,error,store); raise


def verify(output,source,source_models,spec,protocol):
    output=Path(output); ledger=StageLedger(spec['global_ledger'],8); raw=ledger.path.read_bytes(); records=ledger.records()
    report,run=read_json(output/'report.json'),read_json(output/'run.json'); hashes=run['hashes']
    if run['spec']!=spec or report['hashes']!=hashes or report['versions']!=versions(): raise ValueError('Bagging contract changed')
    check_hash(SPEC,hashes['config']); check_hash(PROTOCOL,hashes['protocol']); verify_sources(hashes['sources'])
    before=(output/'ledger-before.jsonl').read_bytes(); after=(output/'ledger-after.jsonl').read_bytes()
    if not raw.startswith(after) or not after.startswith(before) or hashlib.sha256(before).hexdigest()!=spec['ledger_before_sha256']:
        raise ValueError('Bagging ledger snapshot changed')
    ends=[r for r in records if r['kind']=='run_finished' and r.get('experiment')==EXPERIMENT]
    fits=[r for r in records if r['kind']=='fit_started' and r.get('experiment')==EXPERIMENT]
    starts=[r for r in records if r['kind']=='run_started' and r.get('experiment')==EXPERIMENT]
    if (len(ends)!=1 or ends[0]['status']!='completed' or ends[0]['result']!=dict(report_sha256=digest(output/'report.json'),new_fits=len(fits))
            or len(starts)!=1 or starts[0]['hashes']!=hashes or starts[0]['max_fits']!=spec['max_model_fits']
            or json.loads(after.splitlines()[-1])!=ends[0] or len(fits)>spec['max_model_fits']
            or report['new_fits']!=len(fits) or report['fits_after']!=spec['expected_prior_fits']+len(fits)
            or report['fits_before']!=spec['expected_prior_fits'] or ends[0]['consumed_total']!=report['fits_after']
            or report['experiment']!=EXPERIMENT or report['status']!='completed' or report['confirmation_opened'] is not False):
        raise ValueError('No authoritative bagging completion')
    bundle,clock=load_source(source,source_models,spec,protocol,ledger)
    replay=run_models(bundle,protocol,spec,clock,ledger,hashes,output,None,replay=report['folds'],prefix=before)
    if replay!=report['folds'] or conclusion(replay,spec['thresholds'])!=report['conclusion']: raise ValueError('Bagging conclusion changed')
    if ledger.path.read_bytes()!=raw: raise ValueError('Replay changed ledger')
    return dict(status='verified',model_fits=0,ledger_unchanged=True,report_sha256=digest(output/'report.json'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=SOURCE); parser.add_argument('--source-models',type=Path,default=SOURCE_MODELS)
    parser.add_argument('--output',type=Path,default=ROOT/'output'/EXPERIMENT); parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
        if os.environ.get(name)!='1': raise ValueError(f'Set {name}=1 before Python startup')
    spec,protocol=load_contract()
    if args.verify: result=verify(args.output,args.source,args.source_models,spec,protocol)
    else:
        if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(): parser.error('Commit protocol/code before scientific draws or fits')
        ledger=StageLedger(spec['global_ledger'],8); bundle,clock=load_source(args.source,args.source_models,spec,protocol,ledger)
        hashes=dict(config=digest(SPEC),protocol=digest(PROTOCOL),sources=sources(),
                    source_manifest=spec['source']['source_dataset_manifest_sha256'],code_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
        result=execute(bundle,protocol,spec,clock,hashes,args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='folds'}),flush=True)


if __name__=='__main__': main()
