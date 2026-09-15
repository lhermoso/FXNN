from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import numpy as np
from fxnn.bootstrap_fit import ArtifactStore,fit_unit,replay_unit,abort,EXPERIMENT
from fxnn.experiment_fit import StageLedger
from fxnn.research import Dataset
from fxnn.session_models import predict_state


class BootstrapFitTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.ledger=StageLedger(self.root/'ledger',8)
        self.ledger.initialize(0,'synthetic'); self.prefix=self.ledger.path.read_bytes()
        self.ledger.start_run(EXPERIMENT,156,{'fixture':1},independent_failures=True)
        self.data=Dataset(np.array([[0.,1.],[1.,1.],[10.,1.],[12.,1.]]),np.array([0,1,0,1]),np.arange(4)*60,np.arange(4)*60+60,np.arange(4)*60+120,np.arange(4),np.ones(4,int),['a','side'],{'a':[0]},0)
        self.rows=np.array([0,0,0,1,2,3]); self.params={'random_state':0,'max_iter':1000}
        self.cache={}; self.store=ArtifactStore(self.root,100000,minimum_safety=0)

    def fit(self,fit_id='fit',rows=None):
        return fit_unit(self.data,self.rows if rows is None else rows,self.params,self.ledger,fit_id,'fold',{'fixture':1},{'scheme':'synthetic'},self.cache,self.root,self.store)

    def test_unit_weights_duplicates_and_replay(self):
        state,report=self.fit()
        np.testing.assert_allclose(state['mean'],self.data.X[self.rows].mean(axis=0))
        self.assertNotEqual(state['mean'][0],self.data.X.mean(axis=0)[0])
        self.assertIs(self.fit('alias')[0],state); self.assertEqual(self.ledger.consumed(),1)
        self.ledger.finish_run(EXPERIMENT,'completed',{})
        replay=replay_unit(self.data,self.rows,self.params,self.ledger,{'fixture':1},{'scheme':'synthetic'},report,self.root,self.prefix)
        np.testing.assert_array_equal(predict_state(state,self.data.X),predict_state(replay,self.data.X))

    def test_missing_class_no_redraw_and_support_tamper(self):
        rows=np.array([0,0,2]); state,report=self.fit(rows=rows)
        self.assertIsNone(state); self.assertEqual(self.ledger.consumed(),0)
        report=dict(report,support={'rows':999,'positive':0,'negative':999})
        with self.assertRaisesRegex(ValueError,'support'):
            replay_unit(self.data,rows,self.params,self.ledger,{'fixture':1},{'scheme':'synthetic'},report,self.root,self.prefix)

    def test_model_failure_terminal_and_start_binding(self):
        with patch('fxnn.bootstrap_fit.LogisticRegression.fit',side_effect=ValueError('numeric')):
            state,report=self.fit()
        self.assertIsNone(state); self.assertIsNone(self.fit('alias')[0]); self.assertEqual(self.ledger.consumed(),1)
        replay_unit(self.data,self.rows,self.params,self.ledger,{'fixture':1},{'scheme':'synthetic'},report,self.root,self.prefix)
        records=self.ledger.records()
        starts=[r for r in records if r['kind']=='fit_started']; starts[0]['stage']=7
        with patch.object(self.ledger,'records',return_value=records):
            with self.assertRaisesRegex(ValueError,'start contract'):
                replay_unit(self.data,self.rows,self.params,self.ledger,{'fixture':1},{'scheme':'synthetic'},report,self.root,self.prefix)

    def test_storage_faults_abort_and_preserve_attempt(self):
        with patch.object(self.store,'arrays',side_effect=OSError('disk')):
            with self.assertRaises(OSError): self.fit()
        self.cache.clear()
        with self.assertRaisesRegex(RuntimeError,'aborted'): self.fit('later')
        error=OSError('original')
        with patch.object(self.store,'json',side_effect=OSError('failure disk')):
            abort(self.ledger,self.root,error,self.store)
        self.assertEqual(self.ledger.records()[-1]['status'],'aborted')

    def test_disk_check_and_exclusive_fsync(self):
        from collections import namedtuple
        Usage=namedtuple('Usage','total used free')
        with patch('fxnn.bootstrap_fit.shutil.disk_usage',return_value=Usage(10,9,1)):
            with self.assertRaisesRegex(OSError,'free disk'): self.store.check()
        with patch('fxnn.bootstrap_fit.os.fsync',side_effect=OSError('fsync')):
            with self.assertRaises(OSError): self.store.json(self.root/'partial.json',{'value':1})
        self.assertTrue((self.root/'partial.json').exists())
        with self.assertRaises(FileExistsError): self.store.json(self.root/'partial.json',{})

    def test_finish_fit_and_export_report_faults_poison_run(self):
        with patch.object(self.ledger,'finish_fit',side_effect=OSError('terminal unavailable')):
            with self.assertRaises(OSError): self.fit()
        self.assertEqual(self.ledger.consumed(),1)
        self.cache.clear()
        with self.assertRaisesRegex(RuntimeError,'aborted'): self.fit('alias')
        report=__import__('json').loads(next((self.root/'models').glob('*.json')).read_text())
        with self.assertRaises(ValueError):
            replay_unit(self.data,self.rows,self.params,self.ledger,{'fixture':1},{'scheme':'synthetic'},report,self.root,self.prefix)

    def test_start_scaler_and_companion_failures(self):
        original=self.ledger.start_fit
        def start_then_raise(*args,**kwargs):
            original(*args,**kwargs); raise OSError('start fsync failed')
        with patch.object(self.ledger,'start_fit',side_effect=start_then_raise),patch('fxnn.bootstrap_fit.StandardScaler.fit') as scaler:
            with self.assertRaises(OSError): self.fit()
            scaler.assert_not_called()
        self.assertEqual(self.ledger.consumed(),1)
        with self.assertRaises(RuntimeError): self.fit('alias')

    def test_companion_json_failure_never_succeeds(self):
        with patch.object(self.store,'json',side_effect=OSError('companion')):
            with self.assertRaises(OSError): self.fit()
        self.assertEqual(self.ledger.records()[-1]['status'],'failed')
        self.assertTrue(list((self.root/'models').glob('*.npz')))
        with self.assertRaises(RuntimeError): self.fit('later')
