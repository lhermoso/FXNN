import random
import unittest
from datetime import timedelta
from decimal import Decimal as D

from fxnn.labeling import Candle, Config, label_trades, label_trades_reference
from test_labeling import START, MINUTE, candle


class IndexedTests(unittest.TestCase):
    def test_random_paths_match_independent_scanner(self):
        rng=random.Random(42)
        for case in range(40):
            rows=[]; minute=0; price=110000
            for _ in range(120):
                minute += 1 if rng.random() > .03 else 5
                price += rng.randint(-40,40)
                close=price+rng.randint(-70,70)
                low=min(price,close)-rng.randint(0,80)
                high=max(price,close)+rng.randint(0,80)
                rows.append(Candle(START+minute*MINUTE,*(D(v)/100000 for v in (price,high,low,close))))
            config=Config(D('.0001'),D(rng.choice((5,10,50))),D(rng.choice((2,20))),max_hold=rng.choice((1,5,30,200))*MINUTE)
            self.assertEqual(label_trades(rows,config),label_trades_reference(rows,config),case)

    def test_stop_then_target_is_hard_negative_not_winner(self):
        rows=[candle(0,l='1.0980'),candle(1,h='1.1050')]
        trade=label_trades(rows,Config(D('.0001')))[0]
        self.assertEqual(trade.outcome,'stop_loss')
        self.assertEqual(trade.pnl_pips,D(-20))
        self.assertEqual(trade.post_stop_target_status,'reached')
        self.assertEqual(trade.target_after_stop_time,START+2*MINUTE)

    def test_short_hard_negative_and_gap_censor(self):
        rows=[candle(0,h='1.1020'),candle(1,l='1.0950')]
        config=Config(D('.0001'))
        trade=label_trades(rows,config)[1]
        self.assertEqual(trade.outcome,'stop_loss')
        self.assertEqual(trade.post_stop_target_status,'reached')
        rows=[rows[0],candle(2,l='1.0950')]
        self.assertEqual(label_trades(rows,config)[1].post_stop_target_status,'censored')

    def test_same_candle_stop_open_then_target_is_known(self):
        rows=[candle(0),candle(1,o='1.0970',h='1.1050',l='1.0960')]
        trade=label_trades(rows,Config(D('.0001')))[0]
        self.assertEqual(trade.outcome,'stop_loss')
        self.assertEqual(trade.post_stop_target_status,'reached')

    def test_target_after_deadline_not_hard_negative(self):
        rows=[candle(0,l='1.0980'),candle(1),candle(2,h='1.1050')]
        trade=label_trades(rows,Config(D('.0001'),max_hold=2*MINUTE))[0]
        self.assertEqual(trade.post_stop_target_status,'not_reached')

    def test_empty_series(self):
        self.assertEqual(label_trades([],Config(D('.0001'))),[])
