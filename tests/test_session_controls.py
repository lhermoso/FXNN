from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.preprocessing import StandardScaler

from fxnn import session_controls as controls, session_models as old
from fxnn.fit_ledger import FitLedger
from fxnn.mlp_comparison import PHASES
from fxnn.session_dataset import save_arrays, write_json
from test_session_models import fixture


def new_ledger(output):
    ledger = FitLedger(output/'ledger')
    ledger.initialize(0, {'synthetic': True})
    ledger.start_run(controls.EXPERIMENT, 16, {'synthetic': True}, independent_failures=True)
    return ledger


class SessionControlsTests(unittest.TestCase):
    def test_equal_c_and_invalid_support(self):
        for nt, ne in [(100,10),(926669,80321),(926669,28249)]:
            c = controls.equal_c(nt,ne)
            self.assertAlmostEqual(1/(c*ne),1/nt,places=15)
        for nt,ne in [(0,0),(1,2),(True,1),(10,0),(10,1.5)]:
            with self.assertRaises(ValueError): controls.equal_c(nt,ne)

    def test_training_isolation_prior_cache_C_and_failure(self):
        data,clock,_=fixture();spec=json.loads(controls.SPEC.read_text())
        temporal=np.arange(40);rows=np.arange(0,40,3)
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);(output/'models').mkdir();ledger=new_ledger(output);cache={}
            def fit(d, family, identifier):
                return controls.fit_new(d,rows,temporal,family,spec,clock,ledger,identifier,'Q2',{},cache,output)
            state,report=fit(data,'constant','constant')
            self.assertAlmostEqual(float(state['prior']),np.average(data.y[rows],weights=old.open_weights(data,rows,clock)))
            logistic,record=fit(data,'logistic','logistic')
            self.assertEqual(record['C'],len(temporal)/len(rows))
            np.testing.assert_allclose(logistic['mean'],np.average(data.X[rows],weights=old.open_weights(data,rows,clock),axis=0))
            changed=replace(data,X=data.X.copy(),y=data.y.copy(),ends=data.ends.copy())
            changed.X[40:]=999;changed.y[40:]=1-changed.y[40:];changed.ends[40:]+=600
            with patch.object(StandardScaler,'fit',side_effect=AssertionError('no refit')):
                self.assertTrue(fit(changed,'logistic','alias')[1]['reused'])
            with np.load(output/record['model_file'],allow_pickle=False) as saved:
                np.testing.assert_array_equal(old.predict_state(saved,data.X),old.predict_state(logistic,data.X))
            changed.X[rows[0],0]+=1
            def fail(*args,**kwargs):
                self.assertEqual(ledger.records()[-1]['kind'],'fit_started')
                raise ValueError('synthetic failure')
            with patch.object(StandardScaler,'fit',side_effect=fail):
                self.assertEqual(fit(changed,'logistic','failure')[1]['status'],'failed')
            with patch.object(StandardScaler,'fit',side_effect=AssertionError('no retry')):
                self.assertTrue(fit(changed,'logistic','failed-alias')[1]['reused'])
            self.assertEqual(ledger.consumed(),3)
            # Constant remains a distinct counted fit; its cache also rejects changed training X.
            self.assertFalse(fit(changed,'constant','changed-constant')[1]['reused'])
            self.assertEqual(ledger.consumed(),4)

    def test_paired_pipeline_16_fits_replay_and_tampering(self):
        data,clock,oldspec=fixture();spec=json.loads(controls.SPEC.read_text())
        masks={'0.0005':np.arange(90)%3!=0,'0.001':np.arange(90)%4<2}
        parts={f'Q{i+2}':dict(train=np.arange(20+10*i),validation=np.arange(20+10*i,30+10*i),
                            refit=np.arange(30+10*i),test=np.arange(30+10*i,40+10*i)) for i in range(3)}
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/'source';output=base/'output'
            for p in (source,output): (p/'models').mkdir(parents=True)
            ledger=FitLedger(base/'ledger');ledger.initialize(0,{'synthetic':True})
            ledger.start_run(old.EXPERIMENT,16,{'synthetic':True})
            cache={};folds=[]
            # Generate only source controls with synthetic data, then exercise actual reuse preflight.
            for name,part in parts.items():
                fold=dict(fold=name,phases={})
                for phase,train,test in PHASES:
                    fits={};states={}
                    for request in ('constant:temporal','logistic:temporal','logistic:0.0005','logistic:0.001'):
                        family,h=request.split(':');tr=part[train]
                        if h!='temporal': tr=tr[masks[h][tr]]
                        states[request],fits[request]=old.fit_cached(data,tr,family,None,oldspec,clock,ledger,
                            f'{name}:{phase}:{request}',name,{},cache,source)
                    evaluations={}
                    for h,mask in masks.items():
                        rows=part[test];rows=rows[mask[rows]]
                        predictions={('constant' if k=='constant_temporal' else k):old.predict_state(states[v.format(h=h)],data.X[rows])
                                     for k,v in controls.CONTROL_NAMES.items()}
                        file=source/f'{name}_{phase}_{h}.npz'
                        artifact=save_arrays(file,dict(rows=rows,y=data.y[rows],starts=data.starts[rows],
                            sides=data.sides[rows],entry_indices=data.entry_indices[rows],**predictions))
                        evaluations[h]=dict(identity_sha256=controls.identity_hash(data,rows),predictions_file=file.name,
                            predictions_sha256=artifact['sha256'],scores={k:old.score(data.y[rows],p) for k,p in predictions.items()})
                    fold['phases'][phase]=dict(fits=fits,evaluations=evaluations)
                folds.append(fold)
            ledger.finish_run(old.EXPERIMENT,'completed',{})
            raw=ledger.path.read_bytes();prior=ledger.consumed();source_report=dict(folds=folds)
            self.assertEqual(prior,16)
            self.assertEqual(controls.verify_sources(data,masks,parts,clock,source_report,source,raw)['unique_controls'],16)
            ledger.start_run(controls.EXPERIMENT,16,{'synthetic':True},independent_failures=True)
            result=controls.run_controls(data,masks,parts,clock,spec,source_report,source,ledger,{},output)
            self.assertEqual(ledger.consumed()-prior,16)
            report=dict(folds=result,new_fits=16,conclusion=controls.conclude(result,spec['thresholds']))
            write_json(output/'report.json',report)
            evidence=controls.verify_output(output,source,data,masks,parts,clock,ledger.path.read_bytes())
            self.assertEqual(evidence['unique_successful_new_models'],16)
            self.assertEqual(evidence['prediction_archives'],12)
            # Changed train input invalidates source reuse, even when labels and row IDs still agree.
            changed=replace(data,X=data.X.copy());changed.X[0,0]+=1
            with self.assertRaisesRegex(ValueError,'Control training changed'):
                controls.verify_sources(changed,masks,parts,clock,source_report,source,raw)
            file=source/folds[0]['phases']['inner']['fits']['logistic:0.0005']['model_file']
            file.write_bytes(file.read_bytes()+b'corrupt')
            with self.assertRaisesRegex(ValueError,'Control model bytes changed'):
                controls.verify_sources(data,masks,parts,clock,source_report,source,raw)
            with self.assertRaisesRegex(ValueError,'budget exhausted'):
                ledger.start_fit(controls.EXPERIMENT,'seventeenth','Q4',{}, {'synthetic':True})
