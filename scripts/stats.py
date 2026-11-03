"""Lightweight CSV research utilities without external dependencies."""
import argparse
import csv
import math
from pathlib import Path
from .pipeline import ROOT

def series(path, asset, days=90):
    with Path(path).open(newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    rows = [r for r in rows if r.get("asset_key") == asset and r.get("status") == "ok"]
    rows.sort(key=lambda r: r["report_date"])
    return {r["report_date"]: float(r["value"]) for r in rows[-days:] if r.get("value")}

def pearson(a, b):
    if len(a) != len(b) or len(a) < 3:
        return None
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    da = [x - ma for x in a]
    db = [x - mb for x in b]
    denominator = math.sqrt(sum(x*x for x in da)*sum(y*y for y in db))
    return sum(x*y for x, y in zip(da, db)) / denominator if denominator else None

def daily_returns(values):
    dates = sorted(values)
    return {b: (values[b]/values[a] - 1)*100 for a, b in zip(dates, dates[1:]) if values[a]}

def main():
    parser = argparse.ArgumentParser(description="Research daily snapshot series (not returns by exchange close)")
    parser.add_argument("--asset", required=True)
    parser.add_argument("--compare")
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    if args.days < 2:
        parser.error("--days must be >= 2")
    csv_path = ROOT / "data/history/quotes.csv"
    a = series(csv_path, args.asset, args.days)
    ret_a = daily_returns(a)
    print(f"{args.asset}: {len(a)} dated snapshots, {len(ret_a)} changes")
    if a:
        print(f"Latest {max(a)}: {a[max(a)]:.6f}")
    if args.compare:
        b = series(csv_path, args.compare, args.days)
        ret_b = daily_returns(b)
        both = sorted(set(ret_a) & set(ret_b))
        corr = pearson([ret_a[d] for d in both], [ret_b[d] for d in both])
        print(f"{args.asset} x {args.compare}: matched N={len(both)}, Pearson={corr if corr is not None else 'N/A'}")
        print("Caution: calendar-report alignment only; markets have different close times; correlation does not imply causation.")

if __name__ == "__main__":
    main()
