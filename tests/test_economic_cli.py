"""CLI-level non-fit report interruption and fail-closed publication fixtures."""
import importlib.util
import io
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

    def run_case(self,phase,temp,error,poison=False):
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
            with patch.object(economic_report.os,'fsync',side_effect=error('synthetic interruption')):
                with self.assertRaises(error):cli.main(args)
            self.assertFalse(output.exists())
            partials=list(Path(temp).glob(output.name+'.partial-*'))
            self.assertEqual(len(partials),1)
            preserved=(partials[0]/'report.json').read_bytes()
            life.close.assert_not_called();life.fit.assert_not_called()
            if poison:
                life.poison.assert_called_once_with('Aggregate report publication failed')
            else:
                life.poison.assert_not_called()
                cli.main(args)
                self.assertTrue((output/'report.json').is_file())
                self.assertEqual((partials[0]/'report.json').read_bytes(),preserved)
                life.poison.assert_not_called();life.close.assert_not_called();life.fit.assert_not_called()


if __name__=='__main__':unittest.main()
