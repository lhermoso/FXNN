"""All-minute causal opportunities from already closed bid bars.

No outcome, future quote or trained transform is accepted by this interface.
The caller feeds the source scheduler in its original event order.
"""
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
import math

import numpy as np


WINDOWS = (5, 15, 60, 240)
HISTORY = 1941
NAMES = tuple(name for w in WINDOWS for name in (
    f'return_{w}', f'volatility_{w}', f'range_pips_{w}', f'zscore_{w}',
    f'efficiency_{w}')) + ('body', 'upper_wick', 'lower_wick', 'hour_sin',
    'hour_cos', 'weekday_sin', 'weekday_cos', 'direction')


class OpportunityBuilder:
    """Bounded history and an immutable feature snapshot between bar closes."""
    def __init__(self, clock):
        self.clock = clock
        self.bars = deque()
        self.anchors = {}
        self.returns = deque(maxlen=500)
        self.required = 241
        self.quality_pending = False
        self.ordinal = 0
        self.last_event = None
        self.cached = None
        self.reset_reason = 'initial_history'
        self.segment = 0

    def reset(self, reason, *, integrity=True):
        self.bars.clear()
        self.anchors.clear()
        self.returns.clear()
        self.ordinal = 0
        self.quality_pending = self.quality_pending or integrity
        self.required = HISTORY if self.quality_pending else 241
        self.cached = None
        self.reset_reason = str(reason)
        self.segment += 1

    def on_bar(self, bar):
        if (bar.end != bar.start+60000 or not self.clock.is_open(bar.start)
                or (self.last_event is not None and bar.end < self.last_event)):
            raise ValueError('Expected ordered completed open-minute bars')
        self.last_event = bar.end
        if not bar.valid:
            self.reset('invalid_bar', integrity=True)
            return
        prices = (bar.open, bar.high, bar.low, bar.close)
        if (not all(isinstance(p, Decimal) and p.is_finite() and p > 0 for p in prices)
                or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high):
            raise ValueError('Positive finite exact OHLC required')
        if self.bars:
            if bar.start <= self.bars[-1].start:
                raise ValueError('Cannot reopen historical bar')
            if self.clock.elapsed(self.bars[-1].end, bar.start) >= 15*60000:
                self.reset('missing_15_open_minutes', integrity=False)
        coordinate = self.clock.coordinate(bar.start)
        anchor = self.anchors.get(coordinate-1440*60000)
        value, anchor_start = None, None
        if anchor is not None:
            try:
                value = float(bar.close)/float(anchor.close)-1
            except (OverflowError, ZeroDivisionError):
                value = math.nan
            anchor_start = anchor.start
        self.returns.append((self.ordinal, value, anchor_start))
        self.ordinal += 1
        self.bars.append(bar)
        self.anchors[coordinate] = bar
        if len(self.bars) > HISTORY:
            old = self.bars.popleft()
            del self.anchors[self.clock.coordinate(old.start)]
        self.cached = None

    def _history(self):
        if self.cached is not None:
            return self.cached.copy()
        result = dict(side=0, history_valid=False, feature_valid=False,
                      volatility_valid=False, reason='insufficient_history',
                      values=None, sigma=None, price_volatility=None,
                      earliest_input=None, valid_returns=0,
                      observed_history=len(self.bars), segment=self.segment)
        if len(self.bars) < self.required:
            self.cached = result
            return result.copy()
        bars = list(self.bars)
        last = bars[-1]
        result['history_valid'] = True
        self.quality_pending = False
        result['side'] = int(last.close > bars[-61].close)-int(last.close < bars[-61].close)
        result['earliest_input'] = bars[0].start
        p = np.asarray([[float(b.open), float(b.high), float(b.low), float(b.close)]
                        for b in bars[-241:]], dtype=np.float64)
        with np.errstate(all='ignore'):
            o, h, l, c = p.T
            returns = np.diff(np.log(c))
            features = []
            side = result['side']
            for w in WINDOWS:
                r = returns[-w:]
                net = float(np.sum(r))
                vol = math.sqrt(float(np.mean((r-net/w)**2)))
                mean = float(np.mean(c[-w:]))
                std = math.sqrt(float(np.mean((c[-w:]-mean)**2)))
                features.extend((side*net, vol, float(np.mean(h[-w:]-l[-w:]))/.0001,
                                 side*(c[-1]-mean)/max(std, .00001),
                                 abs(net)/max(float(np.sum(np.abs(r))), 1e-12)))
            scale = max(h[-1]-l[-1], .00001)
            features.extend((side*(c[-1]-o[-1])/scale,
                             (h[-1]-max(c[-1], o[-1]))/scale,
                             (min(c[-1], o[-1])-l[-1])/scale))
        result['feature_valid'] = bool(np.isfinite(features).all())
        result['values'] = features if result['feature_valid'] else None
        available = [(i, v, a) for i, v, a in self.returns if v is not None]
        result['valid_returns'] = len(available)
        if available:
            result['earliest_input'] = min(result['earliest_input'], min(a for _, _, a in available))
        if len(available) >= 100:
            weights = [(1-2/101)**(self.ordinal-1-i) for i, _, _ in available]
            values = [v for _, v, _ in available]
            if all(math.isfinite(v) for v in values):
                total = math.fsum(weights)
                shifted = [v-values[0] for v in values]
                mean = math.fsum(w*v for w, v in zip(weights, shifted))/total
                denominator = total-math.fsum(w*w for w in weights)/total
                try:
                    variance = math.fsum(w*(v-mean)**2 for w, v in zip(weights, shifted))/denominator
                except OverflowError:
                    variance = math.inf
                sigma = math.sqrt(variance)
                price = sigma*float(last.close)
                if math.isfinite(price) and price > 0:
                    result.update(sigma=sigma, price_volatility=price, volatility_valid=True)
                else:
                    result['reason'] = 'zero_or_nonfinite_volatility'
            else:
                result['reason'] = 'nonfinite_volatility'
        if not result['feature_valid']:
            result['reason'] = 'nonfinite_features'
        elif result['volatility_valid']:
            result['reason'] = '' if result['side'] else 'no_signal'
        self.cached = result
        return result.copy()

    def decision(self, time, evaluation_end):
        if time % 60000 or not self.clock.is_open(time):
            raise ValueError('Scheduled open minute required')
        if self.last_event is not None and time < self.last_event:
            raise ValueError('Decision cannot precede disclosed history')
        if self.bars and self.bars[-1].end > time:
            raise ValueError('Only completed bars may enter a decision')
        if self.bars and self.clock.elapsed(self.bars[-1].end, time) >= 15*60000:
            self.reset('missing_15_open_minutes', integrity=False)
        self.last_event = time
        result = self._history()
        values = result.pop('values')
        if values is not None:
            date = datetime.fromtimestamp(time//1000, timezone.utc)
            hour = date.hour+date.minute/60
            values = list(values)+[math.sin(2*math.pi*hour/24), math.cos(2*math.pi*hour/24),
                                   math.sin(2*math.pi*date.weekday()/7),
                                   math.cos(2*math.pi*date.weekday()/7), result['side']]
        deadline = cap = None
        try:
            deadline = self.clock.advance(time, 4320*60000)
            cap = self.clock.advance(deadline, 60000)
        except ValueError:
            pass
        result.update(id=f'economic_ticks_v1:{time}', decision_ms=time, X=values,
                      deadline_ms=deadline, information_cap_ms=cap,
                      calendar_eligible=cap is not None and cap < evaluation_end,
                      reset_reason=self.reset_reason)
        result['eligible'] = bool(result['side'] and result['feature_valid']
                                  and result['volatility_valid'] and result['calendar_eligible'])
        if not result['calendar_eligible']:
            result['reason'] = 'evaluation_end'
        return result

    def export_history(self):
        """Authorized development warmup; contains no trained or label state."""
        return dict(version=1,bars=[dict(start=b.start,end=b.end,open=str(b.open),
                    high=str(b.high),low=str(b.low),close=str(b.close),valid=b.valid,
                    observations=b.observations) for b in self.bars],
                    returns=[(i,None if v is None else v if math.isfinite(v) else 'nonfinite',a)
                             for i,v,a in self.returns],
                    required=self.required,quality_pending=self.quality_pending,
                    ordinal=self.ordinal,last_event=self.last_event,
                    reset_reason=self.reset_reason,segment=self.segment)

    @classmethod
    def from_history(cls, clock, state, cutoff):
        from fxnn.tick_economic_source import BidBar
        if state['version']!=1 or state['last_event'] is not None and state['last_event']>cutoff:
            raise ValueError('Warmup exceeds authorized cutoff')
        result=cls(clock)
        for row in state['bars']:
            if row['end']>cutoff:
                raise ValueError('Future warmup bar')
            result.on_bar(BidBar(row['start'],row['end'],*(Decimal(row[k]) for k in ('open','high','low','close')),
                                row['valid'],row['observations']))
        if len(state['returns'])>500 or len(state['bars'])>HISTORY or state['required'] not in (241,HISTORY):
            raise ValueError('Warmup resource/schema mismatch')
        result.returns=deque(((i,math.nan if v=='nonfinite' else v,a) for i,v,a in state['returns']),maxlen=500)
        result.required=state['required'];result.quality_pending=state['quality_pending']
        result.ordinal=state['ordinal'];result.last_event=state['last_event']
        result.reset_reason=state['reset_reason'];result.segment=state['segment']
        result.cached=None
        return result
