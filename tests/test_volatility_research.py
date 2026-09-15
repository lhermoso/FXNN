"""Synthetic runner persistence, prediction replay and failure boundaries."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from fxnn.experiment_fit import StageLedger
from fxnn.research import Dataset
from fxnn.session_clock import weekly_fx_clock
from fxnn import volatility_research as runner


class VolatilityResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root/'result'
        self.ledger = StageLedger(self.root/'ledger.jsonl')
        self.ledger.initialize(0, 'synthetic test fixture')
        self.prefix = self.ledger.path.read_bytes()
        starts = np.arange(1641214800, 1641214800+60*80, 60, dtype=np.int64)
        self.clock = weekly_fx_clock(int(starts[0])-86400, int(starts[-1])+86400)
        data = Dataset(X=np.column_stack((np.sin(np.arange(80)), np.arange(80)/80)),
                       y=np.arange(80) % 2, starts=starts, ends=starts+180,
                       info_ends=starts+240, entry_indices=np.arange(80), sides=np.ones(80, dtype=int),
                       names=['a', 'b'], groups={'fixture': [0, 1]}, dropped_warmup=0)
        self.protocol = {'folds': [{'name': f'q{i}'} for i in (2, 3, 4)]}
        partitions = {f'q{i}': dict(train=np.arange(20), refit=np.arange(30),
                                   validation=np.arange(35, 45), test=np.arange(50, 70))
                      for i in (2, 3, 4)}
        masks = {str(h): np.ones(80, dtype=bool) for h in (.0005, .001)}
        self.tasks = {task: dict(data=data, masks=masks, partitions=partitions) for task in runner.TASKS}
        self.spec = dict(expected_prior_fits=0, max_model_fits=48, thresholds=[.0005, .001],
                         logistic={'random_state': 0, 'max_iter': 1000}, global_ledger=str(self.ledger.path))
        self.hashes = {'source': 'synthetic'}
        self.manifest = {'input_hashes': {'fixture': 'synthetic'}}

    def execute(self):
        with redirect_stdout(io.StringIO()):
            return runner.execute(self.tasks, self.protocol, self.spec, self.clock, self.ledger,
                                  self.hashes, self.output, self.manifest)

    def test_complete_replay_exact_with_cached_fits(self):
        report = self.execute()
        # Identical populations and repeated training pasts reuse contracts.
        self.assertEqual(report['new_fits'], 8)
        self.assertEqual(report['fits_after'], 8)
        self.assertFalse(report['conclusion']['task_ranking_performed'])
        raw = self.ledger.path.read_bytes()
        count = runner.replay_reports(self.tasks, self.protocol, self.spec, self.clock, self.ledger,
                                      self.hashes, self.output, report['tasks'], self.prefix)
        self.assertEqual(count, 1080)
        self.assertEqual(self.ledger.path.read_bytes(), raw)
        terminal = self.ledger.records()[-1]
        self.assertEqual(terminal['result']['report_sha256'], runner.digest(self.output/'report.json'))
        self.assertEqual(terminal['status'], 'completed')
        with self.assertRaises((FileExistsError, ValueError)):
            self.execute()

    def test_prediction_export_failure_aborts_before_next_fit(self):
        with patch.object(runner, 'save_arrays', side_effect=OSError('prediction disk')):
            with self.assertRaisesRegex(OSError, 'prediction disk'):
                self.execute()
        self.assertEqual(self.ledger.consumed(), 2)
        self.assertEqual(self.ledger.records()[-1]['status'], 'aborted')
        self.assertEqual(len(list((self.output/'models').glob('*.npz'))), 2)
        self.assertFalse((self.output/'report.json').exists())

    def test_final_report_failure_and_failure_json_failure_still_close(self):
        original = runner.write_json

        def fail_final(path, value):
            if path.name == 'report.json':
                raise OSError('final report disk')
            return original(path, value)

        with patch.object(runner, 'write_json', side_effect=fail_final):
            with patch('fxnn.experiment_fit.write_json', wraps=original) as helper_write:
                # Only failure.json fails; successful per-fit companions still persist.
                helper_write.side_effect = lambda path, value: (_ for _ in ()).throw(OSError('failure disk')) if path.name == 'failure.json' else original(path, value)
                with self.assertRaisesRegex(OSError, 'final report disk'):
                    self.execute()
        self.assertEqual(self.ledger.consumed(), 8)
        self.assertEqual(self.ledger.records()[-1]['status'], 'aborted')
        self.assertFalse((self.output/'failure.json').exists())

    def test_finish_run_failure_never_claims_completion(self):
        original = self.ledger.finish_run

        def fail_completion(experiment, status, result):
            if status == 'completed':
                raise OSError('ledger completion disk')
            return original(experiment, status, result)

        with patch.object(self.ledger, 'finish_run', side_effect=fail_completion):
            with self.assertRaisesRegex(OSError, 'completion disk'):
                self.execute()
        self.assertTrue((self.output/'report.json').exists())
        self.assertEqual(self.ledger.records()[-1]['status'], 'aborted')
        self.assertFalse((self.output/'ledger-after.jsonl').exists())

    def test_replay_rejects_training_and_prediction_changes(self):
        report = self.execute()
        task = self.tasks['fixed']['data']
        task.X[0, 0] += 1
        with self.assertRaisesRegex(ValueError, 'training contract'):
            runner.replay_reports(self.tasks, self.protocol, self.spec, self.clock, self.ledger,
                                  self.hashes, self.output, report['tasks'], self.prefix)
        task.X[0, 0] -= 1
        prediction = next(self.output.glob('fixed_q2_inner_*.npz'))
        prediction.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Artifact changed'):
            runner.replay_reports(self.tasks, self.protocol, self.spec, self.clock, self.ledger,
                                  self.hashes, self.output, report['tasks'], self.prefix)

    def test_full_verify_read_only_and_terminal_binding(self):
        dataset = self.root/'dataset'
        dataset.mkdir()
        (dataset/'manifest.json').write_text('{}')
        spec_path, protocol_path = self.root/'spec.json', self.root/'protocol.md'
        spec_path.write_text('{}')
        protocol_path.write_text('synthetic preregistration')
        (self.root / 'fxnn').mkdir()
        module = self.root / 'fxnn/synthetic.py'
        module.write_text('# frozen synthetic source\n')
        self.hashes = dict(config=runner.digest(spec_path), protocol=runner.digest(protocol_path),
                           source_hashes={'synthetic.py': runner.digest(module)}, dataset_manifest=runner.digest(dataset/'manifest.json'),
                           ledger_before=hashlib.sha256(self.prefix).hexdigest())
        self.execute()
        raw = self.ledger.path.read_bytes()
        with patch.object(runner, 'SPEC', spec_path), patch.object(runner, 'CONTRACT', protocol_path), \
                patch.object(runner, 'load_contract', return_value=(self.spec, self.protocol)), \
                patch.object(runner, 'ROOT', self.root), \
                patch.object(runner, 'load_data', return_value=(self.tasks, self.clock, self.manifest)):
            result = runner.verify(self.output, dataset)
            self.assertEqual(result['predictions_replayed'], 1080)
            self.assertEqual(self.ledger.path.read_bytes(), raw)
            report = json.loads((self.output/'report.json').read_text())
            report['new_fits'] += 1
            (self.output/'report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'authoritative completed'):
                runner.verify(self.output, dataset)

    def test_later_modules_do_not_invalidate_frozen_source_replay(self):
        (self.root / 'fxnn').mkdir()
        module = self.root / 'fxnn/frozen.py'
        module.write_text('# frozen\n')
        expected = {'frozen.py': runner.digest(module)}
        (self.root / 'fxnn/later_stage.py').write_text('# new independent stage\n')
        with patch.object(runner, 'ROOT', self.root):
            runner.verify_sources(expected)
            module.write_text('# changed frozen implementation\n')
            with self.assertRaisesRegex(ValueError, 'Artifact changed'):
                runner.verify_sources(expected)


if __name__ == '__main__':
    unittest.main()
