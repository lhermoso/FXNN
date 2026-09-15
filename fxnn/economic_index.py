"""Exact disk block index. Tree pruning never supplies an executable quote.

Queries scan at most partial boundary/candidate blocks; no horizon-sized scans.
Ordered marks use a top-level summary tree and two bounded boundary scans.
"""
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys

from .economic_clock import MIN_I64
from .tick_economic_source import EventKey, Hazard, QuoteGroup, digest

RECORD = struct.Struct('<qqQQQQHB')
PRICE = struct.Struct('<qqqq')
MAX_COEFFICIENT_BITS = 12000
MAX_BLOCK_BYTES = 16*1024**2


class UncertainRange(ValueError):
    pass


def exact(value):
    if isinstance(value,float):
        raise ValueError('Binary float execution price forbidden')
    if isinstance(value,Decimal) and not value.is_finite():
        raise ValueError('Finite exact price required')
    return Fraction(value)


@dataclass(frozen=True)
class MarkSummary:
    low: Fraction
    high: Fraction
    drop: Fraction = Fraction(0)
    rise: Fraction = Fraction(0)

    def merge(self, other):
        return MarkSummary(min(self.low,other.low),max(self.high,other.high),
                           max(self.drop,other.drop,self.high-other.low),
                           max(self.rise,other.rise,other.high-self.low))

    def affine(self, units, cash):
        units,cash = exact(units),exact(cash)
        if units >= 0:
            return MarkSummary(cash+units*self.low,cash+units*self.high,units*self.drop,units*self.rise)
        return MarkSummary(cash+units*self.high,cash+units*self.low,-units*self.rise,-units*self.drop)


def merge(a, b):
    return b if a is None else a if b is None else a.merge(b)


def summarize(values):
    result = None
    for value in values:
        result = merge(result,MarkSummary(value,value))
    return result


def summary_json(summary):
    return None if summary is None else [str(v) for v in (summary.low,summary.high,summary.drop,summary.rise)]


def key_json(key):
    return [key.time,key.priority,key.ordinal]


def storage_check(path, needed, min_free):
    if shutil.disk_usage(path).free <= needed+min_free:
        raise OSError('Insufficient disk for declared index output and safety margin')


def durable_json(path, value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,sort_keys=True,allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


def coefficients(groups):
    values = [v for g in groups for v in (g.bid_min,g.bid_max,g.ask_min,g.ask_max) if v is not None]
    exponents = [v.as_tuple().exponent for v in values]
    scale = max(0,-min(exponents,default=0))
    if scale*4 > MAX_COEFFICIENT_BITS:
        raise ValueError('Exact scale exceeds declared precision resources')
    # Bound allocation before exponentiation; precision failure is technical,
    # never a price rounding or a dropped market row.
    for value in values:
        digits = value.as_tuple().digits
        if (len(digits)+value.as_tuple().exponent+scale)*4 > MAX_COEFFICIENT_BITS:
            raise ValueError('Exact coefficient exceeds declared precision resources')
    result = []
    for g in groups:
        row = []
        for value in (g.bid_min,g.bid_max,g.ask_min,g.ask_max):
            if value is None:
                row.append(0); continue
            sign,digits,exponent = value.as_tuple()
            coefficient = 0
            for digit in digits:
                coefficient = coefficient*10+digit
            row.append((-1 if sign else 1)*coefficient*10**(exponent+scale))
        result.append(tuple(row))
    low = min((min(v) for v in result),default=0)
    high = max((max(v) for v in result),default=0)
    encoding = 'int64' if -(2**63) <= low <= high < 2**63 and high-low < 2**63 else 'integer_json'
    return result,scale,encoding


def build_index(groups, hazards, output, contract, *, block_size=1024,
                min_free=20*1024**3, estimated_bytes=0):
    """Publish manifest last; partial files are deliberately preserved on failure.

    No fit or market acquisition is performed here. Production resource checks
    retain at least20GiB; small synthetic fixtures may explicitly use zero.
    """
    if type(block_size) is not int or not 1 <= block_size <= 65536:
        raise ValueError('Invalid registered block size')
    if type(min_free) is not int or min_free < 0 or type(estimated_bytes) is not int or estimated_bytes < 0:
        raise ValueError('Nonnegative resource bounds required')
    output = Path(output)
    storage_check(output.parent,estimated_bytes,min_free)
    output.mkdir(exist_ok=False)
    identity = hashlib.sha256(json.dumps(contract,sort_keys=True,allow_nan=False).encode()).hexdigest()
    manifest = dict(version=1,contract=contract,contract_sha256=identity,block_size=block_size,
                    record_format=RECORD.format,blocks=[],sources=[],groups=0,
                    resources=dict(min_free=min_free,max_coefficient_bits=MAX_COEFFICIENT_BITS,max_block_bytes=MAX_BLOCK_BYTES))
    sources = {}
    previous = None
    required_hazards = set()
    with (output/'records.bin').open('xb') as records, (output/'prices.bin').open('xb') as prices:
        def flush(block):
            if not block:
                return
            rows,scale,encoding = coefficients(block)
            payload = b''.join(PRICE.pack(*r) for r in rows) if encoding == 'int64' else json.dumps(rows,separators=(',',':')).encode()
            if len(payload) > MAX_BLOCK_BYTES:
                raise ValueError('Encoded exact block exceeds resource limit')
            storage_check(output,max(estimated_bytes-records.tell()-prices.tell(),len(payload)+len(block)*RECORD.size),min_free)
            offset = prices.tell()
            prices.write(payload)
            summaries = {}
            for name,column in (('bid',0),('ask',2)):
                summaries[name] = summarize(Fraction(rows[i][column],10**scale) for i,g in enumerate(block) if g.eligible and not g.ambiguous)
            block_record = dict(first=key_json(block[0].key),last=key_json(block[-1].key),count=len(block),
                                record_offset=records.tell(),price_offset=offset,price_bytes=len(payload),
                                scale=scale,encoding=encoding,summary={k:summary_json(v) for k,v in summaries.items()},
                                eligible_count=sum(g.eligible and not g.ambiguous for g in block),
                                eligible_max_timestamp=max((g.timestamp for g in block if g.eligible),default=None),
                                price_sha256=hashlib.sha256(payload).hexdigest())
            packed = bytearray()
            for g in block:
                source = (g.month,g.archive)
                if source not in sources:
                    if len(sources) >= 65536:
                        raise ValueError('Too many source identities')
                    sources[source] = len(sources); manifest['sources'].append(list(source))
                kind = 2 if g.reasons else (3 if g.eligible else 4) if g.ambiguous else 0 if g.eligible else 1
                if g.reasons or g.ambiguous and g.eligible:
                    required_hazards.add(g.key)
                packed.extend(RECORD.pack(MIN_I64 if g.key.time is None else g.key.time,
                    MIN_I64 if g.timestamp is None else g.timestamp,g.key.ordinal,
                    g.first_sequence,g.last_sequence,g.count,sources[source],kind))
            records.write(packed)
            block_record['record_sha256'] = hashlib.sha256(packed).hexdigest()
            manifest['blocks'].append(block_record)
            manifest['groups'] += len(block)
        block = []
        for group in groups:
            if not isinstance(group,QuoteGroup) or group.key.priority != 4 or (previous is not None and group.key <= previous):
                raise ValueError('Groups must retain strict source disclosure order')
            previous = group.key
            block.append(group)
            if len(block) == block_size:
                flush(block); block = []
        flush(block)
        for stream in (records,prices):
            stream.flush(); os.fsync(stream.fileno())
    hazard_rows = []
    previous = None
    for h in hazards:
        if previous is not None and h.key < previous:
            raise ValueError('Hazards must be in disclosure order')
        previous = h.key
        hazard_rows.append(dict(key=key_json(h.key),reason=h.reason,source=list(h.source),
                                affected_start=h.affected_start,affected_end=h.affected_end))
    if not required_hazards.issubset({EventKey(*v['key']) for v in hazard_rows}):
        raise ValueError('Every invalid or ambiguous eligible group requires its disclosed hazard')
    durable_json(output/'hazards.json',hazard_rows)
    manifest['files'] = {name:dict(sha256=digest(output/name),bytes=(output/name).stat().st_size)
                         for name in ('records.bin','prices.bin','hazards.json')}
    storage_check(output,0,min_free)
    durable_json(output/'.manifest.pending',manifest)
    os.link(output/'.manifest.pending',output/'manifest.json')
    directory = os.open(output,os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return manifest


def deep_size(value):
    if isinstance(value,(tuple,list)):
        return sys.getsizeof(value)+sum(deep_size(v) for v in value)
    return sys.getsizeof(value)


class TickIndex:
    """Read-only verified blocks; cache measured in decoded bytes, not block count."""
    def __init__(self, directory, expected_contract_sha256, *, expected_manifest_sha256,
                 cache_bytes=256*1024**2):
        self.root = Path(directory)
        if self.root.is_symlink() or (self.root/'manifest.json').is_symlink():
            raise ValueError('Symlink index path rejected')
        if digest(self.root/'manifest.json') != expected_manifest_sha256:
            raise ValueError('Index manifest hash mismatch')
        self.manifest = json.loads((self.root/'manifest.json').read_text())
        m = self.manifest
        if m['version'] != 1 or m['record_format'] != RECORD.format or m['contract_sha256'] != expected_contract_sha256:
            raise ValueError('Index schema or contract mismatch')
        if hashlib.sha256(json.dumps(m['contract'],sort_keys=True,allow_nan=False).encode()).hexdigest() != expected_contract_sha256:
            raise ValueError('Index contract changed')
        for name,record in m['files'].items():
            if name not in ('records.bin','prices.bin','hazards.json') or (self.root/name).is_symlink() or digest(self.root/name) != record['sha256'] or (self.root/name).stat().st_size != record['bytes']:
                raise ValueError('Index artifact hash/size changed')
        if set(m['files']) != {'records.bin','prices.bin','hazards.json'} or cache_bytes <= 0:
            raise ValueError('Invalid artifact schema or cache limit')
        self.blocks = m['blocks']
        self.first = [EventKey(*b['first']) for b in self.blocks]
        self.last = [EventKey(*b['last']) for b in self.blocks]
        ro,po,total = 0,0,0
        for i,b in enumerate(self.blocks):
            if (not 0 < b['count'] <= m['block_size'] or type(b['eligible_count']) is not int
                    or not 0 <= b['eligible_count'] <= b['count']
                    or b['record_offset'] != ro or b['price_offset'] != po
                    or b['price_bytes'] > MAX_BLOCK_BYTES or b['scale'] < 0
                    or b['scale']*4 > MAX_COEFFICIENT_BITS
                    or b['encoding'] not in ('int64','integer_json') or self.last[i] < self.first[i]
                    or i and self.first[i] <= self.last[i-1]):
                raise ValueError('Invalid block schema, offsets or order')
            ro += b['count']*RECORD.size; po += b['price_bytes']; total += b['count']
        if ro != m['files']['records.bin']['bytes'] or po != m['files']['prices.bin']['bytes'] or total != m['groups']:
            raise ValueError('Incomplete index file or group count')
        self.hazards = [Hazard(EventKey(*v['key']),v['reason'],tuple(v['source']),v['affected_start'],v['affected_end'])
                        for v in json.loads((self.root/'hazards.json').read_text())]
        self.hazard_keys = [h.key for h in self.hazards]
        self.quality_reasons = {h.key:tuple(h.reason.split('|')) for h in self.hazards}
        if any(a>b for a,b in zip(self.hazard_keys,self.hazard_keys[1:])):
            raise ValueError('Hazard index is not disclosure ordered')
        self.cache,self.cache_size,self.cache_limit = OrderedDict(),0,cache_bytes
        self.records = (self.root/'records.bin').open('rb')
        self.prices = (self.root/'prices.bin').open('rb')
        self.size = 1 << max(0,(len(self.blocks)-1).bit_length())
        self.trees = {side:[None]*(2*self.size) for side in ('bid','ask')}
        self.return_times = [None]*(2*self.size)
        self.eligible_counts = [0]*(2*self.size)
        for i,b in enumerate(self.blocks,self.size):
            for side in self.trees:
                v = b['summary'][side]
                self.trees[side][i] = None if v is None else MarkSummary(*map(Fraction,v))
            self.return_times[i] = b['eligible_max_timestamp']
            self.eligible_counts[i] = b['eligible_count']
        for node in range(self.size-1,0,-1):
            self.eligible_counts[node] = self.eligible_counts[node*2]+self.eligible_counts[node*2+1]
            for tree in self.trees.values():
                tree[node] = merge(tree[node*2],tree[node*2+1])
            values = [x for x in self.return_times[node*2:node*2+2] if x is not None]
            self.return_times[node] = max(values,default=None)
        self.metrics = dict(decoded_blocks=0,cache_hits=0,scanned_groups=0,tree_nodes=0)

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()

    def close(self):
        self.records.close(); self.prices.close(); self.cache.clear(); self.cache_size = 0

    def _block(self, i):
        if i in self.cache:
            self.metrics['cache_hits'] += 1
            value,size = self.cache.pop(i); self.cache[i] = value,size
            return value
        b = self.blocks[i]
        self.records.seek(b['record_offset']); raw = self.records.read(b['count']*RECORD.size)
        self.prices.seek(b['price_offset']); payload = self.prices.read(b['price_bytes'])
        if hashlib.sha256(raw).hexdigest() != b['record_sha256'] or hashlib.sha256(payload).hexdigest() != b['price_sha256']:
            raise ValueError('Block changed after verified open')
        records = list(RECORD.iter_unpack(raw))
        prices = list(PRICE.iter_unpack(payload)) if b['encoding']=='int64' else [tuple(v) for v in json.loads(payload)]
        if len(records) != b['count'] or len(prices) != b['count'] or any(len(p)!=4 or any(type(v) is not int or abs(v).bit_length()>MAX_COEFFICIENT_BITS for v in p) for p in prices):
            raise ValueError('Invalid exact-price block shape or precision')
        value = records,prices
        size = deep_size(value)
        if size > self.cache_limit:
            raise ValueError('Decoded block exceeds cache byte bound')
        while self.cache_size+size > self.cache_limit:
            _,(_,removed) = self.cache.popitem(last=False); self.cache_size -= removed
        self.cache[i] = value,size; self.cache_size += size
        self.metrics['decoded_blocks'] += 1
        return value

    def _group(self, block, record, prices):
        time,stamp,ordinal,first,last,count,source,kind = record
        month,archive = self.manifest['sources'][source]
        def decimal(q):
            return Decimal((int(q<0),tuple(map(int,str(abs(q)))),-self.blocks[block]['scale']))
        values = [None]*4 if kind==2 else [decimal(q) for q in prices]
        return QuoteGroup(EventKey(None if time==MIN_I64 else time,4,ordinal),None if stamp==MIN_I64 else stamp,
                          month,archive,first,last,count,*values,self.quality_reasons.get(EventKey(None if time==MIN_I64 else time,4,ordinal),()) if kind==2 else (),kind in (0,3),kind in (3,4))

    def next_hazard(self, after, until):
        i = bisect_right(self.hazard_keys,after)
        return self.hazards[i] if i<len(self.hazards) and self.hazards[i].key<until else None

    def _search(self, left, right, possible, predicate):
        if right <= left or not self.blocks:
            return None
        def visit(node,a,b):
            self.metrics['tree_nodes'] += 1
            if a>=len(self.blocks) or self.last[min(b,len(self.blocks))-1]<left or self.first[a]>=right or not possible(node):
                return None
            if b-a==1:
                records,prices = self._block(a)
                for record,price in zip(records,prices):
                    key = EventKey(None if record[0]==MIN_I64 else record[0],4,record[2])
                    if left<=key<right:
                        self.metrics['scanned_groups'] += 1
                        if predicate(record,price,self.blocks[a]['scale']):
                            return self._group(a,record,price)
                return None
            middle = (a+b)//2
            result = visit(node*2,a,middle)
            return result if result is not None else visit(node*2+1,middle,b)
        return visit(1,0,self.size)

    def first_crossing(self, left, right, side, lower=None, upper=None, *, entry_timestamp=None):
        if side not in ('bid','ask') or lower is None and upper is None:
            raise ValueError('Bid/ask side and at least one exact bound required')
        lower = None if lower is None else exact(lower)
        upper = None if upper is None else exact(upper)
        hazard = self.next_hazard(left,right)
        if hazard is not None:
            right = hazard.key
        column = 0 if side=='bid' else 2
        def possible(node):
            if entry_timestamp is not None and (self.return_times[node] is None or self.return_times[node] <= entry_timestamp):
                return False
            summary = self.trees[side][node]
            return summary is not None and (lower is not None and summary.low<=lower or upper is not None and summary.high>=upper)
        thresholds = {}
        def touches(record,prices,scale):
            if record[-1] != 0 or entry_timestamp is not None and record[1]<=entry_timestamp:
                return False
            if scale not in thresholds:
                unit = 10**scale
                lo = None if lower is None else lower.numerator*unit//lower.denominator
                hi = None if upper is None else -((-upper.numerator*unit)//upper.denominator)
                thresholds[scale] = lo,hi
            lo,hi = thresholds[scale]
            value = prices[column]
            return lo is not None and value<=lo or hi is not None and value>=hi
        return self._search(left,right,possible,touches)

    def first_return(self, hazard, until):
        if hazard.key.time is None:
            raise UncertainRange('Untimed phase-start hazard has no P1 liquidation timestamp')
        boundary = hazard.key.time
        return self._search(hazard.key,until,
            lambda node:self.return_times[node] is not None and self.return_times[node]>boundary,
            lambda record,prices,scale:record[-1] in (0,3) and record[1]>boundary)

    def first_entry(self, decision, expiry):
        right = EventKey(expiry,0,-1)
        hazard = self.next_hazard(decision,right)
        if hazard is not None:
            right = hazard.key
        result = self._search(decision,right,lambda node:self.return_times[node] is not None,
                              lambda record,prices,scale:record[-1] in (0,3))
        return result if result is not None else hazard

    def last_quote(self, left, right, side=None):
        """Last unambiguous eligible paired quote in [left,right), or None.

        Caller must start after any already-accounted hazard. Crossing a hazard
        is an uncertainty error, never permission to reuse a stale mark.
        """
        if side not in (None,'bid','ask'):
            raise ValueError('Expected bid or ask')
        hazard = bisect_left(self.hazard_keys,left)
        if hazard < len(self.hazards) and self.hazard_keys[hazard] < right:
            raise UncertainRange('Last-quote interval crosses a quality hazard')
        if right <= left or not self.blocks:
            return None
        def visit(node,a,b):
            self.metrics['tree_nodes'] += 1
            if (a >= len(self.blocks) or self.last[min(b,len(self.blocks))-1] < left
                    or self.first[a] >= right or self.trees['bid'][node] is None):
                return None
            if b-a == 1:
                records,prices = self._block(a)
                for record,price in zip(reversed(records),reversed(prices)):
                    key = EventKey(None if record[0]==MIN_I64 else record[0],4,record[2])
                    if record[-1]==0 and left<=key<right:
                        return self._group(a,record,price)
                return None
            middle = (a+b)//2
            found = visit(node*2+1,middle,b)
            return found if found is not None else visit(node*2,a,middle)
        return visit(1,0,self.size)

    def iter_groups(self, left, right, *, max_groups=10000):
        """Bounded fixture/audit iterator; never use as an opportunity forward scan."""
        if type(max_groups) is not int or not 0 < max_groups <= 10000:
            raise ValueError('Fixture iterator cap is at most10000 groups')
        count = 0
        begin = bisect_left(self.last,left)
        for block in range(begin,len(self.blocks)):
            if self.first[block]>=right:
                break
            records,prices = self._block(block)
            for record,price in zip(records,prices):
                key = EventKey(None if record[0]==MIN_I64 else record[0],4,record[2])
                if left<=key<right:
                    count += 1
                    if count > max_groups:
                        raise ValueError('Fixture iterator exceeded declared group cap')
                    yield self._group(block,record,price)

    def range_marks(self,left,right,side):
        if side not in self.trees:
            raise ValueError('Expected bid or ask')
        hazard = bisect_left(self.hazard_keys,left)
        if hazard < len(self.hazards) and self.hazard_keys[hazard] < right:
            raise UncertainRange('Ordered mark range crosses a quality hazard')
        column = 0 if side=='bid' else 2
        def visit(node,a,b):
            if a>=len(self.blocks) or self.last[min(b,len(self.blocks))-1]<left or self.first[a]>=right:
                return None
            if left<=self.first[a] and self.last[min(b,len(self.blocks))-1]<right:
                return self.trees[side][node]
            if b-a==1:
                records,prices = self._block(a)
                # Summarize integer coefficients first; one exact conversion per
                # field avoids allocating Fraction objects for every boundary quote.
                summary = None
                for r,p in zip(records,prices):
                    if r[-1]==0 and left<=EventKey(None if r[0]==MIN_I64 else r[0],4,r[2])<right:
                        value = p[column]
                        if summary is None:
                            summary = [value,value,0,0]
                        else:
                            low,high,drop,rise = summary
                            summary = [min(low,value),max(high,value),max(drop,high-value),max(rise,value-low)]
                return None if summary is None else MarkSummary(*(Fraction(v,10**self.blocks[a]['scale']) for v in summary))
            middle = (a+b)//2
            return merge(visit(node*2,a,middle),visit(node*2+1,middle,b))
        return None if right<=left or not self.blocks else visit(1,0,self.size)

    def range_count(self,left,right):
        """Count ordered executable groups, not raw rows or ordinal differences."""
        hazard=bisect_left(self.hazard_keys,left)
        if hazard<len(self.hazard_keys) and self.hazard_keys[hazard]<right:
            raise UncertainRange('Ordered count range crosses a quality hazard')
        def visit(node,a,b):
            if a>=len(self.blocks) or self.last[min(b,len(self.blocks))-1]<left or self.first[a]>=right:
                return 0
            if left<=self.first[a] and self.last[min(b,len(self.blocks))-1]<right:
                return self.eligible_counts[node]
            if b-a==1:
                records,_=self._block(a)
                return sum(r[-1]==0 and left<=EventKey(None if r[0]==MIN_I64 else r[0],4,r[2])<right
                           for r in records)
            middle=(a+b)//2
            return visit(node*2,a,middle)+visit(node*2+1,middle,b)
        return 0 if right<=left or not self.blocks else visit(1,0,self.size)
