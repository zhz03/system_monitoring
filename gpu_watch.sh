PID=1233167
OUT=./mem_only_long_new.csv

# Columns:
# - used_mib: GPU memory (MiB) used by the specific PID
# - sys_used_mib: current system RAM usage (MiB) at the same timestamp
# - cpu_cores: logical CPU cores (per-thread psr) joined as 8/9/11
# - cpu_pct: CPU usage percent of PID (ps pcpu), may exceed 100 for multi-threaded
echo "timestamp,used_mib,sys_used_mib,cpu_cores,cpu_pct" > "$OUT"

while true; do
  ts=$(date -Is)

  # Per-PID GPU memory in MiB (may be empty if PID not present)
  used_mib=$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits \
    | awk -F, -v pid="$PID" '($1+0)==pid {gsub(/ /,"",$2); print $2; found=1} END{if(!found) print ""}')

  # System RAM used in MiB: MemTotal - MemAvailable (from /proc/meminfo)
  sys_used_mib=$(awk '
    /MemTotal:/ {tot=$2}
    /MemAvailable:/ {av=$2}
    END { if (tot>0 && av>0) printf "%.0f", (tot-av)/1024; else print "" }
  ' /proc/meminfo)

  # CPU core ids (per-thread psr) observed at this instant, de-duplicated and sorted
  # Example: 8/9/11 . May be empty if PID is not present.
  cpu_cores=$(ps -L -o psr= -p "$PID" 2>/dev/null | awk '{print $1}' | sort -n | uniq | paste -sd/ -)

  # CPU usage percent of the process (pcpu from ps). Keep as float string.
  cpu_pct=$(ps -o pcpu= -p "$PID" 2>/dev/null | awk '{print $1}')

  echo "$ts,$used_mib,$sys_used_mib,$cpu_cores,$cpu_pct" >> "$OUT"
  sleep 30
done
