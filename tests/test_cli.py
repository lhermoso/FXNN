import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CLITests(unittest.TestCase):
    def test_ambiguous_and_censored_never_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'input.csv'; output=root/'result'
            source.write_text('timestamp,open,high,low,close\n'
                '2025-01-06T00:00:00+00:00,1.1000,1.1050,1.0950,1.1000\n'
                '2025-01-06T00:01:00+00:00,1.1000,1.1050,1.0990,1.1000\n'
                '2025-01-06T00:02:00+00:00,1.1000,1.1010,1.0990,1.1000\n')
            run=subprocess.run([sys.executable,'-m','fxnn',str(source),'--pip-size','.0001',
                '--bar-minutes','1','--verify-samples','3','--output',str(output)],capture_output=True,text=True,check=True)
            report=json.loads(run.stdout)
            self.assertEqual(report['discarded_outcomes'],{'ambiguous':2,'censored':2})
            self.assertEqual(report['usable_labels'],2)
            self.assertEqual(report['verified_trade_labels'],6)
            for filename in ('all_trades.csv','selected_trades.csv','hard_negatives.csv'):
                with (output/filename).open() as stream:
                    rows=list(csv.DictReader(stream))
                self.assertTrue(all(r['outcome'] in ('take_profit','stop_loss','timeout') for r in rows))
            with (output/'all_trades.csv').open() as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual({r['label'] for r in rows},{'0','1'})
