from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.utils import check_random_state, shuffle

from fxnn import session_models as new
from fxnn.fit_ledger import FitLedger
from fxnn.mlp_comparison import FixedMLP
from fxnn.research import Dataset
from fxnn.session_clock import SessionClock
from fxnn.session_neural import FixedUpdates
from fxnn.temporal import uniqueness_weights


def fixture():
    rng = np.random.RandomState(17)
    starts = np.arange(90, dtype=np.int64)*600
    data = Dataset(rng.normal(size=(90,28)), np.arange(90)%2, starts, starts+60,
                   starts+4320*60, np.arange(90), np.ones(90,dtype=np.int8),
                   [f'x{i}' for i in range(28)], {}, 0)
    clock = SessionClock(0,np.ones(10000,dtype=bool))
    spec = json.loads(new.SPEC.read_text())
    return data, clock, spec


def ledger_at(path):
    ledger = FitLedger(path)
    ledger.initialize(0, {'synthetic': True})
    ledger.start_run(new.EXPERIMENT,40,{'synthetic':True},independent_failures=True)
    return ledger


class SessionModelTests(unittest.TestCase):
    def test_open_time_weights_exclude_closure_duration(self):
        data, _, _ = fixture()
        data = replace(data, starts=np.array([0,60]), ends=np.array([240,120]))
        # Minute 2 is closed. First event has 3 open minutes, second 1.
        clock = SessionClock(0,np.array([True,True,False,True,True]))
        actual = new.open_weights(data,np.array([0,1]),clock)
        expected = uniqueness_weights(np.array([0,1]),np.array([3,2]))
        np.testing.assert_allclose(actual,expected)
        self.assertFalse(np.allclose(actual,uniqueness_weights(data.starts,data.ends)))

    def test_full_epoch_and_partial_prefix_match_native_adam(self):
        _, _, spec = fixture()
        X = np.random.RandomState(8).normal(size=(11,3))
        y, w = np.arange(11)%2,np.linspace(.3,1.7,11)
        params = {**spec['model'],'batch_size':4}
        actual = FixedUpdates().fit(X,y,w,params,9)
        native = FixedMLP().fit(X,y,w,params,3)
        for a,b in zip(actual.model.coefs_+actual.model._optimizer.ms+actual.model._optimizer.vs,
                       native.model.coefs_+native.model._optimizer.ms+native.model._optimizer.vs):
            np.testing.assert_array_equal(a,b)
        partial = FixedUpdates().fit(X,y,w,params,5)
        reference = FixedMLP().fit(X,y,w,params,1)
        transformed = reference.scaler.transform(X)
        order = shuffle(np.arange(11),random_state=check_random_state(0))
        reference.model.shuffle = False
        for batch in (order[:4],order[4:8]):
            reference.model.partial_fit(transformed[batch],y[batch],classes=[0,1],sample_weight=w[batch])
        for a,b in zip(partial.model.coefs_+partial.model.intercepts_,reference.model.coefs_+reference.model.intercepts_):
            np.testing.assert_array_equal(a,b)
        self.assertEqual(partial.model._optimizer.t,5)
        self.assertEqual(len(partial.model.loss_curve_),1)

    def test_cache_scaler_isolation_export_and_failure_no_retry(self):
        data,clock,spec = fixture();rows = np.arange(30)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp);(output/'models').mkdir();ledger=ledger_at(output/'ledger');cache={}
            def fit(d,identifier,updates=3):
                return new.fit_cached(d,rows,'mlp',updates,spec,clock,ledger,identifier,'Q2',{},cache,output)
            state,report = fit(data,'one')
            expected = np.average(data.X[rows],weights=new.open_weights(data,rows,clock),axis=0)
            np.testing.assert_allclose(state['mean'],expected)
            changed = replace(data,X=data.X.copy(),y=data.y.copy(),ends=data.ends.copy())
            changed.X[30:] = 9999;changed.y[30:] = 1-changed.y[30:];changed.ends[30:] += 60
            same,alias=fit(changed,'alias')
            self.assertIs(state,same);self.assertTrue(alias['reused'])
            with np.load(output/report['model_file'],allow_pickle=False) as exported:
                np.testing.assert_array_equal(new.predict_state(exported,data.X),new.predict_state(state,data.X))
            def failure(*args,**kwargs):
                self.assertEqual(ledger.records()[-1]['kind'],'fit_started')
                raise ValueError('synthetic failure')
            with patch.object(StandardScaler,'fit',side_effect=failure):
                failed,record=fit(data,'failure',4)
            self.assertIsNone(failed);self.assertEqual(record['status'],'failed')
            with patch.object(FixedUpdates,'fit',side_effect=AssertionError('must not retry')):
                self.assertTrue(fit(data,'failed-alias',4)[1]['reused'])
            self.assertEqual(ledger.consumed(),2)

    def test_pipeline_paired_predictions_and_cross_fold_cache(self):
        data,clock,spec=fixture()
        masks={'0.0005':np.arange(90)%3!=0,'0.001':np.arange(90)%4<2}
        partitions={};protocol={'folds':[]}
        for i in range(3):
            name=f'Q{i+2}';protocol['folds'].append({'name':name})
            n=20+i*10
            partitions[name]=dict(train=np.arange(n),validation=np.arange(n,n+10),
                                   refit=np.arange(n+10),test=np.arange(n+10,n+20))
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);(output/'models').mkdir();ledger=ledger_at(output/'ledger')
            with patch('sklearn.neural_network._multilayer_perceptron.train_test_split',side_effect=AssertionError):
                reports,budget=new.run_models(data,masks,partitions,protocol,spec,clock,ledger,{},output)
            self.assertEqual(budget,20)
            self.assertEqual(ledger.consumed(),28) # All tiny MLP20/budget schedules coincide.
            for report in reports:
                for phase in report['phases'].values():
                    for universe,ev in phase['evaluations'].items():
                        self.assertEqual(len(ev['scores']),4 if universe=='temporal' else 7)
                        with np.load(output/ev['predictions_file'],allow_pickle=False) as saved:
                            for method,value in ev['scores'].items():
                                self.assertEqual(value,new.score(saved['y'],saved[method]))
                                self.assertEqual(value['support'],ev['support'])
            json.dumps(new.conclude(reports,spec['thresholds']),allow_nan=False)

    def test_interruptions_and_nonfinite_are_rejected(self):
        data,_,spec=fixture();X=data.X[:4];y=data.y[:4];w=np.ones(4)
        params={**spec['model'],'batch_size':4}
        with patch.object(MLPClassifier,'_backprop',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):FixedUpdates().fit(X,y,w,params,2)
        for budget in (0,-1,True,1.5):
            with self.assertRaises(ValueError):FixedUpdates().fit(X,y,w,params,budget)

    def test_update_budget_only_depends_on_training_support(self):
        parts={'Q2':{'train':np.arange(1025),'refit':np.arange(2050),'test':np.arange(100000)}}
        self.assertEqual(new.common_budget(parts),60)
        parts['Q2']['test']=np.array([],dtype=int)
        self.assertEqual(new.common_budget(parts),60)
