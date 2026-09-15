"""Temp-only production runner tests: real filesystem, real synthetic TickIndex."""
import hashlib
import multiprocessing
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fxnn.economic_portfolio_run import WindowRunner,month_windows
from fxnn.economic_lifecycle import identity
from fxnn.economic_lifecycle import fingerprint,atomic_json,Lifecycle
from fxnn.fit_ledger import FitLedger
from fxnn.economic_simulator import unpack
from fxnn.economic_index import build_index,TickIndex
from fxnn.economic_clock import SessionClockMs,utc_ms
from fxnn.tick_economic_source import QuoteGroup,EventKey,Hazard,digest
from decimal import Decimal


def lock_probe(path,queue):
    with Path(path).open('rb') as stream:
        try:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            queue.put('acquired')
        except BlockingIOError:queue.put('blocked')


class FixtureLifecycle:
    """Durable CAS seam only; real Lifecycle exercised separately below."""
    def __init__(self,root):
        self.root=root;root.mkdir();atomic_json(root/'fixture.json',dict(guard='OPENED',effects={}))
    def read(self):return json.loads((self.root/'fixture.json').read_text())
    def checkpoint(self,event_id,effect,account_after,*,expected_version):
        s=self.read()
        if expected_version!=len(s['effects']):raise ValueError('CAS')
        s['effects'][event_id]=dict(effect=effect,account_after=account_after)
        atomic_json(self.root/'fixture.json',s)


class RunnerTests(unittest.TestCase):
    def fixture(self,*,gap=False,confirmation=False,zero=False,funding=False,quarter=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        start=utc_ms('2022-03-31T23:59:00+00:00' if quarter else '2022-01-31T23:59:00+00:00');end=start+4*60000
        if funding:start=utc_ms('2022-01-31T21:59:00+00:00')
        clock=SessionClockMs(start-1000,end+1000000,[] if zero else [(start-1000,end+1000000)])
        groups=[]
        for i,t in enumerate(range(start,end,30000)):
            bid=Decimal('1.1');ask=Decimal('1.1002')
            groups.append(QuoteGroup(EventKey(t,4,i),t,'synthetic','a'*64,i,i,1,bid,bid,ask,ask,(),True,False))
        hazards=[Hazard(EventKey(start+60000,1,0),'quote_absence',())] if gap else []
        m=build_index(groups if not zero else [],hazards,root/'index',{'synthetic':True},min_free=0,block_size=2)
        idx=TickIndex(root/'index',m['contract_sha256'],expected_manifest_sha256=digest(root/'index/manifest.json'))
        self.addCleanup(idx.close)
        rows=[dict(id=str(t),decision_ms=t,side=1,eligible=True,price_volatility=.01,
                   deadline_ms=end-60001,earliest_input=start,history_valid=True,observed_history=1941,segment=0)
              for t in clock.minutes(start,end)]
        path=root/'opportunities.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        def predict(a,b):
            return (dict(id=r['id'],probability='.5',model_available=True) for r in rows if a<=r['decision_ms']<b)
        lifecycle=FixtureLifecycle(root/'lifecycle') if confirmation else None
        kwargs=dict(canonical_state_root=None if confirmation else root/'canonical',lifecycle=lifecycle,
                    phase='confirmation' if confirmation else 'development',expected_opportunities=len(rows))
        runner=WindowRunner(idx,clock,start,end,fingerprint(path),predict,{'model':'immutable'},
                            {'science':'immutable'},root/'out',**kwargs)
        return runner,root

    def test_monthly_carry_replay_and_double_invocation(self):
        run,root=self.fixture()
        result=run.run();self.assertEqual(len(result['commits']),2)
        self.assertEqual(run.run(),result)
        before={str(p):(p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob('*') if p.is_file()}
        self.assertEqual(run.replay(),result)
        after={str(p):(p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        reports=unpack(result['reports'])
        for report in reports.values():
            self.assertEqual(report['counts']['entries'],1)
            self.assertEqual(report['counts']['timeout'],1)

    def test_crash_before_commit_restarts_uncommitted_attempt(self):
        for stage in ('journals_fsynced','checkpoint_fsynced'):
            with self.subTest(stage=stage):
                run,root=self.fixture()
                def fail(where):
                    if where==stage:raise RuntimeError('synthetic crash')
                with self.assertRaises(RuntimeError):run.run(fault=fail)
                self.assertFalse((root/'out/portfolio-manifest.json').exists())
                result=run.run();self.assertEqual(run.replay(),result)
                self.assertEqual(len([p for p in (root/'out').iterdir() if p.is_dir()]),3)

    def test_crash_after_authority_skips_committed_month(self):
        run,root=self.fixture(confirmation=True)
        def fail(where):
            if where=='authority_committed':raise RuntimeError('after authoritative commit')
        with self.assertRaises(RuntimeError):run.run(fault=fail)
        self.assertEqual(len(run.lifecycle.read()['effects']),1)
        result=run.run();self.assertEqual(run.replay(),result)
        self.assertEqual(len(run.lifecycle.read()['effects']),2)
        self.assertEqual(len([p for p in (root/'out').iterdir() if p.is_dir()]),2)

    def test_p0_p1_monthly_gap_is_not_deleted_on_resume(self):
        run,root=self.fixture(gap=True)
        result=run.run();self.assertEqual(run.replay(),result)
        reports=unpack(result['reports'])
        self.assertIsNone(reports['P0','S0','primary']['conclusive_pnl'])
        self.assertEqual(reports['P1','S0','primary']['counts']['p1_adverse_liquidation'],1)

    def test_funding_preserved_across_month_commit_and_resume(self):
        run,root=self.fixture(funding=True,confirmation=True)
        fired=[]
        def fail(where):
            if where=='authority_committed' and not fired:
                fired.append(True);raise RuntimeError('monthly pause')
        with self.assertRaises(RuntimeError):run.run(fault=fail)
        result=run.run();self.assertEqual(run.replay(),result)
        reports=unpack(result['reports'])
        self.assertGreater(reports['P0','S1','primary']['funding_recorded'],0)
        self.assertEqual(len(run.lifecycle.read()['effects']),2)

    def test_none_row_probability_does_not_change_model_availability(self):
        run,root=self.fixture()
        original=run.predict
        def predict(a,b):
            for row in original(a,b):
                row['probability']=None
                yield row
        run.predict=predict
        result=run.run()
        for report in unpack(result['reports']).values():
            self.assertTrue(report['arm_model_available'])
        self.assertEqual(run.replay(),result)

    def test_canonical_lock_is_crossprocess(self):
        run,root=self.fixture()
        context=multiprocessing.get_context('spawn')
        with run._locked(True):
            q=context.Queue();p=context.Process(target=lock_probe,args=(str(run.lock),q))
            p.start();self.assertEqual(q.get(timeout=10),'blocked');p.join(10)
            self.assertEqual(p.exitcode,0)
        q=context.Queue();p=context.Process(target=lock_probe,args=(str(run.lock),q))
        p.start();self.assertEqual(q.get(timeout=10),'acquired');p.join(10)
        self.assertEqual(p.exitcode,0)

    def test_real_lifecycle_checkpoint_method_on_temp_reservation_no_fits(self):
        run,root=self.fixture()
        ledger=root/'synthetic-ledger.jsonl';FitLedger(ledger).initialize(0,{'synthetic':True})
        life=Lifecycle(ledger)
        science=root/'science';science.write_text('synthetic')
        life.reserve(0,fingerprint(ledger)['sha256'],{'science':fingerprint(science)},
                     {'synthetic':True},[str(i) for i in range(14)])
        # Only arrange the prior guard state in this isolated temp fixture. This
        # test covers the actual checkpoint/read/CAS methods, not opening/freeze.
        with life._lock(True):
            state=life._load();state['guard']='OPENED';state['sealed']=True;life._save(state)
        runner=WindowRunner(run.index,run.clock,run.start,run.end,run.opportunities,run.predict,
                            run.contract['prediction'],run.bindings,root/'confirmed',
                            lifecycle=life,phase='confirmation',expected_opportunities=4)
        before=ledger.read_bytes();result=runner.run()
        self.assertEqual(len(life.read()['effects']),2)
        self.assertEqual(runner.replay(),result)
        self.assertEqual(ledger.read_bytes(),before)
        self.assertEqual(result,runner.run())

    def test_extra_row_cannot_commit_or_disappear_on_retry(self):
        run,root=self.fixture(zero=True)
        p=Path(run.opportunities['path']);p.write_text(json.dumps({'decision_ms':run.start+1})+'\n')
        run.opportunities=fingerprint(p);run.contract['opportunities']=run.opportunities;run.contract_id=identity(run.contract)
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'Unexpected extra'):run.run()
            self.assertEqual(json.loads(run.registry.read_text())['commits'],[])
        self.assertFalse((root/'out/portfolio-manifest.json').exists())

    def test_quarter_snapshot_at_prior_month_end(self):
        run,root=self.fixture(quarter=True)
        result=run.run();self.assertEqual(result,run.replay())
        first=result['commits'][0]
        data=unpack(json.loads(Path(first['checkpoint']['path']).read_text())['payload'])
        for account in data['accounts'].values():
            snapshot=account['state']['snapshots']['quarter:2022-04-01T00:00:00+00:00']
            self.assertEqual(snapshot.key.time,first['stop'])
            self.assertEqual(snapshot.key.phase,0)
            self.assertEqual(snapshot.state,'OPEN')
        for report in unpack(result['reports']).values():
            self.assertEqual(report['counts']['entries'],1)

    def test_empty_open_calendar_is_valid_not_missing_output(self):
        run,root=self.fixture(zero=True)
        result=run.run();self.assertEqual(result,run.run());self.assertEqual(result,run.replay())
        for report in unpack(result['reports']).values():self.assertEqual(report['conclusive_pnl'],0)

    def test_alias_binding_and_tamper_rejected(self):
        run,root=self.fixture();result=run.run()
        run.output=root/'alias'
        with self.assertRaisesRegex(ValueError,'alias'):run.run()
        run.output=(root/'out').resolve()
        item=next(iter(result['commits'][0]['journals'].values()))['file']
        Path(item['path']).write_text('tampered')
        with self.assertRaisesRegex(ValueError,'fingerprint'):run.replay()

    def test_missing_minute_prevents_authority(self):
        run,root=self.fixture();p=Path(run.opportunities['path']);lines=p.read_text().splitlines()
        p.write_text('\n'.join(lines[1:])+'\n');run.opportunities=fingerprint(p);run.contract['opportunities']=run.opportunities;run.contract_id=identity(run.contract)
        with self.assertRaisesRegex(ValueError,'Missing scheduled'):run.run()
        self.assertFalse((root/'out/portfolio-manifest.json').exists())

if __name__=='__main__':unittest.main(verbosity=2)
