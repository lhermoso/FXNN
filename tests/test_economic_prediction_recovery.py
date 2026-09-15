"""Real synthetic prediction files, process death and canonical zero-fit recovery."""
import copy
import json
import multiprocessing
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fxnn import economic_prediction_recovery as recovery
from fxnn.economic_lifecycle import fingerprint, identity
from fxnn import economic_fit, economic_research, economic_prediction_replay

# Reuse existing synthetic model/source fixture only; its model fitting is mocked.
import test_economic_prediction_replay as prediction_fixture


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=prediction_fixture.ReplayTests('test_full_final_replay_terminal_states_no_files_or_guard_mutations')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.output=self.root/'recoverable-final'
        self.contract={'S':'S','freeze_sha256':self.fixture.package['sha256'],
                       'models':['constant','logistic'],'final_report':self.fixture.final_artifact,
                       'confirmation_evidence':self.fixture.evidence,'config_sha256':identity(self.fixture.config)}
        self.before=copy.deepcopy(self.fixture.supervisor.snapshot)
        self.scientific={p:fingerprint(p) for p in (self.fixture.final_artifact['path'],self.fixture.package['path'])}

    def construct(self, output):
        f=self.fixture
        generator=getattr(economic_research,'_final_probabilities',economic_research.final_probabilities)
        return generator(f.config,f.supervisor,f.matrix,f.final_artifact,output,f.evidence)

    def verify(self, artifact):
        f=self.fixture
        return economic_prediction_replay.verify_final_probabilities(f.config,f.supervisor,f.matrix,
                    f.final_artifact,artifact,f.evidence)

    def run_construction(self, callback=None, output=None, contract=None):
        return recovery.prediction_construction(self.fixture.supervisor,self.contract if contract is None else contract,
                    self.output if output is None else output,callback or self.construct,self.verify)

    def registry(self):
        return self.root/'prediction-construction-v1/state.json'

    def assert_science_unchanged(self):
        self.assertEqual(self.before,self.fixture.supervisor.snapshot)
        for path,expected in self.scientific.items():self.assertEqual(fingerprint(path),expected)
        self.assertFalse(any(p.name.endswith('ledger.jsonl') for p in self.root.rglob('*')))

    def test_process_death_after_mkdir_preserves_attempt_then_replays(self):
        original=economic_fit.new_directory
        def killed(output):
            def fail(path):
                original(path)
                if Path(path)==output:os._exit(17)
            with patch.object(economic_fit,'new_directory',side_effect=fail):self.construct(output)
        process=multiprocessing.get_context('fork').Process(target=lambda:self.run_construction(killed))
        process.start();process.join(10)
        self.assertEqual(process.exitcode,17)
        self.assertTrue(self.output.is_dir())
        result=self.run_construction()
        self.assertEqual(result['scientific_fits'],0)
        state=json.loads(self.registry().read_text())['state']
        self.assertEqual(state['status'],'completed')
        self.assertEqual(state['attempt'],2)
        self.assertTrue(Path(state['preserved_attempts'][0]['archive']).is_dir())
        self.assertEqual(state['preserved_attempts'][0]['artifacts'],{})
        self.assert_science_unchanged()

    def test_process_death_between_families_preserves_completed_constant(self):
        original=economic_fit.durable_arrays
        def killed(output):
            def fail(path,arrays):
                value=original(path,arrays)
                if Path(path).name=='constant.npz':os._exit(18)
                return value
            with patch.object(economic_fit,'durable_arrays',side_effect=fail):self.construct(output)
        process=multiprocessing.get_context('fork').Process(target=lambda:self.run_construction(killed))
        process.start();process.join(10)
        self.assertEqual(process.exitcode,18)
        partial=fingerprint(self.output/'constant.npz')
        self.run_construction()
        state=json.loads(self.registry().read_text())['state']
        preserved=state['preserved_attempts'][0]['artifacts']['constant.npz']
        self.assertEqual(preserved['sha256'],partial['sha256'])
        self.assertEqual(preserved['sha256'],fingerprint(self.output/'constant.npz')['sha256'])
        self.assert_science_unchanged()

    def test_completed_reuse_never_generates_and_tamper_never_rebuilds(self):
        expected=self.run_construction()
        state_before=self.registry().read_bytes()
        self.assertEqual(expected,self.run_construction(lambda out:self.fail('No rebuild')))
        self.assertEqual(state_before,self.registry().read_bytes())
        (self.output/'constant.npz').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.run_construction(lambda out:self.fail('No rebuild'))
        self.assertEqual(state_before,self.registry().read_bytes())

    def test_alias_contract_and_nointent_existing_directory_rejected(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError,'no canonical intent'):self.run_construction()
        self.output.rmdir()
        self.run_construction()
        with self.assertRaisesRegex(ValueError,'alias'):self.run_construction(output=self.root/'alias')
        with self.assertRaisesRegex(ValueError,'alias'):self.run_construction(contract={**self.contract,'S':'other'})
        self.assert_science_unchanged()

    def test_observed_storage_failure_is_durably_failed(self):
        def fail(output):
            output.mkdir()
            raise OSError('synthetic storage failure')
        with self.assertRaises(OSError):self.run_construction(fail)
        self.assertEqual(json.loads(self.registry().read_text())['state']['status'],'failed')
        with self.assertRaisesRegex(ValueError,'requires audit'):self.run_construction()
        self.assert_science_unchanged()

    def test_keyboard_interrupt_is_resumable_not_observed_storage_fault(self):
        def stop(output):
            output.mkdir()
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_construction(stop)
        self.assertEqual(json.loads(self.registry().read_text())['state']['status'],'interrupted')
        self.run_construction()
        self.assert_science_unchanged()

    def test_concurrent_callers_one_construction_under_flock(self):
        marker=self.root/'calls'
        def tracked(output):
            with marker.open('a') as stream:stream.write('one\n')
            return self.construct(output)
        processes=[multiprocessing.get_context('fork').Process(target=lambda:self.run_construction(tracked)) for _ in range(2)]
        for process in processes:process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode,0)
        self.assertEqual(marker.read_text(),'one\n')
        self.assert_science_unchanged()

    def test_process_death_after_rename_resumes_registered_archive(self):
        def stop(output):
            output.mkdir()
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_construction(stop)
        original=recovery.os.replace
        def killed():
            def rename(source,target):
                original(source,target)
                if Path(source).resolve()==self.output.resolve():os._exit(19)
            with patch.object(recovery.os,'replace',side_effect=rename):self.run_construction()
        process=multiprocessing.get_context('fork').Process(target=killed)
        process.start();process.join(10)
        self.assertEqual(process.exitcode,19)
        self.assertEqual(json.loads(self.registry().read_text())['state']['status'],'archiving')
        self.run_construction()
        self.assertEqual(json.loads(self.registry().read_text())['state']['attempt'],2)
        self.assert_science_unchanged()

    def test_process_death_after_candidate_persistence_only_verifies(self):
        original=recovery._save
        def killed():
            def save(path,state):
                original(path,state)
                if state['status']=='verifying':os._exit(20)
            with patch.object(recovery,'_save',side_effect=save):self.run_construction()
        process=multiprocessing.get_context('fork').Process(target=killed)
        process.start();process.join(10)
        self.assertEqual(process.exitcode,20)
        self.run_construction(lambda output:self.fail('Committed candidate must only replay'))
        state=json.loads(self.registry().read_text())['state']
        self.assertEqual(state['attempt'],1)
        self.assertEqual(state['preserved_attempts'],[])
        self.assert_science_unchanged()


if __name__=='__main__':unittest.main()
