"""Authoritative monthly portfolio checkpoints; streaming, restartable, no fits.

Sources/index and predictor are read-only preverified dependencies. The canonical
registry is independent of output aliases. Replay performs no filesystem writes.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import uuid

from fxnn.economic_account import Journal
from fxnn.economic_lifecycle import identity, fingerprint, atomic_json
from fxnn.economic_simulator import Simulator, export_checkpoint, import_checkpoint, pack, unpack, digest_json


def month_windows(start, end):
    current=start
    while current<end:
        d=datetime.fromtimestamp(current/1000,timezone.utc)
        year,month=(d.year+1,1) if d.month==12 else (d.year,d.month+1)
        next_month=int(datetime(year,month,1,tzinfo=timezone.utc).timestamp())*1000
        stop=min(end,next_month)
        yield current,stop
        current=stop


def heads(sim):
    return {'|'.join(k):[a.journal.count,a.journal.head] for k,a in sim.accounts.items()}


def body(sim):
    """Explicit public-checkpoint schema projection, also used by read-only replay."""
    accounts={k:dict(state={n:v for n,v in vars(a).items() if n not in ('clock','journal','costs')},
                     journal=dict(count=a.journal.count,head=a.journal.head,records=a.journal.records))
              for k,a in sim.accounts.items()}
    names=('bindings','start','end','processed_until','cursors','chunks','trade_inputs',
           'pending_inputs','trade_span_caches','last_history_segment','recovery_segment_floor','metrics')
    result=dict(version=1)
    result.update({n:getattr(sim,n) for n in names})
    result['accounts']=accounts
    return result


class PeekRows:
    def __init__(self,rows):self.rows=iter(rows);self.pending=None
    def __iter__(self):return self
    def peek(self):
        if self.pending is None:self.pending=next(self.rows,None)
        return self.pending
    def __next__(self):
        row=self.peek()
        if row is None:raise StopIteration
        self.pending=None
        return row


class TrackedRows:
    def __init__(self, rows):
        self.rows=iter(rows);self.hash=hashlib.sha256();self.count=0
    def __iter__(self):return self
    def __next__(self):
        row=next(self.rows)
        self.hash.update((json.dumps(row,sort_keys=True,separators=(',', ':'),allow_nan=False)+'\n').encode())
        self.count+=1
        return row
    def record(self):return dict(rows=self.count,sha256=self.hash.hexdigest())


class Sinks:
    def __init__(self, directory=None):
        self.directory=directory
        self.streams={};self.hashes={};self.sizes={}
    def factory(self,key):
        name='|'.join(key)
        if name in self.hashes:raise ValueError('Duplicate journal sink')
        self.hashes[name]=hashlib.sha256();self.sizes[name]=0
        if self.directory is not None:
            self.streams[name]=(self.directory/(name+'.jsonl')).open('xb')
        def sink(line):
            raw=line.encode('utf8');self.hashes[name].update(raw);self.sizes[name]+=len(raw)
            if self.directory is not None:self.streams[name].write(raw)
        return Journal(sink=sink,retain=False)
    def attach(self,sim):
        for key,a in sim.accounts.items():
            old=a.journal;j=self.factory(key);j.count=old.count;j.head=old.head;a.journal=j
    def flush(self):
        for stream in self.streams.values():stream.flush();os.fsync(stream.fileno())
    def close(self):
        for stream in self.streams.values():stream.close()
    def records(self):
        return {k:dict(bytes=self.sizes[k],sha256=h.hexdigest()) for k,h in self.hashes.items()}


def verify_file(record):
    if fingerprint(record['path'])!=record:raise ValueError('Artifact fingerprint mismatch')


def verify_journals(commit, previous):
    """Validate both segment bytes and its cumulative append-only chain."""
    current={}
    for key,item in commit['journals'].items():
        verify_file(item['file']);count,head=previous.get(key,[0,None])
        with Path(item['file']['path']).open() as stream:
            for line in stream:
                row=json.loads(line);sha=row.pop('sha256')
                if row['sequence']!=count or row['previous']!=head or identity(row)!=sha:
                    raise ValueError('Journal prefix/hash-chain mismatch')
                count+=1;head=sha
        if [count,head]!=commit['heads'][key]:raise ValueError('Journal cumulative head mismatch')
        current[key]=[count,head]
    if set(current)!=set(commit['heads']) or previous and set(current)!=set(previous):
        raise ValueError('Journal account set mismatch')
    return current


class WindowRunner:
    def __init__(self,index,clock,start,end,opportunities,probability_factory,prediction_binding,
                 scientific_bindings,output,*,canonical_state_root=None,lifecycle=None,
                 phase='development',expected_opportunities):
        if phase not in ('development','confirmation') or phase=='confirmation' and lifecycle is None:
            raise ValueError('Registered phase and confirmation lifecycle required')
        if not callable(probability_factory) or not prediction_binding or not scientific_bindings:
            raise ValueError('Bound probability factory and scientific inputs required')
        if type(expected_opportunities) is not int or expected_opportunities<0:
            raise ValueError('Explicit nonnegative opportunity denominator required')
        if start>=end or start%60000 or end%60000:raise ValueError('Covered nonempty minute window required')
        if sum(1 for _ in clock.minutes(start,end))!=expected_opportunities:
            raise ValueError('Expected opportunities disagree with calendar')
        self.index,self.clock,self.start,self.end=index,clock,start,end
        self.opportunities=dict(opportunities);self.predict=probability_factory
        self.output=Path(output).resolve();self.lifecycle=lifecycle;self.phase=phase
        if lifecycle is not None:
            self.root=lifecycle.root.resolve()
            if canonical_state_root is not None and Path(canonical_state_root).resolve()!=self.root:
                raise ValueError('Lifecycle determines canonical registry')
        elif canonical_state_root is None:raise ValueError('Canonical state root required')
        else:self.root=Path(canonical_state_root).resolve()
        self.registry=self.root/(phase+'-portfolio.json');self.lock=self.root/'portfolio-simulation.lock'
        self.bindings=dict(scientific_bindings)
        self.contract=dict(version=1,experiment='economic_ticks_v1',phase=phase,start=start,end=end,
            scientific=self.bindings,opportunities=self.opportunities,prediction=prediction_binding,
            index_manifest=fingerprint(index.root/'manifest.json'),index_contract=index.manifest['contract_sha256'],
            calendar=dict(first=clock.first,stop=clock.stop,starts=clock.starts,ends=clock.ends),
            expected_opportunities=expected_opportunities,layout='UTC_months_quarter_preclock_v1')
        self.contract_id=identity(self.contract)
        self.windows=list(month_windows(start,end))

    @contextmanager
    def _locked(self,write):
        if write:self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        with self.lock.open('a+b' if write else 'rb') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def _state(self,write):
        if identity(self.contract)!=self.contract_id or self.bindings!=self.contract['scientific']:
            raise ValueError('Runner contract mutated')
        live=None if self.lifecycle is None else self.lifecycle.read()
        if self.phase=='confirmation' and write and (live['guard']!='OPENED' or live.get('poison') or live.get('terminal')):
            raise ValueError('Confirmation not OPENED')
        verify_file(self.opportunities);verify_file(self.contract['index_manifest'])
        if self.registry.exists():
            state=json.loads(self.registry.read_text())
            if state['contract']!=self.contract or state['output']!=str(self.output):
                raise ValueError('Canonical portfolio identity/output alias conflict')
        else:
            if not write:raise ValueError('No authoritative portfolio registration')
            state=dict(contract=self.contract,output=str(self.output),commits=[])
            atomic_json(self.registry,state)
        if self.lifecycle is not None:
            if self.phase=='confirmation':
                if write and live['guard']!='OPENED':raise ValueError('Confirmation not OPENED')
                selected=[v['effect'] for v in live['effects'].values()
                          if v['effect'].get('portfolio_contract')==self.contract_id]
                state['commits']=sorted(selected,key=lambda c:c['start'])
                state['lifecycle_version']=len(live['effects'])
        return state

    def _chunk(self,start,stop):
        return 'portfolio:'+identity(dict(contract=self.contract_id,start=start,stop=stop))

    def _verify_commits(self,state):
        previous={}
        if len(state['commits'])>len(self.windows):raise ValueError('Extra committed months')
        for c,(start,stop) in zip(state['commits'],self.windows):
            if c['chunk_id']!=self._chunk(start,stop) or c['start']!=start or c['stop']!=stop:
                raise ValueError('Noncontiguous/wrong authoritative checkpoint')
            verify_file(c['checkpoint']);previous=verify_journals(c,previous)
            document=json.loads(Path(c['checkpoint']['path']).read_text())
            if document['sha256']!=c['payload_sha256'] or digest_json(document['payload'])!=c['payload_sha256']:
                raise ValueError('Simulator payload hash mismatch')
            decoded=unpack(document['payload'])
            expected_bindings=dict(self.bindings,index_contract=self.contract['index_contract'],
                                   index_manifest=self.contract['index_manifest']['sha256'])
            if decoded['bindings']!=expected_bindings or decoded['start']!=self.start or decoded['end']!=self.end:
                raise ValueError('Checkpoint global scientific/index/window binding mismatch')
            if decoded['processed_until']!=stop or c['chunk_id'] not in decoded['chunks']:
                raise ValueError('Checkpoint boundary mismatch')
            encoded_heads={'|'.join(k):[v['journal']['count'],v['journal']['head']] for k,v in decoded['accounts'].items()}
            if encoded_heads!=previous:raise ValueError('Checkpoint/journal head mismatch')
        return previous

    def _rows(self,start):
        with Path(self.opportunities['path']).open() as stream:
            last=None
            for line in stream:
                row=json.loads(line);t=row['decision_ms']
                if last is not None and t<=last:raise ValueError('Unordered opportunity stream')
                last=t
                if start<=t<self.end:yield row

    def _boundaries(self,start,stop):
        # Start/final supplied by Simulator. Interior quarters belong to prior chunk.
        d=datetime.fromtimestamp(stop/1000,timezone.utc)
        return [(stop,'quarter:'+d.isoformat())] if stop<self.end and d.month in (1,4,7,10) and d.day==1 else []

    def _consume(self,rows,start,stop):
        expected=iter(self.clock.minutes(start,stop))
        missing=object()
        while True:
            t=next(expected,missing)
            if t is missing:
                following=rows.peek()
                if following is not None and following['decision_ms']<stop:
                    raise ValueError('Unexpected extra opportunity before chunk commit')
                return
            row=next(rows,missing)
            if row is missing or row['decision_ms']!=t:raise ValueError('Missing scheduled opportunity')
            yield row

    def run(self,*,fault=None):
        """Complete/restore fixed months. fault hook is for synthetic failure tests."""
        fault=(lambda stage:None) if fault is None else fault
        with self._locked(True):
            state=self._state(True);verified=self._verify_commits(state)
            self.output.mkdir(parents=True,exist_ok=True)
            begin=self.start if not state['commits'] else state['commits'][-1]['stop']
            rows=PeekRows(self._rows(begin));sim=None
            for start,stop in self.windows[len(state['commits']):]:
                attempt=self.output/(str(start)+'-'+uuid.uuid4().hex)
                attempt.mkdir(mode=0o700);sinks=Sinks(attempt)
                try:
                    if sim is None and state['commits']:
                        previous=state['commits'][-1]
                        sim=import_checkpoint(previous['checkpoint']['path'],self.index,self.clock,self.bindings,
                            expected_sha256=previous['payload_sha256'],journal_factory=sinks.factory,
                            verified_journal_heads={tuple(k.split('|')):tuple(v) for k,v in verified.items()})
                    elif sim is None:
                        sim=Simulator(self.index,self.clock,self.start,self.end,self.bindings,journal_factory=sinks.factory)
                    else:sinks.attach(sim)
                    chunk=self._chunk(start,stop)
                    monthly_rows=TrackedRows(self._consume(rows,start,stop));monthly_predictions=TrackedRows(self.predict(start,stop))
                    sim.run_chunk(monthly_rows,monthly_predictions,start=start,stop=stop,
                        chunk_id=chunk,boundaries=self._boundaries(start,stop),
                        expected_opportunities=sum(1 for _ in self.clock.minutes(start,stop)))
                    sinks.flush();fault('journals_fsynced')
                    checkpoint=attempt/'checkpoint.json'
                    payload_sha=export_checkpoint(sim,checkpoint,flush_journals=sinks.flush)
                    fault('checkpoint_fsynced')
                    commit=dict(portfolio_contract=self.contract_id,chunk_id=chunk,start=start,stop=stop,
                        checkpoint=fingerprint(checkpoint),payload_sha256=payload_sha,heads=heads(sim),
                        journals={k:dict(file=fingerprint(attempt/(k+'.jsonl'))) for k in sinks.hashes},
                        source_binding=self.opportunities,prediction_binding=self.contract['prediction'],
                        monthly_inputs=dict(opportunities=monthly_rows.record(),predictions=monthly_predictions.record()))
                    verified=verify_journals(commit,verified)
                    if self.phase=='confirmation':
                        self.lifecycle.checkpoint(chunk,commit,dict(checkpoint=commit['checkpoint'],
                            payload_sha256=payload_sha,heads=commit['heads'],portfolio_contract=self.contract_id),
                            expected_version=state['lifecycle_version'])
                        state['lifecycle_version']+=1
                    else:
                        state['commits'].append(commit);atomic_json(self.registry,state)
                    if self.phase=='confirmation':state['commits'].append(commit)
                    fault('authority_committed')
                finally:sinks.close()
            if next(rows,None) is not None:raise ValueError('Unexpected extra opportunity')
            # Only authoritative commits may produce the published result.
            result=self._result(state)
            atomic_json(self.output/'portfolio-manifest.json',result)
            return result

    def _result(self,state):
        if len(state['commits'])!=len(self.windows):raise ValueError('Incomplete monthly authority')
        final=state['commits'][-1]
        decoded=unpack(json.loads(Path(final['checkpoint']['path']).read_text())['payload'])
        return dict(version=1,contract=self.contract,contract_id=self.contract_id,commits=state['commits'],
                    reports=pack(decoded['chunks'][final['chunk_id']]['reports']))

    def replay(self):
        """Rebuild all committed months in RAM with discard sinks; zero file writes."""
        with self._locked(False):
            state=self._state(False);self._verify_commits(state)
            if len(state['commits'])!=len(self.windows):raise ValueError('Replay requires complete authority')
            rows=PeekRows(self._rows(self.start));sim=None
            for c in state['commits']:
                start,stop=c['start'],c['stop'];sinks=Sinks()
                if sim is None:sim=Simulator(self.index,self.clock,self.start,self.end,self.bindings,journal_factory=sinks.factory)
                else:sinks.attach(sim)
                monthly_rows=TrackedRows(self._consume(rows,start,stop));monthly_predictions=TrackedRows(self.predict(start,stop))
                sim.run_chunk(monthly_rows,monthly_predictions,start=start,stop=stop,
                    chunk_id=c['chunk_id'],boundaries=self._boundaries(start,stop),
                    expected_opportunities=sum(1 for _ in self.clock.minutes(start,stop)))
                if c['monthly_inputs']!=dict(opportunities=monthly_rows.record(),predictions=monthly_predictions.record()):
                    raise ValueError('Replay monthly input differs')
                if heads(sim)!=c['heads'] or digest_json(pack(body(sim)))!=c['payload_sha256']:
                    raise ValueError('Read-only replay checkpoint differs')
                for k,v in sinks.records().items():
                    if v!={n:c['journals'][k]['file'][n] for n in ('bytes','sha256')}:
                        raise ValueError('Read-only replay journal differs')
            if next(rows,None) is not None:raise ValueError('Unexpected extra opportunity')
            return self._result(state)
