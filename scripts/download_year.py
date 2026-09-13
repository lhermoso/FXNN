"""EURUSD daily M1 BI5 download, resumable with per-file audit.

BI5: big-endian seconds/open/close/low/high/volume, 24 bytes.
Reference: https://github.com/Nosvemos/dukascopy-go/blob/main/pkg/dukascopy/bi5.go
chub Dukascopy search returned no documentation; source and live probe checked.
"""
import argparse
import csv
import hashlib
import json
import lzma
import math
import struct
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = "https://datafeed.dukascopy.com/datafeed/EURUSD"


def decode(data):
    raw = lzma.decompress(data) if data else b""
    if len(raw) % 24:
        raise ValueError("Truncated M1 payload")
    result = {}
    previous = -1
    for sec, o, c, l, h, vol in struct.iter_unpack(">IIIIIf", raw):
        if not previous < sec < 86400 or sec % 60:
            raise ValueError("Invalid or duplicate minute offset")
        if not 0 < l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Invalid OHLC")
        if not math.isfinite(vol) or vol < 0:
            raise ValueError("Invalid volume")
        result[sec] = (o, h, l, c, vol)
        previous = sec
    return result


def fetch(day, side, root):
    key = f"{day.year}/{day.month-1:02}/{day.day:02}/{side}_candles_min_1.bi5"
    path = root / "raw_m1" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"day": day.date().isoformat(), "side": side, "key": key}
    try:
        if not path.exists():
            temp = path.with_suffix(".part")
            res = subprocess.run(["curl", "-sS", "--connect-timeout", "8", "--max-time", "25",
                                  "-o", str(temp), "-w", "%{http_code}", f"{ROOT}/{key}"],
                                 capture_output=True, text=True)
            if res.returncode or res.stdout != "200":
                return {**record, "status": "error", "http": res.stdout, "detail": res.stderr.strip()}
            decode(temp.read_bytes())
            temp.replace(path)
        payload = path.read_bytes()
        bars = decode(payload)
        return {**record, "status": "ok" if bars else "empty", "bars": len(bars),
                "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    except (ValueError, OSError, lzma.LZMAError) as exc:
        return {**record, "status": "error", "detail": str(exc)}


def export(records, root, year):
    path = root / f"EURUSD_{year}_m1_bid_ask.csv"
    days = sorted({r["day"] for r in records})
    lookup = {(r["day"], r["side"]): r for r in records}
    count = 0
    daily = []
    with path.with_suffix(".part").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "bid_open", "bid_high", "bid_low", "bid_close",
                         "ask_open", "ask_high", "ask_low", "ask_close", "bid_volume", "ask_volume"])
        for day in days:
            recs = [lookup[(day, s)] for s in ("BID", "ASK")]
            if any(r["status"] == "error" for r in recs):
                daily.append({"day": day, "status": "download_error"})
                continue
            bid, ask = [decode((root / "raw_m1" / r["key"]).read_bytes()) for r in recs]
            if bid.keys() != ask.keys():
                daily.append({"day": day, "status": "unmatched_sides", "bid_only": sorted(bid.keys()-ask.keys()), "ask_only": sorted(ask.keys()-bid.keys())})
                continue
            start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
            for second in bid:
                b, a = bid[second], ask[second]
                # Extremes need not occur at the same tick; do not derive
                # intraminute spreads from independent bid/ask highs/lows.
                writer.writerow([(start+timedelta(seconds=second)).isoformat(),
                                 *(f"{v/100000:.5f}" for v in (*b[:4], *a[:4])), b[4], a[4]])
            count += len(bid)
            daily.append({"day": day, "status": "ok" if bid else "empty", "bars": len(bid),
                          "zero_volume_bars": sum(bid[s][4] == 0 and ask[s][4] == 0 for s in bid)})
    path.with_suffix(".part").replace(path)
    return {"csv": str(path), "bars": count, "daily_coverage": daily,
            "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, default=2025)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--passes", type=int, default=3)
    p.add_argument("--output", type=Path, default=Path("data/dukascopy/EURUSD"))
    args = p.parse_args()
    if not 2004 <= args.year < datetime.now(timezone.utc).year or not 1 <= args.workers <= 8 or not 1 <= args.passes <= 5:
        p.error("Use a completed year >= 2004, workers 1..8 and passes 1..5")
    start = datetime(args.year,1,1,tzinfo=timezone.utc)
    end = start.replace(year=args.year+1)
    jobs = [(start+timedelta(days=i), s) for i in range((end-start).days) for s in ("BID", "ASK")]
    args.output.mkdir(parents=True, exist_ok=True)
    records = {}
    journal = args.output / f"EURUSD_{args.year}_download.jsonl"
    for attempt in range(args.passes):
        todo = [(d,s) for d,s in jobs if records.get((d.date().isoformat(),s),{}).get("status") not in ("ok","empty")]
        if not todo:
            break
        with journal.open("a") as log, ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(fetch,d,s,args.output) for d,s in todo]
            for i, future in enumerate(as_completed(futures),1):
                record = future.result()
                records[(record["day"],record["side"])] = record
                log.write(json.dumps({**record,"pass":attempt+1})+"\n")
                log.flush()
                if i % 50 == 0 or i == len(todo):
                    print(f"Pass {attempt+1}: {i}/{len(todo)}; {dict(Counter(r['status'] for r in records.values()))}",flush=True)
    ordered = sorted(records.values(),key=lambda r:(r["day"],r["side"]))
    report = {"year":args.year,"symbol":"EURUSD","source":ROOT,"price_scale":100000,"pip_size":"0.0001",
              "files":dict(Counter(r["status"] for r in ordered)),"records":ordered,
              "notes":"Provider M1 bars; zero-volume candles retained and counted. No local gap filling. Intrabar TP/SL order remains ambiguous. Empty files are not proof of scheduled closure."}
    report.update(export(ordered,args.output,args.year))
    report["all_files_fetched"] = all(r["status"] in ("ok","empty") for r in ordered)
    (args.output/f"EURUSD_{args.year}_manifest.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k not in ("records","daily_coverage")},indent=2),flush=True)
    if not report["all_files_fetched"] or any(d["status"] == "unmatched_sides" for d in report["daily_coverage"]):
        raise SystemExit("Coverage unresolved; inspect manifest and rerun")


if __name__ == "__main__":
    main()
