"""Download EUR/USD hourly BI5 files; retain raw data and export ticks + M1.

References: https://www.dukascopy.com/wiki/en/development/data-export/
Hourly feed uses milliseconds since hour start, not daily S3 layout.
"""
import argparse
import csv
import gzip
import hashlib
import json
import lzma
import math
import struct
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = "https://datafeed.dukascopy.com/datafeed/EURUSD"


def decode(payload):
    raw = lzma.decompress(payload) if payload else b""
    if len(raw) % 20:
        raise ValueError("BI5 payload is not a multiple of 20 bytes")
    previous = -1
    for ms, ask, bid, av, bv in struct.iter_unpack(">IIIff", raw):
        if not previous <= ms < 3_600_000 or not 0 < bid <= ask:
            raise ValueError("Invalid timestamp or bid/ask")
        if any(not math.isfinite(v) or v < 0 for v in (av, bv)):
            raise ValueError("Invalid quote volume")
        previous = ms
        yield ms, ask, bid, av, bv


def fetch(hour, destination):
    key = f"{hour.year}/{hour.month - 1:02}/{hour.day:02}/{hour.hour:02}h_ticks.bi5"
    path = destination / "raw" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    error = ""
    for attempt in range(3):
        try:
            if not path.exists():
                temp = path.with_suffix(".part")
                response = subprocess.run(
                    ["curl", "-sS", "--connect-timeout", "10", "--max-time", "35",
                     "-w", "%{http_code}", "-o", str(temp), f"{ROOT}/{key}"],
                    capture_output=True, text=True)
                if response.returncode == 0 and response.stdout == "404":
                    temp.unlink(missing_ok=True)
                    return {"hour": hour.isoformat(), "status": "unavailable", "key": key}
                if response.returncode or response.stdout != "200":
                    raise ValueError(f"HTTP {response.stdout}: {response.stderr.strip()}")
                # Check before committing to cache.
                list(decode(temp.read_bytes()))
                temp.replace(path)
            payload = path.read_bytes()
            count = sum(1 for _ in decode(payload))
            return {"hour": hour.isoformat(), "status": "ok" if count else "empty",
                    "ticks": count, "bytes": len(payload), "key": key,
                    "sha256": hashlib.sha256(payload).hexdigest()}
        except (ValueError, lzma.LZMAError, OSError) as exc:
            error = str(exc)
            if attempt < 2:
                time.sleep(attempt + 1)
    return {"hour": hour.isoformat(), "status": "error", "key": key, "error": error}


def export(records, destination, prefix):
    tick_path = destination / f"{prefix}_ticks.csv.gz"
    bars_path = destination / f"{prefix}_m1_bid_ask.csv"
    first = last = None
    total = bars = 0
    max_spread = 0
    spread_sum = 0
    def price(value):
        return f"{value / 100000:.5f}"
    with gzip.open(tick_path.with_suffix(".part"), "wt", newline="") as ticks, bars_path.with_suffix(".part").open("w", newline="") as candles:
        tw, bw = csv.writer(ticks), csv.writer(candles)
        tw.writerow(["timestamp", "bid", "ask", "bid_volume", "ask_volume"])
        bw.writerow(["timestamp", "bid_open", "bid_high", "bid_low", "bid_close",
                     "ask_open", "ask_high", "ask_low", "ask_close", "tick_count"])
        minute, values = None, None
        for record in records:
            if record["status"] not in ("ok", "empty"):
                continue
            hour = datetime.fromisoformat(record["hour"])
            for ms, ask, bid, av, bv in decode((destination / "raw" / record["key"]).read_bytes()):
                stamp = hour + timedelta(milliseconds=ms)
                first = first or stamp
                last = stamp
                total += 1
                spread_sum += ask - bid
                max_spread = max(max_spread, ask - bid)
                tw.writerow([stamp.isoformat(timespec="milliseconds"), price(bid), price(ask), f"{bv:.6g}", f"{av:.6g}"])
                current = stamp.replace(second=0, microsecond=0)
                if current != minute:
                    if values is not None:
                        bw.writerow([minute.isoformat(), *map(price, values[:8]), values[8]])
                        bars += 1
                    minute, values = current, [bid] * 4 + [ask] * 4 + [0]
                values[1], values[2], values[3] = max(values[1], bid), min(values[2], bid), bid
                values[5], values[6], values[7] = max(values[5], ask), min(values[6], ask), ask
                values[8] += 1
        if values is not None:
            bw.writerow([minute.isoformat(), *map(price, values[:8]), values[8]])
            bars += 1
    tick_path.with_suffix(".part").replace(tick_path)
    bars_path.with_suffix(".part").replace(bars_path)
    return {"ticks": total, "m1_bars": bars, "first_tick": first, "last_tick": last,
            "mean_spread_pips": spread_sum / total / 10 if total else None,
            "max_spread_pips": max_spread / 10, "files": [str(tick_path), str(bars_path)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD, inclusive UTC")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD, exclusive UTC")
    parser.add_argument("--output", type=Path, default=Path("data/dukascopy/EURUSD"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end <= start or not 1 <= args.workers <= 8:
        parser.error("End must follow start; workers must be 1..8")
    hours = [start + timedelta(hours=i) for i in range(int((end-start).total_seconds() // 3600))]
    args.output.mkdir(parents=True, exist_ok=True)
    prefix = f"EURUSD_{args.start}_{args.end}"
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, record in enumerate(pool.map(lambda h: fetch(h, args.output), hours), 1):
            records.append(record)
            if i % 24 == 0 or i == len(hours):
                print(f"{i}/{len(hours)} hours: {dict(Counter(r['status'] for r in records))}", flush=True)
    manifest = {"source": ROOT, "symbol": "EURUSD", "start_inclusive": start,
                "end_exclusive": end, "generated_at": datetime.now(timezone.utc),
                "pip_size": "0.0001", "price_scale": 100000,
                "hours": dict(Counter(r["status"] for r in records)), "records": records,
                "notes": "Empty/404 hours are not automatically classified as market closure. No gap filling. Quote volume is not traded volume."}
    manifest.update(export(records, args.output, prefix))
    (args.output / f"{prefix}_manifest.json").write_text(json.dumps(manifest, default=str, indent=2) + "\n")
    print(json.dumps({k:v for k,v in manifest.items() if k != "records"}, default=str, indent=2))
    if any(r["status"] == "error" for r in records):
        raise SystemExit("Incomplete download: see manifest; rerun to retry failed hours")


if __name__ == "__main__":
    main()
