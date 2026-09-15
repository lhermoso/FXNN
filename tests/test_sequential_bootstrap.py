from decimal import Decimal, localcontext
import sys
import unittest
from unittest.mock import patch
import numpy as np
from fxnn.sequential_bootstrap import ATOL, RTOL, IntervalIndex, sample, canonical_order, seed_for

FIXTURE = np.array([(0,3),(2,4),(4,6),(0,10),(0,10),(3,7),(6,12),(10,15),(14,20),(20,25),(25,30),(0,30)], dtype=np.int64)


def dense_probabilities(intervals, chosen):
    indicator = np.array([[int(a <= t < b) for a,b in intervals] for t in range(30)], float)
    c = indicator[:, chosen].sum(axis=1) if chosen else np.zeros(30)
    u = np.array([(1/(c[col > 0]+1)).mean() for col in indicator.T])
    return u/u.sum()


def decimal_uniqueness(intervals, chosen):
    """Independent integer-input oracle; never consume rounded index terms."""
    intervals = [(int(a), int(b)) for a, b in intervals]
    edges = sorted({x for interval in intervals for x in interval})
    positions = {edge: i for i, edge in enumerate(edges)}
    changes = [0] * len(edges)
    for event in chosen:
        a, b = intervals[event]
        changes[positions[a]] += 1
        changes[positions[b]] -= 1
    with localcontext() as context:
        context.prec = 80
        prefix = [Decimal(0)]
        concurrency = 0
        for i, (a, b) in enumerate(zip(edges, edges[1:])):
            concurrency += changes[i]
            prefix.append(prefix[-1] + Decimal(b-a)/Decimal(concurrency+1))
        return [(prefix[positions[b]]-prefix[positions[a]])/Decimal(b-a)
                for a, b in intervals]


class SequentialTests(unittest.TestCase):
    def assert_decimal_bounds(self, intervals, chosen, all_tree=False):
        index = IntervalIndex(intervals[:, 0], intervals[:, 1])
        for event in chosen:
            index.add(event)
        visits = []
        previous = sys.getprofile()
        tree_code = getattr(IntervalIndex._tree_queries, '__code__', None)
        def capture(frame, event, arg):
            if event == 'return' and frame.f_code is tree_code:
                visits.append((frame.f_locals['contributions'].copy(), frame.f_locals['levels']))
        try:
            sys.setprofile(capture)
            values, info = index.uniqueness()
        finally:
            sys.setprofile(previous)
        with localcontext() as context:
            context.prec = 80
            for value, exact, bound in zip(values, decimal_uniqueness(intervals, chosen), info['errors']):
                actual_error = abs(Decimal.from_float(float(value))-exact)
                self.assertLessEqual(actual_error, Decimal.from_float(float(bound)))
                self.assertLessEqual(actual_error, Decimal.from_float(ATOL)+Decimal.from_float(RTOL)*abs(exact))
        self.assertLessEqual(info['max_levels'], index.height+1)
        for contributions, levels in visits:
            self.assertTrue(np.all(contributions <= 2*index.height+2))
            self.assertLessEqual(levels, index.height+1)
        if all_tree:
            self.assertEqual(info['tree_queries'], len(intervals))
            self.assertEqual(sum(len(counts) for counts, _ in visits), len(intervals))
        return index, values, info

    def test_manual_and_dense_every_draw(self):
        index = IntervalIndex(FIXTURE[:3,0], FIXTURE[:3,1])
        index.add(1)
        np.testing.assert_allclose(index.probabilities()[0], [5/14,3/14,6/14], rtol=1e-12,atol=1e-14)
        index.add(2)
        np.testing.assert_allclose(index.probabilities()[0], [5/11,3/11,3/11], rtol=1e-12,atol=1e-14)
        for seed in (0,1):
            with self.subTest(seed=seed):
                chosen = []
                uniforms = np.random.Generator(np.random.PCG64(seed)).random(512)
                def check(step, probabilities):
                    expected = dense_probabilities(FIXTURE, chosen)
                    np.testing.assert_allclose(probabilities, expected, rtol=1e-12,atol=1e-14)
                    cdf = np.cumsum(expected); cdf[-1] = 1
                    chosen.append(int(np.searchsorted(cdf, uniforms[step], side='right')))
                result = sample(FIXTURE[:,0], FIXTURE[:,1], uniforms, 'sequential', check)
                np.testing.assert_array_equal(result['draws'], chosen)

    def test_positive_cancellation_decimal_and_bounded_tree(self):
        index = IntervalIndex(np.array([0,10**18,10**18+2],np.int64), np.array([10**18,10**18+1,10**18+7],np.int64))
        index.add(0)
        values, info = index.uniqueness()
        with localcontext() as context:
            context.prec = 80
            expected = [Decimal(1)/2, Decimal(1), Decimal(1)]
            for value, exact, bound in zip(values,expected,info['errors']):
                self.assertLessEqual(abs(Decimal(float(value))-exact), Decimal(float(bound)))
        self.assertGreater(info['tree_queries'], 0)
        self.assertLessEqual(info['max_levels'], index.height+1)

    def test_positive_inaccurate_prefix_inside_mathematical_bounds(self):
        intervals = np.array([(0, 10**18), (10**18, 10**18+100)], dtype=np.int64)
        index, values, info = self.assert_decimal_bounds(intervals, [0, 1])
        prefix = np.r_[0., np.cumsum(index.d/(index.c+1))]
        naive = (prefix[index.R]-prefix[index.L])/index.D
        self.assertGreater(naive[1], 1/(index.draw_count+1))
        self.assertLess(naive[1], 1)
        self.assertGreater(abs(naive[1]-.5), .1)
        self.assertEqual(values[1], .5)
        self.assertEqual(info['tree_queries'], 1)
        # A guard-bypass mutant is numerically plausible but fails the independent oracle.
        with patch.object(IntervalIndex, '_tree_queries', return_value=(naive[1:].copy(), 1)):
            with self.assertRaises(AssertionError):
                self.assert_decimal_bounds(intervals, [0, 1])

    def test_decimal_overlapping_ranges_and_tree_boundaries(self):
        # Seventeen leaves exercise power-of-two boundaries and zero padding.
        edges = [0, 10**18]
        for width in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59):
            edges.append(edges[-1]+width)
        intervals = list(zip(edges, edges[1:]))
        intervals += [(edges[a], edges[b]) for a, b in ((1, 9), (3, 16), (8, 16), (1, 17), (4, 12))]
        intervals = np.array(intervals, dtype=np.int64)
        chosen = [0, 17, 17, 18, 20, 21, 8, 8, 8]
        index, _, info = self.assert_decimal_bounds(intervals, chosen)
        self.assertEqual(len(index.d), 17)
        self.assertEqual(index.size, 32)
        self.assertGreater(len(np.unique(index.c)), 3)
        self.assertGreater(info['tree_queries'], 10)

    def test_all_candidates_use_bounded_tree_against_decimal80(self):
        edges = np.r_[0, np.cumsum((np.arange(4097) % 17)+1)]
        intervals = list(zip(edges[:-1], edges[1:]))
        intervals += [(edges[a], edges[b]) for a, b in ((0, 4097), (1, 2048), (1023, 4096), (2048, 4097))]
        intervals = np.array(intervals, dtype=np.int64)
        self.assert_decimal_bounds(intervals, [4097, 4098, 4098, 4099, 4100, 1023], all_tree=True)

    def test_order_repeats_and_raw_uniqueness(self):
        ids = np.array([9,3,8])
        order, inverse = canonical_order(ids)
        np.testing.assert_array_equal(ids[order], [3,8,9])
        np.testing.assert_array_equal(order[inverse], np.arange(3))
        with self.assertRaises(ValueError): canonical_order(np.array([1,1]))
        result = sample(np.array([0,0]), np.array([3,3]), np.zeros(512), 'uniform')
        self.assertEqual(len(result['draws']),512)
        self.assertAlmostEqual(result['diagnostics']['raw_mean_uniqueness'], 1/512)
        self.assertEqual(result['diagnostics']['distinct_ids'],1)
        self.assertEqual(seed_for('hash','temporal',0,1), seed_for('hash','temporal',0,1))

    def test_checked_integer_width_and_unsigned_coordinates(self):
        index=IntervalIndex(np.array([-100],np.int8),np.array([100],np.int8))
        np.testing.assert_array_equal(index.D,[200.])
        index=IntervalIndex(np.array([2**63+1],np.uint64),np.array([2**63+5],np.uint64))
        np.testing.assert_array_equal(index.D,[4.])
        with self.assertRaisesRegex(ValueError,'overflow'):
            IntervalIndex(np.array([0],np.uint64),np.array([2**64-1],np.uint64))
