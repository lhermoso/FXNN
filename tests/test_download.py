import csv
import gzip
import lzma
import struct
import tempfile
import unittest
from pathlib import Path

from scripts.download_dukascopy import decode, export


class DownloadTests(unittest.TestCase):
    def test_binary_order_and_time_base(self):
        payload = lzma.compress(struct.pack(">IIIff", 3599999, 110005, 110000, 2, 3))
        self.assertEqual(list(decode(payload)), [(3599999, 110005, 110000, 2, 3)])
        for row in ((3600000, 110005, 110000, 2, 3), (0, 110000, 110005, 2, 3)):
            with self.assertRaises(ValueError):
                list(decode(lzma.compress(struct.pack(">IIIff", *row))))
        with self.assertRaises(ValueError):
            list(decode(lzma.compress(b"truncated")))

    def test_exports_keep_sides_and_do_not_fill_gaps(self):
        rows = [(0, 110005, 110000, 2, 3), (59999, 110015, 110010, 2, 3),
                (120000, 110000, 109995, 2, 3)]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "raw").mkdir()
            (root / "raw/hour.bi5").write_bytes(lzma.compress(b"".join(struct.pack(">IIIff", *r) for r in rows)))
            result = export([{"status": "ok", "hour": "2025-01-06T12:00:00+00:00", "key": "hour.bi5"}], root, "test")
            self.assertEqual((result["ticks"], result["m1_bars"]), (3, 2))
            self.assertEqual(result["mean_spread_pips"], 0.5)
            with (root / "test_m1_bid_ask.csv").open() as stream:
                bars = list(csv.DictReader(stream))
            self.assertEqual(bars[0]["bid_open"], "1.10000")
            self.assertEqual(bars[0]["ask_high"], "1.10015")
            self.assertEqual(bars[1]["timestamp"], "2025-01-06T12:02:00+00:00")
            with gzip.open(root / "test_ticks.csv.gz", "rt") as stream:
                ticks = list(csv.DictReader(stream))
            self.assertEqual(ticks[1]["timestamp"], "2025-01-06T12:00:59.999+00:00")


if __name__ == "__main__":
    unittest.main()
