#!/bin/bash
# Prefetch 楽園町田店 / 中山UNO morning data at ~09:00 for 2026-11-08 analysis.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
OUT="./.cache/morning-2026-11-08"
mkdir -p "$OUT"
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
UA_MOB='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
date '+%Y-%m-%d %H:%M:%S %Z' | tee "$OUT/started.txt"

# 楽園町田店 DeltaNet 4円
CK_R="$OUT/rakuen.ck"
rm -f "$CK_R"
curl -sL -c "$CK_R" -b "$CK_R" -A "$UA" -o "$OUT/rakuen_D0301.html" -w 'rakuen_D0301:%{http_code}:%{size_download}\n' \
  'https://www.d-deltanet.com/pc/D0301.do?pmc=22021031&clc=01&urt=400&pan=1' | tee -a "$OUT/fetch.log"
sleep 5
curl -sL -c "$CK_R" -b "$CK_R" -A "$UA" -o "$OUT/rakuen_top.html" -w 'rakuen_top:%{http_code}:%{size_download}\n' \
  'https://www.d-deltanet.com/pc/D0101.do?pmc=22021031' | tee -a "$OUT/fetch.log" || true

# 中山UNO Site Seven ranking 4円
CK_U="$OUT/uno.ck"
rm -f "$CK_U"
curl -sL -c "$CK_U" -b "$CK_U" -A "$UA_MOB" -o "$OUT/uno_D0100.html" -w 'uno_D0100:%{http_code}:%{size_download}\n' \
  'https://m.site777.jp/f/D0100.do?pmc=13003016' | tee -a "$OUT/fetch.log"
sleep 4
curl -sL -c "$CK_U" -b "$CK_U" -A "$UA_MOB" -o "$OUT/uno_rank.html" -w 'uno_rank:%{http_code}:%{size_download}\n' \
  'https://m.site777.jp/f/D0900.do?pmc=13003016&clc=01' | tee -a "$OUT/fetch.log"
sleep 4
curl -sL -c "$CK_U" -b "$CK_U" -A "$UA_MOB" -o "$OUT/uno_models.html" -w 'uno_models:%{http_code}:%{size_download}\n' \
  'https://m.site777.jp/f/D0300.do?pmc=13003016&clc=01&urt=400&pan=1' | tee -a "$OUT/fetch.log" || true

date '+%Y-%m-%d %H:%M:%S %Z' | tee "$OUT/ready.txt"
echo READY > "$OUT/READY"
echo "prefetch done -> $OUT" | tee -a "$OUT/fetch.log"
