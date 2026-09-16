"""Private dense semantic oracle. Synthetic inputs only; no production imports.

Times are integer milliseconds. Caller supplies the tiny session interval calendar,
rollovers and scheduled signals. Price inputs must be finite decimal strings or
integers (binary floats rejected). This is a reference, not a research pipeline.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from fractions import Fraction
from zoneinfo import ZoneInfo


def exact(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        raise TypeError('Use decimal strings, not binary floats')
    decimal = Decimal(value)
    if not decimal.is_finite():
        raise ValueError('Finite amount required')
    return Fraction(decimal)


def display_usd(value):
    value = exact(value)
    with localcontext() as context:
        context.prec = max(60, len(str(abs(value.numerator))) + len(str(value.denominator)) + 10)
        return str((Decimal(value.numerator) / Decimal(value.denominator)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True)
class Costs:
    commission_rate: Fraction
    slip: Fraction
    annual_funding: Fraction

    @property
    def commission(self):
        return 1000 * self.commission_rate / 100000


COSTS = {
    'S0': Costs(exact('0'), exact('0'), exact('0')),
    'S1': Costs(exact('3.5'), exact('0.00001'), exact('0.05')),
    'S2': Costs(exact('7'), exact('0.00005'), exact('0.1')),
}


class Clock:
    """Independent dense interval arithmetic; close endpoints are excluded."""
    def __init__(self, intervals):
        self.intervals = tuple(intervals)
        if any(a >= b for a, b in self.intervals):
            raise ValueError('Invalid session interval')
        if any(b > c for (_, b), (c, _) in zip(self.intervals, self.intervals[1:])):
            raise ValueError('Overlapping/out-of-order sessions')

    def active(self, t):
        return any(a <= t < b for a, b in self.intervals)

    def coordinate(self, t):
        return sum(max(0, min(t, b) - a) for a, b in self.intervals if a < t)

    def inverse(self, origin, duration):
        if duration < 0:
            raise ValueError('Nonnegative duration required')
        if duration == 0:
            return origin
        remaining = duration
        for a, b in self.intervals:
            left = max(a, origin)
            if left >= b:
                continue
            if remaining <= b - left:
                return left + remaining
            remaining -= b - left
        raise ValueError('Calendar exhausted')


def rollover_factor(utc_datetime):
    local = utc_datetime.astimezone(ZoneInfo('America/New_York'))
    if (local.hour, local.minute, local.second, local.microsecond) != (17, 0, 0, 0):
        return 0
    return 0 if local.weekday() >= 5 else 3 if local.weekday() == 2 else 1


@dataclass
class Position:
    side: int
    entry: Fraction
    source_time: int
    deadline: int
    tp: Fraction
    sl: Fraction


class Account:
    units = 1000
    initial = exact('10000')

    def __init__(self, clock, bundle='S0', policy='P0'):
        if policy not in ('P0', 'P1'):
            raise ValueError('Unregistered uncertainty policy')
        self.clock, self.costs, self.policy = clock, COSTS[bundle], policy
        self.cash = self.initial
        self.position = None
        self.pending = None
        self.mode = 'FLAT'
        self.last_quote = None
        self.last_quote_time = None
        self.hazard_time = None
        self.uncertain = False
        self.scenario_resolved = False
        self.conditional_funding = exact('0')
        self.transactions = []
        self.marks = [(None, self.initial)]
        self.decisions = []
        self.last_exit_time = None
        self.last_logical_time = None

    def equity(self, t):
        if self.uncertain:
            return None
        if self.position is None:
            return self.cash
        if self.last_quote is None or self.clock.coordinate(t) - self.clock.coordinate(self.last_quote_time) >= 60000:
            return None
        bid, ask = self.last_quote
        p = self.position
        liquidation = bid if p.side == 1 else ask
        return self.cash + self.units * p.side * (liquidation - p.entry)

    def mark(self, t):
        self.marks.append((t, self.equity(t)))

    def transaction(self, t, kind, amount, conditional=False):
        self.transactions.append(dict(time=t, kind=kind, amount=amount, conditional=conditional))
        if not conditional:
            self.cash += amount

    def rollover(self, t, factor):
        if factor not in (0, 1, 3):
            raise ValueError('Unregistered rollover factor')
        if self.position is None or not factor:
            return
        debit = self.units * self.position.entry * self.costs.annual_funding * factor / 365
        if self.uncertain:
            self.conditional_funding += debit
            self.transaction(t, 'funding_if_still_open', -debit, conditional=True)
        else:
            self.transaction(t, 'funding', -debit)
        self.mark(t)

    def hazard(self, t):
        if self.position is not None and not self.uncertain:
            self.uncertain = True
            self.hazard_time = t
            self.mode = 'UNRESOLVED'
            self.mark(t)
        if self.pending is not None:
            self.pending = None
            if self.position is None:
                self.mode = 'FLAT'

    def advance(self, t):
        """Fire logical timers before source at t; never derive hazard from return."""
        if self.last_logical_time is not None and t < self.last_logical_time:
            raise ValueError('Availability time must not regress')
        self.last_logical_time = t
        if self.pending and t >= self.pending['decision'] + 30000:
            self.pending = None
            self.mode = 'FLAT'
        if self.position is None or self.uncertain:
            return
        p = self.position
        gap = self.clock.inverse(self.last_quote_time, 60000)
        cap = self.clock.inverse(p.deadline, 60000)
        first_hazard = min(gap, cap)
        if t >= first_hazard:
            self.hazard(first_hazard)
        elif t >= p.deadline:
            self.mode = 'PENDING_TIMEOUT_EXIT'

    def signal(self, t, side, volatility, deadline):
        """Caller schedules after clock events, before source groups at t."""
        if side not in (-1, 1) or exact(volatility) <= 0:
            raise ValueError('Invalid side or volatility')
        blocked = self.position is not None or self.pending is not None or self.last_exit_time == t or self.uncertain
        self.decisions.append(dict(time=t, blocked=blocked))
        if not blocked:
            self.pending = dict(decision=t, side=side, volatility=exact(volatility), deadline=deadline)
            self.mode = 'PENDING_ENTRY'

    def exit(self, t, price, kind, scenario=False):
        p = self.position
        if price <= 0:
            self.hazard(t)
            return
        if scenario:
            # Materialize only the assumed funding, preserving prior conditional records.
            self.transaction(t, 'scenario_funding_settlement', -self.conditional_funding)
            self.scenario_resolved = True
        self.transaction(t, kind, self.units * p.side * (price - p.entry))
        self.transaction(t, 'exit_commission', -self.costs.commission)
        self.position = None
        self.mode = 'FLAT'
        self.last_exit_time = t
        self.marks.append((t, None if self.uncertain else self.cash))

    def quote(self, logical, source, bid, ask, *, valid=True, ambiguous=False, adverse_bid=None, adverse_ask=None):
        """Already-disclosed paired quote. Does not sort source timestamps.

        Call advance(logical) once per timestamp before signals and quote batches.
        Invalid groups disclose a hazard. Off-session valid quotes have no effect.
        """
        if not valid or source is None:
            self.hazard(logical)
            return
        bid, ask = exact(bid), exact(ask)
        if bid <= 0 or ask < bid:
            self.hazard(logical)
            return
        if not self.clock.active(source):
            return
        if self.last_quote_time is not None and source < self.last_quote_time:
            self.hazard(logical)
        if ambiguous:
            self.hazard(logical)
        if self.uncertain:
            if self.policy == 'P1' and self.position and source > self.hazard_time:
                p = self.position
                price = exact(adverse_bid) if p.side == 1 and adverse_bid is not None else exact(adverse_ask) if p.side == -1 and adverse_ask is not None else bid if p.side == 1 else ask
                self.exit(logical, price - p.side * self.costs.slip, 'scenario_exit', scenario=True)
            return
        if ambiguous:
            return
        self.last_quote = bid, ask
        self.last_quote_time = source
        if self.position:
            p = self.position
            if source > p.source_time:
                liquidation = bid if p.side == 1 else ask
                if self.mode == 'PENDING_TIMEOUT_EXIT':
                    self.exit(logical, liquidation - p.side * self.costs.slip, 'timeout')
                elif p.side * (liquidation - p.sl) <= 0:
                    self.exit(logical, liquidation - p.side * self.costs.slip, 'stop')
                elif p.side * (liquidation - p.tp) >= 0:
                    self.exit(logical, p.tp, 'take_profit')
            if self.position:
                self.mark(logical)
            return
        if self.pending and self.pending['decision'] <= source < self.pending['decision'] + 30000 and self.last_exit_time != logical:
            pending = self.pending
            side = pending['side']
            fill = (ask if side == 1 else bid) + side * self.costs.slip
            tp = fill + side * Fraction(5, 2) * pending['volatility']
            sl = fill - side * pending['volatility']
            self.pending = None
            if min(fill, tp, sl) <= 0 or self.units * fill + self.costs.commission > self.cash:
                self.mode = 'FLAT'
                return
            self.position = Position(side, fill, source, pending['deadline'], tp, sl)
            self.mode = 'OPEN'
            self.transaction(logical, 'entry_commission', -self.costs.commission)
            self.mark(logical)

    def drawdown(self):
        if self.uncertain or any(v is None for _, v in self.marks):
            return None
        peak = self.initial
        maximum = exact('0')
        for _, equity in self.marks:
            peak = max(peak, equity)
            maximum = max(maximum, peak - equity)
        return maximum, maximum / self.initial

    def scenario_final_cash(self):
        return self.cash if self.scenario_resolved and self.position is None else None


def schedule(account, events):
    """Tiny dense scheduler: snapshot < funding < timers < signal < source.

    events: (wall_ms, kind, payload). Stable input order preserves same-time source
    ordinals; synthetic caller supplies all event times and relevant timers.
    """
    priorities = {'snapshot': 0, 'funding': 1, 'clock': 2, 'signal': 3, 'quote': 4}
    results = []
    ordered = sorted(enumerate(events), key=lambda pair: (pair[1][0], priorities[pair[1][1]], pair[0]))
    for ordinal, (t, kind, payload) in ordered:
        if kind == 'snapshot':
            results.append((payload, account.equity(t)))
        elif kind == 'funding':
            account.rollover(t, payload)
        elif kind == 'clock':
            account.advance(t)
        elif kind == 'signal':
            account.signal(t, **payload)
        else:
            account.quote(t, **payload)
    return results


def cash_before_transaction(transactions, first_uncertain_ordinal, initial=Fraction(10000)):
    """Certainty overlay: preserve records; exclude tainted transaction suffix.

    The caller supplies the full-order certainty boundary established by quality
    provenance. A wall timestamp alone cannot order same-time funding/disclosure.
    """
    if not 0 <= first_uncertain_ordinal <= len(transactions):
        raise ValueError('Invalid transaction certainty boundary')
    return initial + sum((t['amount'] for t in transactions[:first_uncertain_ordinal]
                          if not t['conditional']), Fraction(0))


def timeout_quote_eligible(clock, deadline, source):
    return clock.active(source) and source >= deadline and 0 <= clock.coordinate(source) - clock.coordinate(deadline) < 60000
