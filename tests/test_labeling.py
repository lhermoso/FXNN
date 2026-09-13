import itertools
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from fxnn.labeling import Candle, Config, Trade, label_trades, select_non_overlapping


START = datetime(2026, 1, 5, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


def candle(i, o="1.1000", h="1.1010", l="1.0990", c="1.1000"):
    return Candle(START + i * MINUTE, *map(D, (o, h, l, c)))


def winner(start, end, pips=50):
    return Trade(start, "long", START + start * MINUTE, START + end * MINUTE,
                 D("1.1"), D("1.105"), "take_profit", D(pips))


class LabelingTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(D("0.0001"))

    def test_long_and_short(self):
        long = label_trades([candle(0, h="1.1050")], self.config)
        self.assertEqual(long[0].outcome, "take_profit")
        self.assertEqual(long[0].pnl_pips, D(50))
        self.assertEqual(long[1].outcome, "stop_loss")
        short = label_trades([candle(0, l="1.0950")], self.config)
        self.assertEqual(short[1].outcome, "take_profit")
        self.assertEqual(short[1].pnl_pips, D(50))

    def test_stop_precedes_later_target(self):
        trades = label_trades([candle(0, l="1.0980"), candle(1, h="1.1050")], self.config)
        self.assertEqual(trades[0].outcome, "stop_loss")
        self.assertEqual(trades[0].pnl_pips, D(-20))

    def test_same_bar_ambiguous(self):
        trade = label_trades([candle(0, h="1.1050", l="1.0980")], self.config)[0]
        self.assertEqual(trade.outcome, "ambiguous")
        self.assertIsNone(trade.pnl_pips)

    def test_gap_stop_slippage(self):
        trade = label_trades([candle(0), candle(1, o="1.0970", h="1.1050", l="1.0960")], self.config)[0]
        self.assertEqual(trade.outcome, "stop_loss")
        self.assertEqual(trade.pnl_pips, D(-30))
        self.assertEqual(trade.end_time, START + MINUTE)

    def test_gap_target_known_before_low(self):
        trade = label_trades([candle(0), candle(1, o="1.1060", h="1.1070", l="1.0970")], self.config)[0]
        self.assertEqual(trade.outcome, "take_profit")
        self.assertEqual(trade.pnl_pips, D(50))

    def test_timeout_boundary_and_censor(self):
        config = Config(D("0.0001"), max_hold=2 * MINUTE)
        self.assertEqual(label_trades([candle(0), candle(1)], config)[0].outcome, "timeout")
        self.assertEqual(label_trades([candle(0), candle(1, h="1.1050")], config)[0].outcome, "boundary")
        self.assertEqual(label_trades([candle(0)], config)[0].outcome, "censored")
        self.assertEqual(label_trades([candle(0), candle(2, h="1.1050")], config)[0].outcome, "censored")

    def test_invalid_inputs(self):
        for pip in ("0", "-1", "NaN", "Infinity"):
            with self.assertRaises(ValueError):
                Config(D(pip))
        with self.assertRaises(ValueError):
            Config(D("0.0001"), max_hold=timedelta(seconds=90))
        for data in ([candle(0), candle(0)], [candle(1), candle(0)], [candle(0, h="1.09")],
                     [Candle(START.replace(tzinfo=None), D(1), D(1), D(1), D(1))]):
            with self.assertRaises(ValueError):
                label_trades(data, self.config)

    def test_jpy_pip(self):
        bar = Candle(START, D(150), D("150.5"), D("149.9"), D(150))
        self.assertEqual(label_trades([bar], Config(D("0.01")))[0].pnl_pips, D(50))

    def test_global_selection_beats_long_interval(self):
        trades = [winner(0, 10), winner(0, 3), winner(3, 6), winner(6, 9)]
        self.assertEqual(select_non_overlapping(trades), trades[1:])

    def test_equal_profit_prefers_short_exposure(self):
        trades = [winner(0, 10), winner(1, 3)]
        self.assertEqual(select_non_overlapping(trades), [trades[1]])

    def test_interval_selection_matches_exhaustive_oracle(self):
        trades = [winner(0, 4, 40), winner(1, 3, 30), winner(3, 6, 25),
                  winner(4, 7, 50), winner(6, 8, 20), winner(7, 10, 30)]
        def score(rows):
            return (sum((t.pnl_pips for t in rows), D(0)),
                    -sum((t.end_time - t.entry_time for t in rows), timedelta(0)))
        valid = []
        for size in range(len(trades) + 1):
            for subset in itertools.combinations(trades, size):
                ordered = sorted(subset, key=lambda t: t.entry_time)
                if all(a.end_time <= b.entry_time for a, b in zip(ordered, ordered[1:])):
                    valid.append(score(ordered))
        self.assertEqual(score(select_non_overlapping(trades)), max(valid))


if __name__ == "__main__":
    unittest.main()
