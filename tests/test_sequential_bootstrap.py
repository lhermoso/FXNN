from decimal import Decimal, localcontext
import unittest
import numpy as np
from fxnn.sequential_bootstrap import IntervalIndex, sample, canonical_order, seed_for

FIXTURE = np.array([(0,3),(2,4),(4,6),(0,10),(0,10),(3,7),(6,12),(10,15),(14,20),(20,25),(25,30),(0,30)], dtype=np.int64)


def dense_probabilities(intervals, chosen):
    indicator = np.array([[int(a <= t < b) for a,b in intervals] for t in range(30)], float)
    c = indicator[:, chosen].sum(axis=1) if chosen else np.zeros(30)
    u = np.array([(1/(c[col > 0]+1)).mean() for col in indicator.T])
    return u/u.sum()


class SequentialTests(unittest.TestCase):
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
