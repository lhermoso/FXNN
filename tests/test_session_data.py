import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import numpy as np

from fxnn.labeling import Candle
from fxnn.session_clock import SessionClock, weekly_fx_clock
from fxnn.session_data import session_labels, session_features, session_events, session_partitions


def candle(minute, price='1.1000', high=None, low=None):
    p=D(price)
    return Candle(datetime.fromtimestamp(minute*60,timezone.utc),p,D(high) if high else p,D(low) if low else p,p)


def reference(candles,clock,horizon,threshold):
    quotes={int(c.timestamp.timestamp()):c for c in candles};endfile=max(quotes)+60
    outputs=[]
    for entry in candles:
        start=int(entry.timestamp.timestamp());deadline=int(clock.deadlines(np.array([start]),horizon)[0])
        for direction in (1,-1):
            target=entry.open+direction*D('.005');stop=entry.open-direction*D('.002')
            miss=0;outcome='censored';end=start;last=entry.close;price=None
            for t in range(start,min(deadline,endfile),60):
                end=t+60
                if not clock.active[(t-clock.first_epoch)//60]:continue
                if t not in quotes:
                    miss+=1
                    if miss>=threshold:break
                    if end==deadline:outcome='timeout';price=last
                    continue
                miss=0;b=quotes[t];last=b.close
                if direction*(b.open-stop)<=0:outcome='stop_loss';price=b.open;end=t;break
                if direction*(b.open-target)>=0:outcome='take_profit';price=target;end=t;break
                tp=b.high>=target if direction==1 else b.low<=target
                sl=b.low<=stop if direction==1 else b.high>=stop
                if tp and sl:outcome='ambiguous';break
                if sl:outcome='stop_loss';price=stop;break
                if tp:outcome='take_profit' if end<deadline else 'boundary';price=target;break
                if end==deadline:outcome='timeout';price=last;break
            outputs.append((outcome,end,price))
    return outputs


class SessionDataTests(unittest.TestCase):
    def test_missing_fourteen_continues_fifteen_censors(self):
        clock=SessionClock(0,np.ones(10000,dtype=bool))
        short,_=session_labels([candle(0),candle(15,'1.1051')],clock)
        long,_=session_labels([candle(0),candle(16,'1.1051')],clock)
        self.assertEqual(short[0].outcome,'take_profit')
        self.assertEqual(long[0].outcome,'censored')
        self.assertEqual(int(long[0].end_time.timestamp()),16*60)
        self.assertEqual(short[1].exit_price,D('1.1051'))

    def test_timeout_before_gap_threshold_does_not_peek_at_eventual_return(self):
        clock=SessionClock(0,np.ones(10000,dtype=bool))
        a,_=session_labels([candle(0),candle(30)],clock,horizon=10)
        b,_=session_labels([candle(0),candle(11)],clock,horizon=10)
        self.assertEqual(a[0],b[0])
        self.assertEqual(a[0].outcome,'timeout')
        self.assertEqual(int(a[0].end_time.timestamp()),600)

    def test_weekend_pause_and_dst(self):
        def epoch(text):return int(datetime.fromisoformat(text).timestamp())
        clock=weekly_fx_clock(epoch('2023-01-01T00:00:00+00:00'),epoch('2024-01-10T00:00:00+00:00'))
        for friday,sunday in [('2023-01-06T21:59:00+00:00','2023-01-08T22:00:00+00:00'),
                              ('2023-07-07T20:59:00+00:00','2023-07-09T21:00:00+00:00')]:
            t0,t1=epoch(friday),epoch(sunday)
            trades,deadlines=session_labels([candle(t0//60),candle(t1//60,'1.1051')],clock)
            self.assertEqual(trades[0].outcome,'take_profit')
            self.assertEqual(int(trades[0].end_time.timestamp()),t1)
            self.assertEqual(clock.elapsed(np.array([t0]),np.array([deadlines[0]])).tolist(),[4320])
            self.assertGreater(deadlines[0]-t0,72*3600)
            self.assertEqual(clock.missing_open_minutes(np.array([t0,t1])).tolist(),[0])

    def test_scalar_reference_random_gaps_and_barriers(self):
        clock=SessionClock(0,np.ones(10000,dtype=bool));rng=np.random.default_rng(31)
        for missing in ([4],[4,5,6],list(range(4,20)),list(range(4,19))):
            price=1.1;source=[]
            for i in range(90):
                price+=rng.normal(0,.0008)
                if i not in missing:
                    p=D(str(price));source.append(Candle(datetime.fromtimestamp(i*60,timezone.utc),p,p+D('.0004'),p-D('.0004'),p))
            actual,_=session_labels(source,clock,horizon=30)
            self.assertEqual([(t.outcome,int(t.end_time.timestamp()),t.exit_price) for t in actual],reference(source,clock,30,15))

    def test_features_ignore_short_gap_reset_long_and_remain_causal(self):
        source=[candle(i,str(1.1+i*.000001)) for i in range(700) if i not in (270,271) and not 400<=i<415]
        stamps=np.array([int(c.timestamp.timestamp()) for c in source])
        clock=SessionClock(0,np.ones(10000,dtype=bool));breaks=clock.gap_breaks(stamps)
        frame=session_features(source,breaks)
        self.assertTrue(frame.valid[np.flatnonzero(stamps==272*60)[0]])
        self.assertFalse(frame.valid[np.flatnonzero(stamps==415*60)[0]])
        changed=[c if int(c.timestamp.timestamp())<350*60 else candle(int(c.timestamp.timestamp())//60,'1.2') for c in source]
        other=session_features(changed,breaks)
        np.testing.assert_array_equal(frame.values[stamps<350*60],other.values[stamps<350*60])
        before=session_events(source,breaks,.0005);after=session_events(changed,breaks,.0005)
        np.testing.assert_array_equal(before[stamps<350*60],after[stamps<350*60])
        self.assertFalse(before[np.flatnonzero(stamps==415*60)[0]])

    def test_partitions_use_true_horizon_and_observed_history_buffer(self):
        clock=SessionClock(0,np.ones(40000,dtype=bool));stamps=np.arange(20000,dtype=np.int64)*60
        stamps=stamps[stamps%120==0]  # Every other minute missing, below threshold.
        def iso(m):return datetime.fromtimestamp(m*60,timezone.utc).isoformat()
        protocol={'development':[iso(0),iso(30000)]}
        fold={'validation_start':iso(10000),'test_start':iso(15000),'test_end':iso(20000)}
        info=clock.deadlines(stamps)
        parts=session_partitions(stamps,info,protocol,fold,clock,stamps)
        history_cut=stamps[stamps<15000*60][-241]
        self.assertTrue(np.all(info[parts['refit']]<history_cut))
        self.assertTrue(np.all(info[parts['test']]<20000*60))
        self.assertLess(history_cut,15000*60-241*60)
        with self.assertRaises(ValueError):session_partitions(stamps,info+60,protocol,fold,clock,stamps)
