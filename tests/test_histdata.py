import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts.download_histdata import normalize, utc_stamp


class HistDataTests(unittest.TestCase):
    def test_fixed_est_in_winter_and_summer(self):
        self.assertEqual(utc_stamp('20250102 120000').hour,17)
        self.assertEqual(utc_stamp('20250702 120000').hour,17)
        self.assertEqual(utc_stamp('20251231 230000').isoformat(),'2026-01-01T04:00:00+00:00')

    def test_annual_normalization_preserves_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); archive=root/'data.zip'
            with ZipFile(archive,'w') as z:
                z.writestr('DAT_ASCII_EURUSD_M1_2025.csv',''.join(
                    f'2025{m:02}02 120000;1.1;1.2;1.0;1.15;0\n' for m in range(1,13)))
            report=normalize(archive,root,2025)
            self.assertEqual(report['rows'],12)
            self.assertEqual(report['gaps'],11)
            self.assertEqual(report['price_side'],'bid')

    def test_incomplete_archive_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); archive=root/'data.zip'
            with ZipFile(archive,'w') as z:
                z.writestr('DAT_ASCII_EURUSD_M1_2025.csv','20250102 120000;1.1;1.2;1.0;1.15;0\n')
            with self.assertRaises(ValueError):normalize(archive,root,2025)

    def test_all_conflicting_occurrences_quarantined(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); archive=root/'data.zip'
            rows=''.join(f'2025{m:02}02 120000;1.1;1.2;1.0;1.15;0\n' for m in range(1,13))
            rows+='20251202 130000;1.1;1.2;1.0;1.15;0\n20251202 130000;1.2;1.3;1.1;1.25;0\n'
            with ZipFile(archive,'w') as z:z.writestr('DAT_ASCII_EURUSD_M1_2025.csv',rows)
            report=normalize(archive,root,2025)
            self.assertEqual(report['rows'],12)
            self.assertEqual(report['duplicate_timestamps'],1)
            self.assertEqual(report['quarantined_rows'],2)
