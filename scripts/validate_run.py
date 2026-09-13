"""Audit annual output, all selected trades and sampled hard negatives independently."""
import argparse
import csv
import hashlib
import json
import random
from dataclasses import fields
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fxnn.labeling import Candle, Config, Trade, label_trades_reference


def audit(input_path, output):
    summary=json.loads((output/'summary.json').read_text())
    assert hashlib.sha256(input_path.read_bytes()).hexdigest()==summary['input_sha256']
    with input_path.open() as f:
        candles=[Candle(datetime.fromisoformat(r['timestamp']),*(Decimal(r[k]) for k in ('open','high','low','close'))) for r in csv.DictReader(f)]
    # This audit targets the initial 50/20/72h M1 experiment explicitly.
    config=Config(Decimal('0.0001'))
    assert summary['config']=={'pip_size':'0.0001','take_profit_pips':'50','stop_loss_pips':'20',
                               'max_hold':'3 days, 0:00:00','bar_duration':'0:01:00'}
    with (output/'selected_trades.csv').open() as f:selected=list(csv.DictReader(f))
    with (output/'hard_negatives.csv').open() as f:hard=list(csv.DictReader(f))
    def key(row):return int(row['entry_index']),row['side']
    selected_map={key(r):r for r in selected}
    hard_map={key(r):r for r in hard}
    assert len(selected_map)==len(selected) and len(hard_map)==len(hard)
    audited=selected+random.Random(7).sample(hard,min(512,len(hard)))
    indices=sorted({int(r['entry_index']) for r in audited})
    reference={(t.entry_index,t.side):t for t in label_trades_reference(candles,config,indices)}
    for row in audited:
        expected=reference[key(row)]
        for field in fields(Trade):
            value=getattr(expected,field.name)
            assert row[field.name]==('' if value is None else str(value)),(key(row),field.name)
    for a,b in zip(selected,selected[1:]):
        assert datetime.fromisoformat(a['end_time'])<=datetime.fromisoformat(b['entry_time'])
    winners=[]; count=0; seen_selected=set(); seen_hard=set()
    with (output/'all_trades.csv').open() as f:
        for row in csv.DictReader(f):
            count+=1
            assert row['outcome'] in ('take_profit','stop_loss','timeout')
            assert row['label']==str(int(row['outcome']=='take_profit'))
            if row['outcome']=='take_profit':
                assert Decimal(row['pnl_pips'])==50
                start,end=map(datetime.fromisoformat,(row['entry_time'],row['end_time']))
                assert timedelta(0)<end-start<timedelta(days=3)
                winners.append((end,start))
            if row['outcome']=='stop_loss':assert Decimal(row['pnl_pips'])<=-20
            if key(row) in selected_map:
                assert row==selected_map[key(row)]
                seen_selected.add(key(row))
            if row['post_stop_target_status']=='reached':
                assert row['outcome']=='stop_loss' and row['label']=='0'
                assert row==hard_map[key(row)]
                seen_hard.add(key(row))
    assert seen_selected==selected_map.keys() and seen_hard==hard_map.keys()
    # For equal positive rewards, earliest-finish greedy independently proves
    # maximum number of disjoint trades (duration tie-break has unit-test oracle).
    greedy_count=0; last=None
    for end,start in sorted(winners):
        if last is None or start>=last:
            greedy_count+=1;last=end
    assert greedy_count==len(selected)==summary['selected']
    assert count==summary['usable_labels']
    assert len(hard)==summary['hard_negatives']
    assert count+sum(summary['discarded_outcomes'].values())==2*len(candles)
    report={'status':'passed','input_sha256':summary['input_sha256'],
            'exported_rows_checked':count,'selected_trades_all_reference_checked':len(selected),
            'sampled_hard_negatives_reference_checked':len(audited)-len(selected),
            'maximum_nonoverlapping_count_independently_verified':greedy_count,
            'ambiguous_or_incomplete_exported':0,
            'files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.csv')}}
    (output/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,default=Path('output/eurusd_2025'))
    args=parser.parse_args()
    print(json.dumps(audit(args.input,args.output),indent=2))
