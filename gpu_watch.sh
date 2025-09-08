PID=685820
OUT=./mem_only_long.csv

# Columns:
# - used_mib: GPU memory (MiB) used by the specific PID
# - sys_used_mib: current system RAM usage (MiB) at the same timestamp
echo "timestamp,used_mib,sys_used_mib" > "$OUT"

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

  echo "$ts,$used_mib,$sys_used_mib" >> "$OUT"
  sleep 30
done
