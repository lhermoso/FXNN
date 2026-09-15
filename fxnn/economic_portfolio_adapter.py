"""Verified economic-research portfolio adapter; no fits, source scan or writes on replay."""
import hashlib
import json
import math
from pathlib import Path

from fxnn.economic_clock import SessionClockMs, utc_ms
from fxnn.economic_lifecycle import fingerprint, verify_manifest, identity
from fxnn.economic_index import TickIndex
from fxnn.economic_portfolio_run import WindowRunner, month_windows
from fxnn.economic_simulator import import_checkpoint, unpack
from fxnn.economic_account import Journal
from fxnn.economic_report import collect_portfolios, evaluate_portfolios


def window(values):
    return tuple(utc_ms(v+'T00:00:00+00:00') for v in values)


class MonthlyPredictions:
    """One metadata/probability pass; bounded month offsets, never a full row list."""
    def __init__(self,artifact,clock,start,end):
        verify_manifest({'operational':artifact})
        self.artifact=dict(artifact);self.ranges={}
        expected=iter(clock.minutes(start,end));missing=object()
        self.windows=list(month_windows(start,end));month=0
        self.summaries={}
        hashes={a:hashlib.sha256() for a,b in self.windows}
        for a,b in self.windows:self.summaries[str(a)]=dict(start=a,stop=b,rows=0)
        with Path(artifact['path']).open('rb') as stream:
            while True:
                offset=stream.tell();line=stream.readline()
                if not line:break
                row=json.loads(line);time=next(expected,missing)
                if time is missing or type(row.get('decision_ms')) is not int or row['decision_ms']!=time:
                    raise ValueError('Operational predictions must cover exact window grid')
                if row.get('id')!=f'economic_ticks_v1:{time}' or type(row.get('model_available')) is not bool:
                    raise ValueError('Operational prediction identity/status mismatch')
                p=row.get('probability')
                if p is not None and (type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1):
                    raise ValueError('Finite probability or explicit null required')
                if not row['model_available'] and p is not None:
                    raise ValueError('Unavailable phase model cannot provide probability')
                while not self.windows[month][0]<=time<self.windows[month][1]:month+=1
                a,b=self.windows[month]
                if a not in self.ranges:self.ranges[a]=[offset,stream.tell()]
                else:self.ranges[a][1]=stream.tell()
                canonical=json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n'
                hashes[a].update(canonical.encode());self.summaries[str(a)]['rows']+=1
        if next(expected,missing) is not missing:raise ValueError('Missing operational prediction rows')
        for a,b in self.windows:self.summaries[str(a)]['sha256']=hashes[a].hexdigest()
        verify_manifest({'operational':artifact})
    def __call__(self,start,stop):
        if (start,stop) not in self.windows:raise ValueError('Unregistered prediction month')
        bounds=self.ranges.get(start)
        if bounds is None:return
        with Path(self.artifact['path']).open('rb') as stream:
            stream.seek(bounds[0])
            while stream.tell()<bounds[1]:yield json.loads(stream.readline())
            if stream.tell()!=bounds[1]:raise ValueError('Prediction byte boundary changed')


def quarter_periods(config,confirmation):
    if confirmation:
        bounds=['2024-01-01','2024-04-01','2024-07-01','2024-10-01','2025-01-01']
        names=['2024Q1','2024Q2','2024Q3','2024Q4']
        if config['confirmation_utc']!=[bounds[0],bounds[-1]]:raise ValueError('Confirmation year changed')
    else:
        folds=config['folds'];names=[f['name'] for f in folds]
        bounds=[f['test_start'][:10] for f in folds]+[folds[-1]['test_end'][:10]]
        if names!=['2023Q2','2023Q3','2023Q4'] or bounds!=['2023-04-01','2023-07-01','2023-10-01','2024-01-01']:
            raise ValueError('Development quarter contract changed')
        if config['development_portfolio_utc']!=[bounds[0],bounds[-1]]:raise ValueError('Portfolio window changed')
        if any(f['test_start']!=bounds[i]+'T00:00:00+00:00' or f['test_end']!=bounds[i+1]+'T00:00:00+00:00' for i,f in enumerate(folds)):
            raise ValueError('Exact UTC fold boundary required')
        if any(folds[i]['test_end']!=folds[i+1]['test_start'] for i in range(len(folds)-1)):
            raise ValueError('Noncontiguous development folds')
    labels=['start']+['quarter:'+v+'T00:00:00+00:00' for v in bounds[1:-1]]+['final']
    return [(name,labels[i],labels[i+1]) for i,name in enumerate(names)]


def collect_checkpoint(result,index,clock,scientific_bindings,periods):
    """Called only with WindowRunner's authoritative verified result; no market queries.

    Run/replay already verified every journal segment and checkpoint. This method
    rechecks the final file/payload and imports its accounts with verified heads,
    then invokes existing Account quarterly aggregation on recorded cash/marks.
    """
    final=result['commits'][-1]
    verify_manifest({'final_checkpoint':final['checkpoint']})
    sim=import_checkpoint(final['checkpoint']['path'],index,clock,scientific_bindings,
        expected_sha256=final['payload_sha256'],journal_factory=lambda key:Journal(sink=lambda line:None,retain=False),
        verified_journal_heads={tuple(k.split('|')):tuple(v) for k,v in final['heads'].items()})
    reports={key:account.report() for key,account in sim.accounts.items()}
    if reports!=unpack(result['reports']) or sim.processed_until!=result['contract']['end']:
        raise ValueError('Final checkpoint/report mismatch')
    return collect_portfolios(sim.accounts,periods)


def portfolio_segment(config,supervisor,data_output,source_evidence,operational,
                      portfolio_output,*,confirmation=False,replay=False):
    """Return economic_report-compatible 12 scenarios plus artifact provenance."""
    snapshot=supervisor.read()
    if snapshot['config']!=config:raise ValueError('Portfolio differs from reserved config')
    if confirmation and (not snapshot['sealed'] or not snapshot.get('P')):
        raise ValueError('Confirmation requires frozen package')
    if confirmation and not replay and snapshot['guard']!='OPENED':raise ValueError('Confirmation not OPENED')
    verify_manifest(snapshot['files'])
    output=Path(data_output).resolve()
    verify_manifest({'dataset':source_evidence['dataset'],'labels':source_evidence['labels'],'operational':operational})
    if Path(source_evidence['dataset']['path']).resolve()!=output/'dataset/manifest.json':
        raise ValueError('Source evidence points to different dataset')
    if Path(source_evidence['labels']['path']).resolve()!=output/'labels/manifest.json':
        raise ValueError('Source evidence points to different labels')
    dataset=json.loads((output/'dataset/manifest.json').read_text())
    labels=json.loads((output/'labels/manifest.json').read_text())
    if labels['dataset_manifest_sha256']!=source_evidence['dataset']['sha256']:
        raise ValueError('Source label lineage differs')
    if dataset['experiment']!='economic_ticks_v1' or set(dataset['files'])!={'opportunities.jsonl','bars.jsonl','warmup.json','index/manifest.json'}:
        raise ValueError('Unregistered dataset manifest schema')
    files={}
    for name,expected in dataset['files'].items():
        actual=fingerprint(output/'dataset'/name)
        if actual['sha256']!=expected['sha256'] or actual['bytes']!=expected['bytes']:
            raise ValueError('Dataset file fingerprint mismatch')
        files[name]=actual
    data_window=window(config['confirmation_utc'] if confirmation else config['development_utc'])
    if (dataset['start_ms'],dataset['end_ms'])!=data_window:raise ValueError('Dataset temporal identity differs')
    contract=dataset['contract']
    if contract.get('experiment')!='economic_ticks_v1':raise ValueError('Dataset contract experiment differs')
    if confirmation:
        verify_manifest({'freeze':snapshot['P'],'source_manifest':source_evidence['source_manifest']})
        if not source_evidence.get('confirmation_access') or any((
            contract.get('S')!=snapshot['S'],source_evidence.get('S')!=snapshot['S'],
            contract.get('freeze_sha256')!=snapshot['P']['sha256'],
            source_evidence.get('freeze_sha256')!=snapshot['P']['sha256'],
            contract.get('source_manifest_sha256')!=source_evidence['source_manifest']['sha256'])):
            raise ValueError('Confirmation dataset not bound to frozen source')
    else:
        if source_evidence.get('confirmation_access') or contract.get('config')!=config or contract.get('preregistered_sha')!=source_evidence.get('preregistered_sha'):
            raise ValueError('Development dataset scientific lineage differs')
        if not contract.get('scientific_files'):raise ValueError('Dataset scientific bindings missing')
        if 'config_sha256' in source_evidence and source_evidence['config_sha256']!=snapshot['files']['configs/economic_ticks_v1.json']['sha256']:
            raise ValueError('Source config fingerprint differs from reservation')
        for artifact in contract['scientific_files'].values():
            if artifact not in snapshot['files'].values():raise ValueError('Dataset scientific file outside reservation')
    start,end=window(config['confirmation_utc'] if confirmation else config['development_portfolio_utc'])
    clock=SessionClockMs.weekly(*window(config['calendar_utc']))
    if sum(1 for _ in clock.minutes(*data_window))!=dataset['expected_opportunities']:
        raise ValueError('Dataset opportunity denominator differs from calendar')
    periods=quarter_periods(config,confirmation)
    predictions=MonthlyPredictions(operational,clock,start,end)
    science=dict(S=snapshot['S'],config_sha256=identity(config),dataset_manifest=source_evidence['dataset']['sha256'],
                 source_evidence=identity(source_evidence),operational=operational['sha256'])
    if confirmation:science['freeze_sha256']=snapshot['P']['sha256']
    with TickIndex(output/'dataset/index',dataset['index_contract_sha256'],
                   expected_manifest_sha256=files['index/manifest.json']['sha256'],
                   cache_bytes=config['index']['cache_bytes']) as index:
        runner=WindowRunner(index,clock,start,end,files['opportunities.jsonl'],predictions,
            dict(operational=operational,monthly=predictions.summaries),science,portfolio_output,
            lifecycle=supervisor,phase='confirmation' if confirmation else 'development',
            expected_opportunities=sum(1 for _ in clock.minutes(start,end)))
        result=runner.replay() if replay else runner.run()
        portfolios=collect_checkpoint(result,index,clock,science,periods)
        # Validate 12 arms, all prescribed quarters and exact total reconciliation.
        evaluate_portfolios(portfolios,confirmation=confirmation)
    artifacts={'final_checkpoint':result['commits'][-1]['checkpoint']}
    published=Path(portfolio_output)/'portfolio-manifest.json'
    if published.exists():
        if json.loads(published.read_text())!=result:raise ValueError('Published portfolio differs from authority')
        artifacts['portfolio_manifest']=fingerprint(published)
    portfolios.update(artifacts=artifacts,scientific_fits=0,replay_verified=bool(replay),
                      portfolio_contract_id=result['contract_id'])
    return portfolios
