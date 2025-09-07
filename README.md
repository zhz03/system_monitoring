# GPU Watch — Per‑Process NVIDIA GPU Usage to CSV

**Overview**
- Lightweight Python 3.8+ CLI that samples per‑process GPU usage and writes rows to a CSV file.
- No third‑party dependencies. Relies on `nvidia-smi` and the Python standard library.
- Targets processes by PID or by command substring/regex. Runs until Ctrl+C.

**Requirements**
- `nvidia-smi` available in `PATH` (NVIDIA driver installed). Verify with `which nvidia-smi`.
- Linux or environments where `nvidia-smi` and `ps` are available.

**Script**
- Entry point: `gpu_watch.py`
- CSV columns: `timestamp,gpu_index,pid,cmd,gpu_mem_mib,sm_util_pct,mem_util_pct`
- Sampling sources:
  - Memory per process via `nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory`.
  - SM/MEM utilization via `nvidia-smi pmon -c 1 -s um` (one‑shot sample).
  - GPU UUID → index mapping via `nvidia-smi --query-gpu=index,uuid`.

**Usage**
- Show help: `python3 gpu_watch.py --help`
- Common flags:
  - `--pid <int>`: Target a single PID.
  - `--match <regex|substring>`: Filter processes by command line (regex; falls back to literal substring if regex is invalid).
  - `--interval <seconds>`: Sampling interval in seconds (default: 30).
  - `--output <path>`: Output CSV path (default: `./gpu_log.csv`). `~` is supported.
  - `--append`: If the output file exists, do not write the header row again.
- Stop with Ctrl+C. On missing `nvidia-smi`, exits with code 1 and an error message.

**Examples**
- Match by command substring/regex and sample every 30s:
  - `python3 gpu_watch.py --match python --interval 30 --output ./gpu.csv`
- Target a specific PID, sample every 10s, and append to an existing file without writing a new header:
  - `python3 gpu_watch.py --pid 1234 --interval 10 --append --output ~/gpu.csv`

**Bash Helper Script**
- Script: `gpu_watch.sh` — minimal logger that records only GPU memory usage for a single PID.
- Output CSV: `timestamp,used_mib` written to `OUT` (default `./mem_only.csv`).
- Configuration: edit `PID` and `OUT` at the top of the script; sampling interval is controlled by `sleep 30`.
- Dependencies: `nvidia-smi`, `awk`, and `date` available in the environment.
- Behavior: if the target PID is not present in `nvidia-smi --query-compute-apps`, an empty value is written for `used_mib`.
- Run:
  - `chmod +x gpu_watch.sh`
  - `./gpu_watch.sh` (runs until Ctrl+C)
- Customize:
  - Change `sleep` duration to adjust interval.
  - Run multiple copies for different PIDs or adapt the `awk` filter to handle a list of PIDs.

**CSV Output**
- Header (first line unless `--append` is used on an existing file):
  - `timestamp,gpu_index,pid,cmd,gpu_mem_mib,sm_util_pct,mem_util_pct`
- Example rows (illustrative):
  - `2025-01-10T14:22:30,0,1622588,python train.py,8234,72,58`
  - `2025-01-10T14:23:00,0,1622588,python train.py,8240,68,61`
- Notes on columns:
  - `gpu_index`: Resolved via GPU UUID→index mapping; falls back to `pmon` GPU column if needed.
  - `cmd`: Full command from `ps`; falls back to `pmon` command if unavailable.
  - `sm_util_pct` / `mem_util_pct`: Integers from `pmon`; may be empty if not reported for a process at that instant.

**How It Works**
- Queries compute processes and memory usage, samples utilization with `pmon`, joins by PID, and writes a row per process per interval.
- Flushes the CSV file after each interval so data is durable during long runs.

**Troubleshooting**
- `ERROR: nvidia-smi not found in PATH.`: Install NVIDIA drivers and ensure `nvidia-smi` is available.
- Empty `sm_util_pct` / `mem_util_pct`: `pmon` may not report utilization for all processes every sample; values can be blank.
- No rows written: Ensure the target process uses CUDA on an NVIDIA GPU and that filtering via `--pid`/`--match` matches the process.

**Development**
- Python style: PEP 8, 4‑space indent, type hints for new code.
- Zero third‑party dependencies; prefer `subprocess` and small helpers like `run_cmd()`.
- Optional tools (if installed):
  - Format: `black .`
  - Lint: `ruff .`

**Testing**
- Framework: `pytest` (suggested). Place tests under `tests/` as `test_*.py`.
- For CLI tests, invoke via `subprocess.run([...])` and use temporary files.
- Mock GPU calls by monkeypatching `run_cmd()` to simulate `nvidia-smi` outputs.
- Aim for ~80% coverage on new or changed logic; include edge cases:
  - Missing `nvidia-smi` in `PATH`.
  - No GPUs or no running compute processes.
  - Invalid regex passed to `--match` (falls back to literal substring).

**Security & Privacy**
- Avoid elevated privileges; write CSV to a user‑owned path.
- `cmd` captures full process command lines; avoid sharing CSVs that may contain sensitive arguments.

**Architecture Notes**
- Periodically samples process memory and utilization, merges by PID, and appends CSV rows until interrupted.

**License**
- See `LICENSE` for details.
