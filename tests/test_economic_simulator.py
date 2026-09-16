"""Synthetic foundation integration tests. Never load market artifacts."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import json
import random
from types import SimpleNamespace
from decimal import Decimal
from fractions import Fraction

from fxnn.economic_simulator import Simulator,export_checkpoint,import_checkpoint,rollover_events,earliest_affected
from fxnn.economic_account import Key,Opportunity,Quote,Journal
from fxnn.economic_index import build_index,TickIndex
from fxnn.economic_clock import SessionClockMs
from fxnn.tick_economic_source import QuoteGroup,EventKey,Hazard,digest


def group(t, ordinal, bid='1.1', ask='1.1002', *, timestamp='default', eligible=True, ambiguous=False, reasons=()):
    timestamp=t if timestamp=='default' else timestamp
    return QuoteGroup(EventKey(t,4,ordinal),timestamp,'synthetic','fixture',ordinal+1,ordinal+1,1,
                      Decimal(bid),Decimal(bid),Decimal(ask),Decimal(ask),reasons,eligible,ambiguous)


def row(t,side=1,deadline=200000,earliest_input=None,**kwargs):
    return dict(id=str(t),decision_ms=t,side=side,eligible=True,price_volatility=.01,
                deadline_ms=deadline,earliest_input=t if earliest_input is None else earliest_input,
                history_valid=True,observed_history=1941,segment=0,**kwargs)


def probability(t, available=True,p='.5'):
    return dict(id=str(t),probability=p,model_available=available)


class SimulatorTests(unittest.TestCase):
    def fixture(self,groups,hazards=(),end=300000):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        folder=Path(temp.name)/'index'
        m=build_index(groups,hazards,folder,{'fixture':True},block_size=2,min_free=0)
        index=TickIndex(folder,m['contract_sha256'],expected_manifest_sha256=digest(folder/'manifest.json'))
        self.addCleanup(index.close)
        clock_stop=max(10000000,end+1000000)
        clock=SessionClockMs(0,clock_stop,[(0,clock_stop)])
        return Simulator(index,clock,0,end,{'science':'fixture'}),Path(temp.name)

    def test_long_short_indexed_tp_and_dense_expectation(self):
        for side,bid,ask in [(1,'1.5','1.5002'),(-1,'.7','.7002')]:
            sim,_=self.fixture([group(0,0),group(1,1,bid,ask)])
            reports=sim.run_chunk([row(0,side=side)],[probability(0)],start=0,stop=300000,chunk_id='a')
            for identity,report in reports.items():
                expected={'S0':Fraction(25),'S1':Fraction('24.93'),'S2':Fraction('24.86')}[identity[1]]
                self.assertEqual(report['conclusive_pnl'],expected)
                self.assertEqual(report['counts']['entries'],1)
                self.assertEqual(report['counts']['take_profit'],1)

    def test_continuous_no_touch_ranges_over60_and_quarters(self):
        groups=[group(t,i) for i,t in enumerate(range(0,270001,30000))]
        sim,_=self.fixture(groups,end=300000)
        reports=sim.run_chunk([row(0,deadline=200000)],[probability(0)],start=0,stop=300000,chunk_id='a',boundaries=[(90000,'q1'),(180000,'q2')])
        a=sim.accounts['P0','S1','primary']
        self.assertEqual(a.cash,Fraction('9999.71'))
        self.assertEqual(a.counts['timeout'],1)
        self.assertNotIn('unresolved_events',a.counts)
        self.assertEqual(a.quarterly('start','q1')['wall_exposure_ms'],90000)
        self.assertGreater(sim.metrics['certified_ranges'],0)

    def test_p0_p1_gap_boundary_and_strict_return(self):
        hazards=[Hazard(EventKey(60000,1,0),'quote_absence',())]
        groups=[group(0,0),group(60000,1),group(60001,2,'1.08','1.0802')]
        sim,_=self.fixture(groups,hazards)
        reports=sim.run_chunk([row(0)],[probability(0)],start=0,stop=300000,chunk_id='a')
        self.assertIsNone(reports['P0','S1','primary']['conclusive_pnl'])
        self.assertEqual(reports['P0','S1','primary']['counts'].get('exits',0),0)
        self.assertEqual(reports['P1','S1','primary']['counts']['p1_adverse_liquidation'],1)
        self.assertIsNone(reports['P1','S1','primary']['max_dollar_drawdown'])

    def test_checkpoint_resume_identical_chunks_no_duplicate(self):
        groups=[group(t,i) for i,t in enumerate(range(0,270001,30000))]
        full,_=self.fixture(groups,end=300000)
        expected=full.run_chunk([row(0)],[probability(0)],start=0,stop=300000,chunk_id='full',boundaries=[(90000,'q1')])
        sim,path=self.fixture(groups,end=300000)
        first=sim.run_chunk([row(0)],[probability(0)],start=0,stop=90000,chunk_id='first',boundaries=[(90000,'q1')])
        checkpoint=path/'checkpoint.json';sha=export_checkpoint(sim,checkpoint)
        resumed=import_checkpoint(checkpoint,sim.index,sim.clock,{'science':'fixture'},expected_sha256=sha)
        self.assertEqual(resumed.run_chunk([],[],start=0,stop=90000,chunk_id='first'),first)
        actual=resumed.run_chunk([],[],start=90000,stop=300000,chunk_id='second')
        for identity in expected:
            self.assertEqual(actual[identity]['conclusive_pnl'],expected[identity]['conclusive_pnl'])
            self.assertEqual(actual[identity]['commission'],expected[identity]['commission'])
            self.assertEqual(resumed.accounts[identity].transactions,full.accounts[identity].transactions)
            self.assertEqual(actual[identity]['journal_head'],expected[identity]['journal_head'])

    def test_history_only_retrotaint_keeps_actions(self):
        g=[group(0,0),group(1,1,'1.5','1.5002'),group(100,2,timestamp=50,reasons=('out_of_order',))]
        h=[Hazard(g[-1].key,'out_of_order',g[-1].identity,-10,1)]
        sim,_=self.fixture(g,h)
        reports=sim.run_chunk([row(0,earliest_input=-10)],[probability(0)],start=0,stop=300000,chunk_id='a')
        a=sim.accounts['P0','S1','primary']
        self.assertEqual(a.counts['take_profit'],1)
        self.assertTrue(a.permanent_unknown_cash)
        self.assertIsNone(reports['P0','S1','primary']['conclusive_pnl'])

    def test_unknown_prestart_alarm_then_actual_recovery(self):
        unknown=group(None,0,timestamp=None,eligible=False,reasons=('invalid_timestamp',))
        groups=[unknown,group(0,1),group(50,2),group(100,3)]
        hazards=[Hazard(unknown.key,'invalid_timestamp',unknown.identity,None,None)]
        sim,_=self.fixture(groups,hazards)
        first=row(0);first.update(history_valid=False,eligible=False,observed_history=0,segment=1)
        second=row(100);second.update(segment=1)
        reports=sim.run_chunk([first,second],[probability(0),probability(100)],start=0,stop=300000,chunk_id='a')
        a=sim.accounts['P0','S0','primary']
        self.assertEqual(a.counts['entries'],1)
        self.assertFalse(a.recovery_needed)
        self.assertTrue(any('untimed_source_provenance' in line for line in a.journal.records))

    def test_ambiguous_pending_cancels_before_group(self):
        ambiguous=group(0,0,ambiguous=True)
        h=[Hazard(ambiguous.key,'distinct_timestamp_group',ambiguous.identity,0,1)]
        sim,_=self.fixture([ambiguous,group(1,1)],h)
        sim.run_chunk([row(0)],[probability(0)],start=0,stop=300000,chunk_id='a')
        a=sim.accounts['P0','S0','primary']
        self.assertEqual(a.counts.get('entries',0),0)
        self.assertEqual(a.counts['entry_cancelled_quality'],1)
        self.assertEqual(sum(json.loads(line).get('reason')=='distinct_timestamp_group' for line in a.journal.records),1)

    def test_offsession_group_never_becomes_mark_or_fill(self):
        sim,_=self.fixture([group(0,0),group(100,1,'2','2.1',eligible=False),group(1000,2)],end=300000)
        sim.clock=SessionClockMs(0,10000000,[(0,100),(1000,10000000)])
        from fxnn.economic_simulator import ClockAdapter
        for a in sim.accounts.values():a.clock=ClockAdapter(sim.clock)
        sim.run_chunk([row(0,deadline=100)],[probability(0)],start=0,stop=300000,chunk_id='a')
        a=sim.accounts['P0','S0','primary']
        self.assertEqual(a.counts['timeout'],1)
        self.assertEqual(a.cash,Fraction('9999.8'))
        self.assertEqual(a.open_exposure,100)

    def test_funding_before_same_time_exit(self):
        t=79200000
        sim,_=self.fixture([group(t-10,0),group(t,1,'1.5','1.5002')],end=t+100000)
        sim.run_chunk([row(t-10,deadline=t+1)],[probability(t-10)],start=0,stop=t+100000,chunk_id='a',boundaries=[(t,'quarter')])
        a=sim.accounts['P0','S1','primary']
        debit=1000*Fraction('1.10021')*Fraction('.05')/365
        self.assertEqual(a.cash,Fraction('10024.93')-debit)
        self.assertEqual(a.quarterly('quarter','final')['funding_recorded'],debit)
        self.assertEqual(a.funding_recorded,debit)

    def test_checkpoint_rejects_partial_chunk_wrong_binding_and_hash(self):
        sim,path=self.fixture([group(0,0)])
        with self.assertRaises(ValueError):
            sim.run_chunk([row(0)],[probability(0)],start=0,stop=300000,chunk_id='bad',expected_opportunities=2)
        with self.assertRaises(ValueError):export_checkpoint(sim,path/'partial.json')
        clean,path=self.fixture([group(0,0),group(1,1,'1.5','1.5002')])
        clean.run_chunk([row(0)],[probability(0)],start=0,stop=300000,chunk_id='ok')
        sha=export_checkpoint(clean,path/'good.json')
        with self.assertRaises(ValueError):
            import_checkpoint(path/'good.json',clean.index,clean.clock,{'science':'changed'},expected_sha256=sha)
        with self.assertRaises(ValueError):
            import_checkpoint(path/'good.json',clean.index,clean.clock,{'science':'fixture'},expected_sha256='wrong')

    def test_independent_exact_oracle_single_trade_costs(self):
        oracle_path=Path(__file__).parent/'fixtures'/'economic_account_oracle.py'
        spec=importlib.util.spec_from_file_location('private_exact_oracle',oracle_path)
        oracle=importlib.util.module_from_spec(spec);sys.modules[spec.name]=oracle;spec.loader.exec_module(oracle)
        for side,bid,ask in [(1,'1.08','1.0802'),(-1,'1.12','1.1202')]:
            sim,_=self.fixture([group(0,0),group(1,1,bid,ask)])
            reports=sim.run_chunk([row(0,side=side)],[probability(0)],start=0,stop=300000,chunk_id='a')
            for bundle in ('S0','S1','S2'):
                a=oracle.Account(oracle.Clock([(0,10000000)]),bundle)
                a.signal(0,side,'.01',200000);a.quote(0,0,'1.1','1.1002');a.advance(1);a.quote(1,1,bid,ask)
                self.assertEqual(reports['P0',bundle,'primary']['cash'],a.cash)
                self.assertEqual(reports['P0',bundle,'primary']['max_dollar_drawdown'],a.drawdown()[0])


    def test_p1_recovers_1941_new_segment_and_resumes(self):
        bad=group(10,1,eligible=False,reasons=('invalid_quote',))
        groups=[group(0,0),bad,group(11,2,'1.09','1.0902'),group(12,3),group(100,4),group(200,5)]
        h=[Hazard(bad.key,'invalid_quote',bad.identity,10,11)]
        sim,_=self.fixture(groups,h)
        second=row(100,deadline=200);second.update(segment=1)
        sim.run_chunk([row(0),second],[probability(0),probability(100)],start=0,stop=300000,chunk_id='a')
        self.assertEqual(sim.accounts['P0','S0','primary'].counts['entries'],1)
        a=sim.accounts['P1','S0','primary']
        self.assertEqual(a.counts['entries'],2)
        self.assertEqual(a.counts['p1_adverse_liquidation'],1)
        self.assertEqual(a.counts['timeout'],1)
        self.assertFalse(a.recovery_needed)

    def test_bounded_queries_no_touch_many_ticks(self):
        groups=[group(t,i) for i,t in enumerate(range(0,10000))]
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'index'
        m=build_index(groups,[],path,{'fixture':True},block_size=128,min_free=0)
        index=TickIndex(path,m['contract_sha256'],expected_manifest_sha256=digest(path/'manifest.json'))
        self.addCleanup(index.close)
        clock=SessionClockMs(0,10000000,[(0,10000000)])
        sim=Simulator(index,clock,0,100000,{'science':'fixture'})
        sim.run_chunk([row(0,deadline=20000)],[probability(0)],start=0,stop=100000,chunk_id='a')
        self.assertEqual(sim.metrics['individual_groups'],12)
        self.assertEqual(sim.metrics['certified_ranges'],12)
        self.assertLess(index.metrics['scanned_groups'],10000)
        for account in sim.accounts.values():
            self.assertEqual(account.mark_count,10000)


    def test_streamed_checkpoint_flush_and_verified_prefix(self):
        sim,path=self.fixture([group(0,0),group(1,1,'1.5','1.5002')])
        logs={}
        def factory(identity):
            logs.setdefault(identity,[])
            return Journal(logs[identity].append,retain=False)
        streamed=Simulator(sim.index,sim.clock,0,300000,{'science':'fixture'},journal_factory=factory)
        streamed.run_chunk([row(0)],[probability(0)],start=0,stop=100,chunk_id='first')
        with self.assertRaises(ValueError):
            export_checkpoint(streamed,path/'noflush.json')
        flushed=[]
        sha=export_checkpoint(streamed,path/'stream.json',flush_journals=lambda:flushed.append(True))
        self.assertEqual(flushed,[True])
        heads={identity:(a.journal.count,a.journal.head) for identity,a in streamed.accounts.items()}
        lengths={identity:len(rows) for identity,rows in logs.items()}
        with self.assertRaises(ValueError):
            import_checkpoint(path/'stream.json',sim.index,sim.clock,{'science':'fixture'},expected_sha256=sha,journal_factory=factory)
        resumed=import_checkpoint(path/'stream.json',sim.index,sim.clock,{'science':'fixture'},expected_sha256=sha,journal_factory=factory,verified_journal_heads=heads)
        self.assertEqual(lengths,{identity:len(rows) for identity,rows in logs.items()})
        resumed.run_chunk([],[],start=100,stop=300000,chunk_id='second')
        self.assertTrue(all(len(logs[k])>lengths[k] for k in logs))


    def test_economic_span_index_against_dense_nonmonotonic_histories(self):
        rng=random.Random(91);trades=[];histories={};cache={}
        account=SimpleNamespace(trade_intervals=trades,position=None,start=0)
        for n in range(1,65):
            identity=str(n);entry=Key(n*10,4);end=Key(n*10+5,4)
            histories[identity]=rng.randrange(-100,n*10+1)
            trades.append((entry,end,identity))
            for _ in range(4):
                left=rng.randrange(-100,n*10+10);right=left+rng.randrange(1,100)
                hazard=Hazard(EventKey(10000,4,1),'late',(),left,right)
                expected=next((a for a,b,i in trades if histories[i]<right and left<b.time+1),None)
                self.assertEqual(earliest_affected(account,hazard,histories,cache),expected)



if __name__=='__main__':unittest.main(verbosity=2)
