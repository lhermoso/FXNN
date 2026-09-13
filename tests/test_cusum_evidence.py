import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fxnn.cusum_evidence import export_evidence
from fxnn.fit_ledger import FitLedger


class EvidenceTests(unittest.TestCase):
    def test_byte_exact_export_and_historical_ledger_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root/'report.json'
            report.write_text(json.dumps(dict(experiment='cusum_v1', status='stopped',
                                             fits_consumed=0, global_fits_consumed=0))+'\n')
            ledger = FitLedger(root/'ledger.jsonl')
            ledger.initialize(0, {'fixture': True})
            ledger.start_run('cusum_v1', 21, {'fixture': True})
            ledger.finish_run('cusum_v1', 'stopped', {
                'report_sha256': hashlib.sha256(report.read_bytes()).hexdigest(), 'fits_consumed': 0})
            snapshot = ledger.path.read_bytes()
            output = root/'export'
            manifest = export_evidence(report, ledger.path, output)
            self.assertEqual((output/'cusum-v1.json').read_bytes(), report.read_bytes())
            self.assertEqual((output/'cusum-v1-ledger.jsonl').read_bytes(), snapshot)
            for name, expected in manifest['files'].items():
                self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(), expected)
            ledger.start_run('future_fixture', 1, {'fixture': True})
            self.assertEqual(export_evidence(report, ledger.path, output), manifest)
            self.assertEqual((output/'cusum-v1-ledger.jsonl').read_bytes(), snapshot)
            (output/'cusum-v1.json').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'Existing evidence differs'):
                export_evidence(report, ledger.path, output)
            output2 = root/'mismatch'
            report.write_text(report.read_text()+' ')
            with self.assertRaisesRegex(ValueError, 'Report does not match'):
                export_evidence(report, ledger.path, output2)
            self.assertFalse(output2.exists())

    def test_published_evidence_hashes_and_zero_fit_ledger(self):
        root = Path(__file__).resolve().parents[1]/'docs/experiments'
        manifest = json.loads((root/'cusum-v1-evidence.json').read_text())
        for name, expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), expected)
        records = [json.loads(line) for line in (root/'cusum-v1-ledger.jsonl').read_text().splitlines()]
        self.assertEqual([r['kind'] for r in records], ['genesis', 'run_started', 'run_finished'])
        self.assertEqual(records[-1]['consumed_total'], 0)
        self.assertEqual(records[-1]['result']['report_sha256'], manifest['files']['cusum-v1.json'])
