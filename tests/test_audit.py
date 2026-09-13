import unittest
from datetime import datetime, timezone
from decimal import Decimal
from fxnn.audit import monthly_audit
from fxnn.labeling import Trade


class AuditTests(unittest.TestCase):
    def trade(self, i, month, outcome):
        time = datetime(2025, month, 1, tzinfo=timezone.utc)
        return Trade(i, 'long', time, time, Decimal('1.1'), None, outcome, None)

    def test_monthly_denominators_and_exclusions(self):
        trades = [self.trade(0, 1, 'take_profit'), self.trade(1, 1, 'stop_loss'),
                  self.trade(2, 1, 'censored'), self.trade(3, 1, 'ambiguous'),
                  self.trade(4, 1, 'boundary'), self.trade(5, 2, 'timeout')]
        report = monthly_audit(trades, {(1, 1), (5, 1)})
        january = report['2025-01']
        self.assertEqual(january['candidates'], 5)
        self.assertEqual(january['excluded_labels'], 3)
        self.assertEqual(january['conclusive']['positive_fraction'], .5)
        self.assertEqual(january['excluded_feature_warmup_or_gaps']['positives'], 1)
        self.assertEqual(january['retained']['positive_fraction'], 0)
        self.assertEqual(report['2025-02']['retained']['negatives'], 1)

    def test_empty_retained_and_invalid_keys(self):
        trades = [self.trade(0, 1, 'censored')]
        report = monthly_audit(trades, set())
        self.assertIsNone(report['2025-01']['retained']['positive_fraction'])
        for keys in ({(0, 1)}, {(1, 1)}):
            with self.assertRaises(ValueError):
                monthly_audit(trades, keys)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            monthly_audit(trades * 2, set())
