"""Conservative OHLC barrier labeling and weighted interval scheduling."""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class Candle:
    timestamp: datetime  # UTC-aware candle opening time
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Config:
    pip_size: Decimal
    take_profit_pips: Decimal = Decimal("50")
    stop_loss_pips: Decimal = Decimal("20")
    max_hold: timedelta = timedelta(days=3)
    bar_duration: timedelta = timedelta(minutes=1)

    def __post_init__(self):
        for value in (self.pip_size, self.take_profit_pips, self.stop_loss_pips):
            if not value.is_finite() or value <= 0:
                raise ValueError("Pip size, TP and SL must be finite and positive")
        if self.bar_duration <= timedelta(0) or self.max_hold < self.bar_duration:
            raise ValueError("Hold duration must be at least one positive bar duration")
        if self.max_hold % self.bar_duration:
            raise ValueError("Hold duration must be a multiple of bar duration")


@dataclass(frozen=True)
class Trade:
    entry_index: int
    side: str
    entry_time: datetime
    end_time: datetime  # conservative upper bound for intrabar exit time
    entry_price: Decimal
    exit_price: Decimal | None
    outcome: str
    pnl_pips: Decimal | None
    post_stop_target_status: str | None = None
    target_after_stop_time: datetime | None = None


def validate_candles(candles: list[Candle], config: Config) -> None:
    previous = None
    for candle in candles:
        if candle.timestamp.utcoffset() != timedelta(0):
            raise ValueError("Timestamps must be timezone-aware UTC")
        values = (candle.open, candle.high, candle.low, candle.close)
        if any(not v.is_finite() or v <= 0 for v in values):
            raise ValueError("OHLC prices must be finite and positive")
        if not candle.low <= min(candle.open, candle.close) <= max(candle.open, candle.close) <= candle.high:
            raise ValueError("Invalid OHLC range")
        if previous is not None:
            delta = candle.timestamp - previous
            if delta < config.bar_duration or delta % config.bar_duration:
                raise ValueError("Candles must be ordered, unique and aligned to bar duration")
        previous = candle.timestamp


def label_trades_reference(candles: list[Candle], config: Config,
                           entry_indices: list[int] | None = None) -> list[Trade]:
    """Evaluate long and short at each open. Missing bars censor pending trades.

    Prices are a single OHLC stream: no spread/fees. Limit fills use TP;
    stop gaps fill at observed open. Intrabar exits use bar end as time bound.
    """
    validate_candles(candles, config)
    results = []
    for index in range(len(candles)) if entry_indices is None else entry_indices:
        if not 0 <= index < len(candles):
            raise ValueError("Entry index outside candle series")
        entry = candles[index]
        deadline = entry.timestamp + config.max_hold
        for side, direction in (("long", 1), ("short", -1)):
            target = entry.open + direction * config.take_profit_pips * config.pip_size
            stop = entry.open - direction * config.stop_loss_pips * config.pip_size
            if min(target, stop) <= 0:
                raise ValueError("Configured barriers produce non-positive prices")
            outcome, exit_price = "censored", None
            end = entry.timestamp
            expected = entry.timestamp
            for j in range(index, len(candles)):
                bar = candles[j]
                if bar.timestamp != expected:
                    break
                end = bar.timestamp + config.bar_duration
                expected = end
                # At later opens, event order is known even if both barriers
                # occur within the subsequent candle's high/low range.
                open_stop = bar.open <= stop if direction == 1 else bar.open >= stop
                open_target = bar.open >= target if direction == 1 else bar.open <= target
                if open_stop or open_target:
                    end = bar.timestamp
                    outcome = "stop_loss" if open_stop else "take_profit"
                    exit_price = bar.open if open_stop else target
                    break
                hit_target = bar.high >= target if direction == 1 else bar.low <= target
                hit_stop = bar.low <= stop if direction == 1 else bar.high >= stop
                if hit_target and hit_stop:
                    outcome = "ambiguous"
                    break
                if hit_stop:
                    outcome, exit_price = "stop_loss", stop
                    break
                if hit_target:
                    # Strictly less than hold limit; last bar cannot establish
                    # this from OHLC alone, so exclude boundary candidates.
                    outcome = "take_profit" if end < deadline else "boundary"
                    exit_price = target
                    break
                if end >= deadline:
                    outcome, exit_price = "timeout", bar.close
                    break
            pnl = None if exit_price is None else direction * (exit_price - entry.open) / config.pip_size
            post_status, post_time = None, None
            if outcome == "stop_loss":
                # Diagnostic only: actual trade already closed at its stop.
                # Follow original target to original deadline, respecting gaps.
                expected_post = candles[j].timestamp
                post_status = "censored"
                for k in range(j, len(candles)):
                    later = candles[k]
                    if later.timestamp != expected_post or later.timestamp >= deadline:
                        break
                    expected_post = later.timestamp + config.bar_duration
                    crossed_open = later.open >= target if direction == 1 else later.open <= target
                    crossed_bar = later.high >= target if direction == 1 else later.low <= target
                    if crossed_open or crossed_bar:
                        candidate_time = later.timestamp if crossed_open else expected_post
                        post_status = "reached" if candidate_time < deadline else "boundary"
                        post_time = candidate_time
                        break
                    if expected_post == deadline:
                        post_status = "not_reached"
                        break
            results.append(Trade(index, side, entry.timestamp, end, entry.open, exit_price, outcome, pnl,
                                 post_status, post_time))
    return results


def label_trades(candles: list[Candle], config: Config) -> list[Trade]:
    """Indexed O(N log N) implementation with identical reference semantics."""
    from .indexed import label_indexed
    return label_indexed(candles, config)


def select_non_overlapping(trades: list[Trade]) -> list[Trade]:
    """Maximize total gross pips, then minimize summed exposure duration.

    Intervals are [entry, end); touching endpoints are compatible. Ties use
    stable entry/side order. Only unambiguous strict-deadline winners qualify.
    """
    winners = sorted((t for t in trades if t.outcome == "take_profit"),
                     key=lambda t: (t.end_time, t.entry_time, t.side))
    ends = [t.end_time for t in winners]
    scores = [(Decimal(0), timedelta(0))]
    predecessors, chosen = [], []
    for i, trade in enumerate(winners):
        predecessor = bisect_right(ends, trade.entry_time, hi=i)
        base = scores[predecessor]
        include = (base[0] + trade.pnl_pips, base[1] - (trade.end_time - trade.entry_time))
        take = include > scores[-1]
        predecessors.append(predecessor)
        chosen.append(take)
        scores.append(include if take else scores[-1])
    selected = []
    cursor = len(winners)
    while cursor:
        i = cursor - 1
        if chosen[i]:
            selected.append(winners[i])
            cursor = predecessors[i]
        else:
            cursor -= 1
    return selected[::-1]
