"""Past-only splits and interval-average uniqueness weights."""
import numpy as np


def split_before(starts, info_ends, boundary, test_end, buffer_seconds=241*60):
    if test_end <= boundary or buffer_seconds < 0:
        raise ValueError('Invalid temporal split')
    train = np.flatnonzero((starts < boundary) & (info_ends < boundary-buffer_seconds))
    test = np.flatnonzero((starts >= boundary) & (starts < test_end) & (info_ends < test_end))
    return train,test


def uniqueness_weights(starts, ends):
    starts,ends = np.asarray(starts),np.asarray(ends)
    if len(starts)==0 or starts.shape!=ends.shape or np.any(ends<=starts):
        raise ValueError('Expected non-empty positive-length event intervals')
    bounds = np.unique(np.concatenate((starts,ends)))
    left,right = np.searchsorted(bounds,starts),np.searchsorted(bounds,ends)
    delta = np.zeros(len(bounds))
    np.add.at(delta,left,1); np.add.at(delta,right,-1)
    concurrent = np.cumsum(delta)[:-1]
    area = np.diff(bounds)/np.maximum(concurrent,1)
    prefix = np.concatenate(([0.0],np.cumsum(area)))
    weights = (prefix[right]-prefix[left])/(ends-starts)
    return weights/weights.mean()
