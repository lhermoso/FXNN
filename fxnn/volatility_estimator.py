"""Finite, causal EW dispersion of exact session-day returns.

Entry i uses endpoints strictly before i. Historical modules remain unchanged.
A missing lag endpoint is unavailable, never interpolated or carried forward.
"""
import math

import numpy as np


def _local_variance(returns, endpoints, endpoint, decay):
    """Two-pass local centering avoids remote history and cancellation."""
    values = returns[endpoints]
    weights = decay ** (endpoint-endpoints)
    shifted = values-values[0]
    total = math.fsum(map(float, weights))
    mean = math.fsum(float(w)*float(v) for w, v in zip(weights, shifted))/total
    numerator = math.fsum(float(w)*(float(v)-mean)**2 for w, v in zip(weights, shifted))
    denominator = total-math.fsum(float(w)**2 for w in weights)/total
    return numerator/denominator if denominator > 0 else math.nan


def causal_volatility(closes, stamps, clock, breaks, *, lag=1440, window=500,
                      span=100, minimum=100):
    """Return aligned sigma, price volatility, validity and dependency arrays.

    ``valid_returns`` counts exact-lag pairs in the entry's finite past window.
    ``history_start_index`` is their earliest anchor, including under-warmup
    windows, or -1 if none exist. Valid rows have an empty reason; invalid rows
    distinguish insufficient history, zero and nonfinite volatility. Positive
    finite prices are required; overflow of otherwise valid prices is reported
    as nonfinite volatility rather than silently dropping an exact-lag pair.
    """
    if any(type(v) is not int or v <= 0 for v in (lag, window, span, minimum)):
        raise ValueError('Volatility parameters must be positive integers')
    if span < 2 or minimum < 2 or minimum > window:
        raise ValueError('Require span>=2 and 2<=minimum<=window')
    closes = np.asarray(closes, dtype=np.float64)
    stamps, breaks = np.asarray(stamps), np.asarray(breaks)
    if (closes.ndim != 1 or stamps.shape != closes.shape or breaks.shape != closes.shape
            or breaks.dtype != np.bool_ or not np.issubdtype(stamps.dtype, np.integer)):
        raise ValueError('Expected aligned one-dimensional prices, integer timestamps and boolean breaks')
    if not np.isfinite(closes).all() or np.any(closes <= 0):
        raise ValueError('Closing prices must be positive and finite')
    if np.any(stamps[1:] <= stamps[:-1]):
        raise ValueError('Timestamps must be strictly increasing')
    indices = clock.indices(stamps)
    if not np.all(clock.active[indices]):
        raise ValueError('Observed timestamps outside session')
    n = len(closes)
    result = dict(sigma=np.full(n, np.nan), price_volatility=np.full(n, np.nan),
                  valid=np.zeros(n, dtype=bool), reason=np.full(n, 'insufficient_history', dtype='<U24'),
                  valid_returns=np.zeros(n, dtype=np.int64),
                  history_start_index=np.full(n, -1, dtype=np.int64))
    if not n:
        return result
    if not np.array_equal(breaks, clock.gap_breaks(stamps, 15)):
        raise ValueError('Breaks must match censoring from 15 missing open minutes')
    coordinate = clock.prefix[indices]
    anchors = np.searchsorted(coordinate, coordinate-lag)
    segment = np.maximum.accumulate(np.where(breaks, np.arange(n), 0))
    available = (coordinate[anchors] == coordinate-lag) & (anchors >= segment)
    returns = np.zeros(n, dtype=np.float64)
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        returns[available] = closes[available]/closes[anchors[available]]-1
    decay = 1-2/(span+1)
    kernel = decay ** np.arange(window)
    boundaries = np.concatenate(([0], np.flatnonzero(breaks), [n]))
    for begin, end in zip(boundaries[:-1], boundaries[1:]):
        length = int(end-begin)
        if length < 2:
            continue
        mask = available[begin:end]
        values = returns[begin:end]
        bad = mask & ~np.isfinite(values)
        x = np.where(mask & ~bad, values, 0.)
        def convolution(value, weights=kernel):
            return np.convolve(value, weights, mode='full')[:length]
        a = convolution(mask.astype(float))
        b = convolution(x)
        with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
            c = convolution(x*x)
            d = convolution(mask.astype(float), kernel*kernel)
            second = b*b/a
            numerator = c-second
            denominator = a-d/a
            variance = numerator/denominator
        # Integer cumulative counts are exact and do not round convolution values.
        past = np.arange(length-1)
        left = np.maximum(0, past-window+1)
        prefix = np.concatenate(([0], np.cumsum(mask, dtype=np.int64)))
        counts = prefix[past+1]-prefix[left]
        bad_prefix = np.concatenate(([0], np.cumsum(bad, dtype=np.int64)))
        invalid_numeric = bad_prefix[past+1]-bad_prefix[left] > 0
        entries = begin+past+1
        result['valid_returns'][entries] = counts
        present = np.flatnonzero(mask)
        has_history = counts > 0
        first = present[np.searchsorted(present, left[has_history])]
        result['history_start_index'][entries[has_history]] = anchors[begin+first]
        for local in np.flatnonzero(counts >= minimum):
            entry = int(entries[local])
            value = variance[local]
            # Overflow or cancellation triggers a local reference computation;
            # an infinite input return cannot be recovered and stays unavailable.
            suspect = (not np.isfinite(value) or
                       numerator[local] <= 64*np.finfo(float).eps*(abs(c[local])+second[local]))
            if not invalid_numeric[local] and suspect:
                endpoints = np.flatnonzero(mask[left[local]:local+1])+left[local]
                try:
                    value = _local_variance(values, endpoints, local, decay)
                except (OverflowError, ValueError):
                    value = math.nan
            if invalid_numeric[local] or not np.isfinite(value) or value < 0:
                result['reason'][entry] = 'nonfinite_volatility'
                continue
            sigma = math.sqrt(float(value))
            with np.errstate(over='ignore', invalid='ignore'):
                price = sigma*closes[entry-1]
            result['sigma'][entry] = sigma
            result['price_volatility'][entry] = price
            if not math.isfinite(price):
                result['reason'][entry] = 'nonfinite_volatility'
            elif sigma == 0 or price == 0:
                result['reason'][entry] = 'zero_volatility'
            else:
                result['valid'][entry] = True
                result['reason'][entry] = ''
    return result
