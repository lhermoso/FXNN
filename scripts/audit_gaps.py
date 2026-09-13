"""Triage HistData gaps without labels or an assumed provider calendar.

Saturday 00:00 through Sunday 20:00 UTC is only a weekend candidate window.
It is deliberately narrower than typical FX closures. Other missing minutes
remain unresolved; neither bucket authorizes gap filling or uncensoring trades.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


def category(stamp, quarantined):
    if stamp in quarantined:
        return "quarantined"
    if stamp.weekday() == 5 or (stamp.weekday() == 6 and stamp.hour < 20):
        return "weekend_candidate"
    return "unresolved"


def audit(root, year):
    gaps_path = root / f"EURUSD_{year}_gaps.json"
    quarantine_path = root / f"EURUSD_{year}_quarantine.csv"
    manifest_path = root / f"EURUSD_{year}_manifest.json"
    source_zone = timezone(timedelta(hours=-5))
    with quarantine_path.open() as stream:
        quarantined = {
            datetime.strptime(r["source_timestamp_EST"], "%Y%m%d %H%M%S")
            .replace(tzinfo=source_zone).astimezone(timezone.utc)
            for r in csv.DictReader(stream)
        }
    totals, monthly, records = Counter(), {}, []
    for gap in json.loads(gaps_path.read_text()):
        start = datetime.fromisoformat(gap["previous"]) + timedelta(minutes=1)
        end = datetime.fromisoformat(gap["next"])
        counts = Counter()
        current = start
        while current < end:
            kind = category(current, quarantined)
            counts[kind] += 1
            # Match the annual manifest's source-timezone month convention.
            month = current.astimezone(source_zone).strftime("%Y-%m")
            monthly.setdefault(month, Counter())[kind] += 1
            current += timedelta(minutes=1)
        if sum(counts.values()) != gap["missing_minutes"]:
            raise ValueError("Gap minute count mismatch")
        totals.update(counts)
        records.append({**gap, "minute_categories": dict(counts)})
    return {
        "year": year,
        "input_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (gaps_path, quarantine_path, manifest_path)},
        "missing_minutes": dict(totals),
        "monthly_source_timezone": monthly,
        "gaps": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/histdata/EURUSD"))
    parser.add_argument("--years", nargs="+", type=int, default=[2022, 2023, 2024, 2025])
    parser.add_argument("--output", type=Path, default=Path("output/gap_triage_v1.json"))
    args = parser.parse_args()
    results = [audit(args.root, y) for y in args.years]
    report = {
        "status": "triage_only_not_provider_calendar",
        "notes": "Internal gaps only; excludes unobserved annual edges. Weekend candidates are not confirmed closures. Unresolved includes holidays, session edges and coverage failures. No filling or label changes.",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "years": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps([{k: r[k] for k in ("year", "missing_minutes", "monthly_source_timezone")}
                      for r in results], indent=2))


if __name__ == "__main__":
    main()
