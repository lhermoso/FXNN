"""Immutable monthly HistData ASCII bid/ask acquisition; development UTC only.

See docs/experiments/histdata-ticks-v1-protocol.md. No research/model imports.
"""
import argparse
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile

MONTHS = [f'{y}{m:02}' for y in (2022, 2023) for m in range(1, 13)]
ORIGIN = 'https://www.histdata.com'
START = datetime(2022, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 1, 1, tzinfo=timezone.utc)
MAX_ZIP = 2 * 1024**3
MAX_RAW = 8 * 1024**3


def fingerprint(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return {'sha256': h.hexdigest(), 'bytes': path.stat().st_size}


def write_json(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write('\n')


def verify_files(root, files):
    for name, expected in files.items():
        if Path(name).name != name or (root / name).is_symlink():
            raise ValueError('Unsafe manifest file')
        if fingerprint(root / name) != expected:
            raise ValueError(f'Resume fingerprint mismatch: {name}')


class Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.forms = []
        self.fields = None
        self.error = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            if self.active:
                self.error = True
            self.active = attrs.get('id') == 'file_down'
            if self.active:
                self.fields = {}
                self.forms.append(self.fields)
                if attrs.get('method', '').upper() != 'POST' or attrs.get('action') != '/get.php':
                    self.error = True
        if tag == 'input' and self.active:
            name = attrs.get('name')
            if name:
                if name in self.fields:
                    self.error = True
                self.fields[name] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.active = False


def parse_form(page, month):
    parser = Form()
    parser.feed(page)
    expected = {'date': month[:4], 'datemonth': month, 'platform': 'ASCII',
                'timeframe': 'T', 'fxpair': 'EURUSD'}
    if parser.error or len(parser.forms) != 1:
        raise ValueError('Expected exactly one valid download form')
    fields = parser.forms[0]
    if set(fields) != {*expected, 'tk'} or not fields['tk'] or any(fields[k] != v for k, v in expected.items()):
        raise ValueError('Download form does not match requested month')
    return fields


def validate_zip(path, month):
    if not 0 < path.stat().st_size <= MAX_ZIP:
        raise ValueError('Archive size out of bounds')
    stem = f'DAT_ASCII_EURUSD_T_{month}'
    with ZipFile(path) as z:
        members = z.infolist()
        names = [m.filename for m in members]
        if len(names) != len(set(names)) or stem + '.csv' not in names or not set(names) <= {stem + '.csv', stem + '.txt'}:
            raise ValueError('Unexpected archive members')
        if any(not 0 < m.file_size <= MAX_RAW or m.flag_bits & 1 for m in members) or sum(m.file_size for m in members) > MAX_RAW:
            raise ValueError('Archive member size/encryption invalid')
        if z.testzip() is not None:
            raise ValueError('Archive CRC failure')
    return stem + '.csv'


def stamp(value):
    if not re.fullmatch(r'[0-9]{8} [0-9]{9}', value):
        raise ValueError('Expected YYYYMMDD HHMMSSmmm')
    return datetime.strptime(value, '%Y%m%d %H%M%S%f').replace(
        tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc)


def audit(archive, output, month):
    member = validate_zip(archive, month)
    counts = Counter()
    days = Counter()
    highwater = first = last = previous_row = None
    spread_min = spread_max = None
    spread_sum = Decimal(0)
    max_gap = 0
    with ZipFile(archive) as z, z.open(member) as source, (output / 'ticks.csv').open('x', newline='') as out, (output / 'quarantine.jsonl').open('x') as quarantine, (output / 'reserved.jsonl').open('x') as reserved:
        writer = csv.writer(out)
        writer.writerow(['timestamp_utc', 'source_timestamp_est', 'bid', 'ask', 'volume', 'source_sequence', 'flags'])
        for sequence, line in enumerate(source, 1):
            counts['source_rows'] += 1
            # The timestamp is inspected before numeric fields. Unknown temporal
            # eligibility never exposes price text outside the immutable ZIP.
            text = line.decode('utf-8-sig' if sequence == 1 else 'utf-8', errors='replace').rstrip('\r\n')
            timestamp = text.split(',', 1)[0]
            try:
                current = stamp(timestamp)
                if timestamp[:6] != month:
                    raise ValueError('Wrong source month')
            except ValueError:
                counts['invalid_rows'] += 1
                quarantine.write(json.dumps({'source_sequence': sequence, 'source_timestamp_est': timestamp,
                    'timestamp_utc': None, 'reasons': ['invalid_timestamp_or_source_month'], 'prices_redacted': True}) + '\n')
                continue
            if not START <= current < END:
                counts['reserved_rows'] += 1
                reserved.write(json.dumps({'source_sequence': sequence, 'timestamp_utc': current.isoformat(),
                    'reason': 'outside_development_utc'}) + '\n')
                continue
            reasons, flags = [], []
            if highwater is not None:
                if current < highwater:
                    reasons.append('out_of_order')
                elif current == highwater:
                    flags.append('simultaneous_timestamp')
                else:
                    max_gap = max(max_gap, (current - highwater).total_seconds())
            highwater = max(highwater, current) if highwater else current
            if text == previous_row:
                flags.append('consecutive_exact_duplicate')
            previous_row = text
            row = text.split(',')
            if len(row) != 4:
                reasons.append('field_count')
            else:
                try:
                    bid, ask, volume = map(Decimal, row[1:])
                    if not all(x.is_finite() for x in (bid, ask, volume)):
                        reasons.append('nonfinite')
                    elif bid <= 0 or ask <= 0 or volume < 0:
                        reasons.append('nonpositive_quote_or_negative_volume')
                    elif ask < bid:
                        reasons.append('crossed_quote')
                except InvalidOperation:
                    reasons.append('invalid_decimal')
            for reason in reasons + flags:
                counts[reason] += 1
            if reasons or flags:
                quarantine.write(json.dumps({'source_sequence': sequence, 'timestamp_utc': current.isoformat(),
                    'source_timestamp_est': timestamp, 'reasons': reasons, 'flags': flags,
                    'retained_in_normalized': not reasons, 'raw': text}) + '\n')
            if reasons:
                counts['invalid_rows'] += 1
                continue
            spread = ask - bid
            spread_min = spread if spread_min is None else min(spread_min, spread)
            spread_max = spread if spread_max is None else max(spread_max, spread)
            spread_sum += spread
            counts['valid_rows'] += 1
            days[current.date().isoformat()] += 1
            first = first or current
            last = current
            writer.writerow([current.isoformat(), timestamp, *row[1:], sequence, '|'.join(flags)])
    return {**{k: counts[k] for k in ('source_rows', 'valid_rows', 'invalid_rows', 'reserved_rows')},
        'anomalies': dict(counts), 'days_utc': dict(days), 'first_utc': first.isoformat() if first else None,
        'last_utc': last.isoformat() if last else None, 'spread_min': str(spread_min), 'spread_max': str(spread_max),
        'spread_mean': str(spread_sum / counts['valid_rows']) if counts['valid_rows'] else None,
        'max_gap_seconds_unclassified': max_gap,
        'simultaneous_order': 'Source sequence retained; timestamp ties do not establish execution priority',
        'invalid_observability': 'Quarantine UTC records mark uncertain minutes even when valid quotes coexist; unknown timestamps remain unresolved.'}


def request(url, target, *, referer=None, fields=None, timeout=60, limit=2 * 1024**2):
    if not url.startswith(ORIGIN + '/') or target.exists():
        raise ValueError('Unexpected URL or existing request destination')
    cmd = ['curl', '--disable', '--silent', '--show-error', '--proto', '=https', '--max-time', str(timeout),
           '--max-filesize', str(limit), '--output', str(target), '--write-out', '%{http_code}\n%{url_effective}']
    if referer:
        cmd += ['--referer', referer]
    for key, value in (fields or {}).items():
        cmd += ['--data-urlencode', f'{key}={value}']
    result = subprocess.run([*cmd, url], capture_output=True, text=True)
    metadata = {'url': url, 'curl_exit': result.returncode, 'response': result.stdout,
                'stderr': result.stderr, 'redirect_policy': 'Reject all redirects; canonical HTTPS URLs only'}
    write_json(target.with_suffix(target.suffix + '.http.json'), metadata)
    if result.returncode or result.stdout != '200\n' + url or not target.exists() or not 0 < target.stat().st_size <= limit:
        raise ValueError(f'HTTP transfer failed: exit={result.returncode}, response={result.stdout!r}')


def acquire_month(output, month, config_hash):
    root = output / month
    if root.is_symlink():
        raise ValueError('Symlink month directory rejected')
    root.mkdir(exist_ok=True)
    record_path = root / 'completed.json'
    if record_path.exists():
        record = json.loads(record_path.read_text())
        if record['config_sha256'] != config_hash or record['month'] != month:
            raise ValueError('Resume config/month mismatch')
        attempt = root / record['attempt']
        if not re.fullmatch(r'attempt-[0-9]{3}', record['attempt']) or attempt.is_symlink():
            raise ValueError('Unsafe attempt path')
        required = {'form.html', 'form.html.http.json', 'raw.zip', 'raw.zip.http.json',
                    'ticks.csv', 'quarantine.jsonl', 'reserved.jsonl', 'audit.json'}
        if set(record['files']) != required or record.get('status') != 'completed':
            raise ValueError('Incomplete resume evidence')
        verify_files(attempt, record['files'])
        if json.loads((attempt / 'audit.json').read_text()) != record['audit']:
            raise ValueError('Resume audit mismatch')
        validate_zip(attempt / 'raw.zip', month)
        return record
    attempts = sorted(root.glob('attempt-*'))
    # Lifetime bound, including interrupted attempts. No silent network retry on resume.
    for index in range(len(attempts) + 1, 3):
        dest = root / f'attempt-{index:03}'
        dest.mkdir()
        url = f'{ORIGIN}/download-free-forex-historical-data/?/ascii/tick-data-quotes/eurusd/{month[:4]}/{int(month[4:])}'
        try:
            request(url, dest / 'form.html')
            fields = parse_form((dest / 'form.html').read_text(), month)
            request(ORIGIN + '/get.php', dest / 'raw.zip', referer=url, fields=fields, timeout=300, limit=MAX_ZIP)
            report = audit(dest / 'raw.zip', dest, month)
            write_json(dest / 'audit.json', report)
            if not report['valid_rows']:
                raise ValueError('No usable development quotes; raw archive preserved')
            files = {p.name: fingerprint(p) for p in dest.iterdir() if p.is_file()}
            record = {'status': 'completed', 'month': month, 'config_sha256': config_hash,
                      'attempt': dest.name, 'source_url': url, 'files': files, 'audit': report}
            write_json(record_path, record)
            return record
        except (ValueError, OSError, EOFError, BadZipFile) as exc:
            write_json(dest / 'failure.json', {'error_type': type(exc).__name__, 'error': str(exc), 'month': month})
    return {'status': 'failed', 'month': month, 'attempts': [str(p.relative_to(output)) for p in sorted(root.glob('attempt-*'))]}


def run(config_path, output, pilot=False):
    config = json.loads(config_path.read_text())
    if config != {'dataset': 'histdata_ticks_v1', 'symbol': 'EURUSD', 'months': MONTHS,
                  'source_timezone': 'UTC-05:00 fixed no DST', 'development_utc': ['2022-01-01', '2024-01-01'], 'max_attempts_per_month': 2}:
        raise ValueError('Only frozen development configuration supported')
    output.mkdir(parents=True, exist_ok=True)
    lock = output / '.acquisition.lock'
    with lock.open('x'):
        pass
    try:
        config_hash = fingerprint(config_path)['sha256']
        identity = output / 'identity.json'
        identity_data = {'config_sha256': config_hash, 'dataset': 'histdata_ticks_v1'}
        if identity.exists():
            if json.loads(identity.read_text()) != identity_data:
                raise ValueError('Dataset identity mismatch')
        elif list(output.iterdir()) != [lock]:
            raise ValueError('New acquisition directory must be empty')
        else:
            write_json(identity, identity_data)
        records = []
        for month in MONTHS:
            if pilot and month != MONTHS[0]:
                records.append({'status': 'pending', 'month': month})
                continue
            records.append(acquire_month(output, month, config_hash))
            print(month, records[-1]['status'], flush=True)
        manifest = {'dataset': config, 'config_sha256': config_hash, 'months': records,
                    'fits': 0, 'notes': 'Structural source audit only. No labels, models, economic performance or profit evidence.'}
        # Immutable run manifests; interrupted attempts are discoverable on resume.
        version = len(list(output.glob('manifest-*.json'))) + 1
        write_json(output / f'manifest-{version:03}.json', manifest)
        return manifest
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/histdata_ticks_v1.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pilot', action='store_true', help='Only fixed first month; other months remain pending')
    args = parser.parse_args()
    run(args.config, args.output, args.pilot)


if __name__ == '__main__':
    main()
