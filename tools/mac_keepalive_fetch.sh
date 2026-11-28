#!/usr/bin/env bash
# Mac でスリープを抑えつつ Site Seven 無料取得→（中山UNO は DMM 併用）→（任意）publish。
# Cloud / ubuntu Actions は Site Seven・PSCUBE が 403 になりやすいので、住宅 IP の Mac を取得経路にする。
# DMM ぱちタウンのシェル（設置機種・ランキング画像）は Cloud でも取れるが、台番号別表は PSCUBE=Mac 前提。
#
# 本体は tools/collect_store.py / tools/run_pachi.py（1店ずつ）。
# 複数店は本スクリプトを店ごとに複数回叩く（間に sleep）。
#
# 使い方:
#   ./tools/mac_keepalive_fetch.sh --store 楽園町田店 --publish
#   ./tools/mac_keepalive_fetch.sh --store 中山UNO --analyze --publish
#   ./tools/mac_keepalive_fetch.sh --store 楽園池袋店 --loop 3600
#   python3 tools/run_pachi.py --store 楽園池袋店 --collect --analyze --publish
#
# launchd 例: tools/macos/com.kuimac.pachi.fetch.plist
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STORE=""
LOOP_SEC=0
DO_PUBLISH=0
MODE="adhoc"
DAY=""
SLEEP="1.5"
RETRIES="3"
ANALYZE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --store) STORE="$2"; shift 2 ;;
    --loop) LOOP_SEC="$2"; shift 2 ;;
    --publish) DO_PUBLISH=1; shift ;;
    --analyze) ANALYZE=1; shift ;;
    --mode) MODE="$2"; shift 2 ;;
    --day) DAY="$2"; shift 2 ;;
    --sleep) SLEEP="$2"; shift 2 ;;
    --retries) RETRIES="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$STORE" ]]; then
  echo "--store <正規店名> が必要（1店のみ。複数店はスクリプトを複数回叩く）" >&2
  exit 2
fi
case "$STORE" in
  all|site777|s7|info|info_only)
    echo "--store は1店の正規店名のみ（$STORE は不可）" >&2
    exit 2
    ;;
esac

run_once() {
  if [[ "$ANALYZE" -eq 1 ]]; then
    local args=(--store "$STORE" --mode "$MODE" --sleep "$SLEEP" --retries "$RETRIES" --collect --analyze)
    if [[ -n "$DAY" ]]; then
      args+=(--day "$DAY")
    fi
    if [[ "$DO_PUBLISH" -eq 1 ]]; then
      args+=(--publish)
    fi
    echo "[mac-fetch] $(TZ=Asia/Tokyo date '+%F %T') store=$STORE mode=$MODE -> run_pachi.py"
    python3 tools/run_pachi.py "${args[@]}"
    return
  fi
  local args=(--store "$STORE" --mode "$MODE" --sleep "$SLEEP" --retries "$RETRIES")
  if [[ -n "$DAY" ]]; then
    args+=(--day "$DAY")
  fi
  if [[ "$DO_PUBLISH" -eq 1 ]]; then
    args+=(--publish)
  fi
  echo "[mac-fetch] $(TZ=Asia/Tokyo date '+%F %T') store=$STORE mode=$MODE -> collect_store.py"
  python3 tools/collect_store.py "${args[@]}"
}

if [[ "$LOOP_SEC" -gt 0 ]]; then
  # ディスプレイは落とせてよいが、システムスリープは抑止（電源接続前提）
  exec caffeinate -i -s bash -c "
    set -euo pipefail
    while true; do
      \"$(printf '%q' "$ROOT")/tools/mac_keepalive_fetch.sh\" \
        --store $(printf '%q' "$STORE") \
        --mode $(printf '%q' "$MODE") \
        --sleep $(printf '%q' "$SLEEP") \
        --retries $(printf '%q' "$RETRIES") \
        ${DAY:+--day $(printf '%q' "$DAY")} \
        ${ANALYZE:+--analyze} \
        ${DO_PUBLISH:+--publish} || true
      sleep $(printf '%q' "$LOOP_SEC")
    done
  "
fi

run_once
