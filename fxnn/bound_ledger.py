"""Atomic binding of a new reservation to exact previously frozen ledger bytes."""
import hashlib
import os
import re
from .experiment_fit import StageLedger


class BoundStageLedger(StageLedger):
    def __init__(self, path, stage, expected_prior, expected_sha256):
        super().__init__(path, stage)
        if (type(expected_prior) is not int or not 0 <= expected_prior <= 1000
                or not isinstance(expected_sha256, str)
                or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None):
            raise ValueError('Valid frozen ledger count and byte hash required')
        self.expected_prior = expected_prior
        self.expected_sha256 = expected_sha256

    def _append(self, stream, records, kind, **values):
        if kind == 'run_started':
            digest = hashlib.sha256()
            offset = 0
            while True:
                chunk = os.pread(stream.fileno(), 1024*1024, offset)
                if not chunk:
                    break
                digest.update(chunk)
                offset += len(chunk)
            if self._consumed(records) != self.expected_prior or digest.hexdigest() != self.expected_sha256:
                raise ValueError('Frozen ledger count or exact bytes changed before reservation')
        return super()._append(stream, records, kind, **values)
