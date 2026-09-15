"""Causal deterministic primary direction and validation-only decision thresholds."""
from decimal import Decimal
import numpy as np
from .cusum_continuation import support

THRESHOLDS = (.3, .4, .5)


def primary_signals(closes, breaks):
    closes, breaks = np.asarray(closes), np.asarray(breaks)
    if closes.ndim != 1 or breaks.shape != closes.shape or breaks.dtype != np.bool_:
        raise ValueError('Aligned close strings and boolean reset mask required')
    values = [Decimal(str(value)) for value in closes]
    if any(not value.is_finite() or value <= 0 for value in values):
        raise ValueError('Invalid source close')
    n = len(values)
    side = np.zeros(n, dtype=np.int8)
    available = np.zeros(n, dtype=bool)
    reasons = np.full(n, 'primary_history', dtype='<U24')
    segment = 0
    for i in range(n):
        if breaks[i]:
            segment = i
        if i-61 < segment:
            continue
        available[i] = True
        side[i] = int(values[i-1] > values[i-61])-int(values[i-1] < values[i-61])
        reasons[i] = 'signal' if side[i] else 'no_momentum'
    return dict(side=side, primary_available=available, primary_reason=reasons)


def join_candidates(side, candidates):
    side = np.asarray(side)
    if side.ndim != 1 or not np.isin(side, (-1, 0, 1)).all():
        raise ValueError('Invalid primary directions')
    entry, direction = candidates['entry_local'], candidates['sides']
    if entry.shape != direction.shape or entry.ndim != 1 or not np.issubdtype(entry.dtype, np.integer):
        raise ValueError('Invalid candidate identity arrays')
    if np.any((entry < 0) | (entry >= len(side))) or not np.isin(direction, (-1, 1)).all():
        raise ValueError('Invalid candidate identity values')
    keys = 2*entry+(direction == -1)
    if len(np.unique(keys)) != len(keys):
        raise ValueError('duplicate source candidate identity')
    lookup = np.full(2*len(side), -1, dtype=np.int64)
    lookup[keys] = np.arange(len(keys))
    rows = np.full(len(side), -1, dtype=np.int64)
    selected = np.flatnonzero(side)
    rows[selected] = lookup[2*selected+(side[selected] == -1)]
    if np.any(rows[selected] < 0):
        raise ValueError('missing selected source candidate identity')
    return rows


def decision_metrics(y, accepted):
    y, accepted = np.asarray(y), np.asarray(accepted)
    counts = support(y)
    if accepted.shape != y.shape or not np.isin(accepted, (0, 1)).all():
        raise ValueError('Decision metrics require available binary decisions')
    tp = int(((y == 1) & (accepted == 1)).sum())
    fp = int(((y == 0) & (accepted == 1)).sum())
    fn = counts['positive']-tp
    tn = counts['negative']-fp
    return dict(**counts, accepted=int(accepted.sum()), rejected=int(len(y)-accepted.sum()),
                tp=tp, fp=fp, fn=fn, tn=tn,
                precision=tp/(tp+fp) if tp+fp else None,
                recall=tp/(tp+fn) if tp+fn else None,
                f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)


def threshold_grid(y, p):
    y, p = np.asarray(y), np.asarray(p)
    support(y)
    if p.shape != y.shape or not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError('Invalid threshold diagnostic probabilities')
    return {str(t): decision_metrics(y, (p >= t).astype(np.int8)) for t in THRESHOLDS}


def choose_threshold(y, p, source_identity_sha256):
    y, p = np.asarray(y), np.asarray(p)
    counts = support(y)
    if p.shape != y.shape or not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError('Invalid validation probabilities')
    grid = threshold_grid(y, p)
    reason = 'empty_validation' if not len(y) else 'no_validation_positives' if not counts['positive'] else None
    selected = None if reason else max(THRESHOLDS, key=lambda t: (grid[str(t)]['f1'], t))
    return dict(available=reason is None, threshold=selected, reason=reason, grid=grid,
                source_identity_sha256=source_identity_sha256,
                rule='maximum_inner_f1_highest_threshold_tie')


def decisions(p, probability_available, selection):
    p, probability_available = np.asarray(p), np.asarray(probability_available)
    if p.shape != probability_available.shape or probability_available.dtype != np.bool_:
        raise ValueError('Invalid probability availability')
    if not np.isfinite(p[probability_available]).all() or np.any((p[probability_available] < 0) | (p[probability_available] > 1)):
        raise ValueError('Invalid available probability')
    available = probability_available & bool(selection['available'])
    accepted = np.full(len(p), -1, dtype=np.int8)
    reason = np.full(len(p), 'probability_unavailable', dtype='<U48')
    if selection['available']:
        if selection['threshold'] not in THRESHOLDS:
            raise ValueError('Unregistered selected threshold')
        accepted[available] = p[available] >= selection['threshold']
        reason[available] = 'available'
    else:
        reason[probability_available] = selection['reason']
    return dict(acceptance_available=available, accepted=accepted, acceptance_reason=reason)
