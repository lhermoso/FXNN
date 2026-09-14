"""Durable, append-only global research budget. Never retry a scientific fit."""
import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def _hash(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, allow_nan=False).encode()).hexdigest()


class FitLedger:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a+', encoding='utf-8') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                stream.seek(0)
                records = []
                for line in stream:
                    record = json.loads(line)
                    claimed = record.pop('sha256')
                    if (claimed != _hash(record) or record['sequence'] != len(records)
                            or record['previous'] != (records[-1]['sha256'] if records else None)):
                        raise ValueError('Corrupt fit ledger; refusing research')
                    record['sha256'] = claimed
                    records.append(record)
                if records and (records[0]['kind'] != 'genesis'
                                or records[0]['total_budget'] != 1000):
                    raise ValueError('Invalid global budget origin')
                yield stream, records
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _append(self, stream, records, kind, **values):
        record = dict(sequence=len(records), previous=records[-1]['sha256'] if records else None,
                      timestamp=datetime.now(timezone.utc).isoformat(), kind=kind, **values)
        record['sha256'] = _hash(record)
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
        records.append(record)
        return record

    @staticmethod
    def _consumed(records):
        return records[0]['prior_fits'] + sum(r['kind'] == 'fit_started' for r in records)

    def initialize(self, prior_fits, evidence):
        if type(prior_fits) is not int or not 0 <= prior_fits <= 1000 or not evidence:
            raise ValueError('Explicit prior consumption and evidence required')
        with self._locked() as (stream, records):
            if not records:
                self._append(stream, records, 'genesis', total_budget=1000,
                             prior_fits=prior_fits, evidence=evidence)
            return self._consumed(records)

    def records(self):
        with self._locked() as (_, records):
            if not records:
                raise ValueError('Ledger must be explicitly initialized')
            return records

    def consumed(self):
        return self._consumed(self.records())

    def start_run(self, experiment, max_fits, hashes, *, independent_failures=False):
        if type(max_fits) is not int or max_fits <= 0 or not hashes:
            raise ValueError('Run requires positive fit budget and hashes')
        with self._locked() as (stream, records):
            if not records:
                raise ValueError('Ledger must be explicitly initialized')
            runs = [r for r in records if r['kind'] == 'run_started']
            finished = {r['experiment'] for r in records if r['kind'] == 'run_finished'}
            if any(r['experiment'] == experiment for r in runs):
                raise ValueError('Experiment already attempted; no scientific reruns')
            if any(r['experiment'] not in finished for r in runs):
                raise ValueError('Unfinished research run blocks new budget reservation')
            if self._consumed(records) + max_fits > 1000:
                raise ValueError('Insufficient global model fit budget')
            policy = {'independent_failures': True} if independent_failures else {}
            self._append(stream, records, 'run_started', experiment=experiment,
                         max_fits=max_fits, hashes=hashes, **policy)

    def start_fit(self, experiment, fit_id, fold, parameters, hashes):
        with self._locked() as (stream, records):
            runs = [r for r in records if r['kind'] == 'run_started' and r['experiment'] == experiment]
            if (not runs or any(r['kind'] == 'run_finished' and r['experiment'] == experiment
                                for r in records)):
                raise ValueError('No active experiment')
            fits = [r for r in records if r['kind'] == 'fit_started' and r['experiment'] == experiment]
            completed = {r['fit_id'] for r in records if r['kind'] == 'fit_finished'
                         and r['experiment'] == experiment
                         and (r['status'] == 'succeeded' or runs[0].get('independent_failures', False))}
            if any(r['fit_id'] not in completed for r in fits):
                raise ValueError('Failed or unfinished fit stops experiment')
            if any(r['fit_id'] == fit_id for r in fits):
                raise ValueError('Fit already attempted')
            if len(fits) >= runs[0]['max_fits'] or self._consumed(records) >= 1000:
                raise ValueError('Model fit budget exhausted')
            return self._append(stream, records, 'fit_started', experiment=experiment,
                                fit_id=fit_id, stage=5, fold=fold, parameters=parameters,
                                seed=0, hashes=hashes)

    def finish_fit(self, experiment, fit_id, status, result):
        if status not in ('succeeded', 'failed'):
            raise ValueError('Invalid fit outcome')
        with self._locked() as (stream, records):
            matching = [r for r in records if r.get('experiment') == experiment
                        and r.get('fit_id') == fit_id]
            if len(matching) != 1 or matching[0]['kind'] != 'fit_started':
                raise ValueError('Fit missing or already finished')
            self._append(stream, records, 'fit_finished', experiment=experiment,
                         fit_id=fit_id, status=status, result=result)

    def finish_run(self, experiment, status, result):
        with self._locked() as (stream, records):
            matching = [r for r in records if r.get('experiment') == experiment
                        and r['kind'] in ('run_started', 'run_finished')]
            if len(matching) != 1:
                raise ValueError('Run missing or already finished')
            self._append(stream, records, 'run_finished', experiment=experiment,
                         status=status, result=result, consumed_total=self._consumed(records))
