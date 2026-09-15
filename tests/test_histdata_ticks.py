import csv
import json
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path
from zipfile import ZipFile
from scripts.download_histdata_ticks import parse_form, audit, validate_zip, fingerprint, verify_files, MONTHS, run, stamp, request, acquire_month


class TickTests(unittest.TestCase):
    def test_form_scoped(self):
        fields={'tk':'abc','date':'2022','datemonth':'202201','platform':'ASCII','timeframe':'T','fxpair':'EURUSD'}
        form='<form id="file_down" method="POST" action="/get.php">'+''.join(f'<input name="{k}" value="{v}">' for k,v in fields.items())+'</form>'
        self.assertEqual(parse_form('<input name="timeframe" value="M1">'+form,'202201'),fields)
        for bad in [form.replace('value="T"','value="M1"'),form+form,form.replace('/get.php','https://evil/get.php')]:
            with self.assertRaises(ValueError):parse_form(bad,'202201')

    def test_stream_precision_invalid_and_ties(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);z=root/'raw.zip'
            with ZipFile(z,'w') as f:
                f.writestr('DAT_ASCII_EURUSD_T_202201.csv','20220102 120000123,1.100001,1.100009,0\n'*2+'20220102 120000123,1.2,1.1,0\n20220102 115959000,1.1,1.2,0\nbad,NaN,2,0\n')
            report=audit(z,root,'202201')
            self.assertEqual(report['valid_rows'],2)
            self.assertEqual(report['invalid_rows'],3)
            with (root/'ticks.csv').open() as f: rows=list(csv.DictReader(f))
            self.assertEqual(rows[0]['timestamp_utc'],'2022-01-02T17:00:00.123000+00:00')
            self.assertEqual(rows[0]['bid'],'1.100001')
            self.assertEqual(rows[1]['source_sequence'],'2')
            self.assertEqual(report['spread_min'],'0.000008')
            q=[json.loads(s) for s in (root/'quarantine.jsonl').read_text().splitlines()]
            self.assertTrue(any('crossed_quote' in r['reasons'] and r['timestamp_utc'] for r in q))
            self.assertNotIn('raw',q[-1])

    def test_reserved_utc_prices_never_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); z=root/'raw.zip'
            with ZipFile(z,'w') as f:f.writestr('DAT_ASCII_EURUSD_T_202312.csv','20231231 185959999,1.1,1.2,0\n20231231 190000000,SECRET,SECRET,SECRET\n')
            r=audit(z,root,'202312');self.assertEqual(r['reserved_rows'],1)
            self.assertNotIn('SECRET',(root/'ticks.csv').read_text()+(root/'quarantine.jsonl').read_text()+(root/'reserved.jsonl').read_text())

    def test_zip_names_and_resume_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);z=root/'raw.zip'
            with ZipFile(z,'w') as f:f.writestr('../bad.csv','x')
            with self.assertRaises(ValueError):validate_zip(z,'202201')
            p=root/'out';p.write_text('a');record={'out':fingerprint(p)}
            verify_files(root,record);p.write_text('b')
            with self.assertRaises(ValueError):verify_files(root,record)
        self.assertEqual(len(MONTHS),24)

    def test_invalid_prices_and_months(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);z=root/'raw.zip'
            values=['NaN,1,0','1,Infinity,0','0,1,0','1,2,-1','bad,2,0','1,2','1,2,0']
            with ZipFile(z,'w') as f:f.writestr('DAT_ASCII_EURUSD_T_202201.csv',''.join('20220102 120000000,'+v+'\n' for v in values)+'20220202 120000000,1,2,0\n')
            r=audit(z,root,'202201');self.assertEqual(r['invalid_rows'],7);self.assertEqual(r['valid_rows'],1)
        self.assertEqual(stamp('20220702 120000000').hour,17)
        for value in ['20220230 120000000','20220102 120000','20220102 1200000000']:
            with self.assertRaises(ValueError):stamp(value)

    def test_crc_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'a.zip'
            with ZipFile(p,'w') as f:f.writestr('DAT_ASCII_EURUSD_T_202201.csv','unique payload')
            with patch('scripts.download_histdata_ticks.MAX_RAW',1):
                with self.assertRaises(ValueError):validate_zip(p,'202201')
            p.write_bytes(p.read_bytes().replace(b'unique payload',b'broken payload'))
            with self.assertRaises(ValueError):validate_zip(p,'202201')

    def test_all_month_failure_manifest_and_bounded_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.json'
            config.write_text(json.dumps({'dataset':'histdata_ticks_v1','symbol':'EURUSD','months':MONTHS,'source_timezone':'UTC-05:00 fixed no DST','development_utc':['2022-01-01','2024-01-01'],'max_attempts_per_month':2}))
            with patch('scripts.download_histdata_ticks.request',side_effect=ValueError('HTTP503')) as fetch:
                result=run(config,root/'data');self.assertEqual(fetch.call_count,48)
                self.assertEqual(len(result['months']),24)
                self.assertTrue(all(r['status']=='failed' for r in result['months']))
                run(config,root/'data');self.assertEqual(fetch.call_count,48)
            config.write_text(config.read_text()+' ')
            with self.assertRaises(ValueError):run(config,root/'data')

    def test_http_redirect_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'page'
            with patch('scripts.download_histdata_ticks.subprocess.run') as call:
                call.return_value.returncode=0;call.return_value.stdout='302\nhttps://www.histdata.com/get.php';call.return_value.stderr=''
                with self.assertRaises(ValueError):request('https://www.histdata.com/get.php',p)
                self.assertNotIn('--location',call.call_args.args[0])
                self.assertEqual(call.call_args.args[0][1],'--disable')

    def test_successful_resume_checks_all_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def fake(url,target,**kwargs):
                if target.name=='form.html':
                    fields={'tk':'abc','date':'2022','datemonth':'202201','platform':'ASCII','timeframe':'T','fxpair':'EURUSD'}
                    target.write_text('<form id="file_down" method="POST" action="/get.php">'+''.join(f'<input name="{k}" value="{v}">' for k,v in fields.items())+'</form>')
                else:
                    with ZipFile(target,'w') as z:z.writestr('DAT_ASCII_EURUSD_T_202201.csv','20220102 120000000,1.1,1.2,0\n')
                target.with_suffix(target.suffix+'.http.json').write_text('{}')
            with patch('scripts.download_histdata_ticks.request',side_effect=fake) as fetch:
                r=acquire_month(root,'202201','hash');self.assertEqual(r['status'],'completed')
                self.assertEqual(acquire_month(root,'202201','hash'),r);self.assertEqual(fetch.call_count,2)
                with self.assertRaises(ValueError):acquire_month(root,'202201','wrong')
                (root/'202201'/'attempt-001'/'ticks.csv').write_text('tamper')
                with self.assertRaises(ValueError):acquire_month(root,'202201','hash')
