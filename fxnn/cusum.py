"""Symmetric causal CUSUM: closed-price events, next continuous opening only."""
import math

import numpy as np


def cusum_events(closes, stamps, threshold):
    closes, stamps = np.asarray(closes, dtype=float), np.asarray(stamps)
    if (closes.ndim != 1 or closes.shape != stamps.shape
            or not np.all(np.isfinite(closes)) or np.any(closes <= 0)
            or not np.all(np.isfinite(stamps)) or np.any(np.diff(stamps) <= 0)
            or np.any(stamps % 60 != 0)
            or not math.isfinite(threshold) or threshold <= 0):
        raise ValueError('Expected positive finite closes, ordered M1 timestamps and threshold')
    events = np.zeros(len(closes), dtype=bool)
    positive = negative = 0.0
    for i in range(1, len(closes)):
        if stamps[i] - stamps[i-1] != 60:
            positive = negative = 0.0
            continue
        change = math.log(closes[i]) - math.log(closes[i-1])
        positive = max(0.0, positive + change)
        negative = min(0.0, negative + change)
        if negative < -threshold:
            negative = 0.0
            events[i] = True
        elif positive > threshold:
            positive = 0.0
            events[i] = True
    return events


def next_entries(events, stamps):
    events, stamps = np.asarray(events, dtype=bool), np.asarray(stamps)
    if events.ndim != 1 or events.shape != stamps.shape:
        raise ValueError('Expected aligned event and timestamp vectors')
    entries = np.zeros(len(events), dtype=bool)
    entries[1:] = events[:-1] & (np.diff(stamps) == 60)
    return entries


def interval_diagnostics(starts, ends):
    """Descriptive overlap on supplied intervals only; no normalized-weight proxy."""
    starts, ends = np.asarray(starts), np.asarray(ends)
    if starts.ndim != 1 or starts.shape != ends.shape or np.any(ends <= starts):
        raise ValueError('Expected aligned positive-length intervals')
    if not len(starts):
        return {'rows': 0, 'raw_uniqueness_mean': None, 'raw_uniqueness_min': None,
                'raw_uniqueness_max': None, 'concurrency_max': 0, 'concurrency_active_mean': None}
    bounds = np.unique(np.concatenate((starts, ends)))
    left, right = np.searchsorted(bounds, starts), np.searchsorted(bounds, ends)
    delta = np.zeros(len(bounds), dtype=np.int64)
    np.add.at(delta, left, 1)
    np.add.at(delta, right, -1)
    concurrent = np.cumsum(delta)[:-1]
    durations = np.diff(bounds)
    area = durations / np.maximum(concurrent, 1)
    prefix = np.concatenate(([0.0], np.cumsum(area)))
    raw = (prefix[right] - prefix[left]) / (ends - starts)
    return {'rows': len(starts), 'raw_uniqueness_mean': float(raw.mean()),
            'raw_uniqueness_min': float(raw.min()), 'raw_uniqueness_max': float(raw.max()),
            'concurrency_max': int(concurrent.max()),
            'concurrency_active_mean': float(np.sum(durations * concurrent)
                                           / durations[concurrent > 0].sum())}
