"""Production supervisor integration tests: real temporary FitLedger and flock."""
import concurrent.futures
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fxnn.fit_ledger import FitLedger
from fxnn.economic_lifecycle import Lifecycle, fingerprint, identity


def opening_worker(path):
    try:
        Lifecycle(path).begin_confirmation()
        return True
    except ValueError:
        return False


def killed_fit_worker(path):
    with Lifecycle(path).fit('0', {'family':'logistic','training':'orphan'}, 'synthetic'):
        Path(path).parent.joinpath('orphan-model').write_bytes(b'orphan')
        os._exit(7)


class ProductionLifecycleTests(unittest.TestCase):
    def test_nonfit_persistence_poison_survives_restart(self):
        self.o.poison('prediction publication failed')
        again=Lifecycle(self.path)
        self.assertEqual(again.read()['poison_reason'],'prediction publication failed')
        with self.assertRaisesRegex(ValueError,'Poisoned'):
            with again.fit('0',{'family':'constant'},'synthetic'):
                self.fail('Poisoned run cannot fit')
        before=self.o.state_path.read_bytes()
        again.poison('second report')
        self.assertEqual(self.o.state_path.read_bytes(),before)

    def test_failed_terminal_verification_is_readonly(self):
        contract={'family':'logistic','training':'failed'}
        with self.o.fit('0',contract,'synthetic') as fit:
            fit.failed({'reason':'numerical fixture'})
        before=self.o.state_path.read_bytes()
        self.assertIsInstance(self.o.verified_terminal(contract,'failed'),dict)
        self.assertEqual(self.o.state_path.read_bytes(),before)
        with self.assertRaises(ValueError):self.o.verified_terminal(contract,'succeeded')
        with self.assertRaises(ValueError):
            with self.o.fit('1',contract,'synthetic'):self.fail('Retry alias')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='economic-lifecycle-production-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.path=self.root/'ledger.jsonl'
        FitLedger(self.path).initialize(0, {'synthetic':True})
        self.source=self.root/'source.txt';self.source.write_text('synthetic scientific content')
        self.files={'source':fingerprint(self.source)}
        self.o=Lifecycle(self.path)
        self.slots=[str(i) for i in range(14)]
        self.o.reserve(0,fingerprint(self.path)['sha256'],self.files,{'fixture':True},self.slots,independent_failures=True)

    def success(self,slot,contract):
        model=self.root/('model-'+slot);model.write_bytes(('synthetic-'+slot).encode())
        science=self.o.read()['S']
        F=identity({'S':science,'contract':contract})
        meta=self.root/('meta-'+slot+'.json');meta.write_text(json.dumps({'S':science,'F':F,'model_sha256':fingerprint(model)['sha256']}))
        with self.o.fit(slot,contract,'synthetic') as fit:
            fit.succeeded({'model':fingerprint(model),'metadata':fingerprint(meta)})

    def ready(self,head='release'):
        head=hashlib.sha1(head.encode()).hexdigest()
        contracts=[{'family':'constant','training':'final'},{'family':'logistic','training':'final'}]
        for slot,c in zip(['12','13'],contracts):self.success(slot,c)
        report=self.root/'report.json';report.write_text('{"synthetic":true}')
        self.o.freeze(head,head,head,True,True,contracts,{'report':fingerprint(report)},dict.fromkeys(['T1','T2','T3','T4','T5'],True))
        return contracts

    def opened(self):
        self.ready();self.o.begin_confirmation()
        payload=self.root/'payload';payload.write_bytes(b'SYNTHETIC NOT MARKET')
        self.o.received_payload(payload)

    def test_read_cache_replay_do_not_write(self):
        c={'family':'logistic','training':'one'};self.success('0',c)
        before={str(p): (p.stat().st_mtime_ns,p.stat().st_size,p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        self.o.read();self.o.cached(c)
        after={str(p): (p.stat().st_mtime_ns,p.stat().st_size,p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_read_nonexistent_does_not_create(self):
        obj=Lifecycle(self.root/'absent'/'ledger')
        with self.assertRaises(FileNotFoundError):obj.read()
        self.assertFalse((self.root/'absent').exists())

    def test_canonical_symlink_path_cannot_reserve_twice(self):
        alias=self.root/'alias';alias.symlink_to(self.path)
        self.assertEqual(Lifecycle(alias).root,self.o.root)
        with self.assertRaises(ValueError):Lifecycle(alias).reserve(0,'0'*64,self.files,{},self.slots)

    def test_existing_ledger_run_prevents_deleted_supervisor_replacement(self):
        self.o.state_path.unlink()
        with self.assertRaises(ValueError):self.o.reserve(0,'0'*64,self.files,{},self.slots)
        self.assertEqual(sum(r['kind']=='run_started' for r in FitLedger(self.path).records()),1)

    def test_atomic_ledger_binding_rejects_wrong_count(self):
        other=self.root/'other'/'ledger';FitLedger(other).initialize(0,{'synthetic':True})
        obj=Lifecycle(other)
        with self.assertRaises(ValueError):obj.reserve(1,fingerprint(other)['sha256'],self.files,{},self.slots)
        self.assertEqual(sum(r['kind']=='run_started' for r in FitLedger(other).records()),0)
        with self.assertRaises(ValueError):obj.reserve(0,fingerprint(other)['sha256'],self.files,{},self.slots)

    def test_clean_pause_and_remaining_final_slots_same_run(self):
        for i in range(12):self.success(str(i),{'family':'constant','training':str(i)})
        check=self.root/'development-report';check.write_text('synthetic report')
        self.o.clean_checkpoint('DEVELOPMENT_VERIFIED',{'report':fingerprint(check)})
        self.o=Lifecycle(self.path);self.o.recover();self.ready()
        records=FitLedger(self.path).records()
        self.assertEqual(sum(r['kind']=='run_started' for r in records),1)
        self.assertEqual(sum(r['kind']=='fit_started' for r in records),14)
        self.assertFalse(any(r['kind']=='run_finished' for r in records))
        self.assertTrue(all(r['stage']==9 for r in records if r['kind']=='fit_started'))

    def test_seal_rejects_unused_slot(self):
        self.ready()
        with self.assertRaises(ValueError):
            with self.o.fit('0',{'family':'logistic'},'x'):pass

    def test_real_process_exit_pending_and_orphan_poison(self):
        process=multiprocessing.get_context('spawn').Process(target=killed_fit_worker,args=(str(self.path),))
        process.start();process.join(15)
        self.assertEqual(process.exitcode,7)
        with self.assertRaises(ValueError):Lifecycle(self.path).recover()
        self.assertTrue(self.o.read()['poison'])
        with self.assertRaises(ValueError):
            with Lifecycle(self.path).fit('1',{'family':'logistic','training':'alias'},'x'):pass
        self.assertEqual(sum(r['kind']=='fit_started' for r in FitLedger(self.path).records()),1)

    def test_persistence_fault_after_terminal_poison_survives_restart(self):
        original=self.o._save
        def fail_once(s):
            if s['fits'].get('0',{}).get('status')=='succeeded' and not s['poison']:
                raise OSError('injected snapshot persistence failure')
            return original(s)
        with patch.object(self.o,'_save',side_effect=fail_once):
            with self.assertRaises(OSError):self.success('0',{'family':'constant'})
        self.assertTrue(Lifecycle(self.path).read()['poison'])
        with self.assertRaises(ValueError):Lifecycle(self.path).recover()

    def test_failed_contract_not_retry_alias_and_corrupt_export_not_cache(self):
        c={'family':'logistic','training':'failed'}
        with self.o.fit('0',c,'x') as f:f.failed({'reason':'synthetic numerical failure'})
        with self.assertRaises(ValueError):
            with self.o.fit('1',c,'x'):pass
        good={'family':'constant','training':'ok'};self.success('2',good)
        (self.root/'model-2').write_bytes(b'tampered')
        with self.assertRaises(ValueError):Lifecycle(self.path).cached(good)

    def test_wrong_CI_or_changed_science_refuses_freeze(self):
        contracts=[{'family':'constant'},{'family':'logistic'}]
        self.success('12',contracts[0]);self.success('13',contracts[1])
        report=self.root/'report';report.write_text('synthetic')
        args=['a'*40,'b'*40,'a'*40,True,True,contracts,{'report':fingerprint(report)},dict.fromkeys(['T1','T2','T3','T4','T5'],True)]
        with self.assertRaises(ValueError):self.o.freeze(*args)
        args[1]='a'*40;self.source.write_text('changed science')
        with self.assertRaises(ValueError):self.o.freeze(*args)
        self.assertEqual(self.o.read()['guard'],'UNOPENED')

    def test_aggregate_only_release_head_allowed_with_unchanged_science(self):
        S=self.o.read()['S'];self.ready('new-docs-release')
        self.assertEqual(self.o.read()['S'],S)
        self.assertEqual(self.o.read()['R']['sha'],hashlib.sha1(b'new-docs-release').hexdigest())

    def test_one_open_eight_process_requests(self):
        self.ready()
        with concurrent.futures.ProcessPoolExecutor(4,mp_context=multiprocessing.get_context('spawn')) as pool:
            outcomes=list(pool.map(opening_worker,[str(self.path)]*8))
        self.assertEqual(sum(outcomes),1)
        self.assertEqual(self.o.read()['guard'],'OPENING')

    def test_crash_after_opening_before_IO_remains_consumed(self):
        self.ready();self.o.begin_confirmation();self.o.process_failure('synthetic before I/O')
        resumed=Lifecycle(self.path);resumed.recover()
        with self.assertRaises(ValueError):resumed.begin_confirmation()
        self.assertEqual(resumed.read()['guard'],'OPENING')

    def test_held_inspection_order_and_changed_payload_rejected(self):
        self.ready();self.o.begin_confirmation()
        with self.assertRaises(ValueError):self.o.record_held_inspection()
        held=self.root/'held';held.write_text('synthetic')
        self.o.mark_held_inspection({'held':fingerprint(held)})
        held.write_text('changed')
        with self.assertRaises(ValueError):self.o.record_held_inspection()
        self.assertEqual(self.o.read()['guard'],'OPENING')
        with self.assertRaises(ValueError):self.o.mark_held_inspection({'held':fingerprint(held)})
        held.write_text('synthetic')
        self.o.record_held_inspection();self.assertEqual(self.o.read()['guard'],'OPENED')

    def test_checkpoint_idempotent_and_terminal_no_regression(self):
        self.opened()
        self.assertTrue(self.o.checkpoint('chunk1',{'funding':-3,'trade':7},{'cash':10004},expected_version=0))
        self.o.process_failure('synthetic evaluation crash')
        resumed=Lifecycle(self.path);resumed.recover()
        self.assertFalse(resumed.checkpoint('chunk1',{'funding':-3,'trade':7},{'cash':10004},expected_version=0))
        with self.assertRaises(ValueError):resumed.checkpoint('chunk1',{'funding':-4},{'cash':10003},expected_version=0)
        self.assertEqual(resumed.read()['account'],{'cash':10004})
        resumed.close('INCOMPLETE',{'reason':'synthetic terminal'})
        with self.assertRaises(ValueError):resumed.recover()
        with self.assertRaises(ValueError):resumed.begin_confirmation()
        with self.assertRaises(ValueError):resumed.checkpoint('new',{}, {},expected_version=1)
        self.assertEqual(resumed.read()['guard'],'INCOMPLETE')

    def test_terminal_ledger_finish_recoverable_once_and_cache_readonly(self):
        self.opened()
        with patch('fxnn.economic_lifecycle.BoundStageLedger.finish_run',side_effect=OSError('injected')):
            with self.assertRaises(OSError):self.o.close('INCOMPLETE',{'reason':'synthetic'})
        resumed=Lifecycle(self.path);resumed.finalize_terminal();resumed.finalize_terminal()
        records=FitLedger(self.path).records()
        self.assertEqual(sum(r['kind']=='run_finished' for r in records),1)
        self.assertEqual(resumed.read()['guard'],'INCOMPLETE')
        before=resumed.state_path.read_bytes()
        resumed.cached({'family':'constant','training':'final'})
        self.assertEqual(before,resumed.state_path.read_bytes())

    def test_all_technical_flags_required_economics_not_an_input(self):
        contracts=[{'family':'constant'},{'family':'logistic'}]
        self.success('12',contracts[0]);self.success('13',contracts[1])
        report=self.root/'negative-report';report.write_text('{"economic_result":"negative"}')
        tests=dict.fromkeys(['T1','T2','T3','T4','T5'],True)
        for key in tests:
            bad={**tests,key:False}
            with self.assertRaises(ValueError):self.o.freeze('c'*40,'c'*40,'c'*40,True,True,contracts,{'report':fingerprint(report)},bad)
        self.o.freeze('c'*40,'c'*40,'c'*40,True,True,contracts,{'report':fingerprint(report)},tests)
        self.o.begin_confirmation();self.assertEqual(self.o.read()['guard'],'OPENING')

    def test_rogue_direct_fit_detected(self):
        FitLedger(self.path).start_fit('economic_ticks_v1','rogue','x',{}, {'x':'y'})
        with self.assertRaises(ValueError):self.o.read()

    def test_checkpoint_stale_predecessor_cannot_overwrite_account(self):
        self.opened()
        self.o.checkpoint('a',{'funding':-3},{'cash':9997},expected_version=0)
        with self.assertRaises(ValueError):self.o.checkpoint('b',{'trade':7},{'cash':10007},expected_version=0)
        self.assertEqual(self.o.read()['account'],{'cash':9997})

    def test_freeze_nested_model_change_blocks_opening(self):
        self.ready()
        (self.root/'model-12').write_bytes(b'changed-after-freeze')
        with self.assertRaises(ValueError):self.o.begin_confirmation()
        self.assertEqual(self.o.read()['guard'],'UNOPENED')

    def test_model_metadata_must_bind_S_F_and_bytes(self):
        model=self.root/'badmodel';model.write_bytes(b'synthetic')
        metadata=self.root/'badmeta';metadata.write_text('{}')
        with self.assertRaises(ValueError):
            with self.o.fit('0',{'family':'logistic'},'x') as fit:
                fit.succeeded({'model':fingerprint(model),'metadata':fingerprint(metadata)})
        self.assertTrue(self.o.read()['poison'])

    def test_ledger_prefix_tamper_detected_without_writes(self):
        self.path.write_bytes(self.path.read_bytes().replace(b'genesis',b'changed',1))
        before=self.o.state_path.read_bytes()
        with self.assertRaises(ValueError):self.o.read()
        self.assertEqual(self.o.state_path.read_bytes(),before)


if __name__=='__main__':unittest.main(verbosity=2)
