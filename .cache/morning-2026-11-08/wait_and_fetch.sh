#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
OUT=/Users/kumagaikousuke/Documents/pachi/.cache/morning-2026-11-08
mkdir -p "$OUT"
while true; do
  now=$(date +%s)
  target=$(python3 -c "import datetime; print(int(datetime.datetime(2026,11,8,9,0,0).timestamp()))")
  rem=$((target-now))
  echo "$(date '+%F %T') rem=$rem" >> "$OUT/waiter.log"
  if [ "$rem" -le 0 ]; then break; fi
  if [ "$rem" -gt 180 ]; then sleep 180; else sleep "$rem"; fi
done
exec /Users/kumagaikousuke/Documents/pachi/tools/morning_prefetch_2026-11-08.sh
