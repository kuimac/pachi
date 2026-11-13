#!/usr/bin/env bash
# Mac でスリープを抑えつつ Site Seven 無料取得→（中山UNO は DMM 併用）→（任意）publish。
# Cloud / ubuntu Actions は Site Seven・PSCUBE が 403 になりやすいので、住宅 IP の Mac を取得経路にする。
# DMM ぱちタウンのシェル（設置機種・ランキング画像）は Cloud でも取れるが、台番号別表は PSCUBE=Mac 前提。
#
# 使い方:
#   ./tools/mac_keepalive_fetch.sh                 # 1回だけ取得
#   ./tools/mac_keepalive_fetch.sh --loop 3600     # 1時間おき（caffeinate 付き）
#   ./tools/mac_keepalive_fetch.sh --store 中山UNO --publish
#
# launchd 例: tools/macos/com.kuimac.pachi.fetch.plist
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STORE="all"
LOOP_SEC=0
DO_PUBLISH=0
MODE="adhoc"
DAY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --store) STORE="$2"; shift 2 ;;
    --loop) LOOP_SEC="$2"; shift 2 ;;
    --publish) DO_PUBLISH=1; shift ;;
    --mode) MODE="$2"; shift 2 ;;
    --day) DAY="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

run_once() {
  local day_args=()
  if [[ -n "$DAY" ]]; then
    day_args=(--day "$DAY")
  fi
  echo "[mac-fetch] $(TZ=Asia/Tokyo date '+%F %T') store=$STORE mode=$MODE"
  python3 tools/prefetch_ranks.py --store "$STORE" --mode "$MODE" "${day_args[@]+"${day_args[@]}"}"
  python3 tools/fetch_site777_all_units.py --store "$STORE" "${day_args[@]+"${day_args[@]}"}"
  # 中山UNO: DMM ぱちタウン / PSCUBE を併用（Site Seven を置き換えない）
  if [[ "$STORE" == "all" || "$STORE" == "中山UNO" ]]; then
    python3 tools/fetch_dmm_ptown.py --store 中山UNO "${day_args[@]+"${day_args[@]}"}" || true
    python3 tools/merge_uno_sources.py "${day_args[@]+"${day_args[@]}"}" || true
  fi
  if [[ "$DO_PUBLISH" -eq 1 ]]; then
    ./tools/publish.sh "Prefetch Mac keepalive $(TZ=Asia/Tokyo date '+%F %H:%M') (${STORE})"
  fi
}

if [[ "$LOOP_SEC" -gt 0 ]]; then
  # ディスプレイは落とせてよいが、システムスリープは抑止（電源接続前提）
  exec caffeinate -i -s bash -c "
    set -euo pipefail
    while true; do
      \"$(printf '%q' "$ROOT")/tools/mac_keepalive_fetch.sh\" \
        --store $(printf '%q' "$STORE") \
        --mode $(printf '%q' "$MODE") \
        ${DAY:+--day $(printf '%q' "$DAY")} \
        ${DO_PUBLISH:+--publish} || true
      sleep $(printf '%q' "$LOOP_SEC")
    done
  "
fi

run_once
