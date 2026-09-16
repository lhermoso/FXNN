"""Versioned HistData confirmation acquisition. No market I/O at import time.

Fixed UTC2024 reader, distinct from immutable stage19 development acquisition.
Transport attempts are globally anchored to the stage9 supervisor directory.
"""
from contextlib import contextmanager
from collections import Counter
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from zipfile import ZipFile, BadZipFile

from scripts import download_histdata_ticks as stage19
from .economic_lifecycle import atomic_json, fingerprint

VERSION = 'economic_confirmation_source_v1'
MONTHS = tuple(f'2024{i:02d}' for i in range(1,13))
START = datetime(2024,1,1,tzinfo=timezone.utc)
STOP = datetime(2025,1,1,tzinfo=timezone.utc)
WINDOW_MS = (1704067200000,1735689600000)
ORIGIN = 'https://www.histdata.com'
MAX_ZIP, MAX_RAW, MAX_FORM, MAX_LINE = 2*1024**3, 8*1024**3, 2*1024**2, 65536
UTILITY_SHA = '6c159ff02de2cddc26581558994eee40a71484a812572fa3c6dc6b44cbb3b887'
PROFILE = {'version':VERSION,'symbol':'EURUSD','months':list(MONTHS),
           'utc_window':['2024-01-01','2025-01-01'],'source_timezone':'EST_fixed_UTC-05',
           'attempts_per_month':2,'redirects':'reject','zip_bytes_max':MAX_ZIP,
           'uncompressed_bytes_max':MAX_RAW,'form_bytes_max':MAX_FORM,'line_bytes_max':MAX_LINE}
REQUIRED = {'form.html','form.html.http.json','raw.zip','raw.zip.http.json',
            'ticks.csv','quarantine.jsonl','reserved.jsonl','audit.json'}
NORMAL = {'ticks.csv','quarantine.jsonl','reserved.jsonl','audit.json'}


def small_fp(path):
    value=fingerprint(path)
    return {k:value[k] for k in ('sha256','bytes')}


def utility_binding():
    if small_fp(stage19.__file__)['sha256'] != UTILITY_SHA:
        raise ValueError('Frozen stage19 utilities changed; explicit review required')


def safe_file(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('Unsafe artifact path')
    return path


def durable_file(path):
    with safe_file(path).open('rb') as f:os.fsync(f.fileno())
    fd=os.open(Path(path).parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


class CurlTransport:
    """Canonical HTTPS only; rejects every redirect, no hidden network retries."""
    def request(self,url,target,*,referer=None,fields=None,limit=MAX_FORM):
        target=Path(target)
        if (not url.startswith(ORIGIN+'/') or target.exists() or target.is_symlink()
                or referer is not None and not referer.startswith(ORIGIN+'/')):
            raise ValueError('Unsafe URL/path')
        command=['/usr/bin/curl','--disable','--silent','--show-error','--globoff','--proto','=https',
                 '--max-time','300','--connect-timeout','60','--max-filesize',str(limit),
                 '--output',str(target),'--write-out','%{http_code}\n%{url_effective}']
        if referer:command+=['--referer',referer]
        for k,v in (fields or {}).items():command+=['--data-urlencode',f'{k}={v}']
        result=subprocess.run([*command,url],capture_output=True,text=True)
        metadata={'url':url,'status_and_url':result.stdout,'exit_code':result.returncode,
                  'redirect_policy':'reject','stderr':result.stderr}
        # Caller persists metadata even on failure; no exception includes source price text.
        return metadata


def checked_response(meta,url,path,limit):
    if (meta.get('url')!=url or meta.get('exit_code')!=0 or meta.get('status_and_url')!='200\n'+url
            or not Path(path).is_file() or Path(path).is_symlink() or not 0<Path(path).stat().st_size<=limit):
        raise ValueError('HTTP status/origin/size validation failed')


def normalize(archive,dest,month):
    """UTC admission before Decimal, no quote parser call for out-of-window rows.

    Same eight-file completed schema as foundation verified_month. Prices of
    reserved/unknown-time lines remain solely in immutable raw ZIP bytes.
    """
    if month not in (*MONTHS,'202312'):raise ValueError('Only fixed confirmation sources')
    utility_binding()
    member=stage19.validate_zip(Path(archive),month)
    dest=Path(dest);counts=Counter();highwater=None;previous_text=None
    with ZipFile(archive) as z,z.open(member) as src, (dest/'ticks.csv').open('x',newline='') as out, (dest/'quarantine.jsonl').open('x') as q, (dest/'reserved.jsonl').open('x') as reserved:
        writer=csv.writer(out);writer.writerow(['timestamp_utc','source_timestamp_est','bid','ask','volume','source_sequence','flags'])
        sequence=0
        while True:
            line=src.readline(MAX_LINE+1)
            if not line:break
            sequence+=1;counts['source_rows']+=1
            too_long=len(line)>MAX_LINE
            if too_long:
                while not line.endswith(b'\n'):
                    line=src.readline(MAX_LINE+1)
                    if not line:break
                text='';stamp_text=''
            else:
                text=line.decode('utf-8-sig' if sequence==1 else 'utf-8',errors='replace').rstrip('\r\n')
                stamp_text=text.split(',',1)[0]
            try:
                timestamp=stage19.stamp(stamp_text)
                if stamp_text[:6]!=month:raise ValueError('source month')
            except ValueError:
                reason='overlong_source_record' if too_long else 'invalid_timestamp_or_source_month'
                counts['invalid_rows']+=1;counts[reason]+=1
                q.write(json.dumps({'source_sequence':sequence,'source_timestamp_est':None,'timestamp_utc':None,'reasons':[reason],'prices_redacted':True})+'\n')
                continue
            if not START<=timestamp<STOP:
                counts['reserved_rows']+=1
                reserved.write(json.dumps({'source_sequence':sequence,'timestamp_utc':timestamp.isoformat(),'reason':'outside_confirmation_utc','prices_redacted':True})+'\n')
                continue
            reasons=[];flags=[]
            if highwater is not None:
                if timestamp<highwater:reasons.append('out_of_order')
                elif timestamp==highwater:flags.append('simultaneous_timestamp')
            highwater=timestamp if highwater is None else max(highwater,timestamp)
            if text==previous_text:flags.append('consecutive_exact_duplicate')
            previous_text=text
            fields=text.split(',')
            if len(fields)!=4:reasons.append('field_count')
            else:
                try:
                    bid,ask,volume=map(Decimal,fields[1:])
                    if not all(x.is_finite() for x in (bid,ask,volume)):reasons.append('nonfinite')
                    elif bid<=0 or ask<=0 or volume<0:reasons.append('nonpositive_quote_or_negative_volume')
                    elif ask<bid:reasons.append('crossed_quote')
                except InvalidOperation:reasons.append('invalid_decimal')
            for r in reasons+flags:counts[r]+=1
            if reasons or flags:
                q.write(json.dumps({'source_sequence':sequence,'timestamp_utc':timestamp.isoformat(),'source_timestamp_est':stamp_text,'reasons':reasons,'flags':flags,'retained_in_normalized':not reasons,'prices_redacted':True})+'\n')
            if reasons:counts['invalid_rows']+=1;continue
            counts['valid_rows']+=1
            writer.writerow([timestamp.isoformat(),stamp_text,*fields[1:],sequence,'|'.join(flags)])
    audit={k:counts[k] for k in ('source_rows','valid_rows','invalid_rows','reserved_rows')}
    audit.update(anomalies=dict(counts),schema=VERSION,window_utc=PROFILE['utc_window'],
                 order='source sequence; ties do not establish execution priority')
    atomic_json(dest/'audit.json',audit)
    for name in NORMAL:durable_file(dest/name)
    return audit


class ConfirmationAcquisition:
    def __init__(self,lifecycle,transport=None):
        self.lifecycle=lifecycle;self.transport=transport or CurlTransport()
        self.root=lifecycle.root/'confirmation-source-v1'

    @contextmanager
    def _locked(self):
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.root.is_symlink():raise ValueError('Symlink acquisition root')
        with (self.root/'acquisition.lock').open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock,fcntl.LOCK_UN)

    def _admit(self):
        utility_binding();s=self.lifecycle.recover()
        if s['config'].get('confirmation_acquisition')!=PROFILE:raise ValueError('Profile not frozen in S')
        if s['terminal'] or s['poison'] or not s['sealed']:raise ValueError('Confirmation inactive/unsealed')
        if s['guard']=='UNOPENED':self.lifecycle.begin_confirmation()
        elif s['guard'] not in ('OPENING','OPENED'):raise ValueError('Terminal guard')

    def _fetch(self,url,dest,**kwargs):
        limit=kwargs.get('limit',MAX_FORM)
        meta=self.transport.request(url,dest,**kwargs)
        atomic_json(dest.with_suffix(dest.suffix+'.http.json'),meta)
        checked_response(meta,url,dest,limit);durable_file(dest)
        atomic_json(dest.with_suffix(dest.suffix+'.receipt.json'),{'file':small_fp(dest),'url':url,'metadata':small_fp(dest.with_suffix(dest.suffix+'.http.json'))})

    def _receipt(self,path):
        rec=json.loads(safe_file(path.with_suffix(path.suffix+'.receipt.json')).read_text())
        if small_fp(safe_file(path))!=rec['file'] or small_fp(safe_file(path.with_suffix(path.suffix+'.http.json')))!=rec['metadata']:
            raise ValueError('Durable payload/HTTP fingerprint changed')
        return rec

    def _received(self,path):
        s=self.lifecycle.read()
        if s['guard']=='OPENING':self.lifecycle.received_payload(path)
        elif s['guard']!='OPENED':raise ValueError('Guard not active')

    def _completed(self,folder,month):
        path=folder/'completed.json'
        if not path.exists():return None
        record=json.loads(safe_file(path).read_text())
        if (record.get('version')!=VERSION or record.get('profile')!=PROFILE or record.get('month')!=month
                or record.get('status')!='completed' or set(record.get('files',{}))!=REQUIRED
                or not re.fullmatch('attempt-00[12]',record.get('attempt',''))):raise ValueError('Completed schema mismatch')
        attempt=folder/record['attempt']
        if attempt.is_symlink():raise ValueError('Symlink attempt')
        for name,expected in record['files'].items():
            if small_fp(safe_file(attempt/name))!=expected:raise ValueError('Completed bytes changed')
        stage19.validate_zip(attempt/'raw.zip',month)
        if json.loads((attempt/'audit.json').read_text())!=record['audit']:raise ValueError('Audit mismatch')
        return record

    def _publish_normalized(self,folder,attempt,month,source_url,held=None):
        # Only uncommitted derived files may be rebuilt; raw/receipts are immutable.
        for name in NORMAL:
            path=attempt/name
            if path.is_symlink():raise ValueError('Symlink partial output')
            if path.exists():path.unlink()
        audit=normalize(attempt/'raw.zip',attempt,month)
        record={'version':VERSION,'profile':PROFILE,'month':month,'status':'completed','attempt':attempt.name,
                'source_url':source_url,'files':{n:small_fp(attempt/n) for n in REQUIRED},'audit':audit,
                'held_source_binding':held,'utility_sha256':UTILITY_SHA}
        atomic_json(folder/'completed.json',record)
        return record

    def _month(self,month):
        folder=self.root/month
        if folder.is_symlink():raise ValueError('Symlink month')
        folder.mkdir(exist_ok=True)
        if any(p.name not in {'attempt-001','attempt-002'} for p in folder.glob('attempt-*')):
            raise ValueError('Unexpected lifetime attempt directory')
        complete=self._completed(folder,month)
        if complete:return complete
        url=f'{ORIGIN}/download-free-forex-historical-data/?/ascii/tick-data-quotes/eurusd/2024/{int(month[4:])}'
        for number in (1,2):
            attempt=folder/f'attempt-{number:03}'
            if attempt.is_symlink():raise ValueError('Symlink attempt')
            if attempt.exists():
                if (attempt/'failure.json').exists():continue
                # Durable raw receipt permits same-attempt deterministic recovery.
                if (attempt/'raw.zip.receipt.json').exists():
                    self._receipt(attempt/'raw.zip');self._received(attempt/'raw.zip')
                    try:stage19.validate_zip(attempt/'raw.zip',month)
                    except (BadZipFile,ValueError):
                        atomic_json(attempt/'failure.json',{'reason':'invalid_archive_structure_or_CRC'})
                        continue
                    return self._publish_normalized(folder,attempt,month,url)
                atomic_json(attempt/'failure.json',{'reason':'interrupted_transfer_consumed_attempt'})
                continue
            attempt.mkdir();atomic_json(attempt/'intent.json',{'month':month,'number':number,'profile':PROFILE})
            try:
                self._fetch(url,attempt/'form.html')
                fields=stage19.parse_form((attempt/'form.html').read_text(),month)
                self._fetch(ORIGIN+'/get.php',attempt/'raw.zip',referer=url,fields=fields,limit=MAX_ZIP)
            except (OSError,ValueError) as exc:
                atomic_json(attempt/'failure.json',{'reason':type(exc).__name__,'phase':'transport_or_form'})
                continue
            self._received(attempt/'raw.zip')
            try:
                stage19.validate_zip(attempt/'raw.zip',month)
            except (BadZipFile,ValueError):
                atomic_json(attempt/'failure.json',{'reason':'invalid_archive_structure_or_CRC'})
                continue
            return self._publish_normalized(folder,attempt,month,url)
        raise ValueError('Two lifetime transport attempts exhausted; terminal disposition required')

    def ingest_held_december(self,archive,metadata):
        """Bindings must come from frozen stage19 manifest; never discover new files."""
        with self._locked():
            frozen=self.lifecycle.read()['config'].get('confirmation_held_december')
            if frozen!={'archive':archive,'metadata':metadata}:raise ValueError('Held source not frozen in S')
            # Empty reserved metadata is known from byte size without numeric access.
            if small_fp(safe_file(metadata['path']))!={k:metadata[k] for k in ('sha256','bytes')}:
                raise ValueError('Held metadata changed')
            if metadata['bytes']==0:return {'status':'no_held_reserved_rows','metadata':metadata}
            self._admit()
            bindings={'archive':archive,'metadata':metadata}
            if self.lifecycle.read()['guard']=='OPENING':
                self.lifecycle.mark_held_inspection(bindings);self.lifecycle.record_held_inspection()
            else:
                marker=self.root/'held-inspection.json'
                if marker.exists():
                    if json.loads(marker.read_text())!=bindings:raise ValueError('Held binding changed')
                else:atomic_json(marker,bindings)
            folder=self.root/'202312';folder.mkdir(exist_ok=True)
            complete=self._completed(folder,'202312')
            if complete:return complete
            if fingerprint(safe_file(archive['path']))!=archive:raise ValueError('Held archive changed')
            attempt=folder/'attempt-001';attempt.mkdir(exist_ok=True)
            target=attempt/'raw.zip'
            if not target.exists():
                shutil.copyfile(archive['path'],target);durable_file(target)
            if small_fp(target)!={k:archive[k] for k in ('sha256','bytes')}:raise ValueError('Held copy changed')
            for name,value in [('form.html','held source19; no new request'),('form.html.http.json',json.dumps({'held':bindings})),('raw.zip.http.json',json.dumps({'held':archive}))]:
                path=attempt/name
                if not path.exists():path.write_text(value);durable_file(path)
            return self._publish_normalized(folder,attempt,'202312','held:stage19:202312',bindings)

    def acquire_all(self):
        held=self.lifecycle.read()['config'].get('confirmation_held_december')
        if not isinstance(held,dict) or set(held)!={'archive','metadata'}:
            raise ValueError('Frozen December2023 held-source binding required')
        held_result=self.ingest_held_december(held['archive'],held['metadata'])
        with self._locked():
            self._admit();records=[]
            for month in MONTHS:records.append(self._month(month))
            manifest={'version':VERSION,'profile':PROFILE,'held_december':held_result,'months':records,
                      'completed_hashes':{m:small_fp(self.root/m/'completed.json') for m in MONTHS},
                      'guard':self.lifecycle.read()['guard'],'fits':0}
            dest=self.root/'manifest.json'
            if dest.exists():
                if json.loads(dest.read_text())!=manifest:raise ValueError('Completed global manifest changed')
            else:atomic_json(dest,manifest)
            return manifest


def verified_confirmation_month(root,expected_completed_sha256,*,lifecycle):
    """Foundation adapter, allowed only after recorded confirmation access."""
    from fxnn.tick_economic_source import verified_month
    s=lifecycle.read()
    if (s['guard'] not in {'OPENED','COMPLETED','INCOMPLETE'} or not s['sealed']
            or s['config'].get('confirmation_acquisition')!=PROFILE):
        raise ValueError('No recorded confirmation access for reader')
    root=Path(root)
    if (root.is_symlink() or root.name not in (*MONTHS,'202312')
            or root.resolve().parent!=(lifecycle.root/'confirmation-source-v1').resolve()):
        raise ValueError('Reader source outside canonical confirmation root')
    yield from verified_month(root,expected_completed_sha256,WINDOW_MS)
