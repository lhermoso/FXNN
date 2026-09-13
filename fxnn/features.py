"""Causal M1 features. Row t uses only closed candles strictly before t."""
from dataclasses import dataclass

import numpy as np

from .labeling import Config, validate_candles
from decimal import Decimal

LOOKBACK = 241


@dataclass
class FeatureFrame:
    values: np.ndarray
    valid: np.ndarray
    names: list[str]
    groups: dict[str, list[int]]
    directional: list[int]


def past_sum(values, window):
    prefix = np.concatenate(([0.0], np.cumsum(values)))
    result = np.zeros(len(values))
    result[window:] = prefix[window:-1] - prefix[:len(values)-window]
    return result


def build_features(candles):
    validate_candles(candles, Config(Decimal('0.0001')))
    n = len(candles)
    if n <= LOOKBACK:
        raise ValueError('At least 242 M1 candles required')
    prices = np.asarray([[float(c.open),float(c.high),float(c.low),float(c.close)] for c in candles])
    stamps = np.asarray([int(c.timestamp.timestamp()) for c in candles], dtype=np.int64)
    o,h,l,c = prices.T
    logs = np.log(c)
    returns = np.concatenate(([0.0], np.diff(logs)))
    columns, names, directional = [], [], []
    groups = {name: [] for name in ('movement','volatility','position','path','context')}

    def add(name, values, group, orient=False):
        index = len(columns)
        columns.append(values); names.append(name); groups[group].append(index)
        if orient: directional.append(index)

    for w in (5,15,60,240):
        net = past_sum(returns,w)
        vol = np.sqrt(np.maximum(past_sum(returns**2,w)/w-(net/w)**2,0))
        mean = past_sum(c,w)/w
        std = np.sqrt(np.maximum(past_sum(c*c,w)/w-mean*mean,0))
        last = np.concatenate(([c[0]],c[:-1]))
        add(f'return_{w}',net,'movement',True)
        add(f'volatility_{w}',vol,'volatility')
        add(f'range_pips_{w}',past_sum(h-l,w)/w/0.0001,'volatility')
        add(f'zscore_{w}',(last-mean)/np.maximum(std,0.00001),'position',True)
        add(f'efficiency_{w}',np.abs(net)/np.maximum(past_sum(np.abs(returns),w),1e-12),'path')
    scale = np.maximum(h-l,0.00001)
    def previous(values):return np.concatenate(([0.0],values[:-1]))
    add('body',previous((c-o)/scale),'path',True)
    add('upper_wick',previous((h-np.maximum(c,o))/scale),'path')
    add('lower_wick',previous((np.minimum(c,o)-l)/scale),'path')
    hours = np.asarray([c.timestamp.hour+c.timestamp.minute/60 for c in candles])
    weekdays = np.asarray([c.timestamp.weekday() for c in candles])
    add('hour_sin',np.sin(2*np.pi*hours/24),'context')
    add('hour_cos',np.cos(2*np.pi*hours/24),'context')
    add('weekday_sin',np.sin(2*np.pi*weekdays/7),'context')
    add('weekday_cos',np.cos(2*np.pi*weekdays/7),'context')
    add('direction',np.ones(n),'context')
    valid = np.zeros(n,dtype=bool)
    valid[LOOKBACK:] = stamps[LOOKBACK:]-stamps[:-LOOKBACK] == LOOKBACK*60
    values = np.column_stack(columns)
    valid &= np.all(np.isfinite(values),axis=1)
    return FeatureFrame(values,valid,names,groups,directional)


def orient_features(frame, indices, sides):
    values = frame.values[indices].copy()
    values[:,frame.directional] *= np.asarray(sides)[:,None]
    values[:,-1] = sides
    return values
