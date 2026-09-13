import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.audit_gaps import audit, category


class GapAuditTests(unittest.TestCase):
    def test_weekend_boundary_does_not_swallow_reopening(self):
        self.assertEqual(category(datetime(2023, 4, 9, 19, 59, tzinfo=timezone.utc), set()), "weekend_candidate")
        self.assertEqual(category(datetime(2023, 4, 9, 20, tzinfo=timezone.utc), set()), "unresolved")

    def test_holiday_not_invented_as_closure(self):
        stamp = datetime(2023, 12, 25, 12, tzinfo=timezone.utc)
        self.assertEqual(category(stamp, set()), "unresolved")
        self.assertEqual(category(stamp, {stamp}), "quarantined")

    def test_mixed_gap_reconciles_and_converts_quarantine_timezone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "EURUSD_2023_manifest.json").write_text("{}")
            (root / "EURUSD_2023_quarantine.csv").write_text(
                "source_timestamp_EST\n20230409 150000\n")
            (root / "EURUSD_2023_gaps.json").write_text(json.dumps([{
                "previous": "2023-04-09T19:58:00+00:00",
                "next": "2023-04-09T20:02:00+00:00", "missing_minutes": 3}]))
            result = audit(root, 2023)
            self.assertEqual(result["missing_minutes"], {
                "weekend_candidate": 1, "quarantined": 1, "unresolved": 1})
            self.assertEqual(result["monthly_source_timezone"]["2023-04"], result["missing_minutes"])
