"""First barrier touch queries using range min/max trees, without price rounding."""
from decimal import Decimal

from .labeling import Candle, Config, Trade, validate_candles


class BarrierIndex:
    def __init__(self, candles):
        size = 1
        while size < len(candles):
            size *= 2
        self.size = size
        self.low = [Decimal("Infinity")] * (2 * size)
        self.high = [Decimal("-Infinity")] * (2 * size)
        for i, candle in enumerate(candles, size):
            self.low[i], self.high[i] = candle.low, candle.high
        for i in range(size-1, 0, -1):
            self.low[i] = min(self.low[2*i], self.low[2*i+1])
            self.high[i] = max(self.high[2*i], self.high[2*i+1])

    def first_touch(self, left, right, lower, upper):
        """First candle in [left,right) touching either price bound, else None."""
        def visit(node, start, end):
            if end <= left or start >= right:
                return None
            if self.low[node] > lower and self.high[node] < upper:
                return None
            if end-start == 1:
                return start
            middle = (start+end)//2
            found = visit(2*node, start, middle)
            return found if found is not None else visit(2*node+1, middle, end)
        return visit(1, 0, self.size)


def label_indexed(candles: list[Candle], config: Config) -> list[Trade]:
    validate_candles(candles, config)
    n = len(candles)
    if not n:
        return []
    tree = BarrierIndex(candles)
    # Stop a search at the first missing bar, never bridge a data gap.
    run_end = [n] * n
    for i in range(n-2, -1, -1):
        run_end[i] = run_end[i+1] if candles[i+1].timestamp-candles[i].timestamp == config.bar_duration else i+1
    horizon = config.max_hold // config.bar_duration
    tp_distance = config.take_profit_pips * config.pip_size
    sl_distance = config.stop_loss_pips * config.pip_size
    results = []
    for i, entry in enumerate(candles):
        right = min(run_end[i], i+horizon)
        deadline = entry.timestamp + config.max_hold
        for side, direction in (("long", 1), ("short", -1)):
            target = entry.open + direction*tp_distance
            stop = entry.open - direction*sl_distance
            if min(target, stop) <= 0:
                raise ValueError("Configured barriers produce non-positive prices")
            hit = tree.first_touch(i, right, min(target,stop), max(target,stop))
            price = None
            if hit is None:
                last = candles[right-1]
                end = last.timestamp + config.bar_duration
                outcome = "timeout" if end == deadline else "censored"
                if outcome == "timeout":
                    price = last.close
            else:
                bar = candles[hit]
                end = bar.timestamp + config.bar_duration
                stop_at_open = direction*(bar.open-stop) <= 0
                target_at_open = direction*(bar.open-target) >= 0
                if stop_at_open or target_at_open:
                    end = bar.timestamp
                    outcome = "stop_loss" if stop_at_open else "take_profit"
                    price = bar.open if stop_at_open else target
                else:
                    target_hit = bar.high >= target if direction == 1 else bar.low <= target
                    stop_hit = bar.low <= stop if direction == 1 else bar.high >= stop
                    if target_hit and stop_hit:
                        outcome = "ambiguous"
                    elif stop_hit:
                        outcome, price = "stop_loss", stop
                    else:
                        outcome = "take_profit" if end < deadline else "boundary"
                        price = target
            pnl = None if price is None else direction*(price-entry.open)/config.pip_size
            post_status, post_time = None, None
            if outcome == "stop_loss":
                lower = Decimal("-Infinity") if direction == 1 else target
                upper = target if direction == 1 else Decimal("Infinity")
                later_hit = tree.first_touch(hit, right, lower, upper)
                if later_hit is None:
                    post_status = "not_reached" if candles[right-1].timestamp+config.bar_duration == deadline else "censored"
                else:
                    later = candles[later_hit]
                    at_open = direction*(later.open-target) >= 0
                    post_time = later.timestamp if at_open else later.timestamp+config.bar_duration
                    post_status = "reached" if post_time < deadline else "boundary"
            results.append(Trade(i,side,entry.timestamp,end,entry.open,price,outcome,pnl,post_status,post_time))
    return results
