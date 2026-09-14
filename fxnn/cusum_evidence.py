"""Export byte-exact scientific artifacts without loading data or fitting models."""
import argparse
import hashlib
import json
from pathlib import Path

from .fit_ledger import _hash


def verify_ledger(raw_bytes):
    """Verify a captured ledger snapshot without opening or creating writable state."""
    records = []
    for line in raw_bytes.splitlines():
        record = json.loads(line)
        content = {key: value for key, value in record.items() if key != 'sha256'}
        if (record['sha256'] != _hash(content) or record['sequence'] != len(records)
                or record['previous'] != (records[-1]['sha256'] if records else None)):
            raise ValueError('Corrupt ledger snapshot')
        records.append(record)
    if not records or records[0]['kind'] != 'genesis' or records[0]['total_budget'] != 1000:
        raise ValueError('Invalid global budget origin')
    return records


def export_evidence(report_path, ledger_path, destination, experiment='cusum_v1'):
    if experiment not in ('cusum_v1', 'cusum_temporal_v2', 'mlp_cusum_v1'):
        raise ValueError('Unknown evidence experiment')
    stem = experiment.replace('_', '-')
    report_bytes = Path(report_path).read_bytes()
    report = json.loads(report_bytes)
    raw_lines = Path(ledger_path).read_bytes().splitlines(keepends=True)
    records = verify_ledger(b''.join(raw_lines))
    finished = [r for r in records if r['kind'] == 'run_finished'
                and r.get('experiment') == experiment]
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    if (report.get('experiment') != experiment or len(finished) != 1
            or finished[0]['result'].get('report_sha256') != report_hash
            or finished[0]['status'] != report.get('status')
            or finished[0]['consumed_total'] != report.get('global_fits_consumed')
            or finished[0]['result'].get('fits_consumed') != report.get('fits_consumed')):
        raise ValueError('Report does not match completed ledger record')
    # Export the immutable historical prefix, even if later stages append to the ledger.
    ledger_bytes = b''.join(raw_lines[:finished[0]['sequence'] + 1])
    payloads = {f'{stem}.json': report_bytes, f'{stem}-ledger.jsonl': ledger_bytes}
    manifest = {'experiment': experiment, 'files': {
        name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()}}
    payloads[f'{stem}-evidence.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    destination = Path(destination)
    for name, value in payloads.items():
        target = destination / name
        if target.exists() and target.read_bytes() != value:
            raise ValueError(f'Existing evidence differs: {target}')
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in payloads.items():
        target = destination / name
        if not target.exists():
            with target.open('xb') as stream:
                stream.write(value)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--experiment', default='cusum_v1', choices=['cusum_v1', 'cusum_temporal_v2', 'mlp_cusum_v1'])
    args = parser.parse_args()
    print(json.dumps(export_evidence(args.report, args.ledger, args.destination, args.experiment), indent=2))


if __name__ == '__main__':
    main()
