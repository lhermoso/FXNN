import unittest
import json
from fractions import Fraction as F
from fxnn.economic_account import Account, Key, PHASE, Opportunity, Quote, Journal, PriceSummary, make_portfolios, rational, economic_diagnostics, Event, replay_events, SegmentCertificate


class Clock:
    """Tiny standalone synthetic calendar; no production foundation dependency."""
    def __init__(self, intervals=((0, 10000000),)):
        self.intervals = intervals
    def active(self, t):
        return any(a <= t < b for a, b in self.intervals)
    def coordinate(self, t):
        return sum(max(0, min(t, b)-a) for a,b in self.intervals if a<t)
    def inverse(self, origin, duration):
        if duration == 0:
            return origin
        for a,b in self.intervals:
            left=max(a,origin)
            if left >= b:
                continue
            if duration <= b-left:
                return left+duration
            duration -= b-left
        raise ValueError('calendar exhausted')


def q(t, bid='1.1', ask='1.1002', **kwargs):
    return Quote(t, rational(bid), rational(ask), f'q{t}', **kwargs)


def op(t=0, side=1, deadline=100000, **kwargs):
    return Opportunity(f'o{t}', side, rational('.01'), deadline, **kwargs)


class AccountTests(unittest.TestCase):
    def make(self, bundle='S0', policy='P0', arm='primary', end=1000000):
        a=Account(Clock(),0,end,policy=policy,bundle=bundle,arm=arm)
        a.process(Key(0,0),'snapshot','start')
        return a
    def enter(self, a, side=1, deadline=100000):
        a.process(Key(0,3),'decision',op(side=side,deadline=deadline,probability=F(1,2)))
        a.process(Key(0,4),'source',q(0))
    def finish(self,a):
        a.process(Key(a.end,0),'snapshot','final')
        return a.process(Key(a.end,5),'end')

    def test_costs_paired_both_sides(self):
        for side in (-1,1):
            for bundle,entry,roundtrip in [('S0','.2','.2'),('S1','.245','.29'),('S2','.32','.44')]:
                a=self.make(bundle);self.enter(a,side,deadline=10)
                self.assertEqual(a._equity(0),10000-rational(entry))
                a.process(Key(10,4),'source',q(10))
                self.assertEqual(a.cash,10000-rational(roundtrip))
                self.assertEqual(a.counts['timeout'],1)
                self.assertEqual(self.finish(a)['conclusive_pnl'],-rational(roundtrip))

    def test_tp_cap_before_mark(self):
        for side,bid,ask in [(1,'1.5','1.5002'),(-1,'.7','.7002')]:
            a=self.make('S1');self.enter(a,side)
            a.process(Key(1,4),'source',q(1,bid,ask))
            self.assertEqual(a.cash,rational('10024.93'))
            self.assertEqual(a.peak_equity,a.cash)
            self.assertEqual(a.max_dollar_drawdown,rational('.245'))

    def test_market_stop_gap_and_exact_touch(self):
        for side,bid,ask in [(1,'1.08','1.0802'),(-1,'1.12','1.1202')]:
            a=self.make('S1');self.enter(a,side)
            entry=a.position.entry
            a.process(Key(1,4),'source',q(1,bid,ask))
            fill=rational(bid if side==1 else ask)-side*rational('.00001')
            self.assertEqual(a.cash,10000+1000*side*(fill-entry)-rational('.07'))
            self.assertEqual(a.counts['stop'],1)

    def test_expiry30_gap60_and_source_boundaries(self):
        a=self.make();a.process(Key(0,3),'decision',op())
        a.process(Key(30000,4),'source',q(30000))
        self.assertIsNone(a.position);self.assertEqual(a.counts['entry_expired'],1)
        for policy in ('P0','P1'):
            a=self.make(policy=policy);self.enter(a)
            a.process(Key(60000,4),'source',q(60000))
            self.assertEqual(a.hazard_key,Key(60000,2));self.assertIsNotNone(a.position)
            a.process(Key(60001,4),'source',q(60001,'1.08','1.0802'))
            self.assertEqual(a.position is None,policy=='P1')
            self.assertIsNone(a.report()['max_dollar_drawdown'])

    def test_p1_reentry_after_liquidation_and_recovery(self):
        a=self.make('S1','P1');self.enter(a)
        a.process(Key(1,4),'quality',dict(reason='invalid',requires_recovery=True))
        a.process(Key(2,4),'source',q(2,'1.09','1.0902'))
        a.process(Key(3,3),'decision',op(3))
        self.assertEqual(a.blocked['recovery_1941_required'],1)
        a.process(Key(3,4),'recovery',1941)
        a.process(Key(4,3),'decision',op(4))
        a.process(Key(4,4),'source',q(4))
        self.assertEqual(a.counts['entries'],2)
        self.assertIsNone(a._equity(4));self.assertIsNotNone(a._equity(4,scenario=True))

    def test_p0_conditional_funding_p1_cash_scenario(self):
        for policy in ('P0','P1'):
            a=self.make('S1',policy);self.enter(a)
            entry=a.position.entry;known=a.cash
            a.process(Key(1,4),'quality',dict(reason='bad',requires_recovery=False))
            a.process(Key(2,1),'funding',3)
            debit=1000*entry*F(1,20)*3/365
            self.assertEqual(a.known_cash,known)
            self.assertEqual(a.conditional_funding,debit)
            self.assertEqual(a.cash,known if policy=='P0' else known-debit)
            self.assertIsNone(self.finish(a)['scenario_pnl'])

    def test_quarter_boundary_funding_then_exit(self):
        a=self.make('S1');self.enter(a,deadline=100)
        a.process(Key(50,4),'source',q(50,'1.11021','1.11041'))
        before=a.cash+10;entry=a.position.entry
        snap=a.process(Key(100,0),'snapshot','quarter')
        self.assertEqual(snap.conclusive_equity,before)
        a.process(Key(100,1),'funding',3)
        a.process(Key(100,4),'source',q(100,'1.11222','1.11242'))
        self.finish(a)
        self.assertEqual(a.quarterly('quarter','final')['conclusive_pnl'],2-1000*entry*F(1,20)*3/365-F(7,200))
        self.assertEqual(a.wall_exposure,100)

    def test_retroactive_taint_preserves_journal(self):
        a=self.make('S1');self.enter(a)
        a.process(Key(1,4),'source',q(1,'1.5','1.5002'))
        original=list(a.transactions);logs=tuple(a.journal.records)
        a.process(Key(2,4),'quality',dict(reason='late',requires_recovery=True,affected_from=Key(0,4)))
        self.assertEqual(a.transactions,original)
        self.assertEqual(tuple(a.journal.records[:len(logs)]),logs)
        self.assertEqual(a.known_cash,10000)
        self.assertTrue(a.permanent_unknown_cash)
        self.assertIsNone(self.finish(a)['conclusive_pnl'])

    def test_no_same_time_exit_and_no_retroactive_reentry(self):
        a=self.make();self.enter(a)
        a.process(Key(0,4,1),'source',q(0,'1.5','1.5002'))
        self.assertIsNotNone(a.position)
        a.process(Key(1,3),'decision',op(1))
        a.process(Key(1,4),'source',q(1,'1.5','1.5002'))
        self.assertEqual(a.blocked['occupied_or_unresolved'],1)
        self.assertEqual(a.counts['entries'],1)

    def test_source_highwater_preserved_p1(self):
        a=self.make(policy='P1');a.process(Key(100,3),'decision',op(100))
        for ordinal,source in enumerate([100,99,100]):
            a.process(Key(100,4,ordinal),'source',q(source))
        self.assertEqual(a.hazard_key,Key(100,4,1))
        a.process(Key(101,4),'source',q(101))
        self.assertEqual(a.counts['p1_adverse_liquidation'],1)

    def test_ambiguous_pending_cancel_and_p1_adverse(self):
        a=self.make();a.process(Key(0,3),'decision',op())
        a.process(Key(0,4),'source',q(0,ambiguous=True,bid_min=F(1),ask_max=F(2)))
        self.assertIsNone(a.pending);self.assertIsNone(a.position)
        a=self.make(policy='P1');self.enter(a)
        a.process(Key(1,4),'quality',dict(reason='gap',requires_recovery=False))
        a.process(Key(2,4),'source',q(2,ambiguous=True,bid_min=F(1),ask_max=F(2)))
        self.assertEqual(a.cash,rational('9899.8'))

    def test_all12_arms_threshold_and_final_window(self):
        accounts=make_portfolios(Clock(),0,1000000)
        self.assertEqual(len(accounts),12)
        for identity,a in accounts.items():
            a.process(Key(0,3),'decision',op(probability=F(49,100)))
            a.process(Key(0,4),'source',q(0))
            self.assertEqual(a.position is None,identity[2]=='filtered')
        a=self.make();a.process(Key(0,3),'decision',op(deadline=940000))
        self.assertEqual(a.blocked['final_window'],1)

    def test_snapshot_stale_and_flat(self):
        a=self.make();self.enter(a)
        self.assertIsNotNone(a.process(Key(59999,0),'snapshot','fresh').conclusive_equity)
        self.assertIsNone(a.process(Key(60000,0),'snapshot','stale').conclusive_equity)
        flat=self.make();self.assertEqual(flat.process(Key(60000,0),'snapshot','flat').conclusive_equity,10000)

    def test_segment_dense_equivalence_both_directions(self):
        for side in (-1,1):
            dense=self.make();fast=self.make();self.enter(dense,side);self.enter(fast,side)
            pairs=[('1.102','1.1022'),('1.098','1.0982'),('1.105','1.1052'),('1.103','1.1032')]
            values=[]
            for t,(bid,ask) in enumerate(pairs,1):
                dense.process(Key(t,4),'source',q(t,bid,ask));values.append(rational(bid if side==1 else ask))
            summary=PriceSummary(values[0],values[-1],min(values),max(values),max(values[i]-values[j] for i in range(4) for j in range(i,4)),max(values[j]-values[i] for i in range(4) for j in range(i,4)),4)
            fast.process(Key(4,4),'segment',dict(summary=summary,last_source_time=4,last_pair=pairs[-1],certified_start=Key(1,4)))
            self.assertEqual(fast._equity(4),dense._equity(4))
            self.assertEqual(fast.max_dollar_drawdown,dense.max_dollar_drawdown)
            self.assertEqual(fast.peak_equity,dense.peak_equity)

    def test_flat_gap_blocks_exact_boundary_then_recovers(self):
        a=self.make();a.process(Key(0,4),'source',q(0))
        a.process(Key(60000,3),'decision',op(60000))
        self.assertEqual(a.blocked['awaiting_strict_quality_return'],1)
        a.process(Key(60000,4),'source',q(60000))
        self.assertEqual(a.gap_boundary,60000)
        a.process(Key(60001,4),'source',q(60001))
        a.process(Key(60002,3),'decision',op(60002))
        a.process(Key(60002,4),'source',q(60002))
        self.assertEqual(a.counts['entries'],1)

    def test_dense_all_scenarios_unavailable_not_positive_diagnostic(self):
        accounts=make_portfolios(Clock(),0,1000000)
        events=[Event(Key(0,0),'snapshot','start'),
                Event(Key(0,3),'decision',op(model_available=False)),
                Event(Key(0,4),'source',q(0)),
                Event(Key(1,4),'source',q(1,'1.5','1.5002')),
                Event(Key(1000000,0),'snapshot','final'),Event(Key(1000000,5),'end')]
        reports=replay_events(accounts,events)
        self.assertEqual(len(reports),12)
        for policy in ('P0','P1'):
            filtered=accounts[policy,'S1','filtered']
            self.assertFalse(filtered.report()['arm_model_available'])
            self.assertEqual(filtered.report()['conclusive_pnl'],0)
            self.assertIsNone(economic_diagnostics(accounts,[('start','final')])[policy]['annual_s1_positive_and_improves'])

    def test_offsession_and_weekend_deadline(self):
        a=Account(Clock(((0,100),(1000,10000000))),0,1000000,policy='P0',bundle='S0',arm='primary')
        a.process(Key(0,3),'decision',op(deadline=100));a.process(Key(0,4),'source',q(0))
        a.process(Key(100,4),'source',q(100,'2','2.1'))
        self.assertEqual(a.last_source_time,0)
        self.assertEqual(a.state,'PENDING_TIMEOUT_EXIT')
        a.process(Key(1000,4),'source',q(1000))
        self.assertEqual(a.counts['timeout'],1)
        self.assertEqual(a.open_exposure,100)
        self.assertEqual(a.wall_exposure,1000)

    def test_funding_before_entry_no_debit(self):
        a=self.make('S1');a.process(Key(0,1),'funding',3)
        self.enter(a)
        self.assertEqual(a.funding_recorded,0)

    def test_retro_taint_current_position_cannot_restore_cash(self):
        a=self.make(policy='P1');self.enter(a)
        a.process(Key(1,4),'quality',dict(reason='old_history',requires_recovery=True,affected_from=Key(0,0)))
        self.assertIsNotNone(a.hazard_key)
        a.process(Key(2,4),'source',q(2))
        self.assertIsNone(a.position)
        a.process(Key(3,4),'recovery',1941)
        a.process(Key(4,3),'decision',op(4))
        self.assertEqual(a.blocked['unknown_equity'],1)
        self.assertIsNone(a._equity(4,scenario=True))

    def test_invalid_segment_summary_rejected(self):
        a=self.make();self.enter(a)
        summary=PriceSummary(F(1),F(1),F(1),F(1),F(0),F(0),1)
        with self.assertRaises(ValueError):
            a.process(Key(1,4),'segment',dict(summary=summary,last_source_time=1,last_pair=('1.1','1.1002'),certified_start=Key(1,4)))

    def test_long_certified_segment_does_not_invent_absence(self):
        dense=self.make();fast=self.make();self.enter(dense);self.enter(fast)
        for t in (30000,60000,90000):
            dense.process(Key(t,4),'source',q(t))
        certificate=SegmentCertificate(Key(30000,4),Key(90000,4),30000,90000,59999,True,'index-proof','q30000','q90000')
        summary=PriceSummary(rational('1.1'),rational('1.1'),rational('1.1'),rational('1.1'),F(0),F(0),3)
        fast.process(Key(90000,4),'segment',dict(summary=summary,last_source_time=90000,last_pair=('1.1','1.1002'),certified_start=Key(30000,4),certificate=certificate))
        self.assertEqual(fast.state,'OPEN')
        self.assertEqual(fast._equity(90000),dense._equity(90000))
        self.assertEqual(fast.max_dollar_drawdown,dense.max_dollar_drawdown)
        self.assertEqual(fast.next_timer(),dense.next_timer())

    def test_certified_flat_refresh_and_missing_initial_gap_rejected(self):
        a=self.make();a.process(Key(0,4),'source',q(0))
        cert=SegmentCertificate(Key(30000,4),Key(90000,4),30000,90000,59999,True,'proof','q30','q90')
        a.process(Key(90000,4),'refresh',dict(certificate=cert,last_pair=('1.1','1.1002')))
        self.assertEqual(a.last_source_time,90000)
        self.assertIsNone(a.gap_boundary)
        b=self.make();b.process(Key(0,4),'source',q(0))
        bad=SegmentCertificate(Key(60000,4),Key(90000,4),60000,90000,59999,True,'proof','q60','q90')
        with self.assertRaises(ValueError):
            b.process(Key(90000,4),'refresh',dict(certificate=bad,last_pair=('1.1','1.1002')))

    def test_no_uncertainty_return_skip(self):
        a=self.make(policy='P1');self.enter(a)
        a.process(Key(1,4),'quality',dict(reason='gap',requires_recovery=False))
        cert=SegmentCertificate(Key(2,4),Key(3,4),2,3,59999,True,'proof','q2','q3')
        with self.assertRaises(ValueError):
            a.process(Key(3,4),'refresh',dict(certificate=cert,last_pair=('1.1','1.1002')))
        with self.assertRaises(ValueError):
            a.process(Key(3,4),'quiescent')

    def test_streaming_journal_and_key_rejection(self):
        lines=[];j=Journal(lines.append,retain=False)
        a=Account(Clock(),0,1000000,policy='P0',bundle='S0',arm='primary',journal=j)
        a.process(Key(0,3),'decision',op());self.assertIsNone(j.records)
        self.assertEqual(json.loads(lines[-1])['sequence'],1)
        with self.assertRaises(ValueError):
            a.process(Key(0,3),'decision',op())


if __name__=='__main__':
    unittest.main(verbosity=2)
