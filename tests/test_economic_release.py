"""Release consumer persistence faults must precede sealing the canonical run."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from fxnn import economic_research as research, economic_report, economic_fit


class EconomicReleaseTests(unittest.TestCase):
    def test_release_sync_fault_poisons_once_and_never_freezes(self):
        self.release_case(OSError)

    def test_release_sync_interruptions_do_not_poison_or_freeze(self):
        for error in (KeyboardInterrupt,SystemExit):
            with self.subTest(error=error.__name__):self.release_case(error)

    def test_release_sync_completes_before_freeze(self):
        self.release_case(None)

    def release_case(self,error):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);sha='a'*40
            config={'folds':[],'logistic':{},'versions':{}}
            life=Mock();life.root=root
            life.read.return_value={'config':config,'guard':'UNOPENED','sealed':False}
            def artifact(name,value):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(value));return {'path':str(path)}
            dataset=artifact('development/dataset/manifest.json',{'contract':{
                'preregistered_sha':sha,'config':config,'scientific_files':{}}})
            phase={'name':'final'}
            final={'phases':[{'phase':phase,'families':{family:{'fit':{'contract':{'family':family}}}
                    for family in ('constant','logistic')}}]}
            artifacts={'development_source':artifact('source.json',{'dataset':dataset}),
                'development_models':artifact('models-dev.json',{}),'final_models':artifact('models-final.json',final),
                'development_portfolios':artifact('portfolio/report.json',{}),
                'development_report':artifact('aggregate/report.json',{'synthetic':True})}
            validation={'head_sha':sha,'preregistered_sha':sha,**dict.fromkeys([
                'synthetic_tests_passed','compile_passed','diff_check_passed',
                'portfolio_replay_passed','model_replay_passed','resource_benchmark_passed'],True)}
            receipts={'ci':artifact('ci.json',{}),'review':artifact('review.json',{}),
                'dependencies':artifact('dependencies.json',{'repository':'lhermoso/FXNN','issues':[
                    {'number':n,'state':'CLOSED','closedAt':'synthetic'} for n in (6,7,8,19)]}),
                'validation':artifact('validation.json',validation)}
            events=[]
            def sync(directory):
                events.append('sync')
                if error:raise error('synthetic report sync failure')
            life.freeze.side_effect=lambda *args:events.append('freeze')
            with ExitStack() as stack:
                for name in ('verify_preregistration','verify_manifest','verified_ci_receipt','verified_review_receipt',
                             'load_window_data','clock_for','verify_operational_predictions','portfolio_segment',
                             'resource_preflight','fingerprint'):
                    stack.enter_context(patch.object(research,name,return_value={}))
                stack.enter_context(patch.object(research,'git',side_effect=lambda repo,*args:'' if args[0]=='status' else sha))
                stack.enter_context(patch.object(economic_fit,'phase_plan',return_value=[phase]))
                stack.enter_context(patch.object(economic_fit,'verify_phases'))
                stack.enter_context(patch.object(economic_report,'build_report',return_value={'synthetic':True}))
                stack.enter_context(patch.object(economic_report,'sync_report_directory',side_effect=sync))
                if error:
                    with self.assertRaises(error):research.release_freeze(root,config,life,sha,receipts,artifacts)
                else:research.release_freeze(root,config,life,sha,receipts,artifacts)
            self.assertEqual(events,['sync'] if error else ['sync','freeze'])
            if error:life.freeze.assert_not_called()
            if error is OSError:life.poison.assert_called_once_with('Report publication synchronization failed')
            else:life.poison.assert_not_called()
            life.fit.assert_not_called();life.close.assert_not_called()


if __name__=='__main__':unittest.main()
