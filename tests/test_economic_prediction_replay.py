"""Synthetic readonly prediction artifacts; model fitting is always mocked out."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from fxnn import economic_prediction_replay as replay
from fxnn.economic_fit import phase_predictions, runtime
from fxnn.economic_lifecycle import fingerprint


class Matrix:
    def __len__(self): return len(self.decision_ms)


class Supervisor:
    def __init__(self, root, snapshot): self.root, self.snapshot = root, snapshot
    def read(self): return copy.deepcopy(self.snapshot)
    def recover(self): raise AssertionError('Readonly verification cannot recover/mutate')
    def fit(self, *args): raise AssertionError('No replay fit')


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='stage9-replay-synthetic-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {'versions':runtime(),'folds':[],'logistic':{}}
        self.matrix = Matrix()
        first = replay.utc_ms('2024-01-01T00:00:00+00:00')
        self.matrix.decision_ms = np.array([first, first+60000, first+120000],dtype=np.int64)
        self.matrix.X = np.zeros((3,28))
        self.matrix.side = np.array([1,0,-1],dtype=np.int8)
        self.matrix.feature_valid = np.ones(3,dtype=bool)
        self.matrix.volatility_valid = np.ones(3,dtype=bool)
        self.matrix.calendar_eligible = np.array([True,True,False])
        self.matrix.eligible = np.array([True,False,False])
        self.matrix.y = np.array([1,-1,-1],dtype=np.int8)
        self.matrix.information_end_ms = np.array([first+1,-1,-1],dtype=np.int64)
        self.models = {}
        self.fits = {}
        for family in replay.FAMILIES:
            state = {'kind':np.asarray(family)}
            if family == 'constant': state['prior'] = np.asarray(.5)
            else: state.update(mean=np.zeros(28),scale=np.ones(28),coef=np.zeros((1,28)),intercept=np.zeros(1))
            fitted = {'status':'succeeded','F':family,'contract':{'family':family,'source':'authorized-development'},
                      'support':{'rows':2,'positive':1,'negative':1},'diagnostics':{}}
            self.models[family] = (state,fitted)
            self.fits[family] = {'F':family,'contract':fitted['contract'],'status':'succeeded','result':{}}
        self.final = {'segment':'final','S':'S','phases':[{'phase':{'name':'final'},'families':{
            family:{'fit':self.models[family][1]} for family in replay.FAMILIES}}]}
        self.final_artifact = self.write('final.json',self.final)
        scientific = self.write('scientific.json', {'synthetic':True})
        R = {'reports':{'final':self.final_artifact},'sha':'synthetic-release'}
        package = {'S':'S','R':R,'fits':self.fits,'models':list(self.fits.values()),
                   'guard':'UNOPENED','technical_tests':dict.fromkeys(('T1','T2','T3','T4','T5'),True)}
        self.package = self.write('freeze.json',package)
        snapshot = {'files':{'science':scientific},'S':'S','P':self.package,'R':R,'fits':self.fits,
                    'config':self.config,'sealed':True,'guard':'OPENED','checkpoints':[
                        {'phase':'FINAL_MODELS_VERIFIED','artifacts':{'report':self.final_artifact}}]}
        self.supervisor = Supervisor(self.root,snapshot)
        self.evidence = self.source_evidence()
        self.phase = {'name':'confirmation','evaluation_start_ms':first,
                      'evaluation_end_ms':replay.utc_ms('2025-01-01T00:00:00+00:00')}
        self.prediction_report = {'phase':self.phase,'families':{},'scientific_fits':0,'S':'S',
            'freeze_sha256':self.package['sha256'],'confirmation_evidence_sha256':self.evidence['sha256']}
        for family in replay.FAMILIES:
            arrays,metrics = phase_predictions(self.matrix,self.models[family][0],self.phase)
            path=self.root/(family+'.npz');np.savez(path,**arrays)
            self.prediction_report['families'][family]={'fit':self.models[family][1],
                                                       'metrics':metrics,'predictions':fingerprint(path)}
            if family=='logistic':
                rows=list(replay.operational_rows(arrays,True))
                self.operational_path=self.root/'operational.jsonl'
                self.operational_path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        self.prediction_report['operational']=fingerprint(self.operational_path)
        self.report_artifact=self.write('prediction-report.json',self.prediction_report)
        self.mock = patch.object(replay,'verified_model',side_effect=lambda supervisor,contract:self.models[contract['family']])
        self.mock.start();self.addCleanup(self.mock.stop)

    def write(self,name,value):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value))
        return fingerprint(path)

    def source_evidence(self):
        receipt=self.write('confirmation-source-v1/manifest.json',{'synthetic':True})
        index=self.write('data/index/manifest.json',{'files':{'hazards.json':{'sha256':'b'*64}}})
        dataset=self.write('data/manifest.json',{'contract':{'experiment':replay.EXPERIMENT,'phase':'confirmation',
            'S':'S','freeze_sha256':self.package['sha256'],'source_manifest_sha256':receipt['sha256']},
            'files':{'index/manifest.json':{k:v for k,v in index.items() if k!='path'}},'expected_opportunities':3})
        labels=self.write('labels/manifest.json',{'dataset_manifest_sha256':dataset['sha256']})
        self.matrix.provenance={'dataset_manifest':dataset['sha256'],'labels_manifest':labels['sha256'],
                                'index_manifest':index['sha256'],'hazard_sha256':'b'*64}
        return self.write('source-evidence.json',{'S':'S','freeze_sha256':self.package['sha256'],
            'confirmation_access':True,'scientific_fits':0,'dataset':dataset,'labels':labels,'source_manifest':receipt})

    def verify(self):
        return replay.verify_final_probabilities(self.config,self.supervisor,self.matrix,self.final_artifact,
                                                  self.report_artifact,self.evidence)

    def snapshot(self):
        return {str(p):(p.stat().st_mtime_ns,p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}

    def test_full_final_replay_terminal_states_no_files_or_guard_mutations(self):
        for guard in ('OPENED','COMPLETED','INCOMPLETE'):
            with self.subTest(guard=guard):
                self.supervisor.snapshot['guard']=guard
                before=self.snapshot(),copy.deepcopy(self.supervisor.snapshot)
                result=self.verify()
                self.assertEqual(result['rows'],3)
                self.assertEqual(result['scientific_fits'],0)
                self.assertEqual(before,(self.snapshot(),self.supervisor.snapshot))

    def test_generation_authentication_remains_opened_only(self):
        self.supervisor.snapshot['guard']='COMPLETED'
        with self.assertRaisesRegex(ValueError,'OPENED-only'):
            replay.authenticate_frozen_models(self.config,self.supervisor,self.final_artifact)
        self.supervisor.snapshot['guard']='UNOPENED'
        with self.assertRaises(ValueError):self.verify()

    def test_npz_every_array_and_metrics_reconstructed_not_only_probability(self):
        for target in ('accepted','metrics'):
            with self.subTest(target=target):
                saved=copy.deepcopy(self.prediction_report)
                if target=='accepted':
                    path=Path(saved['families']['constant']['predictions']['path'])
                    with np.load(path,allow_pickle=False) as archive: arrays={k:archive[k] for k in archive.files}
                    arrays['accepted'][0]=0
                    altered=self.root/'altered.npz';np.savez(altered,**arrays)
                    saved['families']['constant']['predictions']=fingerprint(altered)
                else:saved['families']['constant']['metrics']['metric_rows']+=1
                self.report_artifact=self.write('altered-report.json',saved)
                with self.assertRaisesRegex(ValueError,'mismatch'):self.verify()

    def test_operational_missing_extra_none_and_availability_tamper(self):
        original=self.operational_path.read_text().splitlines()
        for mode in ('missing','extra','none','available','nan'):
            with self.subTest(mode=mode):
                rows=original.copy()
                if mode=='missing':rows.pop()
                elif mode=='extra':rows.append(rows[-1])
                else:
                    row=json.loads(rows[1])
                    if mode=='none':row['probability']=0.0
                    elif mode=='available':row['model_available']=False
                    else:row['probability']=float('nan')
                    rows[1]=json.dumps(row)
                self.operational_path.write_text('\n'.join(rows)+'\n')
                self.prediction_report['operational']=fingerprint(self.operational_path)
                self.report_artifact=self.write('prediction-report.json',self.prediction_report)
                with self.assertRaises(ValueError):self.verify()

    def test_source_evidence_matrix_and_config_mismatch_rejected(self):
        self.matrix.provenance['dataset_manifest']='other'
        with self.assertRaisesRegex(ValueError,'Matrix'):self.verify()
        self.matrix.provenance=json.loads(Path(self.evidence['path']).read_text())
        changed={**self.config,'threshold':.6}
        with self.assertRaisesRegex(ValueError,'config'):
            replay.authenticate_frozen_models(changed,self.supervisor,self.final_artifact,replay=True)

    def test_frozen_report_unbound_or_contract_substitution_rejected(self):
        other=self.write('unbound-final.json',self.final)
        with self.assertRaisesRegex(ValueError,'frozen release'):
            replay.authenticate_frozen_models(self.config,self.supervisor,other,replay=True)
        self.supervisor.snapshot['R']={'reports':{},'sha':'other'}
        with self.assertRaisesRegex(ValueError,'provenance'):self.verify()

    def test_stream_shape_range_type_and_model_unavailable_validation(self):
        for p in (np.array([.5]),np.array([.5,np.inf]),np.array([.5,1.1])):
            with self.subTest(p=p),self.assertRaises(ValueError):
                list(replay.operational_rows({'decision_ms':np.array([1,2]),'probability':p},True))
        rows=list(replay.operational_rows({'decision_ms':np.array([1,2]),'probability':np.array([np.nan,np.nan])},False))
        self.assertEqual([r['probability'] for r in rows],[None,None])
        with self.assertRaises(ValueError):
            list(replay.operational_rows({'decision_ms':np.array([1]),'probability':np.array([.5])},False))

    def test_development_projection_replays_verified_report_and_missing_row(self):
        # verify_phases owns full model/array/metric recomputation; exercise wiring.
        phase={'phase':{'name':'2023Q2:refit'},'families':{
            'logistic':self.prediction_report['families']['logistic']}}
        model={'phases':[phase]}
        artifact=self.write('development-report.json',model)
        self.supervisor.snapshot['checkpoints'].append({'phase':'DEVELOPMENT_VERIFIED','artifacts':{'report':artifact}})
        with patch.object(replay,'phase_plan',return_value=['registered']),patch.object(replay,'verify_phases',return_value=model) as verified:
            result=replay.verify_operational_predictions(self.config,self.supervisor,self.matrix,None,artifact,
                                                        self.prediction_report['operational'])
            self.assertEqual(result['rows'],3)
            verified.assert_called_once()
            self.operational_path.write_text(self.operational_path.read_text().splitlines()[0]+'\n')
            with self.assertRaisesRegex(ValueError,'missing'):
                replay.verify_operational_predictions(self.config,self.supervisor,self.matrix,None,artifact,
                                                       fingerprint(self.operational_path))

    def generated_module(self):
        from fxnn import economic_research
        return economic_research

    def test_generated_final_patch_authenticates_and_replays(self):
        module=self.generated_module()
        output=self.root/'new-generated'
        result=module.final_probabilities(self.config,self.supervisor,self.matrix,self.final_artifact,
                                          output,self.evidence)
        self.assertEqual(result['S'],'S')
        before=self.snapshot()
        self.supervisor.snapshot['guard']='COMPLETED'
        replay.verify_final_probabilities(self.config,self.supervisor,self.matrix,self.final_artifact,
                                          fingerprint(output/'report.json'),self.evidence)
        self.assertEqual(before,self.snapshot())
        with self.assertRaises(ValueError):
            module.final_probabilities(self.config,self.supervisor,self.matrix,self.final_artifact,
                                       self.root/'forbidden',self.evidence)
        self.assertFalse((self.root/'forbidden').exists())

    def test_generated_operational_patch_uses_authenticated_report(self):
        module=self.generated_module()
        model={'phases':[{'phase':{'name':'2023Q2:refit'},'families':{
            'logistic':self.prediction_report['families']['logistic']}}]}
        artifact=self.write('development-models.json',model)
        self.supervisor.snapshot['checkpoints'].append({'phase':'DEVELOPMENT_VERIFIED','artifacts':{'report':artifact}})
        with patch('fxnn.economic_fit.phase_plan',return_value=[]),patch('fxnn.economic_fit.verify_phases',return_value=model),\
             patch.object(replay,'phase_plan',return_value=[]),patch.object(replay,'verify_phases',return_value=model):
            result=module.operational_predictions(self.config,self.supervisor,self.matrix,None,artifact,self.root/'projected.jsonl')
        self.assertEqual([json.loads(line) for line in Path(result['path']).read_text().splitlines()],
                         [json.loads(line) for line in self.operational_path.read_text().splitlines()])



if __name__=='__main__':unittest.main()
