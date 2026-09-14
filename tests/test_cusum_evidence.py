import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fxnn.cusum_evidence import export_evidence, verify_ledger
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
            original_open = Path.open
            def guarded_open(path, mode='r', *args, **kwargs):
                if path == ledger.path and any(flag in mode for flag in ('w', 'a', '+')):
                    self.fail('Audit attempted writable ledger access')
                return original_open(path, mode, *args, **kwargs)
            with patch.object(Path, 'open', guarded_open):
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
            missing = root/'missing'/'ledger.jsonl'
            with self.assertRaises(FileNotFoundError):
                export_evidence(report, missing, output2)
            self.assertFalse(missing.parent.exists())

    def test_ledger_snapshot_chain_rejects_edits_and_truncation(self):
        path = Path(__file__).resolve().parents[1]/'docs/experiments/cusum-v1-ledger.jsonl'
        raw = path.read_bytes()
        records = verify_ledger(raw)
        for field, value in [('previous', 'wrong'), ('sequence', 99), ('max_fits', 22)]:
            changed = [dict(record) for record in records]
            changed[1][field] = value
            with self.assertRaisesRegex(ValueError, 'Corrupt ledger snapshot'):
                verify_ledger(('\n'.join(json.dumps(record) for record in changed)+'\n').encode())
        for broken in (b'', raw[:-8]):
            with self.assertRaises(ValueError):
                verify_ledger(broken)

    def test_published_evidence_hashes_and_zero_fit_ledger(self):
        root = Path(__file__).resolve().parents[1]/'docs/experiments'
        manifest = json.loads((root/'cusum-v1-evidence.json').read_text())
        for name, expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), expected)
        records = verify_ledger((root/'cusum-v1-ledger.jsonl').read_bytes())
        self.assertEqual([r['kind'] for r in records], ['genesis', 'run_started', 'run_finished'])
        self.assertEqual(records[-1]['consumed_total'], 0)
        self.assertEqual(records[-1]['result']['report_sha256'], manifest['files']['cusum-v1.json'])
