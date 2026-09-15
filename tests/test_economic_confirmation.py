"""Offline transport fixtures and real foundation schema interoperability."""
import io
import concurrent.futures
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile,ZIP_STORED

from fxnn.economic_lifecycle import atomic_json,fingerprint
from fxnn.economic_confirmation import (ConfirmationAcquisition,CurlTransport,PROFILE,MONTHS,ORIGIN,
                                    normalize,small_fp,verified_confirmation_month)


def archive_bytes(month,rows):
    out=io.BytesIO()
    with ZipFile(out,'w',compression=ZIP_STORED) as z:z.writestr(f'DAT_ASCII_EURUSD_T_{month}.csv',rows)
    return out.getvalue()


def form(month):
    fields={'date':month[:4],'datemonth':month,'platform':'ASCII','timeframe':'T','fxpair':'EURUSD','tk':'synthetic-token'}
    return ('<form id="file_down" method="POST" action="/get.php">'+''.join(f'<input name="{k}" value="{v}">' for k,v in fields.items())+'</form>').encode()


class FakeLifecycle:
    def __init__(self,root):
        self.root=root/'supervisor';self.root.mkdir()
        self.guard='UNOPENED';self.openings=0;self.numeric_allowed=False
        self.terminal=None;self.poison=False;self.sealed=True
        meta=root/'held-metadata';meta.write_bytes(b'')
        raw=root/'held-archive';raw.write_bytes(archive_bytes('202312','20231231 200000000,1,2,0\n'))
        self.config={'confirmation_acquisition':PROFILE,'confirmation_held_december':{'archive':fingerprint(raw),'metadata':fingerprint(meta)}}
        self.log=[]
    def recover(self):
        if self.terminal or self.poison:raise ValueError('terminal/poison')
        return self.read()
    def read(self):return {'config':self.config,'guard':self.guard,'terminal':self.terminal,'poison':self.poison,'sealed':self.sealed}
    def begin_confirmation(self):
        if self.guard!='UNOPENED':raise ValueError('Consumed')
        self.guard='OPENING';self.openings+=1;self.log.append('opening-durable')
        atomic_json(self.root/'guard.json',{'guard':self.guard})
    def received_payload(self,path):
        if self.guard!='OPENING':raise ValueError('Not opening')
        self.guard='OPENED';self.numeric_allowed=True;self.log.append('payload-durable')
        atomic_json(self.root/'guard.json',{'guard':self.guard,'payload':small_fp(path)})
    def mark_held_inspection(self,bindings):
        self.log.append('held-marker-durable');atomic_json(self.root/'marker.json',bindings)
    def record_held_inspection(self):
        assert (self.root/'marker.json').exists()
        self.guard='OPENED';self.numeric_allowed=True;self.log.append('held-inspection-durable')


class FakeTransport:
    def __init__(self,life):self.life=life;self.calls=[];self.fail_payloads=0;self.crash=False;self.bad_zip=False
    def request(self,url,target,**kwargs):
        assert self.life.guard in ('OPENING','OPENED')
        self.calls.append((url,str(target)));self.life.log.append('transport')
        if url==ORIGIN+'/get.php':
            if self.crash:self.crash=False;raise KeyboardInterrupt('synthetic crash before I/O')
            month=kwargs['fields']['datemonth']
            body=archive_bytes(month,f'{month}02 120000000,1.001,1.002,0\n')
            if month=='202412':body=archive_bytes(month,'20241202 120000000,1.001,1.002,0\n20241231 230000000,RESERVED_SENTINEL,RESERVED_SENTINEL,0\n')
            if self.bad_zip:body=b'invalid archive'
            Path(target).write_bytes(body)
            if self.fail_payloads:
                self.fail_payloads-=1
                return {'url':url,'exit_code':0,'status_and_url':'302\nhttps://evil.invalid/'}
        else:
            year,month=url.rsplit('/',2)[-2:];Path(target).write_bytes(form(year+month.zfill(2)))
        return {'url':url,'exit_code':0,'status_and_url':'200\n'+url}


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='confirmation-offline-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.life=FakeLifecycle(self.root);self.transport=FakeTransport(self.life)
        self.a=ConfirmationAcquisition(self.life,self.transport)

    def test_fixed_twelve_months_guard_before_IO_and_schema_adapter(self):
        import fxnn.economic_confirmation as mod
        real=mod.Decimal
        def guarded_decimal(value):
            self.assertTrue(self.life.numeric_allowed)
            self.assertNotIn('RESERVED_SENTINEL',value)
            return real(value)
        with patch.object(mod,'Decimal',side_effect=guarded_decimal):manifest=self.a.acquire_all()
        self.assertEqual([m['month'] for m in manifest['months']],list(MONTHS))
        self.assertEqual(self.life.openings,1)
        self.assertEqual(len(self.transport.calls),24)
        self.assertLess(self.life.log.index('opening-durable'),self.life.log.index('transport'))
        folder=self.a.root/'202412';digest=small_fp(folder/'completed.json')['sha256']
        rows=list(verified_confirmation_month(folder,digest,lifecycle=self.life))
        self.assertEqual(len(rows),2);self.assertTrue(rows[1].reserved);self.assertIsNone(rows[1].load_quote)
        self.assertEqual(str(rows[0].load_quote()[0]),'1.001')
        for name in ['ticks.csv','quarantine.jsonl','reserved.jsonl','audit.json']:
            self.assertNotIn('RESERVED_SENTINEL',(folder/'attempt-001'/name).read_text())

    def test_resume_completed_hashes_no_network_or_rewrite(self):
        self.a.acquire_all();calls=len(self.transport.calls)
        paths=list(self.a.root.rglob('completed.json'));before={str(p):(p.stat().st_mtime_ns,p.read_bytes()) for p in paths}
        self.a.acquire_all()
        self.assertEqual(len(self.transport.calls),calls)
        self.assertEqual(before,{str(p):(p.stat().st_mtime_ns,p.read_bytes()) for p in paths})

    def test_two_lifetime_attempts_and_alias_root_no_reset(self):
        self.transport.fail_payloads=10
        for _ in range(2):
            with self.assertRaises(ValueError):self.a.acquire_all()
        self.assertEqual(len(self.transport.calls),4)
        self.assertEqual(self.life.openings,1)
        self.assertEqual(len(list((self.a.root/'202401').glob('attempt-*'))),2)

    def test_crash_before_IO_consumes_attempt_same_guard(self):
        self.transport.crash=True
        with self.assertRaises(KeyboardInterrupt):self.a.acquire_all()
        self.assertEqual(self.life.guard,'OPENING')
        self.a.acquire_all()
        self.assertEqual(self.life.openings,1)
        self.assertTrue((self.a.root/'202401'/'attempt-001'/'failure.json').exists())
        self.assertEqual(json.loads((self.a.root/'202401'/'completed.json').read_text())['attempt'],'attempt-002')

    def test_crash_after_receipt_resumes_same_payload_without_download(self):
        import fxnn.economic_confirmation as mod
        real=mod.normalize
        with patch.object(mod,'normalize',side_effect=KeyboardInterrupt('synthetic normalization crash')):
            with self.assertRaises(KeyboardInterrupt):self.a.acquire_all()
        before=len(self.transport.calls)
        self.assertEqual(before,2)
        self.a.acquire_all()
        self.assertEqual(len(self.transport.calls),24)
        self.assertEqual(json.loads((self.a.root/'202401'/'completed.json').read_text())['attempt'],'attempt-001')

    def test_nonempty_held_december_only_after_marker_and_no_2023_numeric(self):
        held=self.life.config['confirmation_held_december']
        path=Path(held['archive']['path']);path.write_bytes(archive_bytes('202312','20231231 180000000,OLD_SENTINEL,OLD_SENTINEL,0\n20231231 200000000,1,2,0\n'))
        meta=Path(held['metadata']['path']);meta.write_text('{"source_sequence":2,"timestamp_utc":"2024-01-01T01:00:00+00:00"}\n')
        held.update(archive=fingerprint(path),metadata=fingerprint(meta))
        import fxnn.economic_confirmation as mod
        real=mod.Decimal
        def checked(value):
            self.assertIn('held-inspection-durable',self.life.log);self.assertNotIn('OLD_SENTINEL',value)
            return real(value)
        with patch.object(mod,'Decimal',side_effect=checked):result=self.a.ingest_held_december(**{'archive':held['archive'],'metadata':held['metadata']})
        self.assertEqual(result['audit']['valid_rows'],1)
        self.assertEqual(result['audit']['reserved_rows'],1)
        self.assertEqual(len(self.transport.calls),0)

    def test_invalid_timestamp_redacts_price_and_preserves_source_sequence(self):
        archive=self.root/'fixture.zip';out=self.root/'normalized';out.mkdir()
        archive.write_bytes(archive_bytes('202401','BROKEN;PRIVATE_SENTINEL\n20240102 120000000,1,2,0\n20240102 115959000,1,2,0\n20240102 120000000,1,2,0\n'))
        audit=normalize(archive,out,'202401')
        self.assertEqual(audit['source_rows'],4);self.assertEqual(audit['invalid_rows'],2)
        for path in out.iterdir():self.assertNotIn('PRIVATE_SENTINEL',path.read_text())
        records=[json.loads(line) for line in (out/'quarantine.jsonl').read_text().splitlines()]
        self.assertEqual([r['source_sequence'] for r in records],[1,3,4])
        self.assertTrue(records[-1]['retained_in_normalized'])

    def test_crc_and_paths_rejected(self):
        archive=self.root/'bad.zip';out=self.root/'out';out.mkdir()
        with ZipFile(archive,'w') as z:z.writestr('../escape.csv','synthetic')
        with self.assertRaises(ValueError):normalize(archive,out,'202401')
        data=bytearray(archive_bytes('202401','20240102 120000000,1,2,0\n'))
        index=data.index(b'20240102');data[index]=ord('3');archive.write_bytes(data)
        with self.assertRaises(Exception):normalize(archive,out,'202401')

    def test_reader_before_recorded_access_rejected(self):
        with self.assertRaises(ValueError):list(verified_confirmation_month(self.a.root/'202401','0'*64,lifecycle=self.life))

    def test_terminal_guard_and_profile_change_prevent_network(self):
        self.life.terminal='INCOMPLETE'
        with self.assertRaises(ValueError):self.a.acquire_all()
        self.assertEqual(self.transport.calls,[])
        self.life.terminal=None;self.life.config['confirmation_acquisition']={}
        with self.assertRaises(ValueError):self.a.acquire_all()
        self.assertEqual(self.transport.calls,[])

    def test_concurrent_acquisition_lock_reuses_one_month_set(self):
        second=ConfirmationAcquisition(self.life,self.transport)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures=[pool.submit(obj.acquire_all) for obj in (self.a,second)]
            results=[f.result(timeout=15) for f in futures]
        self.assertEqual(results[0],results[1])
        self.assertEqual(len(self.transport.calls),24)
        self.assertEqual(self.life.openings,1)

    def test_invalid_zip_consumes_at_most_two_transport_attempts(self):
        self.transport.bad_zip=True
        with self.assertRaises(ValueError):self.a.acquire_all()
        self.assertEqual(len(self.transport.calls),4)
        with self.assertRaises(ValueError):self.a.acquire_all()
        self.assertEqual(len(self.transport.calls),4)
        self.assertEqual(self.life.guard,'OPENED')

    def test_real_staged_supervisor_and_foundation_end_to_end(self):
        from fxnn.economic_lifecycle import Lifecycle,identity
        from fxnn.fit_ledger import FitLedger
        ledger=self.root/'synthetic-ledger';FitLedger(ledger).initialize(0,{'synthetic':True})
        source=self.root/'science';source.write_text('synthetic scientific file')
        lifecycle=Lifecycle(ledger)
        lifecycle.reserve(0,small_fp(ledger)['sha256'],{'science':fingerprint(source)},self.life.config,[str(i) for i in range(14)])
        S=lifecycle.read()['S'];contracts=[{'family':'constant'},{'family':'logistic'}]
        for slot,contract in zip(['12','13'],contracts):
            model=self.root/('model-'+slot);model.write_bytes(b'synthetic model, no fit')
            F=identity({'S':S,'contract':contract})
            meta=self.root/('model-'+slot+'.json');meta.write_text(json.dumps({'S':S,'F':F,'model_sha256':small_fp(model)['sha256']}))
            with lifecycle.fit(slot,contract,'synthetic') as handle:
                handle.succeeded({'model':fingerprint(model),'metadata':fingerprint(meta)})
        report=self.root/'report';report.write_text('synthetic negative result')
        lifecycle.freeze('a'*40,'a'*40,'a'*40,True,True,contracts,{'report':fingerprint(report)},dict.fromkeys(['T1','T2','T3','T4','T5'],True))
        class Recording:
            def __init__(self,wrapped):self.wrapped=wrapped;self.log=[]
            @property
            def guard(self):return self.wrapped.read()['guard']
            def __getattr__(self,key):return getattr(self.wrapped,key)
        recorded=Recording(lifecycle);transport=FakeTransport(recorded)
        acquisition=ConfirmationAcquisition(lifecycle,transport)
        result=acquisition.acquire_all()
        self.assertEqual(lifecycle.read()['guard'],'OPENED')
        self.assertTrue(lifecycle.read()['sealed'])
        self.assertEqual(len(result['months']),12)
        rows=list(verified_confirmation_month(acquisition.root/'202401',small_fp(acquisition.root/'202401'/'completed.json')['sha256'],lifecycle=lifecycle))
        self.assertEqual(len(rows),1)
        before=small_fp(ledger)
        acquisition.acquire_all()
        self.assertEqual(small_fp(ledger),before)
        lifecycle.close('INCOMPLETE',{'reason':'synthetic terminal'})
        with self.assertRaises(ValueError):acquisition.acquire_all()
        self.assertEqual(len(transport.calls),24)

    def test_strict_transport_no_redirect_no_shell_no_implicit_retry(self):
        target=self.root/'transport'
        def fake_run(command,**kwargs):
            self.assertNotIn('--location',command);self.assertNotIn('--retry',command);self.assertNotIn('shell',kwargs)
            self.assertEqual(command[1],'--disable')
            target.write_bytes(b'synthetic')
            return type('Response',(),{'stdout':'302\nhttps://evil.invalid','stderr':'','returncode':0})()
        with patch('fxnn.economic_confirmation.subprocess.run',side_effect=fake_run):
            meta=CurlTransport().request(ORIGIN+'/get.php',target)
        from fxnn.economic_confirmation import checked_response
        with self.assertRaises(ValueError):checked_response(meta,ORIGIN+'/get.php',target,100)
        with self.assertRaises(ValueError):CurlTransport().request('http://www.histdata.com/get.php',self.root/'no')

if __name__=='__main__':unittest.main(verbosity=2)
