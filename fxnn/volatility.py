"""Versioned entry-frozen barriers and finite-history temporal partitions.

Historical session labeling remains untouched. Realized exit time, observed
information end and conservative purge horizon are deliberately separate.
"""
from decimal import Decimal

import numpy as np

from .indexed import BarrierIndex
from .labeling import Config, validate_candles
from .protocol import utc_epoch
from .session_data import censor_times

HISTORY_BUFFER = 1941


def barrier_labels(candles, clock, tp_distance, sl_distance, *, eligible=None,
                   threshold=15, horizon=4320):
    """Scan both directions with price distances fixed before each entry.

    Ineligible entries remain in the candidate universe, with no hypothetical
    exit. Decimal(str(distance)) is the registered float-to-price conversion;
    no pip rounding or favorable resolution of ambiguous candles is used.
    """
    validate_candles(candles, Config(Decimal('.0001')))
    n = len(candles)
    if not n:
        raise ValueError('At least one observed candle required')
    if type(threshold) is not int or threshold < 1:
        raise ValueError('Invalid gap threshold')
    tp, sl = np.asarray(tp_distance, dtype=float), np.asarray(sl_distance, dtype=float)
    eligible = np.ones(n, dtype=bool) if eligible is None else np.asarray(eligible)
    if tp.shape != (n,) or sl.shape != (n,) or eligible.shape != (n,) or eligible.dtype != np.bool_:
        raise ValueError('Misaligned distances or eligibility')
    if (not np.isfinite(tp[eligible]).all() or not np.isfinite(sl[eligible]).all()
            or np.any(tp[eligible] <= 0) or np.any(sl[eligible] <= 0)):
        raise ValueError('Eligible entries require finite positive distances')
    stamps = np.asarray([int(c.timestamp.timestamp()) for c in candles], dtype=np.int64)
    clock.missing_open_minutes(stamps)
    deadlines = clock.deadlines(stamps, horizon)
    censored = censor_times(stamps, clock, threshold)
    right = np.searchsorted(stamps, np.minimum(deadlines, censored), side='left')
    tree = BarrierIndex(candles)
    entry = np.repeat(np.arange(n, dtype=np.int64), 2)
    sides = np.tile(np.array([1, -1], dtype=np.int8), n)
    result = dict(entry_local=entry, sides=sides, starts=stamps[entry],
                  info_ends=deadlines[entry], ends=stamps[entry].copy(),
                  last_information_bar_end=stamps[entry].copy(),
                  outcomes=np.full(2 * n, 'causally_ineligible', dtype='<U24'),
                  entry_price=np.repeat([float(c.open) for c in candles], 2),
                  exit_price=np.full(2 * n, np.nan), pnl_pips=np.full(2 * n, np.nan),
                  tp_distance=tp[entry], sl_distance=sl[entry])
    for i in np.flatnonzero(eligible):
        opening = candles[i].open
        take, loss = Decimal(str(tp[i])), Decimal(str(sl[i]))
        for offset, direction in enumerate((1, -1)):
            row = 2 * i + offset
            target, stop = opening + direction * take, opening - direction * loss
            if min(target, stop) <= 0:
                raise ValueError('Nonpositive entry barrier')
            hit = tree.first_touch(int(i), int(right[i]), min(target, stop), max(target, stop))
            price = None
            if hit is None:
                end = information = min(int(deadlines[i]), int(censored[i]))
                if (deadlines[i] < censored[i]
                        or deadlines[i] == censored[i] == stamps[-1] + 60):
                    outcome = 'timeout'
                    last = int(np.searchsorted(stamps, deadlines[i], side='left')) - 1
                    price = candles[last].close
                else:
                    outcome = 'censored'
            else:
                bar = candles[hit]
                end = information = int(stamps[hit]) + 60
                if direction * (bar.open - stop) <= 0:
                    outcome, price, end = 'stop_loss', bar.open, int(stamps[hit])
                elif direction * (bar.open - target) >= 0:
                    outcome, price, end = 'take_profit', target, int(stamps[hit])
                else:
                    target_hit = bar.high >= target if direction == 1 else bar.low <= target
                    stop_hit = bar.low <= stop if direction == 1 else bar.high >= stop
                    if target_hit and stop_hit:
                        outcome = 'ambiguous'
                    elif stop_hit:
                        outcome, price = 'stop_loss', stop
                    else:
                        outcome, price = ('take_profit' if end < deadlines[i] else 'boundary'), target
            result['outcomes'][row] = outcome
            result['ends'][row] = end
            result['last_information_bar_end'][row] = information
            if price is not None:
                result['exit_price'][row] = float(price)
                result['pnl_pips'][row] = float(direction * (price - opening) / Decimal('.0001'))
    return result


def volatility_partitions(starts, info_ends, protocol, fold, clock, observed_stamps):
    """Full-horizon purge plus 1941 observed candles before each training edge."""
    starts, info_ends, stamps = map(np.asarray, (starts, info_ends, observed_stamps))
    if starts.ndim != 1 or starts.shape != info_ends.shape:
        raise ValueError('Misaligned event horizons')
    if not np.array_equal(info_ends, clock.deadlines(starts)):
        raise ValueError('Information ends must equal full session-clock horizons')
    if stamps.ndim != 1 or np.any(np.diff(stamps) <= 0):
        raise ValueError('Observed timestamps must increase strictly')
    begin, stop = map(utc_epoch, protocol['development'])
    if np.any((starts < begin) | (starts >= stop)):
        raise ValueError('Reserved entries rejected')
    inner, outer, end = (utc_epoch(fold[k]) for k in ('validation_start', 'test_start', 'test_end'))
    if not begin < inner < outer < end <= stop:
        raise ValueError('Invalid chronological fold')
    def cutoff(boundary):
        past = stamps[stamps < boundary]
        return int(past[-HISTORY_BUFFER]) if len(past) >= HISTORY_BUFFER else begin
    return dict(
        train=np.flatnonzero((starts < inner) & (info_ends < cutoff(inner))),
        refit=np.flatnonzero((starts < outer) & (info_ends < cutoff(outer))),
        validation=np.flatnonzero((starts >= inner) & (starts < outer) & (info_ends < outer)),
        test=np.flatnonzero((starts >= outer) & (starts < end) & (info_ends < end)),
    )
