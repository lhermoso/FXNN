import argparse
import csv
import json
import hashlib
import random
import time
from collections import Counter
from dataclasses import asdict, fields
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .labeling import Candle, Config, Trade, label_trades, label_trades_reference, select_non_overlapping


def main():
    parser = argparse.ArgumentParser(description="Label historical Forex OHLC and select non-overlapping winners")
    parser.add_argument("input", type=Path)
    parser.add_argument("--pip-size", type=Decimal, required=True)
    parser.add_argument("--bar-minutes", type=int, required=True)
    parser.add_argument("--tp", type=Decimal, default=Decimal(50))
    parser.add_argument("--sl", type=Decimal, default=Decimal(20))
    parser.add_argument("--max-hours", type=int, default=72)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--verify-samples", type=int, default=0,
                        help="Compare both directions at N seeded random entries against slow reference")
    args = parser.parse_args()
    started = time.perf_counter()
    if args.verify_samples < 0:
        parser.error("Verification sample count must be non-negative")
    try:
        config = Config(args.pip_size, args.tp, args.sl, timedelta(hours=args.max_hours),
                        timedelta(minutes=args.bar_minutes))
        with args.input.open(newline="") as stream:
            candles = [Candle(datetime.fromisoformat(row["timestamp"]),
                              *(Decimal(row[key]) for key in ("open", "high", "low", "close")))
                       for row in csv.DictReader(stream)]
        if not candles:
            raise ValueError("Input contains no candles")
        trades = label_trades(candles, config)
        labeled_at = time.perf_counter()
        verified = min(args.verify_samples, len(candles))
        if verified:
            indices = sorted(random.Random(0).sample(range(len(candles)), verified))
            reference = label_trades_reference(candles, config, indices)
            for expected in reference:
                actual = trades[2*expected.entry_index + (expected.side == "short")]
                if actual != expected:
                    raise ValueError(f"Reference mismatch at entry {expected.entry_index}, {expected.side}")
        selected = select_non_overlapping(trades)
    except (ValueError, ArithmeticError, KeyError, OSError) as exc:
        parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=True)
    resolved = [t for t in trades if t.outcome in ("take_profit", "stop_loss", "timeout")]
    hard_negatives = [t for t in resolved if t.outcome == "stop_loss" and t.post_stop_target_status == "reached"]
    for filename, rows in (("all_trades.csv", resolved), ("selected_trades.csv", selected),
                           ("hard_negatives.csv", hard_negatives)):
        with (args.output / filename).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[field.name for field in fields(Trade)]+["label"])
            writer.writeheader()
            names = [field.name for field in fields(Trade)]
            writer.writerows({**{name: getattr(row, name) for name in names},
                              "label": int(row.outcome == "take_profit")} for row in rows)
    summary = {"config": asdict(config), "candles": len(candles), "outcomes": dict(Counter(t.outcome for t in trades)),
               "selected": len(selected), "selected_gross_pips": sum((t.pnl_pips for t in selected), Decimal(0)),
               "hard_negatives": len(hard_negatives),
               "usable_labels": len(resolved),
               "discarded_outcomes": dict(Counter(t.outcome for t in trades if t.outcome not in ("take_profit", "stop_loss", "timeout"))),
               "post_stop_target_outcomes": dict(Counter(t.post_stop_target_status for t in trades if t.outcome == "stop_loss")),
               "objective": "maximum gross pips; tie: minimum total exposure",
               "price_model": "single OHLC stream; no spread, commission or intrabar slippage",
               "input": str(args.input.resolve()), "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
               "first_candle": candles[0].timestamp, "last_candle": candles[-1].timestamp,
               "engine": "range min/max index O(N log N)",
               "verified_entries": verified, "verified_trade_labels": 2*verified, "verification_seed": 0,
               "load_and_label_seconds": round(labeled_at-started,3),
               "total_seconds": round(time.perf_counter()-started,3),
               "gap_policy": "censor pending trades at any missing candle, including market closures",
               "interpretation": "Retrospective oracle labels, not predicted or executable returns"}
    report = json.dumps(summary, default=str, indent=2)
    (args.output / "summary.json").write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
