#!/usr/bin/env python3
"""
Plot GPU, system memory, and optional CPU% usage over time from CSV logs.

Supports:
- CSV from gpu_watch.py with header:
  timestamp,gpu_index,pid,cmd,gpu_mem_mib,sm_util_pct,mem_util_pct
- Minimal CSV like gpu_watch.sh output with headers:
  timestamp,used_mib[,sys_used_mib][,cpu_cores][,cpu_pct]

Usage examples:
  python3 plot_gpu_usage.py gpu_log.csv --output gpu_usage.png
  python3 plot_gpu_usage.py gpu_log.csv --per-gpu --output per_gpu.png
  python3 plot_gpu_usage.py mem_only.csv --cpu --output mem_mem_cpu.png
  python3 plot_gpu_usage.py gpu_log.csv --show
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple, Optional


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


def load_series_from_gpu_watch(path: str, per_gpu: bool) -> Tuple[
    Dict[str, List[Tuple[datetime, float]]],  # gpu
    Dict[str, List[Tuple[datetime, float]]],  # ram (none here)
    Dict[str, List[Tuple[datetime, float]]],  # cpu (none here)
]:
    """Return (gpu_series_map, ram_series_map, cpu_series_map). Only GPU is populated for this format."""
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
        return series, {}, {}
    else:
        times_sorted = sorted(by_ts_total.keys(), key=parse_time)
        return {"Total": [(parse_time(ts), by_ts_total[ts]) for ts in times_sorted]}, {}, {}


def load_series_from_mem_only(path: str) -> Tuple[
    Dict[str, List[Tuple[datetime, float]]],  # gpu
    Dict[str, List[Tuple[datetime, float]]],  # ram
    Dict[str, List[Tuple[datetime, float]]],  # cpu
]:
    gpu_series: List[Tuple[datetime, float]] = []
    ram_series: List[Tuple[datetime, float]] = []
    cpu_series: List[Tuple[datetime, float]] = []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            ts = row.get("timestamp")
            used = row.get("used_mib")
            sys_used = row.get("sys_used_mib")
            if ts and used not in (None, ""):
                try:
                    gpu_series.append((parse_time(ts), float(used)))
                except Exception:
                    pass
            if ts and sys_used not in (None, ""):
                try:
                    ram_series.append((parse_time(ts), float(sys_used)))
                except Exception:
                    pass
            cpu_pct = row.get("cpu_pct")
            if ts and cpu_pct not in (None, ""):
                try:
                    cpu_series.append((parse_time(ts), float(cpu_pct)))
                except Exception:
                    pass
    gpu_series.sort(key=lambda x: x[0])
    ram_series.sort(key=lambda x: x[0])
    cpu_series.sort(key=lambda x: x[0])
    return {"Total": gpu_series}, ({"System": ram_series} if ram_series else {}), ({"CPU %": cpu_series} if cpu_series else {})


def auto_loader(path: str, per_gpu: bool) -> Tuple[
    Dict[str, List[Tuple[datetime, float]]],
    Dict[str, List[Tuple[datetime, float]]],
    Dict[str, List[Tuple[datetime, float]]],
]:
    # Peek header to decide
    with open(path, newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return {"Total": []}, {}, {}
    header_lc = [h.strip().lower() for h in header]
    if "gpu_mem_mib" in header_lc:
        return load_series_from_gpu_watch(path, per_gpu)
    if "used_mib" in header_lc:
        return load_series_from_mem_only(path)
    raise ValueError("Unrecognized CSV header. Expected gpu_mem_mib or used_mib column.")


def do_plot(
    gpu_series_map: Dict[str, List[Tuple[datetime, float]]],
    ram_series_map: Optional[Dict[str, List[Tuple[datetime, float]]]] = None,
    cpu_series_map: Optional[Dict[str, List[Tuple[datetime, float]]]] = None,
    title_gpu: str = "GPU Memory Usage",
    title_ram: str = "System Memory Usage",
    title_cpu: str = "CPU Usage (%)",
    output: str = None,
    show: bool = False,
    plot_cpu: bool = False,
):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except Exception as e:
        print("matplotlib not available: {}".format(e), file=sys.stderr)
        sys.exit(2)

    # Determine rows: 2 (GPU, RAM) or 3 if CPU requested (and we will show even if empty with a placeholder)
    nrows = 3 if plot_cpu else 2
    fig_axes = plt.subplots(nrows, 1, sharex=True, figsize=(11, 9) if plot_cpu else (11, 7))
    if plot_cpu:
        fig, (ax1, ax2, ax3) = fig_axes
    else:
        fig, (ax1, ax2) = fig_axes
    any_points = False
    # Top subplot: GPU memory
    for name, series in gpu_series_map.items():
        if not series:
            continue
        any_points = True
        xs = [t for t, _ in series]
        ys = [v for _, v in series]
        ax1.plot(xs, ys, label=name, linewidth=1.8)

    if not any_points:
        print("No data points to plot.", file=sys.stderr)
        sys.exit(1)

    ax1.set_title(title_gpu)
    ax1.set_ylabel("GPU Memory (MiB)")

    # Time axis formatting
    ax2.set_xlabel("Time")
    # Time axis formatting on the shared x-axis
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()  # rotates tick labels

    if len(gpu_series_map) > 1:
        ax1.legend(loc="best")

    ax1.grid(True, linestyle=":", alpha=0.4)

    # Bottom subplot: System RAM usage (if available)
    has_ram = False
    if ram_series_map:
        for name, series in ram_series_map.items():
            if not series:
                continue
            has_ram = True
            xs = [t for t, _ in series]
            ys = [v for _, v in series]
            ax2.plot(xs, ys, label=name, color="#cc5500", linewidth=1.8)
    if has_ram:
        ax2.set_title(title_ram)
        ax2.set_ylabel("System Memory (MiB)")
        if len(ram_series_map) > 1:
            ax2.legend(loc="best")
    else:
        ax2.set_title("System Memory Usage (no data)")
        ax2.set_ylabel("System Memory (MiB)")
        ax2.text(0.5, 0.5, "No system memory data", transform=ax2.transAxes,
                 ha="center", va="center", color="gray")
    ax2.grid(True, linestyle=":", alpha=0.4)

    # Optional third subplot: CPU percent
    if plot_cpu:
        has_cpu = False
        if cpu_series_map:
            for name, series in cpu_series_map.items():
                if not series:
                    continue
                has_cpu = True
                xs = [t for t, _ in series]
                ys = [v for _, v in series]
                ax3.plot(xs, ys, label=name, color="#2a9d8f", linewidth=1.8)
        if has_cpu:
            ax3.set_title(title_cpu)
            ax3.set_ylabel("CPU (%)")
            if len(cpu_series_map) > 1:
                ax3.legend(loc="best")
        else:
            ax3.set_title("CPU Usage (%) (no data)")
            ax3.set_ylabel("CPU (%)")
            ax3.text(0.5, 0.5, "No CPU data", transform=ax3.transAxes,
                     ha="center", va="center", color="gray")
        ax3.grid(True, linestyle=":", alpha=0.4)
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
    ap.add_argument("--cpu", action="store_true", help="Add third subplot with CPU usage percent (if column cpu_pct exists)")
    ap.add_argument("--show", action="store_true", help="Force showing the plot window")
    args = ap.parse_args()

    path = os.path.expanduser(args.csv)
    if not os.path.exists(path):
        print(f"CSV not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        gpu_map, ram_map, cpu_map = auto_loader(path, args.per_gpu)
    except Exception as e:
        print(f"Failed to read CSV: {e}", file=sys.stderr)
        sys.exit(1)

    title_gpu = "GPU Memory Usage" + (" (per GPU)" if args.per_gpu else "")
    do_plot(gpu_map, ram_map, cpu_map, title_gpu=title_gpu, title_ram="System Memory Usage",
            title_cpu="CPU Usage (%)", output=args.output, show=args.show, plot_cpu=args.cpu)


if __name__ == "__main__":
    main()
