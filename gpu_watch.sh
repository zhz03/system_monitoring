PID=1622588
OUT=./mem_only.csv
echo "timestamp,used_mib" > "$OUT"
while true; do
  echo -n "$(date -Is)," >> "$OUT"
  nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits \
    | awk -F, -v pid="$PID" '($1+0)==pid {gsub(/ /,"",$2); print $2; found=1} END{if(!found) print ""}' >> "$OUT"
  sleep 30
done
