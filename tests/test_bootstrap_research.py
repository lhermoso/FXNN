from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from collections import namedtuple

import numpy as np
from fxnn import bootstrap_research as runner
from fxnn import meta_research as source_runner
from fxnn.bootstrap_fit import ArtifactStore
from fxnn.experiment_fit import StageLedger
from fxnn.research import Dataset
from fxnn.session_clock import weekly_fx_clock
from fxnn.protocol import utc_epoch


class BootstrapResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.ledger_path=self.root/'ledger'
        ledger=StageLedger(self.ledger_path,7); ledger.initialize(0,'synthetic fixture')
        source_before=self.ledger_path.read_bytes()
        begin=utc_epoch('2023-01-02T00:00:00+00:00'); starts=begin+np.arange(50)*60
        self.clock=weekly_fx_clock(begin-86400,begin+86400)
        X=np.column_stack((np.sin(np.arange(50)),np.ones(50))); y=np.arange(50)%2
        data=Dataset(X,y,starts,starts+60,starts+120,np.arange(50)+100,np.ones(50,np.int8),['a','direction'],{'a':[0]},0)
        op=dict(X=X,starts=starts,entry_indices=data.entry_indices,side=data.sides,causal_valid=np.ones(50,bool),
                primary_reason=np.full(50,'signal'),causal_reason=np.full(50,'eligible'),outcomes=np.where(y,'take_profit','stop_loss'),
                **{f'cusum_{h}':np.ones(50,bool) for h in (.0005,.001)})
        from datetime import datetime,timezone
        stamp=lambda i:datetime.fromtimestamp(int(starts[i]),timezone.utc).isoformat()
        self.protocol={'folds':[dict(name='fixture',validation_start=stamp(25),test_start=stamp(35),test_end=stamp(49))]}
        parts={'fixture':dict(train=np.arange(20),refit=np.arange(20),validation=np.arange(25,33),test=np.arange(35,47))}
        self.bundle=dict(data=data,opportunities=op,opening_rows=np.arange(50),partitions=parts,masks={str(h):np.ones(50,bool) for h in (.0005,.001)},sampling_ends=starts+120)
        params={'C':1.,'random_state':0,'max_iter':1000}
        source_spec=dict(global_ledger=str(self.ledger_path),expected_prior_fits=0,ledger_before_sha256=hashlib.sha256(source_before).hexdigest(),
                         max_model_fits=24,thresholds=[.0005,.001],logistic=params)
        self.source_output=self.root/'source_models'
        with redirect_stdout(io.StringIO()):
            report=source_runner.execute(self.bundle,self.protocol,source_spec,self.clock,{'fixture':'source'},self.source_output)
        self.bundle.update(source_report=report,source_spec=source_spec,source_prefix=source_before,source_models=self.source_output)
        self.prior=ledger.consumed(); self.before=self.ledger_path.read_bytes()
        self.spec=dict(global_ledger=str(self.ledger_path),expected_prior_fits=self.prior,ledger_before_sha256=hashlib.sha256(self.before).hexdigest(),
                       max_model_fits=156,thresholds=[.0005,.001],logistic=params)
        Usage=namedtuple('Usage','total used free')
        self.disk=patch('fxnn.bootstrap_fit.shutil.disk_usage',return_value=Usage(10**13,0,10**13)); self.disk.start(); self.addCleanup(self.disk.stop)
        self.output=self.root/'output'
        self.config=self.root/'config.json'; self.config.write_text('{}')
        self.protocol_file=self.root/'protocol.md'; self.protocol_file.write_text('synthetic protocol')
        protocol_patch=patch.object(runner,'PROTOCOL',self.protocol_file)
        protocol_patch.start(); self.addCleanup(protocol_patch.stop)
        self.hashes=dict(config=runner.digest(self.config),protocol=runner.digest(self.protocol_file),sources={})

    def test_complete_trace_predictions_and_replay(self):
        report=runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        self.assertEqual(report['new_fits'],39)
        raw=self.ledger_path.read_bytes(); ledger=StageLedger(self.ledger_path,8)
        with patch.object(runner,'fit_unit',side_effect=AssertionError('replay cannot fit')):
            replay=runner.run_models(self.bundle,self.protocol,self.spec,self.clock,ledger,self.hashes,self.output,None,replay=report['folds'],prefix=self.before)
        self.assertEqual(replay,report['folds']); self.assertEqual(self.ledger_path.read_bytes(),raw)
        with patch.object(runner,'SPEC',self.config),patch.object(runner,'PROTOCOL',self.protocol_file),patch.object(runner,'load_source',return_value=(self.bundle,self.clock)):
            verified=runner.verify(self.output,self.root,self.source_output,self.spec,self.protocol)
            self.assertEqual(verified['model_fits'],0)
            self.assertEqual(self.ledger_path.read_bytes(),raw)
        phase=report['folds'][0]['phases']['inner']['temporal']
        with np.load(self.output/phase['predictions_file'],allow_pickle=False) as archive:
            np.testing.assert_array_equal(archive['selected_source_rows'][archive['canonical_to_selected']],archive['canonical_source_rows'])
            np.testing.assert_array_equal(archive['canonical_to_selected'][archive['selected_to_canonical']],np.arange(20))
            self.assertIn('full_training_raw_uniqueness',archive.files)
        trace=phase['traces']['uniform_0'][0]
        with np.load(self.output/trace['draws_file'],allow_pickle=False) as archive:
            np.testing.assert_array_equal(archive['draw_original_ids'],archive['canonical_original_ids'][archive['draws']])
            np.testing.assert_array_equal(archive['draw_source_rows'],archive['canonical_source_rows'][archive['draws']])
        changed=self.output/phase['traces']['sequential_0'][0]['probabilities_file']
        with changed.open('r+b') as stream: stream.write(b'corrupt!')
        with self.assertRaisesRegex(ValueError,'artifact changed'):
            runner.run_models(self.bundle,self.protocol,self.spec,self.clock,ledger,self.hashes,self.output,None,replay=report['folds'],prefix=self.before)

    def test_reference_corruption_prevents_any_fit8(self):
        path=self.source_output/'fixture_inner_temporal.npz'; path.write_bytes(b'bad')
        with patch.object(runner,'fit_unit',side_effect=AssertionError('must not fit')):
            with self.assertRaisesRegex(ValueError,'artifact changed'):
                runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        self.assertEqual(self.ledger_path.read_bytes(),self.before)
        self.assertFalse(self.output.exists())

    def test_trace_storage_fault_aborts_without_further_members(self):
        with patch.object(runner,'sampling_trace',side_effect=OSError('trace failure')):
            with self.assertRaisesRegex(OSError,'trace failure'):
                runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        ledger=StageLedger(self.ledger_path,8)
        self.assertEqual(ledger.consumed(),self.prior+1)
        self.assertEqual(ledger.records()[-1]['status'],'aborted')

    def test_members_missing_and_seed_input_isolation(self):
        state=dict(kind=np.array('constant'),prior=np.array(.3))
        ensemble,member=runner.ensemble_predictions([state,None,state],np.ones((5,2)))
        self.assertIsNone(ensemble); self.assertIsNotNone(member[0]); self.assertIsNone(member[1])
        self.assertIsNone(runner.diversity(member)['0-1']['correlation'])
        rows=np.arange(20)
        before=runner.sampling_contract(self.bundle,rows,self.clock,'temporal')[-1]
        self.bundle['data'].y[:]=1-self.bundle['data'].y
        self.bundle['data'].X[:]=9
        self.bundle['source_report']['hashes']={'changed_external_report':'new'}
        after=runner.sampling_contract(self.bundle,rows,self.clock,'temporal')[-1]
        self.assertEqual(before,after)
        first=runner.seed_for(runner.contract_hash(before),'temporal',0,0)
        second=runner.seed_for(runner.contract_hash(after),'temporal',0,0)
        self.assertEqual(first,second)

    def test_atomic_reservation_after_preflight(self):
        original=ArtifactStore.json
        def race(store,path,value):
            result=original(store,path,value)
            if path.name=='run.json':
                other=StageLedger(self.ledger_path,9)
                other.start_run('intervening',1,{'fixture':1}); other.finish_run('intervening','completed',{})
            return result
        with patch.object(ArtifactStore,'json',race):
            with self.assertRaisesRegex(ValueError,'Frozen ledger'):
                runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        records=StageLedger(self.ledger_path,8).records()
        self.assertFalse(any(r.get('experiment')==runner.EXPERIMENT for r in records))

    def test_final_report_failure_json_failure_still_closes(self):
        original=ArtifactStore.json
        def fail(store,path,value):
            if path.name in ('report.json','failure.json'): raise OSError('final disk failure')
            return original(store,path,value)
        with patch.object(runner,'run_models',return_value=[]),patch.object(ArtifactStore,'json',fail):
            with self.assertRaisesRegex(OSError,'final disk failure'):
                runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        records=StageLedger(self.ledger_path,8).records()
        self.assertEqual(records[-1]['status'],'aborted')

    def test_one_fit_intervening_reservation(self):
        original=ArtifactStore.json
        def race(store,path,value):
            result=original(store,path,value)
            if path.name=='run.json':
                other=StageLedger(self.ledger_path,9); other.start_run('other',1,{'fixture':1})
                other.start_fit('other','fit','fold',{},{}); other.finish_fit('other','fit','succeeded',{})
                other.finish_run('other','completed',{})
            return result
        with patch.object(ArtifactStore,'json',race):
            with self.assertRaisesRegex(ValueError,'Frozen ledger'):
                runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        self.assertFalse(any(r.get('experiment')==runner.EXPERIMENT for r in StageLedger(self.ledger_path,8).records()))

    def test_finish_run_failure_closes_aborted(self):
        from fxnn.bound_ledger import BoundStageLedger
        original=BoundStageLedger.finish_run
        def fail(ledger,experiment,status,result):
            if status=='completed': raise OSError('finish run unavailable')
            return original(ledger,experiment,status,result)
        with patch.object(runner,'run_models',return_value=[]),patch.object(BoundStageLedger,'finish_run',fail):
            with self.assertRaisesRegex(OSError,'finish run unavailable'):
                runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        self.assertEqual(StageLedger(self.ledger_path,8).records()[-1]['status'],'aborted')

    def test_ledger_after_failure_no_second_terminal(self):
        original=ArtifactStore.bytes
        def fail(store,path,value):
            if path.name=='ledger-after.jsonl': raise OSError('snapshot unavailable')
            return original(store,path,value)
        with patch.object(runner,'run_models',return_value=[]),patch.object(ArtifactStore,'bytes',fail):
            with self.assertRaisesRegex(OSError,'snapshot unavailable'):
                runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        ends=[r for r in StageLedger(self.ledger_path,8).records() if r['kind']=='run_finished' and r.get('experiment')==runner.EXPERIMENT]
        self.assertEqual(len(ends),1); self.assertFalse((self.output/'ledger-after.jsonl').exists())

    def test_censored_near_end_predictions_and_missing_threshold(self):
        op=self.bundle['opportunities']; rows=np.array([35,36,37]); op['outcomes'][36]='censored'
        predictions={name:np.array([.2,.6,.9]) for name in ('full','uniform_0','uniform_1','sequential_0','sequential_1','weighted_logistic','weighted_constant')}
        selection=runner.choose_threshold(np.zeros(3,int),np.array([.1,.2,.3]),'Q2')
        archive,report,_=runner.evaluate(op,rows,np.array([35]),'temporal',predictions,{name:selection for name in predictions})
        np.testing.assert_array_equal(archive['sequential_0_probability_available'],[1,1,1])
        np.testing.assert_array_equal(archive['sequential_0_accepted'],[-1,-1,-1])
        self.assertEqual(report['support']['rows'],1)

    def test_opportunity_causes_preserved_outside_metric_population(self):
        op=self.bundle['opportunities']; rows=np.array([35,36,37,38])
        op['primary_reason']=op['primary_reason'].astype('U24')
        op['side'][35]=0; op['primary_reason'][35]='no_momentum'
        op['causal_valid'][36]=False; op['causal_reason'][36]='gapped'
        op['cusum_0.0005'][37]=False
        predictions={name:np.array([.7]) for name in ('full','uniform_0','uniform_1','sequential_0','sequential_1','weighted_logistic','weighted_constant')}
        archive,report,_=runner.evaluate(op,rows,np.array([38]),'0.0005',predictions)
        np.testing.assert_array_equal(archive['primary_signal'],[False,True,True,True])
        np.testing.assert_array_equal(archive['event_match'],[True,True,False,True])
        np.testing.assert_array_equal(archive['causal_valid'],[True,False,True,True])
        np.testing.assert_array_equal(archive['primary_reason'],op['primary_reason'][rows])
        np.testing.assert_array_equal(archive['causal_reason'],op['causal_reason'][rows])
        self.assertEqual(report['coverage']['primary_reasons'],{'no_momentum':1,'signal':3})
        self.assertEqual(report['coverage']['causal_reasons'],{'eligible':3,'gapped':1})
        self.assertEqual(report['coverage']['causal_eligible'],1)
        self.assertEqual(sum(report['coverage']['all_outcomes'].values()),4)
        self.assertEqual(sum(report['coverage']['eligible_outcomes'].values()),1)

    def test_source_shuffle_and_weekend_conservative_endpoints(self):
        import copy
        bundle=copy.deepcopy(self.bundle); rows=np.arange(20)
        original=runner.sampling_contract(bundle,rows,self.clock,'temporal')
        permutation=np.arange(49,-1,-1)
        for field in runner.FIELDS: setattr(bundle['data'],field,getattr(bundle['data'],field)[permutation])
        bundle['sampling_ends']=bundle['sampling_ends'][permutation]
        shuffled_rows=np.flatnonzero(np.isin(bundle['data'].entry_indices,self.bundle['data'].entry_indices[rows]))
        shuffled=runner.sampling_contract(bundle,shuffled_rows,self.clock,'temporal')
        self.assertEqual(original[-1],shuffled[-1])
        np.testing.assert_array_equal(bundle['data'].entry_indices[shuffled[0]],self.bundle['data'].entry_indices[original[0]])
        friday=utc_epoch('2023-03-10T21:59:00+00:00'); sunday=utc_epoch('2023-03-12T21:01:00+00:00')
        clock=weekly_fx_clock(friday-86400,sunday+86400)
        bundle['data'].starts[:2]=[friday,sunday-60]
        bundle['data'].ends[:2]=[friday+60,sunday]
        bundle['sampling_ends'][:2]=[sunday,sunday+60]
        _,starts,ends,*_=runner.sampling_contract(bundle,np.array([0,1]),clock,'temporal')
        self.assertTrue(np.all(ends>starts))
        np.testing.assert_array_equal(ends-starts,[2,2])  # Last information, not realized ends.
        bundle['sampling_ends'][:2]=[friday+60,sunday+180]
        _,starts,ends,*_=runner.sampling_contract(bundle,np.array([0,1]),clock,'temporal')
        np.testing.assert_array_equal(np.sort(ends-starts),[1,4])  # Opening hit and absent deadline bar.


    def test_runner_member_missing_class_continues_without_redraw(self):
        original=runner.sampling_trace
        calls=[]
        def force_one_class(starts,ends,contract,pop,master,member,scheme,output,store,**kwargs):
            draws,trace=original(starts,ends,contract,pop,master,member,scheme,output,store,**kwargs)
            calls.append((pop,master,member,scheme))
            # A controlled sampler fixture: one planned member contains only class zero.
            if master==0 and member==0 and scheme=='uniform':
                draws=np.zeros_like(draws)
            return draws,trace
        with patch.object(runner,'sampling_trace',force_one_class):
            report=runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        self.assertEqual(len(calls),36)  # No replacement draw for an unavailable member.
        phase=report['folds'][0]['phases']['inner']['temporal']
        self.assertEqual(phase['fits']['uniform_0'][0]['status'],'technically_unavailable')
        self.assertEqual(phase['fits']['uniform_0'][1]['status'],'succeeded')
        self.assertEqual(phase['fits']['uniform_0'][2]['status'],'succeeded')
        self.assertIsNone(phase['evaluation']['models']['uniform_0']['scores'])
        self.assertEqual(phase['ensemble_divisor'],3)
        with np.load(self.output/phase['predictions_file'],allow_pickle=False) as a:
            self.assertTrue(np.isnan(a['uniform_0_probability']).all())
            self.assertTrue(np.isfinite(a['uniform_0_member_1']).all())

    def test_external_mutation_preserves_actual_states_and_inner_selections(self):
        import copy
        ledger=StageLedger(self.ledger_path,8)
        runner.validate_references(self.bundle,self.protocol,self.clock,ledger)
        baseline=runner.execute(self.bundle,self.protocol,self.spec,self.clock,self.hashes,self.output)
        changed=copy.deepcopy(self.bundle)
        changed['data'].X[35:]+=100
        changed['data'].y[35:]=1-changed['data'].y[35:]
        changed['opportunities']['X'][35:]+=100
        changed['opportunities']['outcomes'][35:]=np.where(changed['data'].y[35:],'take_profit','stop_loss')
        # Exercise orchestration causality with already verified reference states. The real
        # execute preflight separately rejects any mutation of its frozen source artifacts.
        other=self.root/'second-ledger'; other.write_bytes(self.before)
        ledger2=StageLedger(other,8); ledger2.start_run(runner.EXPERIMENT,156,self.hashes)
        output2=self.root/'second'; output2.mkdir(); store=ArtifactStore(output2,10**7)
        result=runner.run_models(changed,self.protocol,self.spec,self.clock,ledger2,self.hashes,output2,store)
        ledger2.finish_run(runner.EXPERIMENT,'completed',{})
        a=baseline['folds'][0]['phases']['inner']; b=result[0]['phases']['inner']
        for population in a:
            for model in a[population]['evaluation']['models']:
                self.assertEqual(a[population]['evaluation']['models'][model]['selection'],b[population]['evaluation']['models'][model]['selection'])
        models1=sorted((self.output/'models').glob('*.npz'))
        self.assertEqual([p.name for p in models1],sorted(p.name for p in (output2/'models').glob('*.npz')))
        for p in models1:
            with np.load(p,allow_pickle=False) as first,np.load(output2/'models'/p.name,allow_pickle=False) as second:
                for key in first.files: np.testing.assert_array_equal(first[key],second[key])


    def test_trace_binding_changes_without_changing_uniform_seed(self):
        ordered,starts,ends,_,_,contract=runner.sampling_contract(self.bundle,np.arange(20),self.clock,'temporal')
        one=self.root/'trace_one'; two=self.root/'trace_two'; one.mkdir(); two.mkdir()
        _,first=runner.sampling_trace(starts,ends,contract,'temporal',0,0,'uniform',one,ArtifactStore(one,10**6))
        self.protocol_file.write_text('changed protocol binding')
        _,second=runner.sampling_trace(starts,ends,contract,'temporal',0,0,'uniform',two,ArtifactStore(two,10**6))
        self.assertNotEqual(first['contract_sha256'],second['contract_sha256'])
        self.assertEqual(first['contract']['derived_seed'],second['contract']['derived_seed'])
        with np.load(one/first['draws_file'],allow_pickle=False) as a,np.load(two/second['draws_file'],allow_pickle=False) as b:
            np.testing.assert_array_equal(a['uniforms'],b['uniforms'])
            np.testing.assert_array_equal(a['draws'],b['draws'])
