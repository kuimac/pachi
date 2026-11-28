#!/usr/bin/env python3
"""1店舗の収集・分析・publish をスクリプトで回す。

複数店は本スクリプトを店ごとに複数回叩く（1プロセスで全店ループしない）。
Site Seven はアクセス過多を避けるためリクエスト間 --sleep（既定 1.5s）。
全台の 509 は fetch 側 --retries。

例:
  python3 tools/run_pachi.py --list
  python3 tools/run_pachi.py --store 楽園池袋店 --collect --analyze --publish
  python3 tools/run_pachi.py --store 楽園町田店 --analyze
  # 複数店の例（店ごとに叩く・収集時は間を空ける）
  for s in 楽園池袋店 楽園町田店; do
    python3 tools/run_pachi.py --store "$s" --collect --analyze
    sleep 45
  done
  ./tools/publish.sh "multi-store analyze"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from store_registry import (  # noqa: E402
    can_collect,
    info_only_stores,
    load_store_names,
    require_one_store,
    site777_stores,
)

TZ = ZoneInfo("Asia/Tokyo")


def now_tokyo() -> datetime:
    return datetime.now(TZ)


def default_day() -> str:
    n = now_tokyo()
    if n.hour < 10:
        return (n - timedelta(days=1)).strftime("%Y-%m-%d")
    return n.strftime("%Y-%m-%d")


def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default="", help="正規店名（1店のみ。all / site777 不可）")
    ap.add_argument("--day", default="")
    ap.add_argument("--mode", choices=["morning", "afternoon", "adhoc"], default="adhoc")
    ap.add_argument("--collect", action="store_true", help="Site Seven 収集（未接続店はスキップ）")
    ap.add_argument("--analyze", action="store_true", help="判断 MD 自動生成")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--list", action="store_true", help="店舗一覧と収集可否を表示して終了")
    ap.add_argument("--sleep", type=float, default=1.5, help="HTTP リクエスト間隔（秒）")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--retry-backoff", type=float, default=60.0)
    ap.add_argument("--no-dmm-uno", action="store_true")
    args = ap.parse_args()

    if args.list:
        print(json.dumps(
            {
                "all": load_store_names(),
                "site777": site777_stores(),
                "info_only": info_only_stores(),
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if not args.collect and not args.analyze and not args.publish:
        ap.error("少なくとも --collect / --analyze / --publish のどれかを指定")
    if not args.store:
        ap.error("--store <正規店名> が必要（複数店はスクリプトを店ごとに複数回叩く）")

    store = require_one_store(args.store)
    day = args.day or default_day()
    print(
        json.dumps(
            {
                "day": day,
                "mode": args.mode,
                "store": store,
                "collect": args.collect,
                "analyze": args.analyze,
                "publish": args.publish,
                "sleep": args.sleep,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    failures = 0
    collected = False
    analyzed = False
    skipped_collect = False

    if args.collect:
        if not can_collect(store):
            print(f"[skip-collect] {store}: Site Seven 未接続")
            skipped_collect = True
        else:
            cmd = [
                sys.executable,
                "tools/collect_store.py",
                "--store",
                store,
                "--day",
                day,
                "--mode",
                "morning" if args.mode == "morning" else "adhoc",
                "--sleep",
                str(args.sleep),
                "--retries",
                str(args.retries),
                "--retry-backoff",
                str(args.retry_backoff),
            ]
            if args.no_dmm_uno:
                cmd.append("--no-dmm-uno")
            code = run(cmd)
            if code:
                failures += 1
            else:
                collected = True

    if args.analyze:
        code = run(
            [
                sys.executable,
                "tools/analyze_store.py",
                "--store",
                store,
                "--day",
                day,
                "--mode",
                args.mode,
            ]
        )
        if code:
            failures += 1
        else:
            analyzed = True

    if args.publish:
        msg = f"Run pachi {store} {day} collect={int(args.collect)} analyze={int(args.analyze)}"
        if run(["./tools/publish.sh", msg]):
            failures += 1

    summary = {
        "ok": failures == 0,
        "failures": failures,
        "store": store,
        "collected": collected,
        "analyzed": analyzed,
        "skipped_collect": skipped_collect,
        "day": day,
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
