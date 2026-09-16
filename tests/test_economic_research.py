import copy
import json
from pathlib import Path
import tempfile
import subprocess
from unittest.mock import patch
import unittest

from fxnn.economic_research import load_config, verified_ci_receipt


class EconomicResearchTests(unittest.TestCase):
    def test_fixed_config_rejects_year_threshold_and_ledger_alias(self):
        path=Path(__file__).resolve().parents[1]/'configs/economic_ticks_v1.json'
        config=load_config(path)
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'config.json'
            for key,value in [('threshold',.6),('confirmation_utc',['2025-01-01','2026-01-01']),
                              ('global_ledger','/tmp/retry/ledger.jsonl'),('max_total_fits',15)]:
                modified=copy.deepcopy(config);modified[key]=value
                target.write_text(json.dumps(modified))
                with self.assertRaises(ValueError):load_config(target)

    def test_preregistration_rejects_deleted_scientific_module(self):
        from fxnn.economic_research import verify_preregistration, science_paths
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'fxnn').mkdir()
            (root/'fxnn/deleted_scientific.py').write_text('VALUE=1\n')
            for path in science_paths(root):
                path.parent.mkdir(parents=True,exist_ok=True)
                if not path.exists():path.write_text('registered\n')
            def git(*args):return subprocess.check_output(['git','-C',temp,*args],text=True).strip()
            git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            git('add','fxnn','scripts','configs','docs');git('commit','-qm','synthetic preregistration')
            sha=git('rev-parse','HEAD')
            verify_preregistration(root,sha)
            (root/'fxnn/deleted_scientific.py').unlink()
            with self.assertRaisesRegex(ValueError,'inventory'):verify_preregistration(root,sha)

    def test_model_checkpoint_rejects_new_output_before_run(self):
        from fxnn.economic_research import model_segment
        from unittest.mock import Mock
        path=Path(__file__).resolve().parents[1]/'configs/economic_ticks_v1.json'
        config=load_config(path)
        with tempfile.TemporaryDirectory() as temp:
            life=Mock();life.read.return_value={'config':config,'checkpoints':[{
                'phase':'DEVELOPMENT_VERIFIED','artifacts':{'report':{'path':temp+'/original/report.json'}}}]}
            with patch('fxnn.economic_fit.run_phases') as fit:
                with self.assertRaisesRegex(ValueError,'authoritative checkpoint'):
                    model_segment(config,life,None,None,Path(temp)/'alias')
                fit.assert_not_called()
            self.assertFalse((Path(temp)/'alias').exists())

    def test_data_intent_resumes_same_contract_preserves_partial_and_rejects_alias(self):
        from fxnn.economic_research import durable_data_segment
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config={'global_ledger':str(root/'ledger.jsonl')}
            output=root/'data'
            def fail():
                output.mkdir();(output/'unfinished').write_text('forensics')
                raise OSError('simulated crash')
            with self.assertRaises(OSError):durable_data_segment(config,output,'development',{'S':'fixed'},fail)
            def succeed():
                output.mkdir();(output/'source-evidence.json').write_text('{"synthetic":true}')
                return {'synthetic':True}
            with patch('fxnn.economic_research.load_window_data'), patch('fxnn.economic_research.validate_data_contract'):
                result=durable_data_segment(config,output,'development',{'S':'fixed'},succeed)
                self.assertEqual(result,{'synthetic':True})
                self.assertEqual(len(list(root.glob('data.partial-*/unfinished'))),1)
                self.assertEqual(durable_data_segment(config,output,'development',{'S':'fixed'},fail),result)
                with self.assertRaisesRegex(ValueError,'alias conflict'):
                    durable_data_segment(config,root/'alias','development',{'S':'fixed'},succeed)
                with self.assertRaisesRegex(ValueError,'alias conflict'):
                    durable_data_segment(config,output,'development',{'S':'changed'},succeed)

    def test_prospective_review_cannot_authorize_frozen_opening(self):
        from fxnn.economic_research import verified_review_receipt, RELEASE_CRITERIA, RELEASE_SCOPE
        sha='a'*40
        review={'schema_version':1,'verdict':'APPROVED','reviewed_head_sha':sha,
                'inconclusive_reason':None,'findings':[],
                'acceptance_criteria':[{'id':'PROSPECTIVE','criterion':'Implementation readiness only; full release review remains mandatory',
                    'status':'COVERED','explicit':True,'severity':'NONE','evidence':'Not authorization to open 2024'}]}
        with self.assertRaisesRegex(ValueError,'prospective approval'):verified_review_receipt(review,sha)
        review['acceptance_criteria']=[{'id':key,'criterion':RELEASE_SCOPE if key=='RELEASE-SCOPE' else key,
            'status':'COVERED','explicit':True,'severity':'NONE','evidence':'Synthetic full release coverage'} for key in RELEASE_CRITERIA]
        self.assertTrue(verified_review_receipt(review,sha))
        for mutation in ('scope','partial','missing','duplicate','implicit','no_evidence'):
            bad=copy.deepcopy(review)
            item=next(v for v in bad['acceptance_criteria'] if v['id']=='RELEASE-SCOPE')
            if mutation=='scope':item['criterion']='Prospective only'
            if mutation=='partial':item['status']='PARTIAL'
            if mutation=='missing':bad['acceptance_criteria'].remove(item)
            if mutation=='duplicate':bad['acceptance_criteria'].append(item)
            if mutation=='implicit':item['explicit']=False
            if mutation=='no_evidence':item['evidence']=''
            with self.assertRaises(ValueError):verified_review_receipt(bad,sha)

    def test_ci_requires_exact_sha_and_meaningful_steps(self):
        sha='a'*40
        receipt=dict(head_sha=sha,conclusion='success',required_jobs=['tests'],
                     meaningful_steps=['caller cannot waive actual workflow steps'],
                     jobs=[dict(name='tests',conclusion='success',steps=[
                         dict(name=name,conclusion='success',
                              started_at='2026-09-15T00:00:00Z',completed_at='2026-09-15T00:00:20Z')
                         for name in ['Run python -m unittest discover -s tests -v',
                                      'Run python -m compileall -q fxnn scripts','Run git diff --check']])])
        self.assertTrue(verified_ci_receipt(receipt,sha))
        for mutation in ('sha','billing','empty','skipped'):
            bad=copy.deepcopy(receipt)
            if mutation=='sha':bad['head_sha']='b'*40
            if mutation=='billing':bad['conclusion']='failure'
            if mutation=='empty':bad['jobs'][0]['steps']=[]
            if mutation=='skipped':bad['jobs'][0]['steps'][0]['conclusion']='skipped'
            with self.assertRaises(ValueError):verified_ci_receipt(bad,sha)


if __name__=='__main__':unittest.main()
