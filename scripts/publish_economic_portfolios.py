#!/usr/bin/env python3
"""Publish/replay frozen portfolio results with their existing exact JSON codec.

Post-results I/O recovery for the original CLI's Fraction serialization defect.
All scientific computation remains in the preregistered modules. No fitting,
source acquisition, release freezing or confirmation opening is exposed here.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxnn import economic_research as research
from fxnn.economic_account import serializable
from fxnn.economic_lifecycle import Lifecycle, atomic_json, fingerprint, verify_manifest
from fxnn.economic_report import evaluate_portfolios

RELATIVE_PATH = 'scripts/publish_economic_portfolios.py'


def read(path):
    return json.loads(Path(path).read_text())


def sync(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def verify_frozen_publisher(repo, snapshot):
    """Bind this I/O executable through original P/R/validation receipt and Git."""
    repo = Path(repo).resolve()
    if not snapshot.get('sealed') or not snapshot.get('P'):
        raise ValueError('Publisher requires frozen confirmation package')
    verify_manifest({'freeze': snapshot['P']})
    package = read(snapshot['P']['path'])
    if package['S'] != snapshot['S'] or package['R'] != snapshot['R']:
        raise ValueError('Publisher freeze provenance mismatch')
    verify_manifest(package['R']['reports'])
    receipt = read(package['R']['reports']['receipt_validation']['path'])
    binding = receipt.get('publication_adapter')
    if not isinstance(binding, dict) or binding.get('repository_relative_path') != RELATIVE_PATH:
        raise ValueError('Frozen publication adapter binding missing or noncanonical')
    artifact = binding.get('artifact')
    actual_path = (repo / RELATIVE_PATH).resolve()
    if not isinstance(artifact, dict) or artifact.get('path') != str(actual_path):
        raise ValueError('Publication adapter path differs from frozen canonical path')
    verify_manifest({'publication_adapter': artifact})
    release_sha = package['R']['sha']
    if receipt.get('head_sha') != release_sha:
        raise ValueError('Publication receipt differs from frozen release SHA')
    committed = subprocess.check_output(['git', '-C', str(repo), 'show', release_sha + ':' + RELATIVE_PATH])
    if len(committed) != artifact['bytes'] or hashlib.sha256(committed).hexdigest() != artifact['sha256']:
        raise ValueError('Publication adapter differs from frozen release Git blob')
    return artifact


def exact_json(result, confirmation):
    """Use the registered codec; prove the actual report interpretation survives."""
    def check_keys(value):
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError('Portfolio JSON requires string keys; no lossy coercion')
            for item in value.values():
                check_keys(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                check_keys(item)
    check_keys(result)
    encoded = json.dumps(serializable(result), sort_keys=True, allow_nan=False) + '\n'
    decoded = json.loads(encoded)
    if evaluate_portfolios(result, confirmation=confirmation) != evaluate_portfolios(decoded, confirmation=confirmation):
        raise ValueError('Exact portfolio report changed during JSON conversion')
    return decoded, encoded


def publish_aggregate(path, decoded, encoded, supervisor):
    """Exclusive same-byte recovery; preserve every failed pending publication."""
    path = Path(path)
    # This lock is publication-only. Read-only replay never calls this function.
    # Setup/close failures are observed persistence errors too.
    try:
        with (path.parent / (path.name + '.publication.lock')).open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pending = path.with_suffix('.pending')
            preserved_files = sorted(path.parent.glob(pending.name + '.partial-*'))
            # A prior process may have died immediately after forensic rename.
            # Finish that preservation before writing or returning success.
            for preserved in preserved_files:
                sync(preserved)
            if preserved_files:
                sync(path.parent)
            if path.exists():
                if path.read_bytes() != encoded.encode('utf8'):
                    raise ValueError('Existing aggregate differs from verified exact result')
                sync(path)
                sync(path.parent)
                return fingerprint(path)
            if pending.exists():
                preserved = pending.with_name(pending.name + '.partial-' + uuid.uuid4().hex)
                # Exclusive lock plus unique name; never truncate failed bytes.
                if preserved.exists():
                    raise FileExistsError('Forensic destination already exists')
                pending.rename(preserved)
                sync(preserved)
                sync(path.parent)
            atomic_json(path, decoded)
            return fingerprint(path)
    except Exception:
        supervisor.poison('Exact portfolio aggregate publication failed')
        raise


def model_artifact(snapshot, final):
    phase = 'FINAL_MODELS_VERIFIED' if final else 'DEVELOPMENT_VERIFIED'
    records = [c for c in snapshot['checkpoints'] if c.get('phase') == phase]
    if len(records) != 1:
        raise ValueError('One authoritative model checkpoint required')
    return records[0]['artifacts']['report']


def execute(repo, output, preregistered_sha, phase, replay=False):
    repo, output = Path(repo).resolve(), Path(output).resolve()
    config = research.load_config(repo / 'configs/economic_ticks_v1.json')
    research.verify_preregistration(repo, preregistered_sha)
    supervisor = Lifecycle(config['global_ledger'])
    snapshot = supervisor.read()
    if phase not in ('development', 'confirmation'):
        raise ValueError('Unregistered publication phase')
    confirmation = phase == 'confirmation'
    if confirmation:
        verify_frozen_publisher(repo, snapshot)
        allowed = {'OPENED', 'COMPLETED', 'INCOMPLETE'} if replay else {'OPENED'}
        if snapshot['guard'] not in allowed:
            raise ValueError('Confirmation publication/replay guard unavailable')
    intent = read(supervisor.root / 'development-data-intent.json')
    canonical_output = Path(intent['binding']['output']).resolve().parent
    if output != canonical_output:
        raise ValueError('Canonical economic output alias conflict')
    evidence = read(output / phase / 'source-evidence.json')
    matrix = research.load_window_data(output / phase, evidence)
    if confirmation:
        predictions = fingerprint(output / 'probabilities-confirmation/report.json')
        research.verify_final_probabilities(config, supervisor, matrix, model_artifact(snapshot, True),
                                            predictions, fingerprint(output / phase / 'source-evidence.json'))
        operational = read(predictions['path'])['operational']
    else:
        operational = fingerprint(output / 'operational-development.jsonl')
        research.verify_operational_predictions(config, supervisor, matrix, research.clock_for(config),
                                                model_artifact(snapshot, False), operational)
    result = research.portfolio_segment(config, supervisor, output / phase, evidence, operational,
                                        output / ('portfolios-' + phase), confirmation=confirmation, replay=replay)
    decoded, encoded = exact_json(result, confirmation)
    if not replay:
        publish_aggregate(output / ('aggregate-' + phase + '.json'), decoded, encoded, supervisor)
    return decoded


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['development', 'confirmation'])
    parser.add_argument('--replay', action='store_true', help='Verify only; never publish aggregate or acquire publication lock')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--preregistered-sha', required=True)
    args = parser.parse_args(argv)
    result = execute(Path(__file__).resolve().parents[1], args.output, args.preregistered_sha, args.phase, args.replay)
    print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
