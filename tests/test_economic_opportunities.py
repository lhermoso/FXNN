import copy
from decimal import Decimal, localcontext
from datetime import datetime, timezone
import math
import unittest

import numpy as np
from fxnn.economic_opportunities import OpportunityBuilder, NAMES
from fxnn.economic_clock import SessionClockMs
from fxnn.tick_economic_source import BidBar
from fxnn.features import build_features, orient_features
from fxnn.labeling import Candle
from fxnn.session_clock import weekly_fx_clock
from fxnn.volatility_estimator import causal_volatility


def bar(i, close=None):
    c = Decimal(str(1.2+.001*math.sin(i/13)+.0002*math.cos(i/71))) if close is None else close
    return BidBar(i*60000,(i+1)*60000,c,c+Decimal('.0001'),c-Decimal('.0001'),c,True,1)


class OpportunitiesTest(unittest.TestCase):
    def setUp(self):
        self.clock = SessionClockMs(0,10000*60000,[(0,10000*60000)])

    def build(self, n=2000):
        result=OpportunityBuilder(self.clock)
        for i in range(n):
            result.on_bar(bar(i))
        return result

    def test_frozen_feature_formulas_previous_bars(self):
        builder=self.build()
        result=builder.decision(2000*60000,self.clock.stop)
        candles=[Candle(datetime.fromtimestamp(i*60,timezone.utc),
                        b.open,b.high,b.low,b.close) for i in range(2001) for b in [bar(i)]]
        frame=build_features(candles)
        expected=orient_features(frame,[2000],[result['side']])[0]
        self.assertEqual(list(NAMES),frame.names)
        # New tick-derived dataset uses local sums; old global prefix cancellation
        # is not an inherited bitwise requirement. Formulas agree within rounding.
        np.testing.assert_allclose(result['X'],expected,rtol=5e-5,atol=1e-8)
        # Independent high-precision local variance verifies the new computation;
        # the old cumulative second moment loses ~1e-5 relative precision here.
        with localcontext() as context:
            context.prec=70
            values=[Decimal.from_float(float(bar(i).close)) for i in range(1995,2000)]
            mean=sum(values)/5
            std=(sum((v-mean)**2 for v in values)/5).sqrt()
            z=Decimal(result['side'])*(values[-1]-mean)/max(std,Decimal('.00001'))
            self.assertAlmostEqual(result['X'][3],float(z),places=10)
        self.assertTrue(result['eligible'])

    def test_sigma_matches_frozen_continuous_estimator(self):
        builder=self.build()
        result=builder.decision(2000*60000,self.clock.stop)
        class ClockAdapter:
            active=np.ones(10001,dtype=bool)
            prefix=np.arange(10002)
            def indices(self,stamps):return stamps//60
            def gap_breaks(self,stamps,minutes):return np.zeros(len(stamps),dtype=bool)
        closes=[float(bar(i).close) for i in range(2001)]
        old=causal_volatility(closes,np.arange(2001,dtype=np.int64)*60,ClockAdapter(),
                              np.zeros(2001,dtype=bool))
        self.assertAlmostEqual(result['sigma'],old['sigma'][2000],places=13)
        self.assertEqual(result['valid_returns'],500)
        self.assertLessEqual(result['earliest_input'],old['history_start_index'][2000]*60000)

    def test_missing_minute_calendar_and_no_future_price(self):
        builder=self.build()
        before=copy.deepcopy(builder.decision(2000*60000,self.clock.stop))
        missing=builder.decision(2001*60000,self.clock.stop)
        self.assertEqual(before['X'][:23],missing['X'][:23])
        self.assertNotEqual(before['X'][23:25],missing['X'][23:25])
        builder.on_bar(bar(2001,Decimal('12')))
        self.assertEqual(before['X'][:23],missing['X'][:23])
        with self.assertRaisesRegex(ValueError,'precede'):
            builder.decision(2001*60000,self.clock.stop)

    def test_quality_warmup_cannot_be_shortened_by_gap(self):
        builder=self.build()
        builder.reset('chronology',integrity=True)
        for i in range(2000,2500):builder.on_bar(bar(i))
        builder.reset('missing_15_open_minutes',integrity=False)
        for i in range(2600,4539):builder.on_bar(bar(i))
        self.assertFalse(builder.decision(4539*60000,self.clock.stop)['history_valid'])
        builder.on_bar(bar(4539));builder.on_bar(bar(4540))
        self.assertTrue(builder.decision(4541*60000,self.clock.stop)['history_valid'])
        builder.reset('missing_15_open_minutes',integrity=False)
        self.assertEqual(builder.required,241)

    def test_gap_reset_before_returning_quote(self):
        builder=self.build()
        self.assertTrue(builder.decision(2014*60000,self.clock.stop)['history_valid'])
        self.assertFalse(builder.decision(2015*60000,self.clock.stop)['history_valid'])
        self.assertEqual(len(builder.bars),0)

    def test_exact_primary_beyond_float_precision_and_zero_sigma(self):
        builder=OpportunityBuilder(self.clock)
        for i in range(2000):
            builder.on_bar(bar(i,Decimal('1.0000000000000000000000000001') if i==1999 else Decimal('1')))
        result=builder.decision(2000*60000,self.clock.stop)
        self.assertEqual(result['side'],1)
        self.assertFalse(result['volatility_valid'])
        self.assertFalse(result['eligible'])

    def test_calendar_only_veto_and_all_minutes_retained(self):
        builder=self.build()
        decision=2000*60000
        cap=decision+4321*60000
        row=builder.decision(decision,cap)
        self.assertFalse(row['eligible'])
        self.assertFalse(row['calendar_eligible'])
        self.assertEqual(row['reason'],'evaluation_end')
        self.assertTrue(builder.decision(decision,cap+1)['eligible'])
        self.assertEqual(row['id'],f'economic_ticks_v1:{decision}')

    def test_invalid_bar_resets_without_rewriting_prior(self):
        builder=self.build()
        prior=builder.decision(2000*60000,self.clock.stop)
        b=bar(2000)
        builder.on_bar(BidBar(b.start,b.end,b.open,b.high,b.low,b.close,False,1))
        after=builder.decision(2001*60000,self.clock.stop)
        self.assertTrue(prior['eligible'])
        self.assertFalse(after['eligible'])
        self.assertEqual(builder.required,1941)

    def test_authorized_warmup_exact_resume_without_labels(self):
        builder=self.build(3000)
        prior=builder.decision(3000*60000,self.clock.stop)
        state=builder.export_history()
        resumed=OpportunityBuilder.from_history(self.clock,state,3000*60000)
        self.assertEqual(prior,resumed.decision(3000*60000,self.clock.stop))
        for i in range(3000,3005):
            builder.on_bar(bar(i));resumed.on_bar(bar(i))
            self.assertEqual(builder.decision((i+1)*60000,self.clock.stop),
                             resumed.decision((i+1)*60000,self.clock.stop))
        with self.assertRaisesRegex(ValueError,'cutoff'):
            OpportunityBuilder.from_history(self.clock,state,2999*60000)


if __name__=='__main__':unittest.main()
