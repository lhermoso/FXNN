"""Verified source-order records, lazy quote groups and immutable causal bid M1."""
from bisect import bisect_right
import csv
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from functools import total_ordering
import hashlib
import heapq
import json
from pathlib import Path
import re

from .economic_clock import MIN_I64, integer_ms, utc_ms


@total_ordering
@dataclass(frozen=True)
class EventKey:
    time: int | None
    priority: int = 4
    ordinal: int = 0

    def tuple(self):
        return (MIN_I64 if self.time is None else integer_ms(self.time), self.priority, self.ordinal)

    def __lt__(self, other):
        return self.tuple() < other.tuple()


@dataclass(frozen=True)
class SourceRow:
    month: str
    archive: str
    sequence: int
    timestamp: int | None
    reasons: tuple
    load_quote: object = None
    reserved: bool = False

    @property
    def identity(self):
        return (self.month, self.archive, self.sequence)


@dataclass(frozen=True)
class GroupStart:
    key: EventKey
    timestamp: int | None


@dataclass(frozen=True)
class QuoteGroup:
    key: EventKey
    timestamp: int | None
    month: str
    archive: str
    first_sequence: int
    last_sequence: int
    count: int
    bid_min: Decimal | None
    bid_max: Decimal | None
    ask_min: Decimal | None
    ask_max: Decimal | None
    reasons: tuple
    eligible: bool
    ambiguous: bool

    @property
    def identity(self):
        return (self.month, self.archive, self.first_sequence, self.last_sequence)


@dataclass(frozen=True)
class Hazard:
    key: EventKey
    reason: str
    source: tuple
    affected_start: int | None = None
    affected_end: int | None = None


@dataclass(frozen=True)
class BidBar:
    start: int
    end: int
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    valid: bool
    observations: int


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified_month(month_root, expected_completed_sha256, window):
    """Read an issue19 completed month; no downloads or reserved numeric access.

    Caller supplies a frozen completed-file digest. All monthly artifacts are
    verified before rows are admitted. The authorized UTC window is mandatory.
    """
    root = Path(month_root)
    if root.is_symlink() or not re.fullmatch(r'\d{6}', root.name):
        raise ValueError('Expected nonsymlink YYYYMM source directory')
    if digest(root/'completed.json') != expected_completed_sha256:
        raise ValueError('Completed manifest hash mismatch')
    manifest = json.loads((root/'completed.json').read_text())
    required = {'form.html','form.html.http.json','raw.zip','raw.zip.http.json',
                'ticks.csv','quarantine.jsonl','reserved.jsonl','audit.json'}
    if (manifest['month'] != root.name or manifest['status'] != 'completed'
            or set(manifest['files']) != required or not re.fullmatch(r'attempt-\d{3}',manifest['attempt'])):
        raise ValueError('Invalid completed month schema')
    folder = root/manifest['attempt']
    if folder.is_symlink():
        raise ValueError('Symlink source attempt')
    for name, record in manifest['files'].items():
        file = folder/name
        expected = record['sha256'] if isinstance(record,dict) else record
        if file.is_symlink() or digest(file) != expected:
            raise ValueError('Frozen monthly artifact changed')
    if json.loads((folder/'audit.json').read_text()) != manifest['audit']:
        raise ValueError('Audit differs from completed manifest')
    archive = manifest['files']['raw.zip']
    archive = archive['sha256'] if isinstance(archive,dict) else archive
    count = 0
    for row in normalized_rows(folder,root.name,archive,window):
        count += 1
        if row.sequence != count:
            raise ValueError('Normalized metadata omits or repeats source sequence')
        yield row
    if count != manifest['audit']['source_rows']:
        raise ValueError('Source row coverage differs from acquisition audit')


def normalized_rows(folder, month, archive, window):
    """Internal normalized/quarantine/reserved merge; production uses verified_month."""
    first, stop = map(integer_ms,window)
    if stop <= first:
        raise ValueError('Authorized UTC window required')

    def entries(path, kind):
        with path.open(newline='') as stream:
            rows = csv.DictReader(stream) if kind == 'quote' else (json.loads(line) for line in stream)
            previous = 0
            for record in rows:
                sequence = int(record['source_sequence'])
                if sequence <= previous:
                    raise ValueError('Source stream sequence must strictly increase')
                previous = sequence
                yield sequence,kind,record

    pending = []
    streams = [iter(entries(Path(folder)/name,kind)) for name,kind in
               (('ticks.csv','quote'),('quarantine.jsonl','quarantine'),('reserved.jsonl','reserved'))]
    for number, stream in enumerate(streams):
        value = next(stream,None)
        if value is not None:
            heapq.heappush(pending,(value[0],number,value))
    while pending:
        sequence = pending[0][0]
        same = {}
        while pending and pending[0][0] == sequence:
            _,number,(_,kind,record) = heapq.heappop(pending)
            same[kind] = record
            value = next(streams[number],None)
            if value is not None:
                heapq.heappush(pending,(value[0],number,value))
        quote, quarantine = same.get('quote'),same.get('quarantine')
        if len(same)>1 and not (set(same)=={'quote','quarantine'} and quarantine.get('retained_in_normalized') and not quarantine.get('reasons')):
            raise ValueError('Conflicting source identity across normalized metadata')
        record = quote or quarantine or same['reserved']
        stamp = record.get('timestamp_utc')
        stamp = None if stamp is None else utc_ms(stamp)
        if quote and quarantine and quote['timestamp_utc'] != quarantine['timestamp_utc']:
            raise ValueError('Retained quarantine timestamp mismatch')
        reserved = 'reserved' in same or stamp is not None and not first <= stamp < stop
        reasons = tuple(quarantine.get('reasons',())) if quarantine else ()
        if stamp is None and not reasons:
            raise ValueError('Untimed row requires integrity reason')
        loader = None
        if quote is not None and not reserved and not reasons:
            # Numeric fields are touched only after temporal admission, and only
            # when this source group is disclosed, never for next-group lookahead.
            def loader(record=quote):
                bid, ask, volume = (Decimal(record[name]) for name in ('bid','ask','volume'))
                if not all(v.is_finite() for v in (bid,ask,volume)) or not 0 < bid <= ask or volume < 0:
                    raise ValueError('Normalized source contains an invalid quote')
                return bid, ask
        yield SourceRow(month,archive,sequence,stamp,reasons,loader,reserved)


def grouped(rows, clock, *, disclosure_stop=None):
    """Yield GroupStart BEFORE numeric parsing, then the atomic QuoteGroup.

    Consumers process clocks/decisions on GroupStart before requesting the group.
    Only next-row identity/timestamp is inspected to find a group boundary.
    """
    iterator = iter(rows)
    pending = next(iterator,None)
    highwater, ordinal, previous_identity = None, 0, None
    while pending is not None:
        row = pending
        if previous_identity is not None and (row.month,row.sequence) <= previous_identity:
            raise ValueError('Global source month/sequence order changed')
        previous_identity = (row.month,row.sequence)
        if row.reserved:
            if row.timestamp is not None:
                highwater = row.timestamp if highwater is None else max(highwater,row.timestamp)
            pending = next(iterator,None)
            continue
        timestamp = row.timestamp
        reasons = row.reasons
        if timestamp is not None:
            integer_ms(timestamp)
            if highwater is not None and timestamp < highwater:
                reasons = tuple(sorted(set(reasons+('out_of_order',))))
            highwater = timestamp if highwater is None else max(highwater,timestamp)
        if disclosure_stop is not None and highwater is not None and highwater >= disclosure_stop:
            pending = next(iterator,None)
            continue
        key = EventKey(highwater,4,ordinal)
        ordinal += 1
        yield GroupStart(key,timestamp)
        first_sequence = row.sequence
        count, last, bid_min, bid_max, ask_min, ask_max, pair = 0,row.sequence,None,None,None,None,None
        ambiguous = False
        while True:
            count += 1; last = row.sequence
            if not reasons:
                if row.load_quote is None:
                    raise ValueError('Valid row missing lazy quote decoder')
                bid, ask = row.load_quote()
                if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
                    raise ValueError('Invalid decoded quote')
                ambiguous |= pair is not None and pair != (bid,ask)
                pair = (bid,ask) if pair is None else pair
                bid_min = bid if bid_min is None else min(bid_min,bid)
                bid_max = bid if bid_max is None else max(bid_max,bid)
                ask_min = ask if ask_min is None else min(ask_min,ask)
                ask_max = ask if ask_max is None else max(ask_max,ask)
            pending = next(iterator,None)
            if (reasons or pending is None or pending.reserved or pending.reasons
                    or pending.timestamp != timestamp or pending.month != row.month
                    or pending.archive != row.archive):
                break
            if pending.sequence <= row.sequence:
                raise ValueError('Source sequence reversed inside group')
            row = pending
            previous_identity = (row.month,row.sequence)
        eligible = timestamp is not None and clock.first <= timestamp < clock.stop and clock.is_open(timestamp) and not reasons
        yield QuoteGroup(key,timestamp,row.month,row.archive,first_sequence,
                         last,count,bid_min,bid_max,ask_min,ask_max,reasons,eligible,ambiguous)


class CausalBarBuilder:
    def __init__(self, clock, start):
        self.clock, self.cursor = clock,start
        self.values = None
        self.invalid = False
        self.count = 0

    def advance(self, time):
        while self.cursor+60000 <= time:
            if self.clock.is_open(self.cursor):
                if self.values is not None or self.invalid:
                    values = (None,None,None,None) if self.values is None else tuple(self.values)
                    yield BidBar(self.cursor,self.cursor+60000,*values,not self.invalid,self.count)
            self.cursor += 60000
            self.values,self.invalid,self.count = None,False,0

    def apply(self, group):
        if group.key.time is None:
            return
        if group.key.time < self.cursor:
            raise ValueError('Cannot reopen a finalized M1 bucket')
        if group.reasons or group.ambiguous and group.eligible:
            self.invalid = True
        if group.eligible and not group.ambiguous:
            bid = group.bid_min
            if self.values is None:
                self.values = [bid,bid,bid,bid]
            else:
                self.values[1] = max(self.values[1],bid)
                self.values[2] = min(self.values[2],bid)
                self.values[3] = bid
            self.count += 1


def archive_span(month):
    if not re.fullmatch(r'\d{6}',month):
        return None,None
    year,number = int(month[:4]),int(month[4:])
    zone = timezone(timedelta(hours=-5))
    first = datetime(year,number,1,tzinfo=zone)
    last = datetime(year+(number==12),1 if number==12 else number+1,1,tzinfo=zone)
    return utc_ms(first.isoformat()),utc_ms(last.isoformat())


def causal_events(rows, clock, start, end):
    """Stream timers, finalized bars, all scheduled decisions and group disclosures.

    Funding/account events are supplied by the future account scheduler before
    this timer/bar/decision layer. Reset events are separate from immutable bars.
    """
    if start % 60000 or end % 60000 or not clock.first <= start < end <= clock.stop:
        raise ValueError('Causal replay bounds must be covered UTC minutes')
    builder = CausalBarBuilder(clock,start)
    decision, gap_due, gap_fired = start,None,False
    history_due, history_fired = None,False

    def advance(until):
        nonlocal decision,gap_fired,history_due,history_fired
        while True:
            pending_times = [decision] if decision < end and decision <= until else []
            if gap_due is not None and not gap_fired and gap_due < end and gap_due <= until:
                pending_times.append(gap_due)
            if history_due is not None and not history_fired and history_due < end and history_due <= until:
                pending_times.append(history_due)
            if not pending_times:
                break
            time = min(pending_times)
            if gap_due == time and not gap_fired:
                gap_fired = True
                yield dict(kind='hazard',value=Hazard(EventKey(time,1,0),'quote_absence',()))
            if history_due == time and not history_fired:
                history_fired = True
                yield dict(kind='reset',time=time,reason='missing_15_open_minutes',key=EventKey(time,1,1))
            if decision == time:
                for bar in builder.advance(time):
                    if bar.valid and bar.close is not None:
                        history_fired = False
                        try:
                            history_due = clock.advance(bar.end,15*60000)
                        except ValueError:
                            history_due = None
                    yield dict(kind='bar',value=bar)
                if clock.is_open(time):
                    yield dict(kind='decision',time=time,key=EventKey(time,3,0))
                decision += 60000

    for event in grouped(rows,clock,disclosure_stop=end):
        if isinstance(event,GroupStart):
            if event.key.time is not None:
                if event.key.time >= start:
                    yield from advance(event.key.time)
            continue
        group = event
        if group.reasons or group.ambiguous and group.eligible:
            reason = '|'.join(group.reasons) if group.reasons else 'distinct_timestamp_group'
            affected_start = None if group.timestamp is None else min(group.timestamp,group.key.time)//60000*60000
            affected_end = None if group.timestamp is None else (group.key.time//60000+1)*60000
            if group.timestamp is None:
                affected_start,affected_end = archive_span(group.month)
            hazard = Hazard(group.key,reason,group.identity,affected_start,affected_end)
            yield dict(kind='hazard',value=hazard)
            yield dict(kind='reset',time=group.key.time,key=group.key,reason=reason)
        if group.key.time is None or group.key.time >= start:
            builder.apply(group)
        yield dict(kind='group',value=group)
        if group.eligible and not group.ambiguous:
            if not gap_fired or group.timestamp > gap_due:
                last_quote = group.timestamp
                gap_fired = False
                try:
                    gap_due = clock.advance(last_quote,60000)
                except ValueError:
                    gap_due = None
    yield from advance(end)
    for bar in builder.advance(end):
        yield dict(kind='bar',value=bar)


class IntegrityUnion:
    """One disclosure-as-of union per fixed fit cutoff; half-open history spans."""
    def __init__(self, hazards, cutoff):
        active = [h for h in hazards if h.key < cutoff and h.reason != 'quote_absence']
        self.unknown = tuple(h.source for h in active if h.affected_start is None)
        intervals = sorted((h.affected_start,h.affected_end,h.source) for h in active if h.affected_start is not None)
        self.intervals = []
        for start,end,source in intervals:
            if end <= start:
                raise ValueError('Invalid integrity interval')
            if self.intervals and start <= self.intervals[-1][1]:
                prior = self.intervals[-1]
                prior[1] = max(prior[1],end)
                prior[2].append(source)
            else:
                self.intervals.append([start,end,[source]])
        self.intervals = [(a,b,tuple(ids)) for a,b,ids in self.intervals]
        self.starts = [v[0] for v in self.intervals]

    def intersects(self, earliest_input, information_end):
        if information_end <= earliest_input:
            raise ValueError('Nonempty half-open training information span required')
        if self.unknown:
            return ('unknown_scope',self.unknown)
        i = bisect_right(self.starts,information_end-1)-1
        return i if i >= 0 and self.intervals[i][1] > earliest_input else None
