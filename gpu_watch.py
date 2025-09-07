#!/usr/bin/env python3
"""
gpu_watch.py — Sample per-process GPU usage periodically and save to CSV.

Features:
- Target by --pid or by command substring/regex via --match
- Collects per-process GPU memory (MiB) and estimated SM/mem utilization (%) via `nvidia-smi pmon`
- Works without extra Python deps (uses subprocess)
- Appends to CSV every --interval seconds until Ctrl+C
- CSV columns: timestamp,gpu_index,pid,cmd,gpu_mem_mib,sm_util_pct,mem_util_pct

Examples:
  python3 gpu_watch.py --match python --interval 30 --output ~/gpu_log.csv
  python3 gpu_watch.py --pid 1622588 --interval 10 --output ./log.csv
"""
import argparse
import csv
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Tuple, Optional

def run_cmd(cmd: List[str], timeout: float = 5.0) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout, text=True)
        return out
    except Exception:
        return ""

def get_uuid_to_index() -> Dict[str, str]:
    # Map GPU UUID -> index
    out = run_cmd(["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"])
    mapping = {}
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2:
            idx, uuid = parts
            mapping[uuid] = idx
    return mapping

def get_process_memory_rows() -> List[Tuple[str, str, str]]:
    """
    Returns list of (pid, gpu_uuid, used_mib) for compute apps.
    """
    # Some nvidia-smi versions support process_name in query, but we only need pid+uuid+mem
    out = run_cmd(["nvidia-smi",
                   "--query-compute-apps=pid,gpu_uuid,used_memory",
                   "--format=csv,noheader,nounits"])
    rows = []
    for line in out.strip().splitlines():
        # Format: "<pid>, <gpu_uuid>, <used_memory_MiB>"
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            pid, uuid, used = parts[:3]
            # Clean used (strip non-digits if any linger)
            used_num = "".join(ch for ch in used if ch.isdigit())
            rows.append((pid, uuid, used_num or "0"))
    return rows

def get_pmon_snapshot() -> List[Dict[str, str]]:
    """
    Returns a list of dict with keys: gpu, pid, sm, mem, cmd
    Using: nvidia-smi pmon -c 1 -s um  (one-shot sample)
    """
    out = run_cmd(["nvidia-smi", "pmon", "-c", "1", "-s", "um"], timeout=7.0)
    result = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Expected columns: gpu pid type sm mem enc dec command
        parts = line.split()
        if len(parts) < 8:
            continue
        gpu = parts[0]
        pid = parts[1]
        # parts[2] = type (C/G/...) not used here
        sm = parts[3]
        mem = parts[4]
        # parts[5] enc, parts[6] dec
        cmd = " ".join(parts[7:])
        if pid == "-" or not pid.isdigit():
            continue
        def parse_pct(x: str) -> Optional[int]:
            try:
                return int(x)
            except Exception:
                return None
        result.append({
            "gpu": gpu,
            "pid": pid,
            "sm": parse_pct(sm),
            "mem": parse_pct(mem),
            "cmd": cmd
        })
    return result

def get_cmd_for_pid(pid: int) -> str:
    # Use ps to get full command line (args)
    try:
        out = run_cmd(["ps", "-o", "args=", "-p", str(pid)]).strip()
        return out or ""
    except Exception:
        return ""

def match_pid(pid: int, matcher: Optional[re.Pattern], pid_target: Optional[int]) -> bool:
    if pid_target is not None:
        return pid == pid_target
    if matcher is None:
        return True
    cmd = get_cmd_for_pid(pid)
    return bool(matcher.search(cmd))

def main():
    ap = argparse.ArgumentParser(description="Monitor per-process GPU usage and save to CSV.")
    group = ap.add_mutually_exclusive_group(required=False)
    group.add_argument("--pid", type=int, help="Target a single PID")
    group.add_argument("--match", type=str, help="Regex/substring to match process command line")
    ap.add_argument("--interval", type=int, default=30, help="Sampling interval in seconds (default: 30)")
    ap.add_argument("--output", type=str, default="gpu_log.csv", help="Output CSV path")
    ap.add_argument("--append", action="store_true", help="Append without header if file exists (default: header added if new file)")
    args = ap.parse_args()

    matcher = None
    if args.match:
        try:
            matcher = re.compile(args.match)
        except re.error:
            # treat as literal substring
            matcher = re.compile(re.escape(args.match))

    uuid_to_index = get_uuid_to_index()

    out_path = os.path.expanduser(args.output)
    file_exists = os.path.exists(out_path)

    # Open CSV
    f = open(out_path, "a", newline="")
    writer = csv.writer(f)

    if not file_exists or not args.append:
        writer.writerow(["timestamp", "gpu_index", "pid", "cmd", "gpu_mem_mib", "sm_util_pct", "mem_util_pct"])
        f.flush()

    try:
        while True:
            ts = datetime.now().isoformat(timespec="seconds")
            mem_rows = get_process_memory_rows()  # (pid, uuid, used_mib)
            pmon_rows = get_pmon_snapshot()       # dicts with pid, gpu, sm, mem, cmd

            # Build quick lookup from pid -> (sm, mem, gpu, cmd_from_pmon)
            pmon_by_pid: Dict[int, Dict[str, Optional[str]]] = {}
            for r in pmon_rows:
                pid = int(r["pid"])
                pmon_by_pid[pid] = {
                    "gpu": r["gpu"],
                    "sm": r["sm"],
                    "mem": r["mem"],
                    "cmd": r["cmd"],
                }

            # Iterate over memory rows (definitive list of CUDA compute procs)
            for pid_str, uuid, used in mem_rows:
                try:
                    pid = int(pid_str)
                except ValueError:
                    continue
                if not match_pid(pid, matcher, args.pid):
                    continue

                # Prefer command from ps (full), fallback to pmon
                cmd = get_cmd_for_pid(pid) or pmon_by_pid.get(pid, {}).get("cmd") or ""

                # GPU index from uuid if available, else from pmon
                gpu_index = uuid_to_index.get(uuid, pmon_by_pid.get(pid, {}).get("gpu") or "")

                sm_util = pmon_by_pid.get(pid, {}).get("sm")
                mem_util = pmon_by_pid.get(pid, {}).get("mem")

                writer.writerow([ts, gpu_index, pid, cmd, used, sm_util if sm_util is not None else "", mem_util if mem_util is not None else ""])
            f.flush()
            time.sleep(max(1, args.interval))
    except KeyboardInterrupt:
        pass
    finally:
        f.close()

if __name__ == "__main__":
    # Quick availability check
    if not run_cmd(["which", "nvidia-smi"]).strip():
        print("ERROR: nvidia-smi not found in PATH.", file=sys.stderr)
        sys.exit(1)
    main()
