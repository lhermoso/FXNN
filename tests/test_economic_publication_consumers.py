"""Supplemental native-Fraction publication and frozen consumer integration tests.

All scientific I/O and lifecycle calls use synthetic fixtures/mocks. The new
publisher's execute/main, exact codec, publication and frozen report comparisons
run unchanged. No repository, source, market or scientific ledger writes.
"""
from contextlib import ExitStack
from fractions import Fraction
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
sys.path.insert(0,str(REPO/'tests'))
from fxnn import economic_fit, economic_research as research, economic_report
from fxnn.economic_account import serializable
from fxnn.economic_lifecycle import fingerprint
from test_economic_report import fixture


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class PublicationConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='economic-publication-consumer-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.publisher=module('economic_publication_consumer_publisher',REPO/'scripts/publish_economic_portfolios.py')
        self.cli=module('economic_publication_consumer_frozen_cli',REPO/'scripts/run_economic_ticks.py')
        self.config={'global_ledger':str(self.root/'UNUSED-ledger'),'folds':[],'logistic':{},'versions':{}}
        self.sha='a'*40
        self.life=Mock();self.life.root=self.root/'canonical';self.life.root.mkdir()
        self.models={}
        for final in (False,True):
            name='final' if final else '2023Q2:refit'
            value={'phases':[{'phase':{'name':name},'families':{
                family:{'fit':{'status':'succeeded','support':{'rows':2,'positive':1,'negative':1},
                               'contract':{'family':family}}} for family in ('constant','logistic')}}]}
            self.models[final]=self.write(('models-final' if final else 'models-development')+'/report.json',value)
        self.snapshot={'config':self.config,'guard':'OPENED','sealed':True,'checkpoints':[
            {'phase':'DEVELOPMENT_VERIFIED','artifacts':{'report':self.models[False]}},
            {'phase':'FINAL_MODELS_VERIFIED','artifacts':{'report':self.models[True]}}]}
        self.life.read.side_effect=lambda:self.snapshot.copy()
        self.write('canonical/development-data-intent.json',{'binding':{'output':str(self.root/'development')}})
        for phase in ('development','confirmation'):
            self.write(phase+'/source-evidence.json',{})
        self.op=self.write('operational-development.jsonl',{'synthetic':'operational'})
        self.write('probabilities-confirmation/report.json',{'operational':self.op})
        self.native={False:fixture(),True:fixture(True)}
        # Native exact amounts are the regression trigger; ordinary json.dumps
        # cannot encode the frozen portfolio result before its existing codec.
        self.assertTrue(any(isinstance(v,Fraction) for v in self.native[False]['scenarios'][0]['total'].values()))

    def write(self,name,value):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,allow_nan=False))
        return fingerprint(path)

    def io_mocks(self,stack,target):
        stack.enter_context(patch.object(target.research,'load_config',return_value=self.config))
        stack.enter_context(patch.object(target.research,'verify_preregistration',return_value={}))
        stack.enter_context(patch.object(target.research,'clock_for',return_value=object()))
        stack.enter_context(patch.object(target.research,'load_window_data',return_value=object()))
        stack.enter_context(patch.object(target.research,'verify_operational_predictions',autospec=True))
        stack.enter_context(patch.object(target.research,'verify_final_probabilities',autospec=True))
        portfolio=stack.enter_context(patch.object(target.research,'portfolio_segment',autospec=True,
            side_effect=lambda *args,**kwargs:self.native[kwargs.get('confirmation',False)]))
        stack.enter_context(patch.object(target,'Lifecycle',return_value=self.life))
        return portfolio

    def published(self,phase):
        with ExitStack() as stack:
            portfolio=self.io_mocks(stack,self.publisher)
            frozen=stack.enter_context(patch.object(self.publisher,'verify_frozen_publisher',autospec=True))
            result=self.publisher.execute(REPO,self.root,self.sha,phase)
        self.assertEqual(result,serializable(self.native[phase=='confirmation']))
        self.assertEqual(json.loads((self.root/('aggregate-'+phase+'.json')).read_text()),result)
        self.assertEqual(portfolio.call_args.kwargs,{'confirmation':phase=='confirmation','replay':False})
        self.assertEqual(frozen.call_count,int(phase=='confirmation'))
        return result

    def assert_no_scientific_writes(self):
        self.life.fit.assert_not_called();self.life.poison.assert_not_called()
        self.life.begin_confirmation.assert_not_called();self.life.received_payload.assert_not_called()
        self.assertFalse((self.root/'UNUSED-ledger').exists())

    def test_actual_execute_publishes_both_native_fraction_phases(self):
        for phase in ('development','confirmation'):
            with self.subTest(phase=phase):
                result=self.published(phase)
                self.assertEqual(economic_report.evaluate_portfolios(result,confirmation=phase=='confirmation'),
                    economic_report.evaluate_portfolios(self.native[phase=='confirmation'],confirmation=phase=='confirmation'))
        self.assert_no_scientific_writes()

    def test_actual_main_stdout_json_for_both_native_fraction_phases(self):
        for phase in ('development','confirmation'):
            with self.subTest(phase=phase),ExitStack() as stack:
                self.io_mocks(stack,self.publisher)
                stack.enter_context(patch.object(self.publisher,'verify_frozen_publisher',autospec=True))
                stdout=stack.enter_context(patch('sys.stdout',new_callable=io.StringIO))
                self.publisher.main([phase,'--output',str(self.root),'--preregistered-sha',self.sha])
                self.assertEqual(json.loads(stdout.getvalue()),serializable(self.native[phase=='confirmation']))
        self.assert_no_scientific_writes()

    def test_actual_replay_both_phases_never_publishes_or_changes_files(self):
        for phase in ('development','confirmation'):
            self.published(phase)
            if phase=='confirmation':self.snapshot['guard']='COMPLETED'
            before={str(p):(p.stat().st_mtime_ns,p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
            with ExitStack() as stack:
                portfolio=self.io_mocks(stack,self.publisher)
                stack.enter_context(patch.object(self.publisher,'verify_frozen_publisher',autospec=True))
                stack.enter_context(patch.object(self.publisher,'publish_aggregate',side_effect=AssertionError('replay write')))
                stdout=stack.enter_context(patch('sys.stdout',new_callable=io.StringIO))
                self.publisher.main([phase,'--replay','--output',str(self.root),'--preregistered-sha',self.sha])
                self.assertEqual(json.loads(stdout.getvalue()),serializable(self.native[phase=='confirmation']))
                self.assertTrue(portfolio.call_args.kwargs['replay'])
            after={str(p):(p.stat().st_mtime_ns,p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
        self.assert_no_scientific_writes()

    def test_output_alias_and_unopened_confirmation_stop_before_scientific_processing(self):
        for phase, alias, guard in [('development', True, 'UNOPENED'), ('confirmation', False, 'UNOPENED')]:
            self.snapshot['guard'] = guard
            with ExitStack() as stack:
                portfolio = self.io_mocks(stack, self.publisher)
                stack.enter_context(patch.object(self.publisher, 'verify_frozen_publisher', autospec=True))
                matrix = self.publisher.research.load_window_data
                with self.assertRaises(ValueError):
                    self.publisher.execute(REPO, self.root/'alias' if alias else self.root, self.sha, phase)
                matrix.assert_not_called()
                portfolio.assert_not_called()
        self.assert_no_scientific_writes()

    def run_report_cli(self,confirmation):
        phase='confirmation-report' if confirmation else 'development-report'
        with ExitStack() as stack:
            self.io_mocks(stack,self.cli)
            stdout=stack.enter_context(patch('sys.stdout',new_callable=io.StringIO))
            self.cli.main([phase,'--config',str(REPO/'configs/economic_ticks_v1.json'),
                           '--output',str(self.root),'--preregistered-sha',self.sha])
            json.loads(stdout.getvalue())
        return json.loads((self.root/('report-confirmation' if confirmation else 'report-development')/'report.json').read_text())

    def test_frozen_report_clis_interpret_published_codec_exactly_as_native(self):
        self.published('development');self.published('confirmation')
        for confirmation in (False,True):
            actual=self.run_report_cli(confirmation)
            kwargs={'confirmation':{'execution_status':'COMPLETED','portfolios':self.native[True]}} if confirmation else {}
            expected=economic_report.build_report(json.loads(Path(self.models[False]['path']).read_text()),
                json.loads(Path(self.models[True]['path']).read_text()),self.native[False],
                artifacts={'development_models':self.models[False],'final_models':self.models[True]},**kwargs)
            self.assertEqual(actual,expected)
            # Re-enter the frozen existing-directory equality branch as well.
            self.assertEqual(self.run_report_cli(confirmation),expected)
        self.assert_no_scientific_writes()

    def test_frozen_complete_consumer_accepts_exact_published_reports(self):
        self.published('development');self.published('confirmation');self.run_report_cli(True)
        with ExitStack() as stack:
            portfolio=self.io_mocks(stack,self.cli)
            stdout=stack.enter_context(patch('sys.stdout',new_callable=io.StringIO))
            self.cli.main(['complete','--config',str(REPO/'configs/economic_ticks_v1.json'),
                           '--output',str(self.root),'--preregistered-sha',self.sha])
            result=json.loads(stdout.getvalue())
        self.life.close.assert_called_once_with('COMPLETED',result)
        self.assertEqual(len(portfolio.call_args_list),2)
        self.assertTrue(all(call.kwargs['replay'] for call in portfolio.call_args_list))
        self.assert_no_scientific_writes()

    def test_frozen_freeze_consumer_compares_published_against_native_replay(self):
        self.published('development');self.run_report_cli(False)
        self.snapshot.update(guard='UNOPENED',sealed=False)
        dataset=self.write('development/dataset/manifest.json',{'contract':{
            'preregistered_sha':self.sha,'config':self.config,'scientific_files':{}}})
        source=self.write('development/source-evidence.json',{'dataset':dataset})
        port=self.write('portfolios-development/portfolio-manifest.json',{'synthetic':True})
        artifacts={'development_source':source,'development_models':self.models[False],'final_models':self.models[True],
                   'development_portfolios':port,'development_report':fingerprint(self.root/'report-development/report.json')}
        validation={'head_sha':self.sha,'preregistered_sha':self.sha,**dict.fromkeys([
            'synthetic_tests_passed','compile_passed','diff_check_passed','portfolio_replay_passed',
            'model_replay_passed','resource_benchmark_passed'],True)}
        receipts={'ci':self.write('ci.json',{}),'review':self.write('review.json',{}),
            'dependencies':self.write('dependencies.json',{'repository':'lhermoso/FXNN','issues':[
                {'number':n,'state':'CLOSED','closedAt':'synthetic'} for n in (6,7,8,19)]}),
            'validation':self.write('validation.json',validation)}
        with ExitStack() as stack:
            for name in ('verify_preregistration','verified_ci_receipt','verified_review_receipt',
                         'load_window_data','clock_for','verify_operational_predictions','resource_preflight'):
                stack.enter_context(patch.object(research,name,return_value={}))
            stack.enter_context(patch.object(research,'git',side_effect=lambda repo,*args:'' if args[0]=='status' else self.sha))
            stack.enter_context(patch.object(research,'portfolio_segment',autospec=True,return_value=self.native[False]))
            stack.enter_context(patch.object(economic_fit,'phase_plan',return_value=[{'name':'final'}]))
            stack.enter_context(patch.object(economic_fit,'verify_phases',autospec=True))
            research.release_freeze(self.root,self.config,self.life,self.sha,receipts,artifacts)
        self.life.freeze.assert_called_once()
        self.assertEqual(self.life.freeze.call_args.args[0],self.sha)
        self.assertEqual(self.life.freeze.call_args.args[5],[{'family':'constant'},{'family':'logistic'}])
        self.assert_no_scientific_writes()


if __name__=='__main__':unittest.main()
