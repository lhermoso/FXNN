"""Fetch and normalize an annual HistData EURUSD M1 archive.

Source docs: https://www.histdata.com/f-a-q/
Download form workflow verified against live HTML and
https://github.com/philipperemy/FX-1-Minute-Data/blob/master/histdata/api.py
chub searches for HistData returned no entries.
"""
import argparse
import csv
import hashlib
import io
import json
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        name = attrs.get("name")
        if tag == "input" and name in ("tk", "date", "datemonth", "platform", "timeframe", "fxpair"):
            self.fields.setdefault(name, attrs.get("value", ""))


def utc_stamp(value):
    # Provider explicitly uses fixed EST, without daylight saving time.
    return datetime.strptime(value, "%Y%m%d %H%M%S").replace(
        tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc)


def normalize(archive, output, year):
    target = output / f"EURUSD_{year}_m1_bid_utc.csv"
    previous = first = last = None
    count = 0
    months = Counter()
    gaps = []
    low_price, high_price = None, None
    with ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError("Archive failed CRC check")
        member = f"DAT_ASCII_EURUSD_M1_{year}.csv"
        with z.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig") as source:
            timestamp_counts = Counter(row[0] for row in csv.reader(source, delimiter=";"))
        duplicates = {stamp for stamp, n in timestamp_counts.items() if n > 1}
        quarantined = []
        with z.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig") as source, target.with_suffix(".part").open("w", newline="") as dest:
            writer = csv.writer(dest)
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            for row in csv.reader(source, delimiter=";"):
                if len(row) != 6:
                    raise ValueError("Expected six CSV fields")
                if row[0] in duplicates:
                    # Exclude every occurrence: conflicting prices cannot be
                    # assigned a trustworthy time from this archive alone.
                    quarantined.append(row)
                    continue
                stamp = utc_stamp(row[0])
                if int(row[0][:4]) != year or stamp.second or stamp.microsecond:
                    raise ValueError("Wrong source year or non-minute timestamp")
                o, h, l, c, volume = map(Decimal, row[1:])
                if any(not value.is_finite() for value in (o,h,l,c,volume)) or not 0 < l <= min(o,c) <= max(o,c) <= h or volume < 0:
                    raise ValueError("Invalid OHLC/volume")
                if previous is not None:
                    if stamp <= previous:
                        raise ValueError("Duplicate or unsorted timestamp")
                    if stamp - previous > timedelta(minutes=1):
                        gaps.append({"previous": previous.isoformat(), "next": stamp.isoformat(),
                                     "missing_minutes": int((stamp-previous).total_seconds()/60)-1})
                first = first or stamp
                last = previous = stamp
                months[row[0][:6]] += 1
                low_price = l if low_price is None else min(low_price,l)
                high_price = h if high_price is None else max(high_price,h)
                writer.writerow([stamp.isoformat(), *row[1:]])
                count += 1
        if set(months) != {f"{year}{m:02}" for m in range(1,13)}:
            raise ValueError("Archive does not cover all twelve months")
        status_name = f"DAT_ASCII_EURUSD_M1_{year}.txt"
        if status_name in z.namelist():
            (output/f"EURUSD_{year}_provider_status.txt").write_bytes(z.read(status_name))
    target.with_suffix(".part").replace(target)
    quarantine_path = output/f"EURUSD_{year}_quarantine.csv"
    with quarantine_path.open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["source_timestamp_EST","open","high","low","close","volume"])
        writer.writerows(quarantined)
    gap_path = output/f"EURUSD_{year}_gaps.json"
    gap_path.write_text(json.dumps(gaps,indent=2)+"\n")
    report = {"source":"HistData.com", "source_url":f"https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/eurusd/{year}",
              "year_in_source_timezone":year,"symbol":"EURUSD","timeframe":"M1","price_side":"bid",
              "source_timezone":"UTC-05:00 fixed, no DST","output_timezone":"UTC","pip_size":"0.0001",
              "rows":count,"first_timestamp":str(first),"last_timestamp":str(last),
              "source_rows":sum(timestamp_counts.values()),"duplicate_timestamps":len(duplicates),
              "quarantined_rows":len(quarantined),"quarantine":str(quarantine_path),
              "months_source_timezone":dict(sorted(months.items())),"min_price":str(low_price),"max_price":str(high_price),
              "gaps":len(gaps),"max_missing_minutes":max((g['missing_minutes'] for g in gaps),default=0),
              "archive_sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
              "csv_sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"csv":str(target),
              "notes":"Bid only; no spread or actual traded volume. Gaps include market closures and possible missing data; unclassified, never filled. M1 cannot resolve intrabar TP/SL order."}
    (output/f"EURUSD_{year}_manifest.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year",type=int,default=2025)
    p.add_argument("--output",type=Path,default=Path("data/histdata/EURUSD"))
    args=p.parse_args()
    if not 2001 <= args.year < datetime.now(timezone.utc).year:
        p.error("Use a completed year >= 2001")
    args.output.mkdir(parents=True,exist_ok=True)
    archive=args.output/f"EURUSD_M1_{args.year}.zip"
    if not archive.exists():
        url=f"https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/eurusd/{args.year}"
        page=subprocess.run(["curl","-sS","-L","--fail","--max-time","30",url],capture_output=True,text=True,check=True).stdout
        form=DownloadForm(); form.feed(page)
        expected={"date":str(args.year),"datemonth":str(args.year),"platform":"ASCII","timeframe":"M1","fxpair":"EURUSD"}
        if not form.fields.get("tk") or any(form.fields.get(k)!=v for k,v in expected.items()):
            raise ValueError("Download form did not match requested archive")
        temp=archive.with_suffix(".part")
        cmd=["curl","-sS","-L","--fail","--max-time","90","-e",url,"-o",str(temp)]
        for key,value in form.fields.items():
            cmd.extend(["--data-urlencode",f"{key}={value}"])
        subprocess.run([*cmd,"https://www.histdata.com/get.php"],check=True)
        with ZipFile(temp) as z:
            if z.testzip() is not None: raise ValueError("Corrupt archive")
        temp.replace(archive)
    print(json.dumps(normalize(archive,args.output,args.year),indent=2))


if __name__ == "__main__":
    main()
