"""Explicit minute clock: scheduled closures pause time; missing quotes do not.

Calendar selection belongs to the research contract. This module never infers a
calendar from gaps in observed prices and never synthesizes price candles.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np


@dataclass
class SessionClock:
    first_epoch: int
    active: np.ndarray

    def __post_init__(self):
        if type(self.first_epoch) is not int or self.first_epoch % 60:
            raise ValueError('Clock origin must be an integer UTC minute')
        active = np.asarray(self.active)
        if active.ndim != 1 or active.dtype != np.bool_ or not len(active):
            raise ValueError('Calendar must be a nonempty one-dimensional boolean mask')
        self.active = active.copy()
        self.prefix = np.concatenate(([0], np.cumsum(self.active, dtype=np.int64)))

    def indices(self, epochs, *, endpoint=False):
        epochs = np.asarray(epochs)
        if (not np.issubdtype(epochs.dtype, np.integer) or np.any(epochs % 60)):
            raise ValueError('Expected integer UTC minute timestamps')
        indices = (epochs-self.first_epoch)//60
        limit = len(self.active) if endpoint else len(self.active)-1
        if np.any(indices < 0) or np.any(indices > limit):
            raise ValueError('Timestamp outside registered calendar')
        return indices

    def elapsed(self, starts, ends):
        starts, ends = np.asarray(starts), np.asarray(ends)
        if starts.shape != ends.shape or np.any(ends < starts):
            raise ValueError('Expected aligned ordered interval endpoints')
        left, right = self.indices(starts, endpoint=True), self.indices(ends, endpoint=True)
        return self.prefix[right]-self.prefix[left]

    def deadlines(self, starts, active_minutes=4320):
        if type(active_minutes) is not int or active_minutes <= 0:
            raise ValueError('Horizon must be positive integer session minutes')
        starts = np.asarray(starts)
        left = self.indices(starts)
        if not np.all(self.active[left]):
            raise ValueError('Entries must be in scheduled open minutes')
        target = self.prefix[left]+active_minutes
        if np.any(target > self.prefix[-1]):
            raise ValueError('Calendar does not cover complete information horizons')
        # First boundary reaching target: timeout at Friday close stays Friday,
        # not Sunday reopen, even though cumulative open time is equal there.
        right = np.searchsorted(self.prefix, target, side='left')
        return self.first_epoch+right*60

    def missing_open_minutes(self, observed_epochs):
        stamps = np.asarray(observed_epochs)
        indices = self.indices(stamps)
        if stamps.ndim != 1 or np.any(np.diff(stamps) <= 0):
            raise ValueError('Observed timestamps must be strictly increasing')
        if not np.all(self.active[indices]):
            raise ValueError('Observed timestamps outside selected session calendar')
        return np.diff(self.prefix[indices])-1

    def gap_breaks(self, observed_epochs, censor_from_minutes=15):
        if type(censor_from_minutes) is not int or censor_from_minutes < 1:
            raise ValueError('Gap threshold must be a positive integer')
        gaps = self.missing_open_minutes(observed_epochs)
        # Boundary at the returning observed candle. Closures count zero.
        return np.concatenate(([False], gaps >= censor_from_minutes))


def calendar_from_rule(first_epoch, stop_epoch, is_open):
    """Build mask from an explicit time-only rule, never from observed prices."""
    if (type(first_epoch) is not int or type(stop_epoch) is not int
            or first_epoch % 60 or stop_epoch % 60 or stop_epoch <= first_epoch):
        raise ValueError('Expected ordered UTC minute boundaries')
    active = np.fromiter((bool(is_open(datetime.fromtimestamp(t, timezone.utc)))
                          for t in range(first_epoch, stop_epoch, 60)), dtype=bool)
    return SessionClock(first_epoch, active)


def weekly_fx_clock(first_epoch, stop_epoch):
    """Weekly convention Sun 17:00 to Fri 17:00 America/New_York, stored UTC.

    Not a broker holiday calendar; exceptional closures remain gap-policy cases.
    ZoneInfo applies historical DST; no fixed 22:00 UTC assumption.
    """
    from zoneinfo import ZoneInfo
    zone = ZoneInfo('America/New_York')
    def is_open(stamp):
        local = stamp.astimezone(zone)
        day = local.weekday()
        return day < 4 or day == 4 and local.hour < 17 or day == 6 and local.hour >= 17
    return calendar_from_rule(first_epoch, stop_epoch, is_open)
