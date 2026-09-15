"""Indexed event supervisor. No downloads, fits, calibration or raw tick scan.

Uses the account event API and exact TickIndex.range_count API. All opportunity/probability rows arrive
from the caller's already verified, authorized iterators.
"""
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import heapq
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from fxnn.economic_account import (Account, Key, Journal, Opportunity, Quote, Position,
    Transaction, Snapshot, Fill, PriceSummary, SegmentCertificate, make_portfolios, rational)
from fxnn.tick_economic_source import EventKey, Hazard, QuoteGroup
from fxnn.economic_index import TickIndex, UncertainRange


class ClockAdapter:
    def __init__(self, clock):
        self.clock = clock
    def active(self, time):
        return self.clock.is_open(time)
    def coordinate(self, time):
        return self.clock.coordinate(time)
    def inverse(self, origin, duration):
        return self.clock.advance(origin, duration)


def source_key(key, quality=False):
    if key.time is None or key.priority != 4 or key.ordinal < 0:
        raise ValueError('Timed source group key required')
    return Key(key.time, 4, 4*key.ordinal + (1 if quality else 2))


def after(key):
    return EventKey(key.time, key.priority, key.ordinal+1)


def before_time(time):
    return EventKey(time, -2, 0)


def group_quote(group, *, quality_disclosed=False):
    def number(value):
        return None if value is None else rational(value)
    return Quote(group.timestamp, number(group.bid_min), number(group.ask_min),
                 json.dumps(group.identity, separators=(',', ':')), valid=not group.reasons,
                 ambiguous=group.ambiguous, bid_min=number(group.bid_min),
                 ask_max=number(group.ask_max), requires_recovery=bool(group.reasons or group.ambiguous),
                 quality_disclosed=quality_disclosed)


def rollover_events(start, stop):
    """Actual calendar instants, DST aware, half-open evaluation/chunk range."""
    zone = ZoneInfo('America/New_York')
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    day = (epoch+timedelta(milliseconds=start)).astimezone(zone).date()
    last = (epoch+timedelta(milliseconds=stop)).astimezone(zone).date()
    while day <= last:
        if day.weekday() < 5:
            local = datetime(day.year, day.month, day.day, 17, tzinfo=zone)
            delta = local.astimezone(timezone.utc)-epoch
            time = (delta.days*86400+delta.seconds)*1000
            if start <= time < stop:
                yield EventKey(time, 0, 0), 'funding', 3 if day.weekday()==2 else 1
        day += timedelta(days=1)


def digest_json(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def earliest_affected(account, hazard, trade_inputs, cache):
    """Earliest affected trade in O(log trades), with amortized append updates.

    Closed-trade ends increase because the account holds one position. A small
    min-history segment tree locates the first overlapping history span after
    the end-time lower bound; history starts need not be monotonic. Price/index
    source data never enters this cache. Archive-wide taint returns first trade.
    """
    if hazard.reason == 'quote_absence':
        return None
    entries=cache.setdefault('entries',[])
    ends=cache.setdefault('ends',[])
    histories=cache.setdefault('histories',[])
    size=cache.setdefault('size',1)
    tree=cache.setdefault('tree',[None,None])
    for entry,end,identity in account.trade_intervals[len(entries):]:
        if ends and end.time+1<ends[-1]:
            raise ValueError('Closed trade endpoints regressed')
        entries.append(entry);ends.append(end.time+1)
        histories.append(trade_inputs.get(identity,entry.time))
        if len(entries)>size:
            size*=2;tree=[None]*(2*size)
            for i,value in enumerate(histories):tree[size+i]=value
            for node in range(size-1,0,-1):
                children=[v for v in tree[node*2:node*2+2] if v is not None]
                tree[node]=min(children,default=None)
        else:
            node=size+len(entries)-1;tree[node]=histories[-1]
            while node>1:
                node//=2;children=[v for v in tree[node*2:node*2+2] if v is not None]
                tree[node]=min(children,default=None)
    cache['size'],cache['tree']=size,tree
    left,right=hazard.affected_start,hazard.affected_end
    if left is None or right is None:
        return entries[0] if entries else account.position.entry_key if account.position else None
    begin=bisect_right(ends,left)
    def search(node,a,b):
        if b<=begin or a>=len(entries) or tree[node] is None or tree[node]>=right:
            return None
        if b-a==1:return entries[a]
        middle=(a+b)//2
        found=search(node*2,a,middle)
        return found if found is not None else search(node*2+1,middle,b)
    found=search(1,0,size)
    if found is not None:return found
    if account.position:
        p=account.position;history=trade_inputs.get(p.identity,p.entry_key.time)
        disclosure=account.start if hazard.key.time is None else hazard.key.time
        if history<right and left<disclosure+1:return p.entry_key
    return None


class Simulator:
    def __init__(self, index, clock, start, end, bindings, *, journal_factory=None):
        if not isinstance(index, TickIndex) or not callable(getattr(index,'range_count',None)):
            raise TypeError('Verified TickIndex with exact range_count required')
        if start >= end or not bindings:
            raise ValueError('Window and immutable scientific bindings required')
        self.index, self.clock = index, clock
        self.start, self.end = start, end
        self.bindings = dict(bindings)
        self.bindings['index_contract'] = index.manifest['contract_sha256']
        self.bindings['index_manifest'] = hashlib.sha256((index.root/'manifest.json').read_bytes()).hexdigest()
        self.accounts = make_portfolios(ClockAdapter(clock),start,end,journal_factory)
        self.cursors = {identity:before_time(start) for identity in self.accounts}
        self.processed_until = start
        self.chunks = {}
        self.trade_inputs = {}
        self.pending_inputs = {}
        self.trade_span_caches = {identity:{} for identity in self.accounts}
        self.last_history_segment = None
        self.recovery_segment_floor = None
        self.chunk_active = False
        self.metrics = Counter()
        self.query_binding = digest_json(self.bindings)

    def _hazard_at_or_after(self, left, right):
        i = bisect_left(self.index.hazard_keys,left)
        return self.index.hazards[i] if i<len(self.index.hazards) and self.index.hazards[i].key<right else None

    def _first(self, left, right):
        if left >= right:
            return None
        expiry = right.time+1
        result = self.index.first_entry(left,expiry)
        return result if result is not None and result.key<right else None

    def _proof(self, identity, left, right, first, last):
        if self._hazard_at_or_after(left,right) is not None:
            raise UncertainRange('Certificate would cross a disclosed hazard')
        record = dict(binding=self.query_binding,left=left.tuple(),right=right.tuple(),
                      first=first.identity,last=last.identity,gap_upper_bound_open_ms=59999)
        return SegmentCertificate(source_key(first.key),source_key(last.key),first.timestamp,last.timestamp,
                                  59999,True,digest_json(record),str(first.identity),str(last.identity))

    def _quiet(self, identity, right):
        """Summarize prefix strictly before next externally significant event."""
        account = self.accounts[identity]
        left = self.cursors[identity]
        if right <= left:
            return
        if account.state == 'UNRESOLVED' or account.pending:
            self.cursors[identity] = right
            return
        if account.gap_boundary is not None:
            first = self.index.first_return(Hazard(EventKey(account.gap_boundary,1,0),'strict_return',()),right)
            if first is not None:
                left = max(left,first.key)
        else:
            first = self._first(left,right)
        if isinstance(first,Hazard):
            raise UncertainRange('Unprocessed hazard inside quiet prefix')
        if first is None:
            self.cursors[identity] = right
            return
        last = self.index.last_quote(left,right)
        if last is None:
            raise UncertainRange('Quiet interval has no unambiguous last quote')
        certificate = self._proof(identity,left,right,first,last)
        pair = (rational(last.bid_min),rational(last.ask_min))
        if account.position:
            side = 'bid' if account.position.side==1 else 'ask'
            summary = self.index.range_marks(left,right,side)
            count = self.index.range_count(left,right)
            if summary is None or not count:
                raise ValueError('Missing exact held summary/count')
            first_price = rational(first.bid_min if side=='bid' else first.ask_min)
            last_price = pair[0 if side=='bid' else 1]
            values = PriceSummary(first_price,last_price,summary.low,summary.high,summary.drop,summary.rise,count)
            account.process(source_key(last.key),'segment',dict(summary=values,last_source_time=last.timestamp,
                            last_pair=pair,certified_start=source_key(first.key),certificate=certificate))
        else:
            account.process(source_key(last.key),'refresh',dict(certificate=certificate,last_pair=pair))
        self.metrics['certified_ranges'] += 1
        self.cursors[identity] = right

    def _advance(self, identity, right):
        account = self.accounts[identity]
        while self.cursors[identity] < right:
            left = self.cursors[identity]
            timer = account.next_timer(ignore_absence=True)
            limit = right
            timer_key = None if timer is None else EventKey(timer,1,-1)
            if timer_key is not None and timer_key < limit:
                limit = timer_key
            result = None
            if account.pending:
                result = self._first(left,limit)
            elif account.position and account.state == 'OPEN':
                p = account.position
                result = self.index.first_crossing(left,limit,'bid' if p.side==1 else 'ask',
                        lower=min(p.stop,p.take),upper=max(p.stop,p.take),entry_timestamp=p.entry_source_time)
            elif account.position and account.state == 'PENDING_TIMEOUT_EXIT':
                result = self._first(left,limit)
            elif account.position and account.state == 'UNRESOLVED' and account.policy=='P1':
                hazard = Hazard(EventKey(account.hazard_key.time,1,0),'account_hazard',())
                result = self.index.first_return(hazard,limit)
                if result is not None and result.key < left:
                    raise ValueError('First P1 return was skipped by driver prefix')
            if isinstance(result,Hazard):
                raise UncertainRange('Hazard missing from supervisor event stream')
            if result is not None:
                self._quiet(identity,result.key)
                account.process(source_key(result.key),'source',group_quote(result))
                self.cursors[identity] = after(result.key)
                if account.position and account.position.identity in self.pending_inputs:
                    self.trade_inputs[account.position.identity] = self.pending_inputs[account.position.identity]
                self.metrics['individual_groups'] += 1
                continue
            self._quiet(identity,limit)
            if limit == right:
                break
            account.process(Key(timer,2),'timer')
            self.cursors[identity] = after(limit)

    def _source_hazard(self, hazard):
        if hazard.reason != 'quote_absence':
            self.recovery_segment_floor = self.last_history_segment if self.last_history_segment is not None else 0
        for identity, account in self.accounts.items():
            affected = earliest_affected(account,hazard,self.trade_inputs,self.trade_span_caches[identity])
            payload = dict(reason=hazard.reason,requires_recovery=hazard.reason!='quote_absence',affected_from=affected)
            if hazard.key.time is None:
                key = Key(self.start,0,1+hazard.key.ordinal)
                account.process(key,'prestart_quality',payload)
                account.journal.append(key,'untimed_source_provenance',source_time=None,source=hazard.source)
            elif hazard.key.priority == 1:
                if account.gap_boundary != hazard.key.time:
                    account.process(Key(hazard.key.time,2,1+hazard.key.ordinal),'timer_quality',payload)
            else:
                account.process(source_key(hazard.key,quality=True),'quality',payload)
            if hazard.key.priority == 1 and hazard.key.time is not None:
                self.cursors[identity] = max(self.cursors[identity],after(hazard.key))
            if hazard.key.priority == 4:
                groups = list(self.index.iter_groups(hazard.key,after(hazard.key),max_groups=1))
                if groups and groups[0].eligible and not groups[0].reasons:
                    account.process(source_key(groups[0].key),'source',group_quote(groups[0],quality_disclosed=True))
                self.cursors[identity] = max(self.cursors[identity],after(hazard.key))

    def _opportunity(self, row, probability):
        identity = str(row['id'])
        active_pending={a.pending[1].identity for a in self.accounts.values() if a.pending}
        self.pending_inputs={k:v for k,v in self.pending_inputs.items() if k in active_pending}
        self.pending_inputs[identity] = row['decision_ms'] if row.get('earliest_input') is None else row['earliest_input']
        segment = row.get('segment')
        if self.last_history_segment is not None and (type(segment) is not int or segment<self.last_history_segment):
            raise ValueError('Causal history segment regressed')
        recovered = (bool(row.get('history_valid')) and row.get('observed_history',0)>=1941
                     and type(segment) is int and (self.recovery_segment_floor is None or segment>self.recovery_segment_floor))
        p = probability.get('probability')
        p = None if p is None else rational(str(p))
        volatility = row.get('price_volatility')
        opportunity = Opportunity(identity,row['side'],rational(str(volatility)) if volatility is not None else Fraction(0),
                row['deadline_ms'] if row.get('deadline_ms') is not None else row['decision_ms'],
                causal_available=bool(row.get('eligible')),model_available=bool(probability.get('model_available')),probability=p)
        for account in self.accounts.values():
            if account.recovery_needed and recovered:
                account.process(Key(row['decision_ms'],3,0),'decision_recovery',1941)
            account.process(Key(row['decision_ms'],3,1),'decision',opportunity)
        self.last_history_segment = segment

    def _events(self, opportunities, probabilities, start, stop, boundaries):
        def decisions():
            missing = object()
            oi, pi = iter(opportunities),iter(probabilities)
            previous = None
            while True:
                row, probability = next(oi,missing),next(pi,missing)
                if row is missing or probability is missing:
                    if row is not missing or probability is not missing:
                        raise ValueError('Opportunity/probability lengths differ')
                    return
                t = row['decision_ms']
                if not start<=t<stop or previous is not None and t<=previous or str(row['id'])!=str(probability['id']):
                    raise ValueError('Opportunity/probability identity, window or order mismatch')
                previous=t
                yield EventKey(t,3,0),'decision',(row,probability)
        def quality():
            for hazard in self.index.hazards:
                if hazard.key.time is None:
                    if start==self.start:
                        yield EventKey(start,-2,1+hazard.key.ordinal),'hazard',hazard
                elif start<=hazard.key.time<stop:
                    yield hazard.key,'hazard',hazard
        def snapshots():
            for t,name in sorted(boundaries):
                if not start<=t<=stop:
                    raise ValueError('Boundary outside chunk')
                yield EventKey(t,-2,0),'snapshot',name
        return heapq.merge(decisions(),rollover_events(start,stop),quality(),snapshots(),key=lambda event:event[0])

    def run_chunk(self, opportunities, probabilities, *, start, stop, chunk_id, boundaries=(), expected_opportunities=None):
        """Execute one identical-contract chunk; only completed chunks checkpoint.

        Caller keeps chunk IDs bound to immutable opportunity/probability hashes.
        Duplicate completed chunk returns its stored summary without reapplying it.
        """
        if self.chunk_active:
            raise ValueError('Failed/active chunk must restore prior durable checkpoint')
        if chunk_id in self.chunks:
            prior=self.chunks[chunk_id]
            if prior['start']!=start or prior['stop']!=stop:
                raise ValueError('Chunk identity reused for different window')
            return prior['reports']
        if start!=self.processed_until or not start<stop<=self.end:
            raise ValueError('Chunks must cover the registered window continuously')
        if start==self.start and (start,'start') not in boundaries:
            boundaries=tuple(boundaries)+((start,'start'),)
        if stop==self.end and (stop,'final') not in boundaries:
            boundaries=tuple(boundaries)+((stop,'final'),)
        if len({t for t,_ in boundaries})!=len(boundaries) or len({name for _,name in boundaries})!=len(boundaries):
            raise ValueError('Boundary timestamps and names must be unique; share one snapshot across adjacent periods')
        if any(name in next(iter(self.accounts.values())).snapshots for _,name in boundaries):
            raise ValueError('Boundary already checkpointed; do not replay it')
        self.chunk_active=True
        count=0
        for key,kind,payload in self._events(opportunities,probabilities,start,stop,boundaries):
            for identity in self.accounts:
                self._advance(identity,key)
            if kind=='snapshot':
                for account in self.accounts.values():
                    account.process(Key(key.time,0),'snapshot',payload)
            elif kind=='funding':
                for account in self.accounts.values():
                    account.process(Key(key.time,1),'funding',payload)
            elif kind=='hazard':
                self._source_hazard(payload)
            else:
                self._opportunity(*payload);count+=1
        for identity in self.accounts:
            self._advance(identity,before_time(stop))
        if expected_opportunities is not None and count!=expected_opportunities:
            raise ValueError('Incomplete opportunity denominator')
        self.processed_until=stop
        if stop==self.end:
            for account in self.accounts.values():
                account.process(Key(stop,5),'end')
        reports={identity:account.report() for identity,account in self.accounts.items()}
        self.chunks[chunk_id]=dict(start=start,stop=stop,reports=reports)
        self.chunk_active=False
        return reports


CLASSES = {c.__name__:c for c in (Key,Opportunity,Quote,Position,Transaction,Snapshot,Fill,PriceSummary,SegmentCertificate)}


def pack(value):
    if isinstance(value,Fraction):
        return {'$fraction':[value.numerator,value.denominator]}
    if isinstance(value,EventKey):
        return {'$eventkey':[value.time,value.priority,value.ordinal]}
    if is_dataclass(value):
        return {'$class':type(value).__name__,'fields':{f.name:pack(getattr(value,f.name)) for f in fields(value)}}
    if isinstance(value,Counter):
        return {'$counter':[[pack(k),pack(v)] for k,v in value.items()]}
    if isinstance(value,dict):
        return {'$dict':[[pack(k),pack(v)] for k,v in value.items()]}
    if isinstance(value,tuple):
        return {'$tuple':[pack(v) for v in value]}
    if isinstance(value,list):
        return [pack(v) for v in value]
    if value is None or type(value) in (bool,int,str):
        return value
    raise TypeError(f'Unsupported checkpoint type: {type(value).__name__}')


def unpack(value):
    if isinstance(value,list):
        return [unpack(v) for v in value]
    if not isinstance(value,dict):
        return value
    if '$fraction' in value:
        return Fraction(*value['$fraction'])
    if '$eventkey' in value:
        return EventKey(*value['$eventkey'])
    if '$class' in value:
        cls=CLASSES[value['$class']]
        return cls(**{k:unpack(v) for k,v in value['fields'].items()})
    if '$counter' in value:
        return Counter({unpack(k):unpack(v) for k,v in value['$counter']})
    if '$dict' in value:
        return {unpack(k):unpack(v) for k,v in value['$dict']}
    if '$tuple' in value:
        return tuple(unpack(v) for v in value['$tuple'])
    raise ValueError('Unknown checkpoint tag')


def export_checkpoint(simulator, path, *, flush_journals=None):
    """Publish an exclusive immutable checkpoint after durable journal flush."""
    if simulator.chunk_active:
        raise ValueError('Cannot checkpoint a partial/failed chunk')
    if any(a.journal.records is None for a in simulator.accounts.values()):
        if flush_journals is None:
            raise ValueError('Streaming journal fsync callback required before checkpoint')
        flush_journals()
    path=Path(path)
    if path.exists():
        raise FileExistsError(path)
    accounts={}
    for identity,a in simulator.accounts.items():
        accounts[identity]=dict(state={k:v for k,v in vars(a).items() if k not in ('clock','journal','costs')},
                               journal=dict(count=a.journal.count,head=a.journal.head,records=a.journal.records))
    body=dict(version=1,bindings=simulator.bindings,start=simulator.start,end=simulator.end,
              processed_until=simulator.processed_until,cursors=simulator.cursors,chunks=simulator.chunks,
              trade_inputs=simulator.trade_inputs,pending_inputs=simulator.pending_inputs,trade_span_caches=simulator.trade_span_caches,last_history_segment=simulator.last_history_segment,
              recovery_segment_floor=simulator.recovery_segment_floor,
              metrics=simulator.metrics,accounts=accounts)
    encoded=pack(body);document=dict(payload=encoded,sha256=digest_json(encoded))
    temporary=path.with_name(path.name+'.pending')
    with temporary.open('x') as stream:
        json.dump(document,stream,sort_keys=True,separators=(',',':'),allow_nan=False)
        stream.flush();os.fsync(stream.fileno())
    os.link(temporary,path)
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)
    return document['sha256']


def import_checkpoint(path, index, clock, bindings, *, expected_sha256, journal_factory=None, verified_journal_heads=None):
    document=json.loads(Path(path).read_text())
    if document['sha256']!=expected_sha256 or digest_json(document['payload'])!=expected_sha256:
        raise ValueError('Checkpoint content hash mismatch')
    body=unpack(document['payload'])
    if body['version']!=1:
        raise ValueError('Unsupported checkpoint version')
    simulator=Simulator(index,clock,body['start'],body['end'],bindings,journal_factory=None)
    if simulator.bindings!=body['bindings']:
        raise ValueError('Checkpoint scientific/index bindings differ')
    for identity, saved in body['accounts'].items():
        a=simulator.accounts[identity]
        a.__dict__.update(saved['state'])
        if journal_factory is not None:
            if verified_journal_heads is None or verified_journal_heads.get(identity)!=(saved['journal']['count'],saved['journal']['head']):
                raise ValueError('Verified durable journal prefix does not match checkpoint')
            a.journal=journal_factory(identity)
        a.journal.count=saved['journal']['count'];a.journal.head=saved['journal']['head']
        a.journal.records=saved['journal']['records']
    for name in ('processed_until','cursors','chunks','trade_inputs','pending_inputs','trade_span_caches','last_history_segment','recovery_segment_floor','metrics'):
        setattr(simulator,name,body[name])
    return simulator
