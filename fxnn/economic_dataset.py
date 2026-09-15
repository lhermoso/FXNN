"""Streaming stage9 source/feature/index build and separate outcome projection."""
from collections import Counter
import json
import os
from pathlib import Path

from fxnn.economic_index import build_index, TickIndex, durable_json
from fxnn.tick_economic_source import causal_events, digest
from .economic_opportunities import OpportunityBuilder
from .economic_labels import label_one


def line(stream, value):
    stream.write(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')


def build_dataset(rows, clock, start, end, output, contract, *, min_free=20*1024**3,
                  warmup=None, estimated_index_bytes=6310000000):
    """The caller verifies source bindings and preregistration before this call.

    Files publish by a final manifest only. Failures leave forensic partials;
    another invocation cannot silently overwrite or certify those partials.
    """
    output=Path(output)
    output.mkdir(exist_ok=False)
    builder=OpportunityBuilder(clock) if warmup is None else OpportunityBuilder.from_history(clock,warmup,start)
    hazards=[]
    counts=Counter()
    with (output/'opportunities.jsonl').open('x') as opportunities, (output/'bars.jsonl').open('x') as bars:
        def groups():
            for event in causal_events(rows,clock,start,end):
                kind=event['kind']
                counts['events_'+kind]+=1
                if kind=='bar':
                    bar=event['value']
                    builder.on_bar(bar)
                    line(bars,dict(start=bar.start,end=bar.end,valid=bar.valid,
                                   open=None if bar.open is None else str(bar.open),
                                   high=None if bar.high is None else str(bar.high),
                                   low=None if bar.low is None else str(bar.low),
                                   close=None if bar.close is None else str(bar.close),
                                   observations=bar.observations))
                elif kind=='reset':
                    builder.reset(event['reason'],integrity=event['reason']!='missing_15_open_minutes')
                elif kind=='decision':
                    value=builder.decision(event['time'],end)
                    line(opportunities,value)
                    counts['opportunities']+=1
                    counts['eligible']+=int(value['eligible'])
                    counts['reason_'+value['reason']]+=1
                elif kind=='hazard':
                    hazards.append(event['value'])
                elif kind=='group':
                    group=event['value']
                    counts['disclosed_source_rows']+=group.count
                    counts['eligible_groups']+=int(group.eligible)
                    counts['ambiguous_groups']+=int(group.ambiguous)
                    yield group
                else:
                    raise ValueError('Unknown causal source event')
        index_manifest=build_index(groups(),hazards,output/'index',contract,
                                   block_size=1024,min_free=min_free,
                                   estimated_bytes=estimated_index_bytes)
        for stream in (opportunities,bars):
            stream.flush();os.fsync(stream.fileno())
    expected=sum(1 for _ in clock.minutes(start,end))
    if counts['opportunities']!=expected:
        raise ValueError('All-minute opportunity denominator mismatch')
    durable_json(output/'warmup.json',builder.export_history())
    files={name:dict(sha256=digest(output/name),bytes=(output/name).stat().st_size)
           for name in ('opportunities.jsonl','bars.jsonl','index/manifest.json','warmup.json')}
    manifest=dict(version=1,experiment='economic_ticks_v1',start_ms=start,end_ms=end,
                  contract=contract,index_contract_sha256=index_manifest['contract_sha256'],
                  files=files,counts=dict(counts),expected_opportunities=expected)
    durable_json(output/'manifest.json',manifest)
    return manifest


def verified_records(path, expected_sha256):
    path=Path(path)
    if path.is_symlink() or digest(path)!=expected_sha256:
        raise ValueError('Dataset content fingerprint mismatch')
    with path.open() as stream:
        for row in stream:
            yield json.loads(row)


def build_labels(dataset, expected_manifest_sha256, output):
    dataset,output=Path(dataset),Path(output)
    if digest(dataset/'manifest.json')!=expected_manifest_sha256:
        raise ValueError('Dataset manifest fingerprint mismatch')
    manifest=json.loads((dataset/'manifest.json').read_text())
    output.mkdir(exist_ok=False)
    counts=Counter()
    with TickIndex(dataset/'index',manifest['index_contract_sha256'],
                   expected_manifest_sha256=manifest['files']['index/manifest.json']['sha256']) as index:
        with (output/'labels.jsonl').open('x') as stream:
            for opportunity in verified_records(dataset/'opportunities.jsonl',
                                  manifest['files']['opportunities.jsonl']['sha256']):
                label=label_one(opportunity,index)
                line(stream,label)
                counts['rows']+=1
                counts['reason_'+label['reason']]+=1
                counts['unavailable' if label['label'] is None else 'positive' if label['label'] else 'negative']+=1
            stream.flush();os.fsync(stream.fileno())
        metrics=dict(index.metrics)
    if counts['rows']!=manifest['expected_opportunities']:
        raise ValueError('Label denominator differs from opportunity stream')
    result=dict(version=1,dataset_manifest_sha256=expected_manifest_sha256,counts=dict(counts),
                labels_sha256=digest(output/'labels.jsonl'),label_bytes=(output/'labels.jsonl').stat().st_size,
                index_query_metrics=metrics)
    durable_json(output/'manifest.json',result)
    return result
