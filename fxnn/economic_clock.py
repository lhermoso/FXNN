"""Exact millisecond session time; calendar exclusions never synthesize quotes."""
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone

from .session_clock import weekly_fx_clock

MIN_I64, MAX_I64 = -(2**63), 2**63-1


def integer_ms(value):
    if type(value) is not int or not MIN_I64 < value <= MAX_I64:
        raise ValueError('Expected representable integer milliseconds')
    return value


def utc_ms(text):
    value = datetime.fromisoformat(text)
    if value.tzinfo is None or value.microsecond % 1000:
        raise ValueError('Timezone and exact millisecond timestamp required')
    delta = value.astimezone(timezone.utc)-datetime(1970, 1, 1, tzinfo=timezone.utc)
    return integer_ms((delta.days*86400+delta.seconds)*1000+delta.microseconds//1000)


class SessionClockMs:
    """Intervals are half-open UTC ranges, with earliest-wall elapsed inverse."""
    def __init__(self, first, stop, intervals):
        self.first, self.stop = integer_ms(first), integer_ms(stop)
        if stop <= first:
            raise ValueError('Ordered clock bounds required')
        self.starts, self.ends, self.prefix = [], [], [0]
        for a, b in intervals:
            integer_ms(a); integer_ms(b)
            if not first <= a < b <= stop or (self.ends and a < self.ends[-1]):
                raise ValueError('Open intervals must be ordered and disjoint')
            if self.ends and a == self.ends[-1]:
                self.ends[-1] = b
                self.prefix[-1] += b-a
            else:
                self.starts.append(a); self.ends.append(b)
                self.prefix.append(self.prefix[-1]+b-a)

    @classmethod
    def weekly(cls, first, stop):
        if first % 60000 or stop % 60000:
            raise ValueError('Weekly calendar bounds must be minute boundaries')
        base = weekly_fx_clock(first//1000, stop//1000)
        intervals, begin = [], None
        for i, active in enumerate(base.active):
            if active and begin is None:
                begin = first+i*60000
            if not active and begin is not None:
                intervals.append((begin, first+i*60000)); begin = None
        if begin is not None:
            intervals.append((begin, stop))
        return cls(first, stop, intervals)

    def _check(self, value):
        integer_ms(value)
        if not self.first <= value <= self.stop:
            raise ValueError('Timestamp outside registered calendar')

    def coordinate(self, value):
        self._check(value)
        i = bisect_right(self.starts, value)-1
        return 0 if i < 0 else self.prefix[i]+min(value, self.ends[i])-self.starts[i]

    def elapsed(self, start, end):
        if end < start:
            raise ValueError('Ordered time interval required')
        return self.coordinate(end)-self.coordinate(start)

    def is_open(self, value):
        self._check(value)
        i = bisect_right(self.starts, value)-1
        return i >= 0 and value < self.ends[i]

    def advance(self, origin, duration):
        self._check(origin)
        if type(duration) is not int or duration < 0:
            raise ValueError('Nonnegative integer open duration required')
        if duration == 0:
            return origin
        target = self.coordinate(origin)+duration
        if target > self.prefix[-1]:
            raise ValueError('Calendar does not cover requested open duration')
        i = bisect_left(self.prefix, target)-1
        return integer_ms(self.starts[i]+target-self.prefix[i])

    def next_open(self, value):
        self._check(value)
        if self.is_open(value):
            return value
        i = bisect_left(self.starts, value)
        return self.starts[i] if i < len(self.starts) else None

    def minutes(self, start=None, end=None):
        start = self.first if start is None else start
        end = self.stop if end is None else end
        self._check(start); self._check(end)
        for a, b in zip(self.starts, self.ends):
            begin = max(a, ((start+59999)//60000)*60000)
            yield from range(begin, min(b, end), 60000)
