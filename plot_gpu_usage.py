#!/usr/bin/env python3
"""
Plot GPU memory usage over time from CSV logs.

Supports:
- CSV from gpu_watch.py with header:
  timestamp,gpu_index,pid,cmd,gpu_mem_mib,sm_util_pct,mem_util_pct
- Minimal CSV like gpu_watch.sh output with header:
  timestamp,used_mib

Usage examples:
  python3 plot_gpu_usage.py gpu_log.csv --output gpu_usage.png
  python3 plot_gpu_usage.py gpu_log.csv --per-gpu --output per_gpu.png
  python3 plot_gpu_usage.py mem_only.csv --output mem_only.png
  python3 plot_gpu_usage.py gpu_log.csv --show
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple


def parse_time(ts: str) -> datetime:
    # Prefer ISO8601 parsing; Python 3.7+ supports offsets
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        # Fallbacks: try common formats without timezone
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(ts, fmt)
            except Exception:
                pass
        raise


def load_series_from_gpu_watch(path: str, per_gpu: bool) -> Dict[str, List[Tuple[datetime, float]]]:
    """Return mapping name -> [(time, value MiB)]"""
    by_ts_total: Dict[str, float] = defaultdict(float)  # ts -> total MiB
    by_ts_gpu: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))  # ts -> gpu -> MiB

    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            ts = row.get("timestamp")
            if not ts:
                continue
            mem = row.get("gpu_mem_mib")
            if mem is None or mem == "":
                continue
            try:
                mem_val = float(mem)
            except ValueError:
                continue
            by_ts_total[ts] += mem_val
            gpu = (row.get("gpu_index") or "").strip()
            if gpu:
                by_ts_gpu[ts][gpu] += mem_val

    if per_gpu:
        # Build series per GPU index
        series: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        # Collect all unique GPUs seen
        all_gpus = set()
        for ts, gpu_map in by_ts_gpu.items():
            all_gpus.update(gpu_map.keys())
        # Sorted timestamps
        times_sorted = sorted(by_ts_total.keys(), key=parse_time)
        for gpu in sorted(all_gpus, key=lambda x: (x == "", x)):
            for ts in times_sorted:
                val = by_ts_gpu.get(ts, {}).get(gpu, 0.0)
                series[f"GPU {gpu}"] .append((parse_time(ts), val))
        return series
    else:
        times_sorted = sorted(by_ts_total.keys(), key=parse_time)
        return {"Total": [(parse_time(ts), by_ts_total[ts]) for ts in times_sorted]}


def load_series_from_mem_only(path: str) -> Dict[str, List[Tuple[datetime, float]]]:
    series: List[Tuple[datetime, float]] = []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            ts = row.get("timestamp")
            used = row.get("used_mib")
            if not ts or used is None or used == "":
                continue
            try:
                series.append((parse_time(ts), float(used)))
            except Exception:
                continue
    series.sort(key=lambda x: x[0])
    return {"Total": series}


def auto_loader(path: str, per_gpu: bool) -> Dict[str, List[Tuple[datetime, float]]]:
    # Peek header to decide
    with open(path, newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return {"Total": []}
    header_lc = [h.strip().lower() for h in header]
    if "gpu_mem_mib" in header_lc:
        return load_series_from_gpu_watch(path, per_gpu)
    if "used_mib" in header_lc:
        return load_series_from_mem_only(path)
    raise ValueError("Unrecognized CSV header. Expected gpu_mem_mib or used_mib column.")


def do_plot(series_map: Dict[str, List[Tuple[datetime, float]]], title: str, output: str = None, show: bool = False):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except Exception as e:
        print("matplotlib not available: {}".format(e), file=sys.stderr)
        sys.exit(2)

    fig, ax = plt.subplots(figsize=(10, 5))
    any_points = False
    for name, series in series_map.items():
        if not series:
            continue
        any_points = True
        xs = [t for t, _ in series]
        ys = [v for _, v in series]
        ax.plot(xs, ys, label=name, linewidth=1.8)

    if not any_points:
        print("No data points to plot.", file=sys.stderr)
        sys.exit(1)

    ax.set_title(title)
    ax.set_xlabel("Time")
    ax.set_ylabel("GPU Memory (MiB)")

    # Time axis formatting
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()

    if len(series_map) > 1:
        ax.legend(loc="best")

    ax.grid(True, linestyle=":", alpha=0.4)
    fig.tight_layout()

    if output:
        plt.savefig(output, dpi=150)
        print(f"Saved plot to {output}")
    if show or not output:
        # If no output specified, show interactively
        plt.show()


def main():
    ap = argparse.ArgumentParser(description="Plot GPU memory usage over time from CSV.")
    ap.add_argument("csv", help="Path to CSV file from gpu_watch.py or mem_only.csv")
    ap.add_argument("--per-gpu", action="store_true", help="Plot separate lines for each GPU index (gpu_watch.csv only)")
    ap.add_argument("--output", "-o", help="Output image path (e.g., plot.png). If omitted, shows interactively.")
    ap.add_argument("--show", action="store_true", help="Force showing the plot window")
    args = ap.parse_args()

    path = os.path.expanduser(args.csv)
    if not os.path.exists(path):
        print(f"CSV not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        series_map = auto_loader(path, args.per_gpu)
    except Exception as e:
        print(f"Failed to read CSV: {e}", file=sys.stderr)
        sys.exit(1)

    title = "GPU Memory Usage" + (" (per GPU)" if args.per_gpu else "")
    do_plot(series_map, title=title, output=args.output, show=args.show)


if __name__ == "__main__":
    main()

