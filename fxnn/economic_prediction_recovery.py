"""One canonical recoverable construction of frozen confirmation predictions.

Only prediction artifacts and this private registry are written. No fit, ledger,
confirmation guard, source or model transition is performed here.
"""
import fcntl
import json
import os
from pathlib import Path

from fxnn.economic_lifecycle import atomic_json, fingerprint, identity, verify_manifest


class PredictionConstructionFailed(ValueError):
    """An observed integrity/persistence fault forbids automatic rebuilding."""


def _sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save(path, state):
    atomic_json(path, {'state': state, 'sha256': identity(state)})


def _load(path):
    envelope = json.loads(path.read_text())
    state = envelope['state']
    if envelope['sha256'] != identity(state) or state.get('version') != 1:
        raise PredictionConstructionFailed('Corrupt prediction registry')
    return state


def _inventory(path):
    if not path.exists():
        return {}
    result = {}
    for child in sorted(path.rglob('*')):
        if child.is_symlink():
            raise PredictionConstructionFailed('Symlink in preserved prediction attempt')
        if child.is_file():
            result[str(child.relative_to(path))] = fingerprint(child)
    return result


def _preserve(state, registry, output):
    """The rename intent makes death immediately before/after rename recoverable."""
    attempt = state['attempt']
    if state['status'] != 'archiving':
        archive = output.parent/(f'.{output.name}.interrupted-{state["contract_sha256"][:16]}-{attempt:04d}')
        if archive.exists() or archive.is_symlink():
            raise PredictionConstructionFailed('Unregistered archive already exists')
        state.update(status='archiving', archive=str(archive), had_output=output.exists())
        _save(registry, state)
    archive = Path(state['archive'])
    if state['had_output']:
        if output.exists() and not archive.exists():
            if output.is_symlink() or not output.is_dir():
                raise PredictionConstructionFailed('Unexpected partial output type')
            os.replace(output, archive)
            _sync(output.parent)
        elif output.exists() or not archive.is_dir():
            raise PredictionConstructionFailed('Ambiguous interrupted prediction rename')
    elif output.exists() or archive.exists():
        raise PredictionConstructionFailed('Unexpected output after empty interrupted attempt')
    state['preserved_attempts'].append({'attempt': attempt,
        'archive': str(archive) if state['had_output'] else None,
        'artifacts': _inventory(archive) if state['had_output'] else {}})
    state.update(status='building', attempt=attempt+1)
    state.pop('archive', None)
    state.pop('had_output', None)
    _save(registry, state)


def prediction_construction(supervisor, contract, output, construct, verify):
    """Serialize construction/recovery; callbacks do deterministic generation/replay.

    construct(new_output_path) must generate report.json exclusively and return
    only after its writes complete. verify(expected_report_fingerprint) must be
    read-only mathematical replay. Callback Exception is durable failure;
    KeyboardInterrupt/SystemExit and process death retain recoverable intent.
    """
    output = Path(output).resolve()
    required = {'S', 'freeze_sha256', 'models', 'final_report', 'confirmation_evidence', 'config_sha256'}
    if set(contract) != required:
        raise ValueError('Complete frozen prediction contract required')
    binding = {'contract': contract, 'output': str(output)}
    bound_hash = identity(binding)
    root = supervisor.root/'prediction-construction-v1'
    if root.is_symlink():
        raise PredictionConstructionFailed('Symlink canonical prediction registry')
    root.mkdir(mode=0o700, exist_ok=True)
    _sync(root.parent)
    registry = root/'state.json'
    with (root/'construction.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fresh = False
        if registry.exists():
            state = _load(registry)
            if state['binding'] != binding or state['contract_sha256'] != bound_hash:
                raise PredictionConstructionFailed('Prediction output/contract alias forbidden')
            if state['status'] == 'failed':
                raise PredictionConstructionFailed('Prediction construction fault requires audit')
            for preserved in state['preserved_attempts']:
                if preserved['archive'] is not None and not Path(preserved['archive']).is_dir():
                    raise PredictionConstructionFailed('Preserved prediction attempt disappeared')
                if preserved['artifacts']:
                    verify_manifest(preserved['artifacts'])
            if state['status'] == 'completed':
                verify_manifest({'report': state['report']})
                verify(state['report'])
                return json.loads(Path(state['report']['path']).read_text())
        else:
            if output.exists() or output.is_symlink():
                raise PredictionConstructionFailed('Preexisting prediction output has no canonical intent')
            state = {'version': 1, 'binding': binding, 'contract_sha256': bound_hash,
                     'status': 'building', 'attempt': 1, 'preserved_attempts': []}
            _save(registry, state)
            fresh = True
        snapshot = supervisor.read()
        if (snapshot.get('guard') != 'OPENED' or not snapshot.get('sealed') or
                snapshot.get('poison') or snapshot.get('terminal')):
            raise PredictionConstructionFailed('Only active frozen OPENED evaluation may construct predictions')
        try:
            if state['status'] == 'verifying':
                verify_manifest({'report': state['candidate_report']})
                verify(state['candidate_report'])
            else:
                if not fresh:
                    if state['status'] not in ('building', 'interrupted', 'archiving'):
                        raise PredictionConstructionFailed('Unknown prediction construction phase')
                    _preserve(state, registry, output)
                construct(output)
                report = fingerprint(output/'report.json')
                state.update(status='verifying', candidate_report=report)
                _save(registry, state)
                verify(report)
            state.update(status='completed', report=state.pop('candidate_report'))
            _save(registry, state)
            return json.loads(Path(state['report']['path']).read_text())
        except (KeyboardInterrupt, SystemExit):
            # Keep archiving/verifying durable progress intact; its recovery is
            # stricter than rebuilding an uncommitted construction attempt.
            if state['status'] == 'building':
                state['status'] = 'interrupted'
                _save(registry, state)
            raise
        except Exception as error:
            state.update(status='failed', failure_type=type(error).__name__)
            _save(registry, state)
            raise
