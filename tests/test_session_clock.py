import unittest
from datetime import datetime, timezone

import numpy as np

from fxnn.session_clock import SessionClock, calendar_from_rule


def stamp(text):
    return int(datetime.fromisoformat(text).timestamp())


class SessionClockTests(unittest.TestCase):
    def test_weekend_pauses_but_missing_weekday_minutes_do_not(self):
        # Synthetic UTC weekdays: test mechanics without choosing real calendar.
        clock=calendar_from_rule(stamp('2023-01-06T00:00:00+00:00'),
                                 stamp('2023-01-13T00:00:00+00:00'),lambda t:t.weekday()<5)
        entry=stamp('2023-01-06T17:00:00+00:00')
        deadline=clock.deadlines(np.array([entry]))[0]
        self.assertEqual(deadline,stamp('2023-01-11T17:00:00+00:00'))
        self.assertEqual(clock.elapsed(np.array([entry]),np.array([deadline]))[0],4320)
        observations=np.array([stamp(t) for t in ['2023-01-06T23:59:00+00:00',
                              '2023-01-09T00:00:00+00:00','2023-01-09T00:04:00+00:00']])
        self.assertEqual(clock.missing_open_minutes(observations).tolist(),[0,3])
        self.assertEqual(clock.gap_breaks(observations).tolist(),[False,False,False])

    def test_fourteen_allowed_fifteen_censors(self):
        clock=SessionClock(0,np.ones(100,dtype=bool))
        self.assertEqual(clock.missing_open_minutes(np.array([0,15*60,31*60])).tolist(),[14,15])
        self.assertEqual(clock.gap_breaks(np.array([0,15*60,31*60])).tolist(),[False,False,True])
        self.assertEqual(clock.deadlines(np.array([0]),20).tolist(),[20*60])

    def test_exact_close_deadline_not_moved_to_reopening(self):
        clock=SessionClock(0,np.array([True]*10+[False]*20+[True]*10))
        self.assertEqual(clock.deadlines(np.array([0]),10).tolist(),[600])
        self.assertEqual(clock.deadlines(np.array([0]),11).tolist(),[31*60])
        self.assertEqual(clock.missing_open_minutes(np.array([9*60,30*60])).tolist(),[0])

    def test_price_gaps_never_define_clock_and_calendar_is_copied(self):
        mask=np.ones(100,dtype=bool)
        clock=SessionClock(0,mask)
        mask[:]=False
        self.assertEqual(clock.deadlines(np.array([0]),72).tolist(),[72*60])
        self.assertEqual(clock.gap_breaks(np.array([0,20*60])).tolist(),[False,True])
        self.assertEqual(clock.deadlines(np.array([0]),72).tolist(),[72*60])

    def test_reject_invalid_calendar_or_timestamps(self):
        for mask in (np.array([1,0]),np.array([],dtype=bool),np.array([[True]])):
            with self.assertRaises(ValueError):SessionClock(0,mask)
        clock=SessionClock(0,np.array([True,False,True]))
        for stamps in (np.array([30]),np.array([-60]),np.array([60]),np.array([0.])):
            with self.assertRaises(ValueError):clock.deadlines(stamps,1)
        with self.assertRaises(ValueError):clock.deadlines(np.array([0]),3)
        with self.assertRaises(ValueError):clock.gap_breaks(np.array([0,0]))
        with self.assertRaises(ValueError):clock.gap_breaks(np.array([0,60]))
        with self.assertRaises(ValueError):clock.gap_breaks(np.array([0]),0)
