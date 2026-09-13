"""Development-only temporal contract, shared by audits and future experiments."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .temporal import split_before


def utc_epoch(value):
    stamp = datetime.fromisoformat(value)
    if stamp.utcoffset() != timedelta(0) or stamp.second or stamp.microsecond:
        raise ValueError('Protocol boundaries must be UTC minute timestamps')
    return int(stamp.timestamp())


def load_protocol(path):
    protocol = json.loads(Path(path).read_text())
    if (protocol['kind'] != 'research_data_protocol'
            or protocol['experiment'] != 'multiyear_v1'
            or protocol['confirmation_locked'] is not True):
        raise ValueError('Expected locked multiyear research data protocol')
    development = list(map(utc_epoch, protocol['development']))
    confirmation = list(map(utc_epoch, protocol['confirmation']))
    if not development[0] < development[1] <= confirmation[0] < confirmation[1]:
        raise ValueError('Development and confirmation must be ordered and disjoint')
    if protocol['source_years'] != [2022, 2023]:
        raise ValueError('Only development source years 2022 and 2023 are authorized')
    if (protocol['source'] != 'HistData' or protocol['price_side'] != 'bid'
            or protocol['gap_policy'] != 'censor_all_reset_all'
            or protocol['horizon_minutes'] != 4320):
        raise ValueError('Unsupported source, gap policy or label horizon')
    for key in ('lookback_minutes', 'minimum_rows', 'minimum_per_class'):
        if type(protocol[key]) is not int or protocol[key] <= 0:
            raise ValueError('Protocol limits must be positive integers')
    if protocol['lookback_minutes'] < 241:
        raise ValueError('Buffer cannot be shorter than feature history')
    if not protocol['folds']:
        raise ValueError('At least one fold required')
    names = set()
    previous_end = development[0]
    for fold in protocol['folds']:
        inner, outer, end = (utc_epoch(fold[k]) for k in
                             ('validation_start', 'test_start', 'test_end'))
        if (fold['name'] in names or not development[0] < inner < outer < end <= development[1]
                or outer < previous_end):
            raise ValueError('Invalid or overlapping development folds')
        names.add(fold['name'])
        previous_end = end
    return protocol


def partition_indices(starts, info_ends, protocol, fold):
    """Reject reserved input; select by UTC and conservative information horizon."""
    starts, info_ends = np.asarray(starts), np.asarray(info_ends)
    if (starts.ndim != 1 or starts.shape != info_ends.shape
            or not np.all(np.isfinite(starts)) or not np.all(np.isfinite(info_ends))):
        raise ValueError('Expected aligned finite event times')
    first, stop = map(utc_epoch, protocol['development'])
    if np.any((starts < first) | (starts >= stop)):
        raise ValueError('Reserved or out-of-development entries rejected')
    if np.any(info_ends != starts + protocol['horizon_minutes'] * 60):
        raise ValueError('Information ends must use the conservative label horizon')
    inner, outer, end = (utc_epoch(fold[k]) for k in
                         ('validation_start', 'test_start', 'test_end'))
    buffer = protocol['lookback_minutes'] * 60
    train, validation = split_before(starts, info_ends, inner, outer, buffer)
    refit, test = split_before(starts, info_ends, outer, end, buffer)
    return dict(train=train, validation=validation, refit=refit, test=test)


def class_support(labels, minimum_rows, minimum_per_class):
    labels = np.asarray(labels)
    if labels.ndim != 1 or not np.all((labels == 0) | (labels == 1)):
        raise ValueError('Expected binary labels')
    positive = int(labels.sum())
    negative = len(labels) - positive
    return {'rows': len(labels), 'positive': positive, 'negative': negative,
            'eligible': len(labels) >= minimum_rows
                        and min(positive, negative) >= minimum_per_class}


def require_training_support(labels, partitions, protocol):
    """Guard before fitting; external labels never decide whether training runs."""
    labels = np.asarray(labels)
    report = {name: class_support(labels[partitions[name]], protocol['minimum_rows'],
                                 protocol['minimum_per_class'])
              for name in ('train', 'validation', 'refit')}
    if not all(part['eligible'] for part in report.values()):
        raise ValueError('Insufficient development class support; abort comparison: '
                         + json.dumps(report, sort_keys=True))
    return report
