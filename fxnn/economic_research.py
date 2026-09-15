"""Preregistered orchestration and attestations for the fixed stage9 experiment."""
import hashlib
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .economic_clock import SessionClockMs, utc_ms
from .economic_confirmation import PROFILE
from .economic_portfolio_adapter import portfolio_segment
from .economic_prediction_replay import verify_final_probabilities, verify_operational_predictions
from .economic_dataset import build_dataset, build_labels
from .economic_index import TickIndex
from .economic_lifecycle import Lifecycle, fingerprint, verify_manifest, atomic_json
from .tick_economic_source import verified_month, digest


LEDGER = '/Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl'
EXPERIMENT = 'economic_ticks_v1'
RELEASE_SCOPE = 'Full preconfirmation release review for the one-time frozen 2024 opening'
RELEASE_CRITERIA = frozenset({'RELEASE-SCOPE','RELEASE-IMPLEMENTATION','RELEASE-DEVELOPMENT',
    'RELEASE-FINAL-MODELS','RELEASE-REPLAY','RELEASE-CI','RELEASE-UNOPENED','RELEASE-RESOURCES'})


def load_config(path):
    from .economic_fit import phase_plan
    config=json.loads(Path(path).read_text())
    fixed={'experiment':EXPERIMENT,'kind':'offline_economic_confirmation',
           'global_ledger':LEDGER,'global_fit_limit':1000,'max_total_fits':14,
           'max_development_fits':12,'max_final_fits':2,'population':'temporal',
           'threshold':.5,'initial_capital_usd':10000,'position_eur':1000,
           'max_positions':1,'margin_notional_fraction':1.0,
           'pending_entry_seconds':30,'quote_gap_open_seconds':60,
           'horizon_open_minutes':4320,'timeout_fill_open_seconds':60,
           'history_buffer_observed_bars':1941,'tp_volatility_multiple':2.5,
           'sl_volatility_multiple':1.0,'development_utc':['2022-01-01','2024-01-01'],
           'confirmation_utc':['2024-01-01','2025-01-01'],
           'post_open_retuning':False,'confirmation_acquisition':PROFILE}
    for key,value in fixed.items():
        if config.get(key)!=value:
            raise ValueError('Unregistered economic configuration: '+key)
    months=[str(y)+f'{m:02d}' for y in (2022,2023) for m in range(1,13)]
    if [m['month'] for m in config['source_months']]!=months:
        raise ValueError('All24 development source months in source order required')
    if any(re.fullmatch('[0-9a-f]{64}',m['completed_sha256']) is None for m in config['source_months']):
        raise ValueError('Frozen development source fingerprints required')
    if config['index']['block_size']!=1024 or config['index']['cache_bytes']!=256*1024**2:
        raise ValueError('Unregistered index resources')
    if config['volatility']!=dict(lag_open_minutes=1440,window_observed=500,span=100,minimum=100):
        raise ValueError('Unregistered volatility estimator')
    if config['feature_windows']!=[5,15,60,240]:
        raise ValueError('Unregistered feature windows')
    if config.get('model_phases')!=phase_plan(config['folds']):
        raise ValueError('Phase calendar differs from registered folds')
    return config


def git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()


def science_paths(repo):
    repo=Path(repo).resolve()
    paths=list((repo/'fxnn').glob('*.py'))
    paths += [repo/p for p in ('scripts/download_histdata_ticks.py','scripts/run_economic_ticks.py',
              'configs/economic_ticks_v1.json','docs/experiments/economic-ticks-v1-protocol.md',
              'docs/experiments/economic-ticks-v1-computation.md',
              'docs/experiments/economic-ticks-v1-bindings.json')]
    return sorted(paths)


def verify_preregistration(repo, preregistered_sha):
    repo=Path(repo).resolve()
    if re.fullmatch('[0-9a-f]{40}',preregistered_sha) is None:
        raise ValueError('Full preregistration commit required')
    if git(repo,'rev-parse',preregistered_sha+'^{commit}')!=preregistered_sha:
        raise ValueError('Preregistration is not a commit')
    current={str(path.relative_to(repo)) for path in science_paths(repo)}
    registered={name for name in git(repo,'ls-tree','-r','--name-only',preregistered_sha).splitlines()
                if (name.startswith('fxnn/') and name.count('/')==1 and name.endswith('.py'))
                or name in current}
    if registered!=current:
        raise ValueError('Scientific file inventory differs from preregistration')
    for relative in sorted(registered):
        path=repo/relative
        committed=subprocess.check_output(['git','-C',str(repo),'show',preregistered_sha+':'+relative])
        if hashlib.sha256(committed).hexdigest()!=digest(path):
            raise ValueError('Scientific content differs from preregistration: '+relative)
    return {str(path.relative_to(repo)):fingerprint(path) for path in science_paths(repo)}


def runtime_bindings(config, tzfile, curl_binary):
    import numpy
    import sklearn
    actual=dict(python=platform.python_version(),numpy=numpy.__version__,sklearn=sklearn.__version__)
    if actual!=config['versions']:
        raise ValueError('Scientific runtime differs from frozen versions')
    from zoneinfo import TZPATH
    frozen=json.loads((Path(__file__).resolve().parents[1]/'docs/experiments/economic-ticks-v1-bindings.json').read_text())['runtime']
    selected=next((Path(base)/'America/New_York' for base in TZPATH if (Path(base)/'America/New_York').is_file()),None)
    if selected is None or selected.resolve()!=Path(tzfile).resolve():
        raise ValueError('Timezone binding is not the calendar runtime source')
    result=dict(python_binary=fingerprint(Path(sys.executable).resolve()),
                timezone=fingerprint(tzfile),curl_binary=fingerprint(curl_binary))
    for actual_key,frozen_key in [('python_binary','python_executable'),('timezone','new_york_tzfile')]:
        if any(result[actual_key][key]!=frozen[frozen_key][key] for key in ('sha256','bytes')):
            raise ValueError('Runtime binary/timezone content differs from preregistration')
    if Path(curl_binary).resolve()!=Path('/usr/bin/curl').resolve():
        raise ValueError('Only the bound transport binary is used')
    return result


def resource_preflight(output, config):
    output=Path(output)
    parent=output if output.exists() else output.parent
    while not parent.exists():
        parent=parent.parent
    # Index plus JSONL, model/prediction and source margins, before allocation.
    required=config['index']['min_free_bytes']+config['index']['estimated_bytes']+4*1024**3
    if shutil.disk_usage(parent).free < required:
        raise OSError('Insufficient disk for full economic stage plus frozen free margin')
    return dict(required_free_bytes=required,available_free_bytes=shutil.disk_usage(parent).free)


def development_source(config, progress=None):
    window=tuple(utc_ms(value+'T00:00:00+00:00') for value in config['development_utc'])
    root=Path(config['source_root'])
    for record in config['source_months']:
        if progress is not None:progress({'phase':'development_source','month':record['month']})
        yield from verified_month(root/record['month'],record['completed_sha256'],window)


def _make_development_data(repo, config, output, preregistered_sha, progress=None):
    files=verify_preregistration(repo,preregistered_sha)
    output=Path(output)
    resource_preflight(output,config)
    output.mkdir(parents=True,exist_ok=False)
    first,stop=(utc_ms(v+'T00:00:00+00:00') for v in config['development_utc'])
    clock=SessionClockMs.weekly(*(utc_ms(v+'T00:00:00+00:00') for v in config['calendar_utc']))
    contract=dict(experiment=EXPERIMENT,preregistered_sha=preregistered_sha,
                  scientific_files=files,config=config)
    dataset=build_dataset(development_source(config,progress),clock,first,stop,output/'dataset',
                          contract,min_free=config['index']['min_free_bytes'],
                          estimated_index_bytes=config['index']['estimated_bytes'])
    labels=build_labels(output/'dataset',digest(output/'dataset/manifest.json'),output/'labels')
    evidence=dict(preregistered_sha=preregistered_sha,config_sha256=digest(Path(repo)/'configs/economic_ticks_v1.json'),
                  dataset=fingerprint(output/'dataset/manifest.json'),labels=fingerprint(output/'labels/manifest.json'),
                  counts=dataset['counts'],label_counts=labels['counts'],confirmation_access=False,
                  scientific_fits=0)
    atomic_json(output/'source-evidence.json',evidence)
    return evidence


def reserve_models(repo, config, preregistered_sha, *, tzfile, curl_binary, slots):
    files=verify_preregistration(repo,preregistered_sha)
    files.update(runtime_bindings(config,tzfile,curl_binary))
    supervisor=Lifecycle(config['global_ledger'])
    supervisor.reserve(config['expected_prior_fits'],config['ledger_before_sha256'],files,config,slots,
                       independent_failures=config['independent_numerical_failures'])
    return supervisor


def load_window_data(output, evidence):
    """Authenticate manifests before handing flat arrays and hazards to fitting."""
    from .economic_fit import load_matrix
    output=Path(output)
    verify_manifest({'dataset':evidence['dataset'],'labels':evidence['labels']})
    if Path(evidence['dataset']['path']).resolve()!=(output/'dataset/manifest.json').resolve():
        raise ValueError('Dataset evidence path mismatch')
    if Path(evidence['labels']['path']).resolve()!=(output/'labels/manifest.json').resolve():
        raise ValueError('Label evidence path mismatch')
    dataset=json.loads((output/'dataset/manifest.json').read_text())
    labels=json.loads((output/'labels/manifest.json').read_text())
    if labels['dataset_manifest_sha256']!=evidence['dataset']['sha256']:
        raise ValueError('Labels do not bind this dataset')
    paths={'opportunities':output/'dataset/opportunities.jsonl',
           'bars':output/'dataset/bars.jsonl','labels':output/'labels/labels.jsonl'}
    expected={'opportunities':dataset['files']['opportunities.jsonl']['sha256'],
              'bars':dataset['files']['bars.jsonl']['sha256'],'labels':labels['labels_sha256']}
    artifacts={key:fingerprint(path) for key,path in paths.items()}
    if any(value['sha256']!=expected[key] for key,value in artifacts.items()):
        raise ValueError('Window input hash differs from manifest')
    with TickIndex(output/'dataset/index',dataset['index_contract_sha256'],
                   expected_manifest_sha256=dataset['files']['index/manifest.json']['sha256']) as index:
        hazards=tuple(index.hazards)
        provenance=dict(dataset_manifest=evidence['dataset']['sha256'],
                        labels_manifest=evidence['labels']['sha256'],
                        index_manifest=dataset['files']['index/manifest.json']['sha256'],
                        hazard_sha256=index.manifest['files']['hazards.json']['sha256'])
    matrix=load_matrix(paths['opportunities'],paths['labels'],paths['bars'],artifacts,hazards,provenance)
    if len(matrix)!=dataset['expected_opportunities']:
        raise ValueError('Matrix does not cover all scheduled opportunities')
    return matrix


def model_segment(config, supervisor, data, clock, output, *, final=False):
    from .economic_fit import phase_plan, run_phases, verify_phases
    snapshot=supervisor.read()
    if snapshot['config']!=config:
        raise ValueError('Model invocation differs from reserved scientific config')
    phases=phase_plan(config['folds'])
    output=Path(output)
    name='FINAL_MODELS_VERIFIED' if final else 'DEVELOPMENT_VERIFIED'
    existing=[c for c in snapshot['checkpoints'] if c.get('phase')==name]
    if existing and (len(existing)!=1 or Path(existing[0]['artifacts']['report']['path']).resolve()!=(output/'report.json').resolve()):
        raise ValueError('Model output differs from authoritative checkpoint')
    if existing or output.exists():
        artifact=fingerprint(output/'report.json')
        # A completed segment must already have a canonical clean checkpoint.
        name='FINAL_MODELS_VERIFIED' if final else 'DEVELOPMENT_VERIFIED'
        checkpoints=[c for c in snapshot['checkpoints'] if c.get('phase')==name]
        if len(checkpoints)!=1 or checkpoints[0]['artifacts'].get('report')!=artifact:
            raise ValueError('Existing model segment lacks authoritative checkpoint')
        verify_phases(data,clock,phases,config['logistic'],config['versions'],supervisor,artifact)
        return json.loads((output/'report.json').read_text())
    report,_=run_phases(data,clock,phases,config['logistic'],config['versions'],supervisor,output,final=final)
    return report


def operational_predictions(config, supervisor, matrix, clock, model_report_artifact, output):
    """Authenticate outer reports before producing a complete operational stream."""
    import os
    import numpy as np
    from .economic_fit import phase_plan, verify_phases
    from .economic_dataset import line
    from .economic_prediction_replay import operational_rows, verify_operational_predictions
    snapshot=supervisor.read()
    if snapshot['config']!=config:
        raise ValueError('Operational projection differs from registered config')
    checkpoints=[c for c in snapshot['checkpoints'] if c.get('phase')=='DEVELOPMENT_VERIFIED']
    if len(checkpoints)!=1 or checkpoints[0]['artifacts'].get('report')!=model_report_artifact:
        raise ValueError('Development model report lacks authoritative checkpoint')
    model_report=verify_phases(matrix,clock,phase_plan(config['folds']),config['logistic'],
                              config['versions'],supervisor,model_report_artifact)
    output=Path(output)
    with output.open('x',encoding='utf8',newline='\n') as stream:
        previous=None
        for phase in model_report['phases']:
            if not phase['phase']['name'].endswith(':refit'):
                continue
            family=phase['families']['logistic']
            with np.load(family['predictions']['path'],allow_pickle=False) as arrays:
                for row in operational_rows(arrays,family['fit']['status']=='succeeded'):
                    if previous is not None and row['decision_ms']<=previous:
                        raise ValueError('Outer operational stream overlaps or regresses')
                    previous=row['decision_ms']
                    line(stream,row)
        stream.flush();os.fsync(stream.fileno())
    artifact=fingerprint(output)
    verify_operational_predictions(config,supervisor,matrix,clock,model_report_artifact,artifact)
    return artifact


def _make_confirmation_data(config, supervisor, development_evidence, output, progress=None):
    """All numeric confirmation access routes through the already frozen guard."""
    from .economic_confirmation import ConfirmationAcquisition, verified_confirmation_month, MONTHS
    from .economic_opportunities import OpportunityBuilder
    supervisor.recover()
    snapshot=supervisor.read()
    if not snapshot['sealed'] or snapshot['config']!=config:
        raise ValueError('Confirmation requires the complete unchanged frozen package')
    verify_manifest({'development_dataset':development_evidence['dataset']})
    package=json.loads(Path(snapshot['P']['path']).read_text())
    if any(model['contract']['scientific_provenance']['dataset_manifest']!=development_evidence['dataset']['sha256']
           for model in package['models']):
        raise ValueError('Warmup dataset is not the frozen final models source')
    development=Path(development_evidence['dataset']['path']).parent
    d=json.loads((development/'manifest.json').read_text())
    if digest(development/'warmup.json')!=d['files']['warmup.json']['sha256']:
        raise ValueError('Authorized development warmup changed')
    warmup=json.loads((development/'warmup.json').read_text())
    resource_preflight(output,config)
    acquisition=ConfirmationAcquisition(supervisor)
    acquired=acquisition.acquire_all()  # Guard is durable before any acquisition I/O.
    source_manifest=fingerprint(acquisition.root/'manifest.json')
    first,stop=(utc_ms(v+'T00:00:00+00:00') for v in config['confirmation_utc'])
    clock=SessionClockMs.weekly(*(utc_ms(v+'T00:00:00+00:00') for v in config['calendar_utc']))
    OpportunityBuilder.from_history(clock,warmup,first)
    def rows():
        if acquired['held_december']['status']=='completed':
            path=acquisition.root/'202312'
            yield from verified_confirmation_month(path,digest(path/'completed.json'),lifecycle=supervisor)
        for month in MONTHS:
            if progress is not None:progress({'phase':'confirmation_source','month':month})
            yield from verified_confirmation_month(acquisition.root/month,
                        acquired['completed_hashes'][month]['sha256'],lifecycle=supervisor)
    output=Path(output)
    resource_preflight(output,config)
    output.mkdir(parents=True,exist_ok=False)
    contract=dict(experiment=EXPERIMENT,phase='confirmation',S=snapshot['S'],
                  freeze_sha256=snapshot['P']['sha256'],source_manifest_sha256=source_manifest['sha256'],
                  development_warmup_sha256=d['files']['warmup.json']['sha256'])
    dataset=build_dataset(rows(),clock,first,stop,output/'dataset',contract,
                          min_free=config['index']['min_free_bytes'],warmup=warmup,
                          estimated_index_bytes=config['index']['estimated_bytes'])
    labels=build_labels(output/'dataset',digest(output/'dataset/manifest.json'),output/'labels')
    evidence=dict(dataset=fingerprint(output/'dataset/manifest.json'),
                  labels=fingerprint(output/'labels/manifest.json'),source_manifest=source_manifest,
                  counts=dataset['counts'],label_counts=labels['counts'],S=snapshot['S'],
                  freeze_sha256=snapshot['P']['sha256'],confirmation_access=True,scientific_fits=0)
    atomic_json(output/'source-evidence.json',evidence)
    return evidence


def _final_probabilities(config, supervisor, matrix, final_model_report_artifact, output,
                        confirmation_evidence_artifact):
    """Generate only under OPENED; terminal verification uses the readonly helper."""
    import os
    from .economic_fit import phase_predictions, durable_arrays, durable_json, new_directory
    from .economic_dataset import line
    from .economic_prediction_replay import (authenticate_frozen_models, authenticate_confirmation_matrix,
        operational_rows, verify_final_probabilities)
    snapshot,models=authenticate_frozen_models(config,supervisor,final_model_report_artifact)
    authenticate_confirmation_matrix(supervisor,snapshot,matrix,confirmation_evidence_artifact)
    output=Path(output);new_directory(output)
    phase=dict(name='confirmation',evaluation_start_ms=utc_ms('2024-01-01T00:00:00+00:00'),
               evaluation_end_ms=utc_ms('2025-01-01T00:00:00+00:00'))
    family_reports={}
    for family in ('constant','logistic'):
        state,fitted=models[family]
        arrays,metrics=phase_predictions(matrix,state,phase)
        artifact=durable_arrays(output/(family+'.npz'),arrays)
        family_reports[family]=dict(fit=fitted,predictions=artifact,metrics=metrics)
        if family=='logistic':
            with (output/'operational.jsonl').open('x',encoding='utf8',newline='\n') as stream:
                for row in operational_rows(arrays,True):line(stream,row)
                stream.flush();os.fsync(stream.fileno())
    report=dict(phase=phase,families=family_reports,scientific_fits=0,
                S=snapshot['S'],freeze_sha256=snapshot['P']['sha256'],
                confirmation_evidence_sha256=confirmation_evidence_artifact['sha256'],
                operational=fingerprint(output/'operational.jsonl'))
    report_artifact=durable_json(output/'report.json',report)
    verify_final_probabilities(config,supervisor,matrix,final_model_report_artifact,
                              report_artifact,confirmation_evidence_artifact)
    return report


def final_probabilities(config, supervisor, matrix, final_model_report_artifact, output,
                        confirmation_evidence_artifact):
    """One contract-bound prediction construction; interrupted work is preserved."""
    from .economic_lifecycle import identity
    from .economic_prediction_replay import authenticate_frozen_models, authenticate_confirmation_matrix
    from .economic_prediction_recovery import prediction_construction
    snapshot,models=authenticate_frozen_models(config,supervisor,final_model_report_artifact)
    authenticate_confirmation_matrix(supervisor,snapshot,matrix,confirmation_evidence_artifact)
    contract=dict(S=snapshot['S'],freeze_sha256=snapshot['P']['sha256'],
                  models={family:{'F':fitted['F'],'contract_sha256':identity(fitted['contract'])}
                          for family,(_,fitted) in models.items()},
                  final_report=final_model_report_artifact,
                  confirmation_evidence=confirmation_evidence_artifact,config_sha256=identity(config))
    def construct(path):
        return _final_probabilities(config,supervisor,matrix,final_model_report_artifact,path,
                                    confirmation_evidence_artifact)
    def verify(artifact):
        return verify_final_probabilities(config,supervisor,matrix,final_model_report_artifact,
                                          artifact,confirmation_evidence_artifact)
    return prediction_construction(supervisor,contract,output,construct,verify)


def verified_ci_receipt(receipt, release_sha):
    """Validate a captured GitHub job receipt, never infer missing jobs as passes."""
    if receipt.get('head_sha',receipt.get('headSha'))!=release_sha or receipt.get('conclusion')!='success':
        raise ValueError('Required CI did not succeed on release SHA')
    jobs=receipt.get('jobs',[])
    if not jobs:
        raise ValueError('CI has no executed jobs')
    required={'tests'}
    if not required or not required <= {job.get('name') for job in jobs}:
        raise ValueError('Required CI contexts missing')
    for job in jobs:
        if job['name'] not in required:continue
        if job.get('conclusion')!='success':
            raise ValueError('Required CI job failed')
        steps=job.get('steps',[])
        expected={'Run python -m unittest discover -s tests -v',
                  'Run python -m compileall -q fxnn scripts','Run git diff --check'}
        meaningful=[s for s in steps if s.get('name') in expected]
        if {s['name'] for s in meaningful}!=expected or any(s.get('conclusion')!='success' or not s.get('started_at',s.get('startedAt')) or
                                 not s.get('completed_at',s.get('completedAt')) for s in meaningful):
            raise ValueError('Required job lacks meaningful executed steps')
    return True


def verified_review_receipt(receipt, release_sha):
    """A gateway result is evidence for its stated review scope only."""
    if (receipt.get('schema_version')!=1 or receipt.get('verdict')!='APPROVED'
            or receipt.get('reviewed_head_sha')!=release_sha or receipt.get('inconclusive_reason')):
        raise ValueError('Conclusive independent exact-SHA review required')
    if any(f.get('severity') in ('P0','P1','P2') for f in receipt.get('findings',[])):
        raise ValueError('Independent review retains blocking findings')
    criteria=receipt.get('acceptance_criteria',[])
    by_id={item.get('id'):item for item in criteria}
    if len(by_id)!=len(criteria) or not RELEASE_CRITERIA <= set(by_id):
        raise ValueError('Full release review acceptance scope missing; prospective approval is insufficient')
    if (by_id['RELEASE-SCOPE'].get('criterion')!=RELEASE_SCOPE or
            any(by_id[key].get('status')!='COVERED' or by_id[key].get('explicit') is not True
                or by_id[key].get('severity')!='NONE' or not by_id[key].get('evidence')
                for key in RELEASE_CRITERIA)):
        raise ValueError('Required full release acceptance coverage incomplete')
    return True


def clock_for(config):
    return SessionClockMs.weekly(*(utc_ms(v+'T00:00:00+00:00') for v in config['calendar_utc']))


def release_freeze(repo, config, supervisor, preregistered_sha, receipts, artifacts):
    """Freeze only after verified implementation/development release evidence.

    Receipts are captured by the operator from GitHub/gateway and local checks;
    their original bytes are bound into P. Economic outcomes are never T gates.
    """
    from .economic_fit import phase_plan, verify_phases
    verify_preregistration(repo,preregistered_sha)
    sha=git(repo,'rev-parse','HEAD')
    if git(repo,'status','--porcelain','--untracked-files=all'):
        raise ValueError('Release worktree must be clean')
    verify_manifest(receipts);verify_manifest(artifacts)
    required_artifacts={'development_source','development_models','final_models',
                        'development_portfolios','development_report'}
    if set(artifacts)!=required_artifacts:
        raise ValueError('Complete development source/model/portfolio/report artifacts required')
    required={'ci','review','dependencies','validation'}
    if set(receipts)!=required:
        raise ValueError('All original release receipts required')
    values={key:json.loads(Path(fp['path']).read_text()) for key,fp in receipts.items()}
    verified_ci_receipt(values['ci'],sha)
    verified_review_receipt(values['review'],sha)
    dependencies=values['dependencies']
    if (dependencies.get('repository')!='lhermoso/FXNN' or
            {i.get('number') for i in dependencies.get('issues',[])}!={6,7,8,19} or
            any(i.get('state')!='CLOSED' or not i.get('closedAt') for i in dependencies['issues'])):
        raise ValueError('T1 requires all four actual closed dependencies')
    validation=values['validation']
    if (validation.get('head_sha')!=sha or validation.get('preregistered_sha')!=preregistered_sha or
            any(validation.get(key) is not True for key in
                ('synthetic_tests_passed','compile_passed','diff_check_passed',
                 'portfolio_replay_passed','model_replay_passed','resource_benchmark_passed'))):
        raise ValueError('T4 exact-release validation receipts missing')
    snapshot=supervisor.read()
    if snapshot['config']!=config or snapshot['guard']!='UNOPENED' or snapshot['sealed']:
        raise ValueError('T5 requires unchanged unsealed UNOPENED package')
    source=json.loads(Path(artifacts['development_source']['path']).read_text())
    source_root=Path(source['dataset']['path']).parent.parent
    dataset=json.loads(Path(source['dataset']['path']).read_text())
    contract=dataset['contract']
    if (contract.get('preregistered_sha')!=preregistered_sha or contract.get('config')!=config
            or contract.get('scientific_files')!=verify_preregistration(repo,preregistered_sha)):
        raise ValueError('T2 development source differs from registered contract')
    data=load_window_data(Path(source['dataset']['path']).parent.parent,source)
    phases=phase_plan(config['folds']);clock=clock_for(config)
    for name in ('development_models','final_models'):
        verify_phases(data,clock,phases,config['logistic'],config['versions'],supervisor,artifacts[name])
    final=json.loads(Path(artifacts['final_models']['path']).read_text())
    if len(final['phases'])!=1 or final['phases'][0]['phase']!=phases[-1]:
        raise ValueError('T3 requires exact registered final phase')
    contracts=[final['phases'][0]['families'][family]['fit']['contract'] for family in ('constant','logistic')]
    for contract in contracts:supervisor.verified_terminal(contract,'succeeded')
    operational=source_root.parent/'operational-development.jsonl'
    verify_operational_predictions(config,supervisor,data,clock,artifacts['development_models'],fingerprint(operational))
    portfolios=portfolio_segment(config,supervisor,source_root,source,fingerprint(operational),
        Path(artifacts['development_portfolios']['path']).parent,replay=True)
    from .economic_report import build_report
    development_models=json.loads(Path(artifacts['development_models']['path']).read_text())
    expected_report=build_report(development_models,final,portfolios,
        artifacts={'development_models':artifacts['development_models'],'final_models':artifacts['final_models']})
    if json.loads(Path(artifacts['development_report']['path']).read_text())!=expected_report:
        raise ValueError('Development report differs from verified complete portfolio replay')
    resource_preflight(supervisor.root,config)
    bound={**{'receipt_'+k:v for k,v in receipts.items()},**artifacts}
    return supervisor.freeze(sha,sha,sha,True,True,contracts,bound,{f'T{i}':True for i in range(1,6)})



def durable_data_segment(config, output, phase, contract, build):
    """Resume only identical non-fit construction; retain every incomplete attempt.

    A canonical intent prevents output aliases. Completed evidence is immutable;
    a crash before publication may rebuild derived files under the same contract.
    Raw receipts and the one-way confirmation guard remain acquisition-owned.
    """
    import fcntl
    import os
    import uuid
    from .economic_lifecycle import identity
    root=Lifecycle(config['global_ledger']).root
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    output=Path(output).resolve()
    intent=root/(phase+'-data-intent.json')
    binding=dict(phase=phase,output=str(output),contract=contract,config=config)
    with (root/'data-construction.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if intent.exists():
            state=json.loads(intent.read_text())
            if state['binding']!=binding:
                raise ValueError('Canonical data contract/output alias conflict')
        else:
            if output.exists():
                raise ValueError('Existing data output has no canonical construction intent')
            state=dict(binding=binding,identity=identity(binding),completed=None,partials=[])
            atomic_json(intent,state)
        if state['completed'] is not None:
            verify_manifest({'source_evidence':state['completed']})
            evidence=json.loads(Path(state['completed']['path']).read_text())
            validate_data_contract(evidence,phase,contract,config)
            load_window_data(output,evidence)
            return evidence
        if output.exists():
            # Never overwrite completed evidence: validate and recover its publication.
            if (output/'source-evidence.json').exists():
                evidence=json.loads((output/'source-evidence.json').read_text())
                validate_data_contract(evidence,phase,contract,config)
                load_window_data(output,evidence)
                state['completed']=fingerprint(output/'source-evidence.json')
                atomic_json(intent,state)
                return evidence
            partial=output.with_name(output.name+'.partial-'+uuid.uuid4().hex)
            output.rename(partial)
            fd=os.open(output.parent,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
            state['partials'].append(str(partial));atomic_json(intent,state)
        result=build()
        validate_data_contract(result,phase,contract,config)
        load_window_data(output,result)
        state['completed']=fingerprint(output/'source-evidence.json')
        atomic_json(intent,state)
        return result


def make_development_data(repo, config, output, preregistered_sha, progress=None):
    files=verify_preregistration(repo,preregistered_sha)
    return durable_data_segment(config,output,'development',
        dict(preregistered_sha=preregistered_sha,scientific_files=files),
        lambda:_make_development_data(repo,config,output,preregistered_sha,progress))


def make_confirmation_data(config, supervisor, development_evidence, output, progress=None):
    snapshot=supervisor.read()
    if not snapshot['sealed'] or snapshot['terminal'] or snapshot['poison']:
        raise ValueError('Only active frozen confirmation may construct data')
    return durable_data_segment(config,output,'confirmation',
        dict(S=snapshot['S'],P=snapshot['P'],development=development_evidence),
        lambda:_make_confirmation_data(config,supervisor,development_evidence,output,progress))



def validate_data_contract(evidence, phase, binding, config):
    verify_manifest({'dataset':evidence['dataset']})
    dataset=json.loads(Path(evidence['dataset']['path']).read_text())
    if phase=='development':
        expected=dict(experiment=EXPERIMENT,preregistered_sha=binding['preregistered_sha'],
                      scientific_files=binding['scientific_files'],config=config)
        if evidence.get('preregistered_sha')!=binding['preregistered_sha']:
            raise ValueError('Development evidence preregistration mismatch')
    else:
        verify_manifest({'source':evidence['source_manifest'],'development':binding['development']['dataset']})
        canonical=Lifecycle(config['global_ledger']).root/'confirmation-source-v1/manifest.json'
        if Path(evidence['source_manifest']['path']).resolve()!=canonical.resolve():
            raise ValueError('Confirmation source must be canonical acquisition')
        development=json.loads(Path(binding['development']['dataset']['path']).read_text())
        expected=dict(experiment=EXPERIMENT,phase='confirmation',S=binding['S'],
            freeze_sha256=binding['P']['sha256'],source_manifest_sha256=evidence['source_manifest']['sha256'],
            development_warmup_sha256=development['files']['warmup.json']['sha256'])
    if dataset['contract']!=expected:
        raise ValueError('Dataset source contract differs from canonical construction intent')
    expected_window=config['development_utc' if phase=='development' else 'confirmation_utc']
    if [dataset['start_ms'],dataset['end_ms']]!=[utc_ms(v+'T00:00:00+00:00') for v in expected_window]:
        raise ValueError('Dataset window differs from registered phase')
