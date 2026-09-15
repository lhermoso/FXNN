from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from fxnn.economic_labels import label_one, training_admission
from fxnn.economic_index import build_index, TickIndex
from fxnn.tick_economic_source import EventKey, QuoteGroup, Hazard, digest


def quote(t,bid,ask=None,ordinal=0):
    bid=Decimal(str(bid));ask=bid if ask is None else Decimal(str(ask))
    return QuoteGroup(EventKey(t,4,ordinal),t,'202201','a'*64,ordinal,ordinal,1,
                      bid,bid,ask,ask,(),True,False)


def opportunity(side=1,deadline=100000):
    return dict(id='synthetic',decision_ms=0,side=side,price_volatility=.01,
                earliest_input=-200000000,information_cap_ms=deadline+60000,
                deadline_ms=deadline,reason='',eligible=True)


class LabelTests(unittest.TestCase):
    def evaluate(self,groups,hazards=(),op=None):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'index'
            manifest=build_index(groups,hazards,path,{'synthetic':True},block_size=2,min_free=0)
            with TickIndex(path,manifest['contract_sha256'],expected_manifest_sha256=digest(path/'manifest.json')) as index:
                return label_one(op or opportunity(),index)

    def test_long_and_short_exact_targets(self):
        for side,entry,exit in [(1,quote(0,'1','1.0002'),quote(1,'1.0252')),
                                (-1,quote(0,'1'),quote(1,'.9748','.975'))]:
            with self.subTest(side=side):
                result=self.evaluate([entry,exit],op=opportunity(side))
                self.assertEqual(result['label'],1)
                self.assertEqual(result['information_end_ms'],2)

    def test_stop_is_negative_and_same_timestamp_not_exit(self):
        result=self.evaluate([quote(0,'1',ordinal=0),quote(0,'2',ordinal=1),quote(1,'.98',ordinal=2)])
        self.assertEqual(result['label'],0)
        self.assertEqual(result['reason'],'sl')
        self.assertEqual(result['terminal_key'][0],1)

    def test_entry_expiry_is_half_open(self):
        result=self.evaluate([quote(30000,'1')])
        self.assertIsNone(result['label'])
        self.assertEqual(result['reason'],'entry_expired')

    def test_deadline_quote_is_timeout_not_tp(self):
        result=self.evaluate([quote(0,'1'),quote(100000,'2',ordinal=1)])
        self.assertEqual(result['label'],0)
        self.assertEqual(result['reason'],'timeout')

    def test_timeout_exact_cap_excluded_last_ms_included(self):
        for time,expected in [(159999,0),(160000,None)]:
            result=self.evaluate([quote(0,'1'),quote(time,'1',ordinal=1)])
            self.assertEqual(result['label'],expected)
            if expected is not None:self.assertEqual(result['information_end_ms'],160000)

    def test_hazard_later_same_time_preserves_entry_censors_label(self):
        hazard=Hazard(EventKey(0,4,1),'chronology',(),-60000,60000)
        result=self.evaluate([quote(0,'1'),quote(1,'2',ordinal=2)],[hazard])
        self.assertEqual(result['entry_ms'],0)
        self.assertIsNone(result['label'])
        self.assertEqual(result['reason'],'censored:chronology')

    def test_timer_before_return_cannot_be_repaired(self):
        hazard=Hazard(EventKey(60000,1,0),'quote_absence',())
        result=self.evaluate([quote(0,'1'),quote(60000,'2',ordinal=1)],[hazard])
        self.assertIsNone(result['label'])
        self.assertEqual(result['reason'],'censored:quote_absence')

    def test_training_integrity_strict_cutoff_and_full_history(self):
        cutoff=300000000
        op=opportunity();op['information_cap_ms']=1000000
        label=dict(opportunity_id='synthetic',label=1,information_cap_ms=1000000,
                   earliest_input_ms=-200000000,information_end_ms=1001)
        bars=list(range(0,cutoff,60000))
        for disclosure,expected in [(cutoff-1,[]),(cutoff,[0]),(cutoff+1,[0])]:
            hazard=Hazard(EventKey(disclosure,4,0),'chronology',(),-60000,0)
            admitted,_=training_admission([op],[label],[hazard],cutoff,bars)
            self.assertEqual(admitted,expected)

    def test_full_cap_purge_not_early_exit(self):
        cutoff=300000000;bars=list(range(0,cutoff,60000))
        boundary=bars[-1942]
        for cap,expected in [(boundary-1,[0]),(boundary,[])]:
            op=opportunity();op['information_cap_ms']=cap
            label=dict(opportunity_id='synthetic',label=1,information_cap_ms=cap,
                       earliest_input_ms=-100000,information_end_ms=2)
            self.assertEqual(training_admission([op],[label],[],cutoff,bars)[0],expected)


if __name__=='__main__':unittest.main()
