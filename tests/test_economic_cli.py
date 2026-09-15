"""CLI-level non-fit report interruption and fail-closed publication fixtures."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fxnn import economic_report
from test_economic_report import fixture


class EconomicCliTests(unittest.TestCase):
    def test_both_report_phases_resume_interruptions_without_poison(self):
        for phase in ('development-report','confirmation-report'):
            for error in (KeyboardInterrupt,SystemExit):
                with self.subTest(phase=phase,error=error.__name__), tempfile.TemporaryDirectory() as temp:
                    self.run_case(phase,temp,error)

    def test_observed_storage_error_still_poisons_both_report_phases(self):
        for phase in ('development-report','confirmation-report'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as temp:
                self.run_case(phase,temp,OSError,poison=True)

    def test_both_report_phases_finish_sync_after_interrupted_rename(self):
        for phase in ('development-report','confirmation-report'):
            for error in (KeyboardInterrupt,SystemExit):
                with self.subTest(phase=phase,error=error.__name__), tempfile.TemporaryDirectory() as temp:
                    self.run_case(phase,temp,error,after_rename=True)

    def test_retry_sync_storage_error_poisons_once(self):
        for phase in ('development-report','confirmation-report'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as temp:
                self.run_case(phase,temp,KeyboardInterrupt,after_rename=True,retry_failure=True)

    def test_completion_finishes_report_durability_before_lifecycle_close(self):
        source=Path(__file__).resolve().parents[1]/'scripts/run_economic_ticks.py'
        spec=importlib.util.spec_from_file_location('economic_cli_completion_fixture',source)
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();target=root/'report-confirmation';target.mkdir()
            artifacts={name:{'path':temp+'/'+name,'bytes':0,'sha256':letter*64}
                       for name,letter in [('development_models','a'),('final_models','b')]}
            result=economic_report.build_report(None,None,fixture(),
                confirmation={'execution_status':'COMPLETED','portfolios':fixture(True)},artifacts=artifacts)
            (target/'report.json').write_text(json.dumps(result))
            life=Mock();life.read.return_value={'checkpoints':[
                {'phase':'DEVELOPMENT_VERIFIED','artifacts':{'report':artifacts['development_models']}},
                {'phase':'FINAL_MODELS_VERIFIED','artifacts':{'report':artifacts['final_models']}}]}
            events=[];original_fsync=economic_report.os.fsync
            def synced(fd):events.append(economic_report.os.fstat(fd).st_ino);return original_fsync(fd)
            life.close.side_effect=lambda *args:events.append('close')
            def read(path):
                if Path(path)==target/'report.json':return result
                if str(path).endswith('probabilities-confirmation/report.json'):return {'operational':{}}
                if str(path).endswith('source-evidence.json'):return {}
                return None
            with patch.object(cli.research,'load_config',return_value={'global_ledger':temp+'/ledger'}),                 patch.object(cli.research,'verify_preregistration'),patch.object(cli.research,'clock_for'),                 patch.object(cli.research,'load_window_data'),patch.object(cli.research,'verify_final_probabilities'),                 patch.object(cli.research,'portfolio_segment',side_effect=lambda *args,**kw:fixture(kw.get('confirmation',False))),                 patch.object(cli,'Lifecycle',return_value=life),patch.object(cli,'read',side_effect=read),                 patch.object(cli,'fingerprint',return_value={'synthetic':True}),                 patch.object(economic_report.os,'fsync',side_effect=synced),patch('sys.stdout',new_callable=io.StringIO):
                cli.main(['complete','--output',temp,'--preregistered-sha','a'*40])
            self.assertEqual(events,[target.stat().st_ino,root.stat().st_ino,'close'])
            life.poison.assert_not_called();life.fit.assert_not_called()

    def run_case(self,phase,temp,error,poison=False,after_rename=False,retry_failure=False):
        source=Path(__file__).resolve().parents[1]/'scripts/run_economic_ticks.py'
        spec=importlib.util.spec_from_file_location('economic_cli_fixture',source)
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        life=Mock()
        life.read.return_value={'checkpoints':[
                {'recoverable_failure':'earlier interruption'},
                {'phase':'DEVELOPMENT_VERIFIED','artifacts':{'report':{'path':temp+'/dev','sha256':'a'*64,'bytes':0}}},
                {'phase':'FINAL_MODELS_VERIFIED','artifacts':{'report':{'path':temp+'/final','sha256':'b'*64,'bytes':0}}}]}
        kwargs={} if phase=='development-report' else {'confirmation':{'execution_status':'COMPLETED','portfolios':fixture(True)}}
        report=economic_report.build_report(None,None,fixture(),**kwargs)
        args=[phase,'--output',temp,'--preregistered-sha','a'*40]
        output=Path(temp)/('report-development' if phase=='development-report' else 'report-confirmation')
        with patch.object(cli.research,'load_config',return_value={'global_ledger':temp+'/ledger'}),\
             patch.object(cli.research,'verify_preregistration'),patch.object(cli.research,'clock_for'),\
             patch.object(cli,'Lifecycle',return_value=life),patch.object(cli,'read',return_value={}),\
             patch.object(economic_report,'build_report',return_value=report),patch('sys.stdout',new_callable=io.StringIO):
            original_fsync=economic_report.os.fsync
            calls=0
            def interrupt(fd):
                nonlocal calls
                calls+=1
                if calls==(6 if after_rename else 1):raise error('synthetic interruption')
                return original_fsync(fd)
            with patch.object(economic_report.os,'fsync',side_effect=interrupt):
                with self.assertRaises(error):cli.main(args)
            self.assertEqual(output.exists(),after_rename)
            partials=list(Path(temp).glob(output.name+'.partial-*'))
            self.assertEqual(len(partials),0 if after_rename else 1)
            preserved_path=(output if after_rename else partials[0])/'report.json'
            preserved=preserved_path.read_bytes()
            life.close.assert_not_called();life.fit.assert_not_called()
            if poison:
                life.poison.assert_called_once_with('Aggregate report publication failed')
            else:
                life.poison.assert_not_called()
                synchronized=[]
                def retry_sync(fd):
                    synchronized.append(economic_report.os.fstat(fd).st_ino)
                    if retry_failure:raise OSError('retry synchronization failed')
                    return original_fsync(fd)
                with patch.object(economic_report.os,'fsync',side_effect=retry_sync):
                    if retry_failure:
                        with self.assertRaises(OSError):cli.main(args)
                    else:cli.main(args)
                self.assertTrue((output/'report.json').is_file())
                self.assertEqual(preserved_path.read_bytes(),preserved)
                if retry_failure:
                    life.poison.assert_called_once_with('Aggregate report publication failed')
                else:
                    life.poison.assert_not_called()
                    if after_rename:self.assertEqual(synchronized,[output.stat().st_ino,output.parent.stat().st_ino])
                life.close.assert_not_called();life.fit.assert_not_called()



if __name__=='__main__':unittest.main()
