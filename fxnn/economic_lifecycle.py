"""Durable stage9 supervisor. All fitting must use the exclusive fit context.

No constructor, read, cache lookup or replay call creates or updates files.
State identity derives exclusively from the resolved canonical ledger path.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path

from fxnn.bound_ledger import BoundStageLedger
from fxnn.fit_ledger import _hash as ledger_record_hash

EXPERIMENT = 'economic_ticks_v1'
BUDGET = 14
TERMINAL = {'COMPLETED', 'INCOMPLETE'}


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                      separators=(',', ':')).encode()).hexdigest()


def fingerprint(path):
    path = Path(path)
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('File changed during hashing')
    return {'path': str(path.resolve()), 'bytes': after.st_size, 'sha256': h.hexdigest()}


def verify_manifest(manifest):
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError('Nonempty artifact manifest required')
    for value in manifest.values():
        if fingerprint(value['path']) != value:
            raise ValueError('Artifact identity mismatch')


def atomic_json(path, value):
    """Caller holds supervisor lock; errors never imply a committed transition."""
    temp = path.with_suffix('.pending')
    with temp.open('w', encoding='utf8') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Lifecycle:
    def __init__(self, canonical_ledger):
        self.ledger_path = Path(canonical_ledger).resolve()
        self.root = self.ledger_path.parent / (EXPERIMENT + '.lifecycle')
        self.state_path = self.root / 'state.json'
        self.lock_path = self.root / 'supervisor.lock'

    @contextmanager
    def _lock(self, write=False):
        if write:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Read-only callers must not create even an empty lock or state file.
        with self.lock_path.open('a+b' if write else 'rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _load(self):
        envelope = json.loads(self.state_path.read_text())
        s = envelope['state']
        if envelope['sha256'] != identity(s) or s['experiment'] != EXPERIMENT:
            raise ValueError('Corrupt supervisor state')
        if s['ledger_path'] != str(self.ledger_path):
            raise ValueError('Canonical ledger changed')
        expected_S=identity({'files':s['files'],'config':s['config'],'slots':s['slots'],
                             'independent_failures':s['independent_failures']})
        if s['S']!=expected_S:raise ValueError('Scientific content identity changed')
        return s

    def _save(self, s):
        atomic_json(self.state_path, {'state': s, 'sha256': identity(s)})

    def _records(self):
        # FitLedger.records opens a+, so verification uses a genuine readonly reader.
        with self.ledger_path.open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_SH)
            data = stream.read()
        records = []
        for line in data.splitlines():
            record = json.loads(line)
            claimed = record.pop('sha256')
            if (claimed != ledger_record_hash(record) or record['sequence'] != len(records)
                    or record['previous'] != (records[-1]['sha256'] if records else None)):
                raise ValueError('Corrupt ledger chain')
            record['sha256'] = claimed
            records.append(record)
        if not records or records[0]['kind'] != 'genesis' or records[0]['total_budget'] != 1000:
            raise ValueError('Invalid ledger origin')
        return data, records

    def _validate(self, s):
        data, records = self._records()
        bound = s['ledger_prefix']
        if len(data) < bound['bytes'] or hashlib.sha256(data[:bound['bytes']]).hexdigest() != bound['sha256']:
            raise ValueError('Ledger prefix changed')
        runs = [r for r in records if r.get('experiment') == EXPERIMENT and r['kind'] == 'run_started']
        if len(runs) != 1 or runs[0]['max_fits'] != BUDGET or runs[0]['hashes']['S'] != s['S']:
            raise ValueError('Missing or conflicting canonical reservation')
        known = {f['F'] for f in s['fits'].values()}
        started = {r['fit_id'] for r in records if r.get('experiment') == EXPERIMENT and r['kind'] == 'fit_started'}
        if not started <= known:
            raise ValueError('Fit bypassed canonical supervisor')
        return records

    def _bind_prefix(self, s):
        data, _ = self._records()
        s['ledger_prefix'] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def _ledger(self, s):
        return BoundStageLedger(self.ledger_path, 9, s['expected_prior'], s['expected_sha256'])

    @staticmethod
    def _active(s):
        if s['poison'] or s['terminal']:
            raise ValueError('Poisoned or terminal run')

    def reserve(self, expected_prior, expected_sha256, scientific_files, scientific_config,
                slots, *, independent_failures=False):
        if len(slots) != BUDGET or len(set(slots)) != BUDGET or not all(isinstance(x, str) and x for x in slots):
            raise ValueError('Exactly14 unique preregistered slots required')
        verify_manifest(scientific_files)
        S = identity({'files': scientific_files, 'config': scientific_config, 'slots':list(slots),
                      'independent_failures':independent_failures})
        with self._lock(True):
            if self.state_path.exists():
                raise ValueError('Canonical stage already attempted; resume only')
            data, records = self._records()
            if any(r.get('experiment') == EXPERIMENT for r in records):
                raise ValueError('Existing reservation requires integrity recovery, not replacement')
            s = dict(experiment=EXPERIMENT, ledger_path=str(self.ledger_path),
                     expected_prior=expected_prior, expected_sha256=expected_sha256,
                     files=scientific_files, config=scientific_config, S=S, slots=list(slots),
                     independent_failures=independent_failures,
                     fits={}, poison=False, sealed=False, terminal=None, guard='UNOPENED',
                     P=None, R=None, reservation_pending=True, effects={}, account=None,
                     checkpoints=[], ledger_prefix={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            self._save(s)  # Durable intent prevents a new reservation on partial failure.
            try:
                self._ledger(s).start_run(EXPERIMENT, BUDGET, {'S':S}, independent_failures=independent_failures)
                s['reservation_pending'] = False
                self._bind_prefix(s)
                self._save(s)
            except BaseException:
                s['poison'] = True
                self._save(s)
                raise
        return S

    def read(self):
        with self._lock():
            s = self._load()
            self._validate(s)
            return s

    def recover(self):
        """Clean checkpoint recovery only. Pending fits remain durably poisoned."""
        with self._lock(True):
            s = self._load()
            records = self._validate(s)
            starts = {r['fit_id'] for r in records if r.get('experiment') == EXPERIMENT and r['kind']=='fit_started'}
            ends = {r['fit_id'] for r in records if r.get('experiment') == EXPERIMENT and r['kind']=='fit_finished'}
            if s['reservation_pending'] or starts != ends or any(f['status']=='pending' for f in s['fits'].values()):
                s['poison'] = True
                self._save(s)
            self._active(s)
            verify_manifest(s['files'])
            if s['sealed']:self._verify_freeze(s)
            return s

    @contextmanager
    def fit(self, slot, contract, fold):
        """Hold global lock across fit and persistence. Always explicitly terminalize handle.

        Catch registered numerical failures inside this context and call handle.failed().
        An escaped exception or incomplete handle poisons the run; never retry.
        """
        with self._lock(True):
            s = self._load(); records = self._validate(s); self._active(s)
            if s['sealed'] or slot not in s['slots'] or slot in s['fits']:
                raise ValueError('Sealed, unregistered or attempted slot')
            verify_manifest(s['files'])
            F = identity({'S':s['S'], 'contract':contract})
            if any(f['F']==F for f in s['fits'].values()):
                raise ValueError('Contract already attempted; verify cache, never fit alias')
            starts = {r['fit_id'] for r in records if r.get('experiment')==EXPERIMENT and r['kind']=='fit_started'}
            ends = {r['fit_id'] for r in records if r.get('experiment')==EXPERIMENT and r['kind']=='fit_finished'}
            if starts != ends or any(f['status']=='pending' for f in s['fits'].values()):
                s['poison']=True;self._save(s);raise ValueError('Pending fit requires audit')
            s['fits'][slot] = {'F':F,'status':'pending','contract':contract}
            self._save(s)
            handle = _Fit(self,s,slot,F)
            try:
                self._ledger(s).start_fit(EXPERIMENT,F,fold,contract,{'S':s['S'],'F':F})
                yield handle
                if not handle.terminal:
                    raise ValueError('Fit context exited without terminal')
                self._bind_prefix(s);self._save(s)
            except BaseException:
                s['poison']=True;self._save(s)
                raise

    def cached(self, contract):
        return self.verified_terminal(contract, 'succeeded')

    def verified_terminal(self, contract, status):
        if status not in ('succeeded', 'failed'):
            raise ValueError('Explicit terminal fit status required')
        s=self.read()  # Verified terminal artifacts remain available for read-only replay.
        verify_manifest(s['files'])
        F=identity({'S':s['S'],'contract':contract})
        fits=[f for f in s['fits'].values() if f['F']==F]
        if len(fits)!=1 or fits[0]['status']!=status:
            raise ValueError('No matching durable terminal')
        _,records=self._records()
        terminal=[r for r in records if r.get('experiment')==EXPERIMENT and r['kind']=='fit_finished' and r['fit_id']==F]
        if len(terminal)!=1 or terminal[0]['status']!=status or terminal[0]['result']!=fits[0]['result']:
            raise ValueError('Cache terminal mismatch')
        if status=='succeeded':verify_manifest(fits[0]['result']['artifacts'])
        return fits[0]['result']

    def poison(self, reason):
        """Durable non-fit persistence failure; never authorizes replacement work."""
        if not isinstance(reason,str) or not reason:
            raise ValueError('Explicit poison reason required')
        with self._lock(True):
            s=self._load();self._validate(s)
            if s['terminal']:
                raise ValueError('Terminal replay is read-only')
            if not s['poison']:
                s['poison']=True;s['poison_reason']=reason;self._save(s)

    def clean_checkpoint(self, phase, artifacts):
        """Durable development/final/release pause, without closing the run."""
        if phase not in {'DEVELOPMENT_VERIFIED','FINAL_MODELS_VERIFIED','RELEASE_PENDING'}:
            raise ValueError('Unknown clean checkpoint phase')
        with self._lock(True):
            s=self._load();records=self._validate(s);self._active(s)
            if s['sealed'] or s['guard']!='UNOPENED':raise ValueError('Checkpoint phase closed')
            starts={r['fit_id'] for r in records if r.get('experiment')==EXPERIMENT and r['kind']=='fit_started'}
            ends={r['fit_id'] for r in records if r.get('experiment')==EXPERIMENT and r['kind']=='fit_finished'}
            if starts!=ends or any(f['status']=='pending' for f in s['fits'].values()):
                raise ValueError('Unfinished fits cannot checkpoint cleanly')
            verify_manifest(artifacts)
            s['checkpoints'].append({'phase':phase,'artifacts':artifacts})
            self._save(s)

    def freeze(self, release_sha, ci_sha, review_sha, ci_passed, review_passed,
               final_contracts, reports, technical_tests):
        with self._lock(True):
            s=self._load();records=self._validate(s);self._active(s)
            if s['sealed'] or s['guard']!='UNOPENED':raise ValueError('Already sealed/opened')
            if (not isinstance(release_sha,str) or re.fullmatch('[0-9a-f]{40}',release_sha) is None
                    or not (release_sha==ci_sha==review_sha and ci_passed is True and review_passed is True)):
                raise ValueError('Exact-SHA CI/review required')
            if set(technical_tests)!= {'T1','T2','T3','T4','T5'} or any(v is not True for v in technical_tests.values()):
                raise ValueError('Technical prerequisites unavailable')
            if len(final_contracts)!=2 or {c.get('family') for c in final_contracts}!={'constant','logistic'}:
                raise ValueError('Registered final constant and logistic required')
            verify_manifest(s['files']);verify_manifest(reports)
            starts={r['fit_id'] for r in records if r.get('experiment')==EXPERIMENT and r['kind']=='fit_started'}
            terminals={r['fit_id']:r for r in records if r.get('experiment')==EXPERIMENT and r['kind']=='fit_finished'}
            if starts!=set(terminals) or any(f['status']=='pending' for f in s['fits'].values()):
                raise ValueError('T3 requires all fits terminal, not run_finished')
            model_bindings=[]
            for contract in final_contracts:
                F=identity({'S':s['S'],'contract':contract})
                matches=[f for f in s['fits'].values() if f['F']==F and f['status']=='succeeded']
                if len(matches)!=1 or F not in terminals or terminals[F]['result']!=matches[0]['result']:
                    raise ValueError('Final model not durably verified')
                verify_manifest(matches[0]['result']['artifacts']);model_bindings.append(matches[0])
            if len({x['F'] for x in model_bindings})!=2:raise ValueError('Distinct final contracts required')
            R={'sha':release_sha,'ci_sha':ci_sha,'review_sha':review_sha,'ci_passed':True,'review_passed':True,'reports':reports}
            for recorded in s['fits'].values():
                if recorded['status']=='succeeded':verify_manifest(recorded['result']['artifacts'])
            package={'S':s['S'],'fits':s['fits'],'models':model_bindings,'R':R,'technical_tests':technical_tests,'guard':'UNOPENED'}
            atomic_json(self.root/'freeze.json',package)
            s['R']=R;s['P']=fingerprint(self.root/'freeze.json');s['sealed']=True
            self._save(s)
            return s['P']

    def _verify_freeze(self, s):
        verify_manifest({'P':s['P']})
        package=json.loads(Path(s['P']['path']).read_text())
        if package['S']!=s['S'] or package['R']!=s['R']:
            raise ValueError('Freeze provenance mismatch')
        verify_manifest(package['R']['reports'])
        for model in package['fits'].values():
            if model['status']=='succeeded':verify_manifest(model['result']['artifacts'])

    def begin_confirmation(self):
        with self._lock(True):
            s=self._load();self._validate(s);self._active(s)
            if not s['sealed'] or s['guard']!='UNOPENED':raise ValueError('Opening unavailable/consumed')
            self._verify_freeze(s);verify_manifest(s['files'])
            s['guard']='OPENING';self._save(s)  # Return is permission for I/O only after fsync.
            return s['P']

    def received_payload(self, path):
        with self._lock(True):
            s=self._load();self._validate(s);self._active(s)
            if s['guard']!='OPENING':raise ValueError('Not first payload')
            with Path(path).open('rb') as stream:os.fsync(stream.fileno())
            s['payload']=fingerprint(path);s['guard']='OPENED';self._save(s)

    def mark_held_inspection(self, manifest):
        with self._lock(True):
            s=self._load();self._validate(s);self._active(s)
            if s['guard']!='OPENING':raise ValueError('Opening must precede inspection')
            verify_manifest(manifest)
            if s.get('held_marker') and s['held_marker'] != manifest:
                raise ValueError('Held inspection binding immutable')
            s['held_marker']=manifest;self._save(s)

    def record_held_inspection(self):
        with self._lock(True):
            s=self._load();self._validate(s);self._active(s)
            if s['guard']!='OPENING' or not s.get('held_marker'):raise ValueError('No preinspection marker')
            verify_manifest(s['held_marker']);s['inspection_recorded']=True;s['guard']='OPENED';self._save(s)
            # Numeric exposure is permitted only after this call returns.

    def checkpoint(self, event_id, effect, account_after, *, expected_version):
        with self._lock(True):
            s=self._load();self._validate(s);self._active(s)
            if s['guard']!='OPENED':raise ValueError('Not active confirmation')
            payload={'effect':effect,'account_after':account_after}
            if event_id in s['effects']:
                if s['effects'][event_id]!=payload:raise ValueError('Checkpoint conflict')
                return False
            if type(expected_version) is not int or expected_version != len(s['effects']):
                raise ValueError('Stale checkpoint predecessor')
            s['effects'][event_id]=payload;s['account']=account_after;self._save(s);return True

    def process_failure(self, reason):
        with self._lock(True):
            s=self._load();self._validate(s);self._active(s)
            s['checkpoints'].append({'recoverable_failure':str(reason),'guard':s['guard']});self._save(s)

    def close(self, status, result):
        if status not in TERMINAL:raise ValueError('Invalid terminal status')
        with self._lock(True):
            s=self._load();self._validate(s)
            if s['terminal'] or (status=='COMPLETED' and (s['guard']!='OPENED' or s['poison'])):
                raise ValueError('Terminal transition refused')
            # Terminal intent first; a crash cannot restore active evaluation.
            s['terminal']=status;s['terminal_result']=result
            if s['guard']!='UNOPENED':s['guard']=status
            self._save(s)
            self._finalize_terminal(s)

    def _finalize_terminal(self, s):
        records=self._validate(s)
        done=[r for r in records if r.get('experiment')==EXPERIMENT and r['kind']=='run_finished']
        if done:
            if len(done)!=1 or done[0]['status']!=s['terminal'] or done[0]['result']!=s['terminal_result']:
                raise ValueError('Terminal ledger conflict')
        else:
            self._ledger(s).finish_run(EXPERIMENT,s['terminal'],s['terminal_result'])
        self._bind_prefix(s);self._save(s)

    def finalize_terminal(self):
        """Complete ledger closure after a crash, never resume evaluation."""
        with self._lock(True):
            s=self._load()
            if not s['terminal']:raise ValueError('No terminal intent')
            self._finalize_terminal(s)


class _Fit:
    def __init__(self, owner, state, slot, F):
        self.owner,self.state,self.slot,self.F=owner,state,slot,F
        self.terminal=False

    def _finish(self,status,result):
        if self.terminal:raise ValueError('Terminal already recorded')
        self.owner._ledger(self.state).finish_fit(EXPERIMENT,self.F,status,result)
        self.state['fits'][self.slot].update(status=status,result=result)
        self.terminal=True

    def succeeded(self, artifacts, diagnostics=None):
        if not {'model','metadata'} <= set(artifacts):
            raise ValueError('Model and JSON metadata artifacts required')
        verify_manifest(artifacts)
        metadata=json.loads(Path(artifacts['metadata']['path']).read_text())
        if metadata.get('F')!=self.F or metadata.get('S')!=self.state['S'] or metadata.get('model_sha256')!=artifacts['model']['sha256']:
            raise ValueError('Model metadata must bind S/F/model bytes')
        self._finish('succeeded',{'artifacts':artifacts,'diagnostics':diagnostics or {}})

    def failed(self, diagnostics):
        self._finish('failed',{'diagnostics':diagnostics})
