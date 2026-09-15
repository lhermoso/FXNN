"""Indexed hypothetical S0 outcomes, separate from operational opportunities.

These labels are TP-first proxies. No portfolio accounting or future label
availability controls the earlier opportunity or its probability.
"""
from fractions import Fraction
from decimal import Decimal

from fxnn.tick_economic_source import EventKey, Hazard, IntegrityUnion


def label_one(opportunity, index):
    result = dict(opportunity_id=opportunity['id'], label=None, reason=opportunity['reason'],
                  entry_key=None, entry_source=None, entry_ms=None,
                  terminal_key=None, terminal_source=None, information_end_ms=None,
                  earliest_input_ms=opportunity['earliest_input'],
                  information_cap_ms=opportunity['information_cap_ms'])
    if not opportunity['eligible']:
        return result
    decision = opportunity['decision_ms']
    entry = index.first_entry(EventKey(decision, 3, 0), decision+30000)
    if entry is None:
        result['reason'] = 'entry_expired'
        return result
    if isinstance(entry, Hazard):
        result['reason'] = 'entry_hazard:'+entry.reason
        return result
    if not entry.eligible or entry.ambiguous:
        raise ValueError('Entry query returned a non-executable group')
    side = opportunity['side']
    fill = Fraction(entry.ask_min if side == 1 else entry.bid_min)
    volatility = Fraction(Decimal(str(opportunity['price_volatility'])))
    target, stop = fill+side*Fraction(5,2)*volatility, fill-side*volatility
    if min(fill, target, stop, volatility) <= 0:
        result['reason'] = 'invalid_prospective_prices'
        return result
    result.update(entry_key=entry.key.tuple(), entry_source=entry.identity,
                  entry_ms=entry.timestamp)
    deadline, cap = opportunity['deadline_ms'], opportunity['information_cap_ms']
    right = EventKey(cap, 0, -1)
    hazard = index.next_hazard(entry.key, right)
    crossing = index.first_crossing(entry.key, EventKey(deadline, 1, 0),
                                    'bid' if side == 1 else 'ask',
                                    lower=min(target, stop), upper=max(target, stop),
                                    entry_timestamp=entry.timestamp)
    if crossing is not None and (hazard is None or crossing.key < hazard.key):
        price = Fraction(crossing.bid_min if side == 1 else crossing.ask_min)
        take_profit = price >= target if side == 1 else price <= target
        result.update(label=int(take_profit), reason='tp' if take_profit else 'sl',
                      terminal_key=crossing.key.tuple(), terminal_source=crossing.identity,
                      information_end_ms=crossing.timestamp+1)
        return result
    if hazard is not None and hazard.key < EventKey(deadline, 1, 0):
        result['reason'] = 'censored:'+hazard.reason
        return result
    terminal = index.first_entry(EventKey(deadline, 0, -1), cap)
    if (isinstance(terminal, Hazard) or terminal is None or
            hazard is not None and hazard.key <= terminal.key):
        result['reason'] = 'censored:'+hazard.reason if hazard is not None else 'timeout_unobserved'
        return result
    if not terminal.eligible or terminal.ambiguous:
        raise ValueError('Timeout query returned a non-executable group')
    result.update(label=0, reason='timeout', terminal_key=terminal.key.tuple(),
                  terminal_source=terminal.identity, information_end_ms=terminal.timestamp+1)
    if result['information_end_ms'] > cap:
        raise ValueError('Terminal information exceeds conservative cap')
    return result


def training_admission(opportunities, labels, hazards, cutoff, bar_starts):
    """Full-cap purge plus observed-history buffer, integrity strictly as of cutoff.

    bar_starts contains only causal valid completed observations. The caller
    freezes a copy per cutoff; no future integrity mask may rewrite this array.
    """
    from bisect import bisect_left
    if len(opportunities) != len(labels):
        raise ValueError('Aligned opportunities and labels required')
    if any(b <= a for a, b in zip(bar_starts, bar_starts[1:])):
        raise ValueError('Ordered unique causal observed bar starts required')
    # The bar ending exactly at cutoff is finalized after the pre-clock cut.
    boundary_index = bisect_left(bar_starts, cutoff-60000)
    buffer_start = bar_starts[boundary_index-1941] if boundary_index >= 1941 else None
    union = IntegrityUnion(hazards, EventKey(cutoff, 0, -1))
    accepted, reasons = [], []
    for i, (op, label) in enumerate(zip(opportunities, labels)):
        if label['opportunity_id'] != op['id']:
            raise ValueError('Label identity mismatch')
        reason = None
        if op['decision_ms'] >= cutoff:
            reason = 'not_past'
        elif label['label'] is None:
            reason = 'label_unavailable'
        elif buffer_start is None or label['information_cap_ms'] >= buffer_start:
            reason = 'purged_full_cap_and_history'
        elif union.intersects(label['earliest_input_ms'], label['information_end_ms']) is not None:
            reason = 'integrity_disclosed_before_cutoff'
        if reason is None:
            accepted.append(i)
        reasons.append(reason)
    return accepted, reasons
