import csv
import lzma
import struct
import tempfile
import unittest
from pathlib import Path

from scripts.download_year import decode, export


def payload(rows):
    return lzma.compress(b"".join(struct.pack(">IIIIIf",*row) for row in rows))


class YearDownloadTests(unittest.TestCase):
    def test_record_order_is_open_close_low_high(self):
        result=decode(payload([(60,110000,110010,109990,110020,2.0)]))
        self.assertEqual(result[60],(110000,110020,109990,110010,2.0))

    def test_invalid_records_rejected(self):
        for row in [(86400,100,100,90,110,1),(1,100,100,90,110,1),
                    (0,100,100,110,90,1),(0,100,100,90,110,float('nan'))]:
            with self.assertRaises(ValueError):
                decode(payload([row]))
        with self.assertRaises(ValueError):
            decode(payload([(0,100,100,90,110,1)]*2))
        with self.assertRaises(ValueError):
            decode(lzma.compress(b"x"))

    def test_export_joins_sides_and_reports_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'raw_m1').mkdir()
            records=[]
            for day in ('2025-01-02','2025-01-03'):
                for side in ('BID','ASK'):
                    key=f'{day}_{side}.bi5'
                    sec=60 if day.endswith('03') and side=='ASK' else 0
                    value=110000 if side=='BID' else 110010
                    (root/'raw_m1'/key).write_bytes(payload([(sec,value,value,value,value,0)]))
                    records.append({'day':day,'side':side,'key':key,'status':'ok'})
            report=export(records,root,2025)
            self.assertEqual(report['bars'],1)
            self.assertEqual(report['daily_coverage'][0]['zero_volume_bars'],1)
            self.assertEqual(report['daily_coverage'][1]['status'],'unmatched_sides')
            with Path(report['csv']).open() as f:
                row=next(csv.DictReader(f))
            self.assertEqual(row['bid_open'],'1.10000')
            self.assertEqual(row['ask_open'],'1.10010')
