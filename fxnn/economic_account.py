"""Exact event-driven economic accounts for the frozen issue-9 contract.

Staging module: stdlib only. No market loading, model fitting or index ownership.
Clock adapter: active(ms), coordinate(ms), inverse(origin_ms, open_duration_ms).
Use a durable journal sink with retain=False for large event streams.
"""
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from collections import Counter
import hashlib
import json

INITIAL = Fraction(10000)
UNITS = 1000
PHASE = {'snapshot': 0, 'funding': 1, 'timer': 2, 'decision': 3, 'source': 4, 'end': 5}


def rational(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError('Exact decimal input required')
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError('Invalid decimal text') from error
    if not parsed.is_finite():
        raise ValueError('Nonfinite price/amount')
    return Fraction(parsed)


def serializable(value):
    if isinstance(value, Fraction):
        return {'numerator': value.numerator, 'denominator': value.denominator}
    if isinstance(value, Key):
        return [value.time, value.phase, value.ordinal]
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serializable(v) for v in value]
    return value


@dataclass(frozen=True, order=True)
class Key:
    time: int
    phase: int
    ordinal: int = 0

    def __post_init__(self):
        if any(type(v) is not int for v in (self.time, self.phase, self.ordinal)) or self.ordinal < 0:
            raise ValueError('Integer time/phase and nonnegative ordinal required')


@dataclass(frozen=True)
class Costs:
    commission: Fraction
    slip: Fraction
    annual_rate: Fraction


COSTS = {
    'S0': Costs(Fraction(0), Fraction(0), Fraction(0)),
    'S1': Costs(Fraction(7, 200), Fraction(1, 100000), Fraction(1, 20)),
    'S2': Costs(Fraction(7, 100), Fraction(1, 20000), Fraction(1, 10)),
}


@dataclass(frozen=True)
class Opportunity:
    identity: str
    side: int
    volatility: Fraction
    deadline: int
    causal_available: bool = True
    model_available: bool = True
    probability: Fraction | None = None


@dataclass(frozen=True)
class Quote:
    source_time: int | None
    bid: Fraction | None
    ask: Fraction | None
    identity: str
    valid: bool = True
    ambiguous: bool = False
    bid_min: Fraction | None = None
    ask_max: Fraction | None = None
    requires_recovery: bool = False
    quality_disclosed: bool = False


@dataclass(frozen=True)
class Position:
    identity: str
    side: int
    entry: Fraction
    entry_key: Key
    entry_source_time: int
    deadline: int
    cap: int
    stop: Fraction
    take: Fraction
    source_identity: str


@dataclass(frozen=True)
class Transaction:
    key: Key
    kind: str
    amount: Fraction
    trade: str | None
    certainty: str


@dataclass(frozen=True)
class Fill:
    key: Key
    trade: str
    price: Fraction
    kind: str
    slippage: Fraction


@dataclass(frozen=True)
class Snapshot:
    key: Key
    operational_cash: Fraction
    known_cash: Fraction
    conclusive_equity: Fraction | None
    scenario_equity: Fraction | None
    mark_wall_age: int | None
    mark_open_age: int | None
    state: str


@dataclass(frozen=True)
class PriceSummary:
    """Exact ordered liquidation-price summary from a certified held segment."""
    first: Fraction
    last: Fraction
    minimum: Fraction
    maximum: Fraction
    max_drop: Fraction
    max_rise: Fraction
    count: int


@dataclass(frozen=True)
class SegmentCertificate:
    start: Key
    end: Key
    first_source_time: int
    last_source_time: int
    max_internal_gap_open_ms: int
    no_hazards: bool
    proof_id: str
    first_identity: str
    last_identity: str


class Journal:
    """Append-only hash chain; immutable canonical text is the sink boundary."""
    def __init__(self, sink=None, retain=True):
        if not retain and sink is None:
            raise ValueError('Streaming mode needs durable journal sink')
        self.sink = sink
        self.records = [] if retain else None
        self.count = 0
        self.head = None

    def append(self, key, kind, **values):
        record = serializable(dict(sequence=self.count, previous=self.head, key=key, kind=kind, **values))
        body = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(body.encode()).hexdigest()
        line = json.dumps(dict(record, sha256=digest), sort_keys=True, separators=(',', ':'))
        if self.sink is not None:
            self.sink(line + '\n')
        if self.records is not None:
            self.records.append(line)
        self.head = digest
        self.count += 1


class Account:
    def __init__(self, clock, start, end, *, policy, bundle, arm, journal=None):
        if policy not in ('P0', 'P1') or bundle not in COSTS or arm not in ('primary', 'filtered'):
            raise ValueError('Unregistered scenario')
        if start >= end:
            raise ValueError('Invalid evaluation interval')
        self.clock, self.start, self.end = clock, start, end
        self.policy, self.bundle, self.arm = policy, bundle, arm
        self.costs = COSTS[bundle]
        self.journal = journal or Journal()
        self.state = 'FLAT'
        self.cash = INITIAL
        self.position = None
        self.pending = None
        self.last_key = None
        self.last_source_time = None
        self.last_quote = None
        self.last_exit_key = None
        self.hazard_key = None
        self.tainted_from = None
        self.recovery_needed = False
        self.gap_boundary = None
        self.permanent_unknown_cash = False
        self.transactions = []
        self.trade_intervals = []
        self.fills = []
        self.snapshots = {}
        self.active_period = None
        self.period_stats = {}
        self.counts = Counter()
        self.blocked = Counter()
        self.conditional_funding = Fraction(0)
        self.realized = Fraction(0)
        self.commissions = Fraction(0)
        self.slippage_attributed = Fraction(0)
        self.funding_recorded = Fraction(0)
        self.turnover_eur = Fraction(0)
        self.turnover_usd = Fraction(0)
        self.peak_notional = Fraction(0)
        self.wall_exposure = 0
        self.open_exposure = 0
        self.exposure_until = start
        self.mark_count = 0
        self.mark_missing = 0
        self.last_known_equity = INITIAL
        self.peak_equity = INITIAL
        self.max_dollar_drawdown = Fraction(0)
        self.drawdown_unknown = False
        self.capital_breach = False
        self.journal.append(Key(start, -1), 'initial', capital=INITIAL, units=UNITS,
                            policy=policy, bundle=bundle, arm=arm)

    def _exposure(self, t):
        if t < self.exposure_until:
            raise ValueError('Exposure time regression')
        if self.position is not None:
            self.wall_exposure += t - self.exposure_until
            self.open_exposure += self.clock.coordinate(t) - self.clock.coordinate(self.exposure_until)
        self.exposure_until = t

    @property
    def known_cash(self):
        return INITIAL + sum((r.amount for r in self.transactions
                              if r.certainty == 'conclusive' and (self.tainted_from is None or r.key < self.tainted_from)), Fraction(0))

    def _cashflow(self, key, kind, amount, certainty='conclusive'):
        transaction = Transaction(key, kind, amount, self.position.identity if self.position else None, certainty)
        self.transactions.append(transaction)
        if certainty != 'conditional':
            self.cash += amount
        self.journal.append(key, 'transaction', transaction_kind=kind, amount=amount,
                            trade=transaction.trade, certainty=certainty)

    def _equity(self, t, scenario=False):
        if self.permanent_unknown_cash or (self.tainted_from is not None and not scenario):
            return None
        if self.position is None:
            return self.cash
        if self.state == 'UNRESOLVED' or self.last_quote is None:
            return None
        age = self.clock.coordinate(t) - self.clock.coordinate(self.last_source_time)
        if age >= 60000:
            return None
        liquidation = self.last_quote[0 if self.position.side == 1 else 1]
        return self.cash + UNITS * self.position.side * (liquidation - self.position.entry)

    def _mark(self, key):
        equity = self._equity(key.time, scenario=True)
        self._period_mark(equity)
        self.mark_count += 1
        if equity is None:
            self.mark_missing += 1
            self.drawdown_unknown = True
        else:
            if self.tainted_from is None:
                self.last_known_equity = equity
            self.capital_breach |= equity < 0
            self.peak_equity = max(self.peak_equity, equity)
            self.max_dollar_drawdown = max(self.max_dollar_drawdown, self.peak_equity - equity)

    def _period_mark(self, equity, *, maximum=None, minimum=None, internal_drop=Fraction(0)):
        if self.active_period is None:
            return
        stats = self.period_stats[self.active_period]
        if equity is None:
            stats['unknown_marks'] = True
            return
        maximum = equity if maximum is None else maximum
        minimum = equity if minimum is None else minimum
        stats['drawdown'] = max(stats['drawdown'], stats['peak']-minimum, internal_drop)
        stats['peak'] = max(stats['peak'], maximum)
        stats['capital_breach'] |= minimum < 0

    def snapshot(self, key, name):
        if name in self.snapshots:
            raise ValueError('Duplicate boundary name')
        wall_age = None if self.last_source_time is None else key.time - self.last_source_time
        open_age = None if self.last_source_time is None else self.clock.coordinate(key.time) - self.clock.coordinate(self.last_source_time)
        snapshot = Snapshot(key, self.cash, self.known_cash, self._equity(key.time),
                            self._equity(key.time, scenario=True), wall_age, open_age, self.state)
        self._period_mark(snapshot.scenario_equity)
        if self.active_period is not None:
            self.period_stats[self.active_period]['end_name'] = name
        self.snapshots[name] = snapshot
        self.active_period = name
        self.period_stats[name] = dict(peak=snapshot.scenario_equity or INITIAL, drawdown=Fraction(0),
                                       unknown_marks=snapshot.scenario_equity is None, capital_breach=False,
                                       blocked=Counter(), model_unavailable=0, opportunities=0)
        self.journal.append(key, 'snapshot', name=name, **{k: v for k, v in snapshot.__dict__.items() if k != 'key'})
        if self.position is not None and snapshot.scenario_equity is None:
            self.drawdown_unknown = True
        return snapshot

    def next_timer(self, ignore_absence=False):
        timers = []
        if self.pending:
            timers.append(self.pending[0].time + 30000)
        if not ignore_absence and self.last_source_time is not None and self.gap_boundary is None:
            timers.append(self.clock.inverse(self.last_source_time, 60000))
        if self.position and self.state != 'UNRESOLVED':
            p = self.position
            if self.state == 'OPEN':
                timers.append(p.deadline)
            timers.append(p.cap)
        return min(timers) if timers else None

    def _timers(self, key, ignore_absence=False):
        if self.pending and key.time >= self.pending[0].time + 30000:
            self.journal.append(key, 'pending_expired', opportunity=self.pending[1].identity)
            self.pending = None
            self.state = 'FLAT'
            self.counts['entry_expired'] += 1
        if not ignore_absence and self.last_source_time is not None and self.gap_boundary is None:
            gap = self.clock.inverse(self.last_source_time, 60000)
            if key.time >= gap:
                self._hazard(Key(gap, PHASE['timer']), 'quote_gap', False)
        if self.position and self.state != 'UNRESOLVED':
            p = self.position
            gap = p.cap if ignore_absence else self.clock.inverse(self.last_source_time, 60000)
            if key.time >= min(gap, p.cap):
                boundary = min(gap, p.cap)
                self._hazard(Key(boundary, PHASE['timer']), 'quote_gap' if gap <= p.cap else 'timeout_unfilled', False)
            elif key.time >= p.deadline and self.state == 'OPEN':
                self.state = 'PENDING_TIMEOUT_EXIT'
                self.journal.append(key, 'deadline', trade=p.identity)

    def _hazard(self, key, reason, requires_recovery, affected_from=None):
        self.counts['integrity_events'] += 1
        self.recovery_needed |= requires_recovery
        self.gap_boundary = key.time if self.gap_boundary is None else max(self.gap_boundary, key.time)
        if self.pending:
            self.counts['entry_cancelled_quality'] += 1
            self.pending = None
            self.state = 'FLAT'
        if affected_from is not None:
            self.tainted_from = affected_from if self.tainted_from is None else min(self.tainted_from, affected_from)
            self.drawdown_unknown = True
            # No replacement of an already executed historical portfolio.
            if self.position is None or affected_from < self.position.entry_key:
                self.permanent_unknown_cash = True
                if self.position is None:
                    self.state = 'UNRESOLVED'
        if self.position and self.state != 'UNRESOLVED':
            self.state = 'UNRESOLVED'
            self.hazard_key = key
            self.tainted_from = key if self.tainted_from is None else min(key, self.tainted_from)
            self.drawdown_unknown = True
            self.counts['unresolved_events'] += 1
        self.journal.append(key, 'quality', reason=reason, affected_from=affected_from,
                            requires_recovery=requires_recovery, trade=self.position.identity if self.position else None)

    def _funding(self, key, factor):
        if factor not in (0, 1, 3):
            raise ValueError('Unregistered rollover factor')
        if self.position is None or factor == 0:
            return
        debit = UNITS * self.position.entry * self.costs.annual_rate * factor / 365
        certainty = 'conclusive'
        if self.state == 'UNRESOLVED':
            self.conditional_funding += debit
            certainty = 'conditional' if self.policy == 'P0' else 'scenario'
        elif self.tainted_from is not None:
            certainty = 'scenario'
        self._cashflow(key, 'funding', -debit, certainty)
        self.funding_recorded += debit
        self._mark(key)

    def _decision(self, key, opportunity):
        if not isinstance(opportunity, Opportunity):
            raise TypeError('Opportunity required')
        self.counts['opportunities'] += 1
        missing_model = self.arm == 'filtered' and not opportunity.model_available
        self.counts['opportunity_model_unavailable'] += int(missing_model)
        self.counts['opportunity_causal_unavailable'] += int(not opportunity.causal_available)
        if self.active_period is not None:
            self.period_stats[self.active_period]['opportunities'] += 1
            self.period_stats[self.active_period]['model_unavailable'] += int(missing_model)
        reason = None
        if self.position or self.pending or self.state == 'UNRESOLVED':
            reason = 'occupied_or_unresolved'
        elif self.last_exit_key is not None and self.last_exit_key.time == key.time:
            reason = 'same_time_reentry'
        elif opportunity.side not in (-1, 1):
            reason = 'no_primary_signal'
        elif not opportunity.causal_available:
            reason = 'causal_unavailable'
        elif self.recovery_needed:
            reason = 'recovery_1941_required'
        elif self.gap_boundary is not None:
            reason = 'awaiting_strict_quality_return'
        elif self.permanent_unknown_cash:
            reason = 'unknown_equity'
        elif self.arm == 'filtered' and not opportunity.model_available:
            reason = 'model_unavailable'
        elif self.arm == 'filtered' and opportunity.probability is None:
            reason = 'probability_unavailable'
        elif self.arm == 'filtered' and not 0 <= rational(opportunity.probability) <= 1:
            raise ValueError('Probability outside [0,1]')
        elif self.arm == 'filtered' and rational(opportunity.probability) < Fraction(1, 2):
            reason = 'filter_rejected'
        elif rational(opportunity.volatility) <= 0:
            reason = 'invalid_volatility'
        elif opportunity.deadline <= key.time or self.clock.inverse(opportunity.deadline, 60000) >= self.end:
            reason = 'final_window'
        elif not self.clock.active(key.time):
            reason = 'off_session_decision'
        if reason:
            self.blocked[reason] += 1
            if self.active_period is not None:
                self.period_stats[self.active_period]['blocked'][reason] += 1
        else:
            self.pending = key, replace(opportunity, volatility=rational(opportunity.volatility))
            self.state = 'PENDING_ENTRY'
            self.counts['pending_entries'] += 1
        self.journal.append(key, 'decision', opportunity=opportunity.identity, reason=reason,
                            side=opportunity.side, probability=opportunity.probability)

    def _fill_entry(self, key, quote, bid, ask):
        pending_key, opportunity = self.pending
        if not pending_key.time <= quote.source_time < pending_key.time + 30000:
            return
        side = opportunity.side
        fill = (ask if side == 1 else bid) + side * self.costs.slip
        take = fill + side * Fraction(5, 2) * opportunity.volatility
        stop = fill - side * opportunity.volatility
        self.pending = None
        if min(fill, take, stop) <= 0 or UNITS * fill + self.costs.commission > self.cash:
            self.counts['entry_invalid_or_capital'] += 1
            self.state = 'FLAT'
            self.journal.append(key, 'entry_rejected', opportunity=opportunity.identity, reason='invalid_fill_barrier_or_capital')
            return
        self.position = Position(opportunity.identity, side, fill, key, quote.source_time,
                                 opportunity.deadline, self.clock.inverse(opportunity.deadline, 60000),
                                 stop, take, quote.identity)
        self.state = 'OPEN'
        self.hazard_key = None
        certainty = 'conclusive' if self.tainted_from is None else 'scenario'
        self._cashflow(key, 'entry_commission', -self.costs.commission, certainty)
        self.commissions += self.costs.commission
        self.slippage_attributed += UNITS * self.costs.slip
        self.turnover_eur += UNITS
        self.turnover_usd += UNITS * fill
        self.peak_notional = max(self.peak_notional, UNITS * fill)
        self.counts['entries'] += 1
        self.fills.append(Fill(key, opportunity.identity, fill, 'entry', UNITS * self.costs.slip))
        self.journal.append(key, 'entry', trade=opportunity.identity, price=fill, source=quote.identity,
                            side=side, take=take, stop=stop)

    def _exit(self, key, quote, fill, reason):
        p = self.position
        if fill <= 0:
            self._hazard(key, 'invalid_exit_arithmetic', True)
            return False
        certainty = 'conclusive' if self.tainted_from is None else 'scenario'
        pnl = UNITS * p.side * (fill - p.entry)
        self._cashflow(key, 'realized_pnl', pnl, certainty)
        self._cashflow(key, 'exit_commission', -self.costs.commission, certainty)
        self.realized += pnl
        self.commissions += self.costs.commission
        if reason != 'take_profit':
            self.slippage_attributed += UNITS * self.costs.slip
        self.turnover_eur += UNITS
        self.turnover_usd += UNITS * fill
        self.trade_intervals.append((p.entry_key, key, p.identity))
        self.counts['exits'] += 1
        self.fills.append(Fill(key, p.identity, fill, reason, Fraction(0) if reason == 'take_profit' else UNITS * self.costs.slip))
        self.counts[reason] += 1
        self.journal.append(key, 'exit', trade=p.identity, price=fill, source=quote.identity,
                            reason=reason, pnl=pnl, information_end=quote.source_time + 1,
                            certainty=certainty)
        self.position = None
        self.state = 'FLAT'
        self.last_exit_key = key
        self.hazard_key = None
        self.conditional_funding = Fraction(0)
        self._mark(key)  # Excludes the terminal quote's hypothetical pre-fill peak.
        return True

    def _source(self, key, quote):
        if not isinstance(quote, Quote):
            raise TypeError('Quote required')
        if not quote.valid or quote.source_time is None:
            self._hazard(key, 'invalid_source', True)
            return
        if quote.source_time > key.time:
            raise ValueError('Future quote disclosed before its timestamp')
        try:
            bid, ask = rational(quote.bid), rational(quote.ask)
        except (ValueError, TypeError):
            self._hazard(key, 'invalid_price', True)
            return
        if bid <= 0 or ask < bid:
            self._hazard(key, 'invalid_pair', True)
            return
        if not quote.quality_disclosed and self.last_source_time is not None and quote.source_time < self.last_source_time:
            self._hazard(key, 'chronology', True)
        if not self.clock.active(quote.source_time):
            self.counts['off_session_quotes'] += 1
            return
        if quote.ambiguous and not quote.quality_disclosed:
            self._hazard(key, 'ambiguous_group', True)
        if self.state == 'UNRESOLVED':
            if self.policy == 'P1' and self.position and self.hazard_key and quote.source_time > self.hazard_key.time:
                side = self.position.side
                adverse = rational(quote.bid_min) if side == 1 and quote.bid_min is not None else rational(quote.ask_max) if side == -1 and quote.ask_max is not None else bid if side == 1 else ask
                if quote.ambiguous and ((side == 1 and quote.bid_min is None) or (side == -1 and quote.ask_max is None)):
                    raise ValueError('Adverse side extreme required for ambiguous P1 liquidation')
                exited = self._exit(key, quote, adverse - side * self.costs.slip, 'p1_adverse_liquidation')
                if exited and not quote.ambiguous:
                    self.gap_boundary = None
                    self.last_source_time = quote.source_time
                    self.last_quote = bid, ask
            return
        if quote.ambiguous:
            return
        if self.gap_boundary is not None:
            if quote.source_time <= self.gap_boundary:
                return
            self.gap_boundary = None
        self.last_source_time = quote.source_time
        self.last_quote = bid, ask
        if self.position:
            p = self.position
            if quote.source_time > p.entry_source_time:
                liquidation = bid if p.side == 1 else ask
                if self.state == 'PENDING_TIMEOUT_EXIT':
                    self._exit(key, quote, liquidation - p.side * self.costs.slip, 'timeout')
                elif p.side * (liquidation - p.stop) <= 0:
                    self._exit(key, quote, liquidation - p.side * self.costs.slip, 'stop')
                elif p.side * (liquidation - p.take) >= 0:
                    self._exit(key, quote, p.take, 'take_profit')
            if self.position:
                self._mark(key)
            return
        if self.pending and (self.last_exit_key is None or self.last_exit_key.time != key.time):
            self._fill_entry(key, quote, bid, ask)
            if self.position:
                self._mark(key)

    def process(self, key, kind, payload=None):
        """Process monotonic full keys. Timers before this key are inserted exactly.

        Source quality events use phase 4 and source ordinals, never global phase 2.
        Snapshot and funding events must be supplied at their actual calendar times.
        Recovery is a source-ordered declaration by the verified bar-history caller.
        """
        if self.state == 'ENDED':
            raise ValueError('Account already ended')
        if key.time < self.start or key.time > self.end or (self.last_key is not None and key <= self.last_key):
            raise ValueError('Nonmonotonic or out-of-window full event key')
        expected = PHASE.get(kind, PHASE['source'] if kind in ('quality', 'recovery', 'segment', 'refresh', 'quiescent') else None)
        if kind == 'timer_quality':
            expected = PHASE['timer']
        elif kind == 'prestart_quality':
            expected = PHASE['snapshot']
        elif kind == 'decision_recovery':
            expected = PHASE['decision']
        if expected is None or key.phase != expected:
            raise ValueError('Wrong event phase')
        certificate = payload.get('certificate') if kind in ('segment', 'refresh') else None
        if certificate is not None:
            self._validate_certificate(key, certificate, kind)
        ignore_absence = certificate is not None
        timer = self.next_timer(ignore_absence=ignore_absence)
        while timer is not None and Key(timer, PHASE['timer']) < key:
            timer_key = Key(timer, PHASE['timer'])
            self._exposure(timer)
            self._timers(timer_key, ignore_absence=ignore_absence)
            timer = self.next_timer(ignore_absence=ignore_absence)
        self._exposure(key.time)
        if kind == 'snapshot':
            result = self.snapshot(key, payload)
        elif kind == 'funding':
            result = self._funding(key, payload)
        elif kind == 'timer':
            result = self._timers(key)
        elif kind == 'decision':
            result = self._decision(key, payload)
        elif kind == 'source':
            result = self._source(key, payload)
        elif kind in ('quality', 'timer_quality', 'prestart_quality'):
            result = self._hazard(key, **payload)
        elif kind in ('recovery', 'decision_recovery'):
            if payload != 1941:
                raise ValueError('Recovery requires exactly registered caller certificate 1941')
            self.recovery_needed = False
            self.journal.append(key, 'recovery', observed_bars=1941)
            result = None
        elif kind == 'segment':
            result = self._segment(key, **payload)
        elif kind == 'refresh':
            if certificate is None:
                raise ValueError('Flat refresh requires continuity certificate')
            result = self._refresh(key, **payload)
        elif kind == 'quiescent':
            if self.state != 'UNRESOLVED' or (self.policy == 'P1' and self.position is not None):
                raise ValueError('Quiescent skip only for absorbing unresolved account')
            self.journal.append(key, 'quiescent_exposure', state=self.state)
            result = None
        else:
            result = self._finish(key)
        self.last_key = key
        return result

    def _validate_certificate(self, key, certificate, kind):
        if not isinstance(certificate, SegmentCertificate) or certificate.no_hazards is not True or not certificate.proof_id or not certificate.first_identity or not certificate.last_identity:
            raise ValueError('Index continuity certificate required')
        c = certificate
        if c.end != key or c.start > key or (self.last_key is not None and c.start <= self.last_key):
            raise ValueError('Certificate key range must strictly follow processed prefix')
        if (type(c.max_internal_gap_open_ms) is not int or not 0 <= c.max_internal_gap_open_ms < 60000
                or not c.start.time <= c.first_source_time <= c.last_source_time <= key.time
                or not self.clock.active(c.first_source_time) or not self.clock.active(c.last_source_time)):
            raise ValueError('Invalid eligible-source continuity bound')
        if self.last_source_time is not None and self.gap_boundary is None:
            if self.clock.coordinate(c.first_source_time)-self.clock.coordinate(self.last_source_time) >= 60000:
                raise ValueError('Uncertified initial absence before segment')
        if self.clock.coordinate(key.time)-self.clock.coordinate(c.last_source_time) >= 60000:
            raise ValueError('Uncertified terminal absence after segment')
        if self.pending is not None or self.state == 'UNRESOLVED':
            raise ValueError('Cannot skip pending fills or unresolved P1 return')
        if self.position is not None and c.first_source_time <= self.position.entry_source_time:
            raise ValueError('Held certificate must exclude entry timestamp')
        if self.position is not None and key.time >= self.position.deadline:
            raise ValueError('Certificate cannot skip deadline')
        if kind == 'refresh' and self.position is not None:
            raise ValueError('Flat refresh cannot skip held marks')

    def _refresh(self, key, certificate, last_pair):
        bid, ask = (rational(v) for v in last_pair)
        if bid <= 0 or ask < bid:
            raise ValueError('Invalid refresh pair')
        if self.gap_boundary is not None and certificate.first_source_time <= self.gap_boundary:
            raise ValueError('Strict return must be after hazard boundary')
        self.gap_boundary = None
        self.last_source_time = certificate.last_source_time
        self.last_quote = bid, ask
        self.journal.append(key, 'flat_refresh', proof_id=certificate.proof_id,
                            start=certificate.start, last_source_time=certificate.last_source_time)

    def _segment(self, key, summary, last_source_time, last_pair, certified_start, certificate=None):
        """Index adapter: whole segment is eligible, ordered, barrier/hazard-free.

        Caller must split at every funding, deadline, gap, decision and boundary.
        No exit/entry group may be included. This fast path never invents quotes.
        """
        if not isinstance(summary, PriceSummary) or summary.count <= 0 or not self.position or self.state != 'OPEN':
            raise ValueError('Held segment contract invalid')
        if certified_start <= self.position.entry_key or certified_start > key:
            raise ValueError('Segment must exclude entry group')
        if certificate is not None and (certified_start != certificate.start or last_source_time != certificate.last_source_time):
            raise ValueError('Certificate/segment endpoints disagree')
        if self.next_timer(ignore_absence=certificate is not None) is not None and key.time >= self.next_timer(ignore_absence=certificate is not None):
            raise ValueError('Segment crosses a clock boundary')
        if last_source_time > key.time or last_source_time < self.last_source_time or not self.clock.active(last_source_time):
            raise ValueError('Invalid segment terminal source timestamp')
        pair = tuple(rational(v) for v in last_pair)
        if len(pair) != 2 or pair[0] <= 0 or pair[1] < pair[0]:
            raise ValueError('Invalid segment terminal quote pair')
        p = self.position
        if pair[0 if p.side == 1 else 1] != summary.last:
            raise ValueError('Segment terminal summary/quote mismatch')
        lo, hi = summary.minimum, summary.maximum
        if lo <= 0 or not 0 <= summary.max_drop <= hi-lo or not 0 <= summary.max_rise <= hi-lo:
            raise ValueError('Invalid ordered extrema')
        if lo > hi or not lo <= summary.first <= hi or not lo <= summary.last <= hi:
            raise ValueError('Invalid exact range summary')
        if (p.side == 1 and (lo <= p.stop or hi >= p.take)) or (p.side == -1 and (lo <= p.take or hi >= p.stop)):
            raise ValueError('Segment contains a terminal touch')
        offset = self.cash - UNITS * p.side * p.entry
        maximum = offset + UNITS * (hi if p.side == 1 else -lo)
        minimum = offset + UNITS * (lo if p.side == 1 else -hi)
        internal_drop = UNITS * (summary.max_drop if p.side == 1 else summary.max_rise)
        self._period_mark(offset + UNITS*p.side*summary.last, maximum=maximum, minimum=minimum, internal_drop=internal_drop)
        self.max_dollar_drawdown = max(self.max_dollar_drawdown, self.peak_equity - minimum, internal_drop)
        self.peak_equity = max(self.peak_equity, maximum)
        self.capital_breach |= minimum < 0
        self.last_source_time = last_source_time
        self.last_quote = tuple(rational(v) for v in last_pair)
        self.mark_count += summary.count
        if self.tainted_from is None:
            self.last_known_equity = offset + UNITS * p.side * summary.last
        self.journal.append(key, 'held_segment', count=summary.count, start=certified_start,
                            last_source_time=last_source_time, proof_id=None if certificate is None else certificate.proof_id)

    def _finish(self, key):
        if key.time != self.end:
            raise ValueError('End must equal registered evaluation end')
        if 'final' not in self.snapshots:
            raise ValueError('Supply pre-clock final boundary snapshot before ending')
        if self.pending:
            self.counts['pending_at_end'] += 1
        self.counts['unresolved_at_end'] = int(self.position is not None and self.state == 'UNRESOLVED')
        self.state = 'ENDED'
        self.journal.append(key, 'ended', unresolved=self.counts['unresolved_at_end'])
        return self.report()

    def quarterly(self, start_name, end_name):
        left, right = self.snapshots[start_name], self.snapshots[end_name]
        tainted = self.tainted_from is not None and self.tainted_from < right.key
        known = None if tainted or left.conclusive_equity is None or right.conclusive_equity is None else right.conclusive_equity - left.conclusive_equity
        scenario = None if self.permanent_unknown_cash or left.scenario_equity is None or right.scenario_equity is None else right.scenario_equity - left.scenario_equity
        stats = self.period_stats[start_name]
        if stats.get('end_name') != end_name:
            raise ValueError('Period report requires adjacent declared boundaries')
        flows = [r for r in self.transactions if left.key.time <= r.key.time < right.key.time]
        fills = [f for f in self.fills if left.key.time <= f.key.time < right.key.time]
        exposure = list(self.trade_intervals)
        if self.position:
            exposure.append((self.position.entry_key, Key(min(self.exposure_until, self.end), PHASE['end']), self.position.identity))
        wall = open_ms = 0
        for begin, end, _ in exposure:
            a, b = max(begin.time, left.key.time), min(end.time, right.key.time)
            if a < b:
                wall += b-a
                open_ms += self.clock.coordinate(b)-self.clock.coordinate(a)
        return dict(conclusive_pnl=known, scenario_pnl=scenario,
                    model_available=stats['model_unavailable'] == 0, opportunities=stats['opportunities'],
                    blocked=dict(stats['blocked']),
                    max_dollar_drawdown=None if tainted or stats['unknown_marks'] else stats['drawdown'],
                    capital_breach=stats['capital_breach'],
                    realized_recorded=sum((r.amount for r in flows if r.kind == 'realized_pnl'), Fraction(0)),
                    commission=sum((-r.amount for r in flows if r.kind.endswith('commission')), Fraction(0)),
                    funding_recorded=sum((-r.amount for r in flows if r.kind == 'funding'), Fraction(0)),
                    slippage_attribution_only=sum((f.slippage for f in fills), Fraction(0)),
                    turnover_eur=UNITS*len(fills), turnover_usd=UNITS*sum((f.price for f in fills), Fraction(0)),
                    entries=sum(f.kind == 'entry' for f in fills), exits=sum(f.kind != 'entry' for f in fills),
                    wall_exposure_ms=wall, open_exposure_ms=open_ms,
                    recorded_cashflow=sum((r.amount for r in flows if r.certainty != 'conditional'), Fraction(0)),
                    conditional_funding=sum((-r.amount for r in flows if r.certainty == 'conditional'), Fraction(0)))

    def report(self):
        final = self.snapshots.get('final')
        conclusive = None if final is None or self.tainted_from is not None else final.conclusive_equity
        scenario = None if final is None or self.permanent_unknown_cash else final.scenario_equity
        return dict(policy=self.policy, bundle=self.bundle, arm=self.arm, state=self.state,
                    conclusive_equity=conclusive, conclusive_pnl=None if conclusive is None else conclusive - INITIAL,
                    arm_model_available=self.counts['opportunity_model_unavailable'] == 0,
                    potential_exposure_unknown=self.permanent_unknown_cash,
                    scenario_equity=scenario, scenario_pnl=None if scenario is None else scenario - INITIAL,
                    cash=self.cash, known_cash=self.known_cash, realized_pnl=self.realized,
                    conclusive_unrealized=None if conclusive is None else conclusive-final.operational_cash,
                    scenario_unrealized=None if scenario is None else scenario-final.operational_cash,
                    net_return=None if conclusive is None else (conclusive-INITIAL)/INITIAL,
                    commission=self.commissions, slippage_attribution_only=self.slippage_attributed,
                    funding_recorded=self.funding_recorded, funding_if_still_open=self.conditional_funding,
                    turnover_eur=self.turnover_eur, turnover_usd=self.turnover_usd,
                    wall_exposure_ms=self.wall_exposure, open_exposure_ms=self.open_exposure,
                    peak_notional=self.peak_notional, last_known_equity=self.last_known_equity,
                    max_dollar_drawdown=None if self.drawdown_unknown or self.tainted_from is not None else self.max_dollar_drawdown,
                    drawdown_fraction_initial=None if self.drawdown_unknown or self.tainted_from is not None else self.max_dollar_drawdown / INITIAL,
                    capital_breach=self.capital_breach, mark_count=self.mark_count, mark_missing=self.mark_missing,
                    counts=dict(self.counts), blocked=dict(self.blocked), journal_head=self.journal.head,
                    conditional_scenario_not_lower_bound=self.policy == 'P1', profit_claim=False)


def make_portfolios(clock, start, end, journal_factory=None):
    accounts = {}
    for policy in ('P0', 'P1'):
        for bundle in ('S0', 'S1', 'S2'):
            for arm in ('primary', 'filtered'):
                identity = policy, bundle, arm
                journal = None if journal_factory is None else journal_factory(identity)
                accounts[identity] = Account(clock, start, end, policy=policy, bundle=bundle, arm=arm, journal=journal)
    return accounts


def economic_diagnostics(accounts, periods):
    """Descriptive G4/G5 only. Never authorizes/vetoes confirmation opening."""
    results = {}
    for policy in ('P0', 'P1'):
        primary = accounts[policy, 'S1', 'primary']
        filtered = accounts[policy, 'S1', 'filtered']
        comparisons = []
        for left, right in periods:
            pr = primary.quarterly(left, right)
            fr = filtered.quarterly(left, right)
            p = pr['conclusive_pnl']
            f = fr['conclusive_pnl'] if fr['model_available'] else None
            comparisons.append(None if p is None or f is None else f > 0 and f > p)
        stress = accounts[policy, 'S2', 'filtered'].report()
        pnl, dd = stress['conclusive_pnl'], stress['max_dollar_drawdown']
        g5 = None if pnl is None or dd is None or not stress['arm_model_available'] else pnl > 0 and dd <= INITIAL / 20 and not stress['capital_breach']
        primary_total, filtered_total = primary.report(), filtered.report()
        ptotal, ftotal = primary_total['conclusive_pnl'], filtered_total['conclusive_pnl']
        annual = None if ptotal is None or ftotal is None or not filtered_total['arm_model_available'] else ftotal > 0 and ftotal > ptotal
        results[policy] = dict(annual_s1_positive_and_improves=annual, quarterly_s1_positive_and_improves=tuple(comparisons),
                               s2_positive_and_drawdown=g5, opening_gate=False)
    return results


@dataclass(frozen=True)
class Event:
    key: Key
    kind: str
    payload: object = None


def replay_events(accounts, events):
    """One ordered pass for the fixed 12 accounts; no sorting or market loading.

    Source-only dense adapter for small fixtures. For scale, the index supervisor
    dispatches account-specific certified segments directly via Account.process.
    The journal sink handles decisions and state-changing events; unchanged dense
    marks need not allocate per-tick records, and source identity remains in the
    immutable verified input index owned by the caller.
    """
    previous = None
    for event in events:
        if previous is not None and event.key <= previous:
            raise ValueError('Event stream must preserve full disclosure order')
        if event.kind == 'segment':
            raise ValueError('Held summaries are account/side-specific')
        for account in accounts.values():
            account.process(event.key, event.kind, event.payload)
        previous = event.key
    return {identity: account.report() for identity, account in accounts.items()}
