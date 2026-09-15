from decimal import Decimal
import unittest
from fxnn.economic_clock import SessionClockMs
from fxnn.tick_economic_source import SourceRow, GroupStart, QuoteGroup, grouped, causal_events, IntegrityUnion, Hazard, EventKey


def row(seq, stamp, bid='1.1', ask='1.2', reasons=()):
    return SourceRow('synthetic', 'a'*64, seq, stamp, reasons, lambda: (Decimal(bid), Decimal(ask)))


class EconomicSourceTests(unittest.TestCase):
    def test_source_order_hazard_and_no_next_price(self):
        seen = []
        def lazy(seq, t):
            return SourceRow('synthetic','a'*64,seq,t,(),lambda:(seen.append(seq) or Decimal('1'),Decimal('2')))
        clock = SessionClockMs(0, 200, [(0, 200)])
        iterator = iter(grouped([lazy(1,100),lazy(2,99),lazy(3,100),lazy(4,101)],clock))
        self.assertIsInstance(next(iterator),GroupStart); self.assertEqual(seen,[])
        first=next(iterator); self.assertEqual(seen,[1])
        rest=list(iterator); groups=[first]+[x for x in rest if isinstance(x,QuoteGroup)]
        self.assertEqual([g.key.time for g in groups],[100,100,100,101])
        self.assertIn('out_of_order',groups[1].reasons)
        self.assertEqual([g.timestamp for g in groups],[100,99,100,101])
        self.assertNotIn(2,seen)

    def test_ties_unknown_and_bars(self):
        clock=SessionClockMs(0,180000,[(0,180000)])
        rows=[row(1,None,reasons=('invalid_timestamp_or_source_month',)),row(2,59999),row(3,60000),row(4,60000,'1.3','1.4'),row(5,120001)]
        events=list(causal_events(rows,clock,0,180000))
        initial=next(e for e in events if e['kind']=='hazard')
        self.assertIsNone(initial['value'].key.time)
        bars=[e['value'] for e in events if e['kind']=='bar']
        self.assertEqual(bars[0].close,Decimal('1.1')); self.assertTrue(bars[0].valid)
        self.assertFalse(bars[1].valid)
        decision=next(i for i,e in enumerate(events) if e['kind']=='decision' and e['time']==60000)
        tie=next(i for i,e in enumerate(events) if e['kind']=='group' and e['value'].ambiguous)
        self.assertLess(decision,tie)
        self.assertTrue(any(e['kind']=='hazard' and e['value'].reason=='quote_absence' for e in events))

    def test_gap_equality_and_offsession(self):
        clock=SessionClockMs(0,240000,[(0,60000),(120000,240000)])
        events=list(causal_events([row(1,0),row(2,60000),row(3,120000),row(4,120001)],clock,0,240000))
        hazards=[e['value'] for e in events if e['kind']=='hazard' and e['value'].reason=='quote_absence']
        self.assertEqual(hazards[0].key.time,60000)
        self.assertFalse(next(e['value'] for e in events if e['kind']=='group' and e['value'].timestamp==60000).eligible)

    def test_asof_full_span_half_open(self):
        hazards=[Hazard(EventKey(100,4,1),'quality',('id',),10,30),Hazard(EventKey(200,4,2),'quality',('late',),40,70)]
        union=IntegrityUnion(hazards,EventKey(200,0,-1))
        self.assertIsNotNone(union.intersects(0,20)); self.assertIsNone(union.intersects(30,40))
        self.assertIsNone(union.intersects(40,60))

    def test_missing_history_timer_before_decision_without_return(self):
        clock=SessionClockMs(0,1200000,[(0,1200000)])
        events=list(causal_events([row(1,0)],clock,0,1200000))
        resets=[(i,e) for i,e in enumerate(events) if e['kind']=='reset' and e['reason']=='missing_15_open_minutes']
        self.assertEqual(len(resets),1)
        index,event=resets[0]; self.assertEqual(event['time'],16*60000)
        decision=next(i for i,e in enumerate(events) if e['kind']=='decision' and e['time']==16*60000)
        self.assertLess(index,decision)

    def test_verified_month_merge_reserved_redaction_and_hash(self):
        import csv,json,hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from fxnn.tick_economic_source import verified_month,digest
        from fxnn.economic_clock import utc_ms
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/'202312';folder=root/'attempt-001';folder.mkdir(parents=True)
            stamp='2023-12-31T23:59:59.999000+00:00'
            with (folder/'ticks.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['timestamp_utc','source_timestamp_est','bid','ask','volume','source_sequence','flags'])
                w.writerow([stamp,'20231231 185959999','1.10','1.11','0',1,'simultaneous_timestamp'])
                # Even if malformed numeric text leaked into a normalized reserved
                # fixture, temporal admission precedes numeric decoding.
                w.writerow(['2024-01-01T00:00:00+00:00','20231231 190000000','BAD','BAD','BAD',3,''])
            (folder/'quarantine.jsonl').write_text(json.dumps(dict(source_sequence=1,timestamp_utc=stamp,reasons=[],retained_in_normalized=True))+'\n'+json.dumps(dict(source_sequence=2,timestamp_utc=None,reasons=['invalid_timestamp_or_source_month'],prices_redacted=True))+'\n')
            (folder/'reserved.jsonl').write_text(json.dumps(dict(source_sequence=4,timestamp_utc='2024-01-01T00:00:01+00:00'))+'\n')
            audit=dict(source_rows=4);(folder/'audit.json').write_text(json.dumps(audit))
            for name in ('form.html','form.html.http.json','raw.zip','raw.zip.http.json'):
                (folder/name).write_text('synthetic nonmarket bytes')
            complete=dict(month='202312',status='completed',attempt='attempt-001',audit=audit,files={p.name:dict(sha256=digest(p)) for p in folder.iterdir()})
            (root/'completed.json').write_text(json.dumps(complete)); expected=digest(root/'completed.json')
            records=list(verified_month(root,expected,(utc_ms('2022-01-01T00:00:00+00:00'),utc_ms('2024-01-01T00:00:00+00:00'))))
            self.assertEqual([r.sequence for r in records],[1,2,3,4]);self.assertEqual(records[0].load_quote(),(Decimal('1.10'),Decimal('1.11')))
            self.assertTrue(records[2].reserved);self.assertIsNone(records[2].load_quote)
            (folder/'quarantine.jsonl').write_text('tampered')
            with self.assertRaisesRegex(ValueError,'artifact changed'):
                list(verified_month(root,expected,(0,10)))

    def test_prefix_future_price_invariance(self):
        clock=SessionClockMs(0,180000,[(0,180000)])
        def prefix(future):
            stream=causal_events([row(1,59999),row(2,60000,future,future)],clock,0,180000)
            before=[]
            for e in stream:
                before.append(e)
                if e['kind']=='decision' and e['time']==60000:
                    break
            return before
        self.assertEqual(prefix('100'),prefix('900'))

    def test_reserved_header_highwater_cannot_pull_late_row_into_training(self):
        clock=SessionClockMs(0,180000,[(0,180000)])
        loaded=[]
        rows=[row(1,59999),SourceRow('synthetic','a'*64,2,180000,(),None,True),
              SourceRow('synthetic','a'*64,3,60001,(),lambda:loaded.append('forbidden'))]
        events=list(causal_events(rows,clock,0,180000))
        self.assertEqual(loaded,[])
        self.assertEqual([e['value'].first_sequence for e in events if e['kind']=='group'],[1])

    def test_unknown_archive_scope_is_not_global_scope(self):
        from fxnn.tick_economic_source import archive_span
        from fxnn.economic_clock import utc_ms
        a,b=archive_span('202301')
        h=Hazard(EventKey(a,4,0),'invalid_timestamp',('202301','a'*64,1),a,b)
        union=IntegrityUnion([h],EventKey(b+1,0,-1))
        self.assertIsNotNone(union.intersects(a,a+1))
        self.assertIsNone(union.intersects(utc_ms('2023-03-01T00:00:00+00:00'),utc_ms('2023-03-02T00:00:00+00:00')))
