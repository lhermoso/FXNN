"""Fixed-width fractional differences: each entry uses closes through t-1."""
from dataclasses import dataclass
import math

import numpy as np


@dataclass
class FractionalFrame:
    values: np.ndarray
    valid: np.ndarray
    weights: np.ndarray

    @property
    def lookback(self):
        return len(self.weights)


def fractional_weights(d, threshold=1e-4, max_terms=1440):
    if (not math.isfinite(d) or not 0 <= d <= 1
            or not math.isfinite(threshold) or not 0 < threshold < 1
            or not isinstance(max_terms, int) or max_terms < 1):
        raise ValueError('Invalid fractional difference configuration')
    weights = [1.0]
    for k in range(1, max_terms+1):
        weight = -weights[-1] * (d-k+1) / k
        if abs(weight) < threshold:
            return np.asarray(weights)
        if k == max_terms:
            raise ValueError('Weight threshold not reached within maximum history')
        weights.append(weight)
    raise AssertionError('Unreachable')


def fractional_features(log_prices, stamps, d, threshold=1e-4, max_terms=1440):
    logs = np.asarray(log_prices, dtype=float)
    stamps = np.asarray(stamps)
    if (logs.ndim != 1 or logs.shape != stamps.shape or not len(logs)
            or not np.all(np.isfinite(logs)) or not np.all(np.isfinite(stamps))
            or np.any(np.diff(stamps) < 60) or np.any(np.diff(stamps) % 60)):
        raise ValueError('Expected finite log prices and ordered M1 timestamps')
    weights = fractional_weights(d, threshold, max_terms)
    length = len(weights)
    values = np.full(len(logs), np.nan)
    valid = np.zeros(len(logs), dtype=bool)
    if len(logs) > length:
        # Full convolution is past-only; shift by one for an entry at the open.
        values[length:] = np.convolve(logs, weights, mode='full')[length-1:len(logs)-1]
        valid[length:] = stamps[length:] - stamps[:-length] == length * 60
    values[~valid] = np.nan
    return FractionalFrame(values, valid, weights)
