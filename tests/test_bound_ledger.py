import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from fxnn.bound_ledger import BoundStageLedger
from fxnn.experiment_fit import StageLedger


class BoundLedgerTests(unittest.TestCase):
    def test_atomic_intervening_runs(self):
        for fits in (0, 1):
            with self.subTest(fits=fits), TemporaryDirectory() as tmp:
                path = Path(tmp)/'ledger'
                ordinary = StageLedger(path)
                ordinary.initialize(0, 'synthetic')
                frozen = hashlib.sha256(path.read_bytes()).hexdigest()
                bound = BoundStageLedger(path, 7, 0, frozen)
                ordinary.start_run('intervening', 1, {'fixture': 1})
                if fits:
                    ordinary.start_fit('intervening', 'fit', 'fold', {}, {})
                    ordinary.finish_fit('intervening', 'fit', 'succeeded', {})
                ordinary.finish_run('intervening', 'completed', {})
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'Frozen ledger'):
                    bound.start_run('meta', 24, {'fixture': 1})
                self.assertEqual(path.read_bytes(), before)

    def test_exact_bytes_success_and_validation(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'ledger'
            ordinary = StageLedger(path); ordinary.initialize(0, 'synthetic')
            raw = path.read_bytes()
            bound = BoundStageLedger(path, 7, 0, hashlib.sha256(raw).hexdigest())
            path.write_bytes(raw.replace(b'\n', b'\r\n'))
            with self.assertRaisesRegex(ValueError, 'Frozen ledger'):
                bound.start_run('meta', 24, {'fixture': 1})
            path.write_bytes(raw)
            bound.start_run('meta', 24, {'fixture': 1})
            self.assertEqual(bound.records()[-1]['kind'], 'run_started')
            for count, digest in ((-1, 'a'*64), (True, 'a'*64), (0, 'wrong')):
                with self.assertRaises(ValueError):
                    BoundStageLedger(path, 7, count, digest)

    def test_inherited_unfinished_and_corrupt_chain_guards(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'ledger'
            original = StageLedger(path); original.initialize(0, 'fixture')
            original.start_run('active', 1, {'fixture': 1})
            bound = BoundStageLedger(path, 7, 0, hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, 'Unfinished research run'):
                bound.start_run('meta', 24, {'fixture': 1})
            original.finish_run('active', 'completed', {})
            raw = path.read_bytes().replace(b'fixture', b'corrupt')
            path.write_bytes(raw)
            bound = BoundStageLedger(path, 7, 0, hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(ValueError, 'Corrupt fit ledger'):
                bound.start_run('meta', 24, {'fixture': 1})
