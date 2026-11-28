#!/usr/bin/env python3
"""全店舗の収集・分析・publish をスクリプト一発で回す。

Mac 住宅 IP 前提。Site Seven はアクセス過多を避けるため:
  - リクエスト間 --sleep（既定 1.5s）
  - 店と店のあいだ --between-stores（既定 45s）
  - 全台の 509 は fetch 側 --retries

例:
  python3 tools/run_pachi.py --list
  python3 tools/run_pachi.py --store 楽園池袋店 --collect --analyze --publish
  python3 tools/run_pachi.py --store all --collect --analyze --publish
  python3 tools/run_pachi.py --store site777 --collect
  python3 tools/run_pachi.py --store all --analyze   # 既存CSVのみ
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from store_registry import (  # noqa: E402
    can_collect,
    info_only_stores,
    load_store_names,
    resolve_targets,
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
    ap.add_argument("--store", default="all", help="店名 / all / site777 / info")
    ap.add_argument("--day", default="")
    ap.add_argument("--mode", choices=["morning", "afternoon", "adhoc"], default="adhoc")
    ap.add_argument("--collect", action="store_true", help="Site Seven 収集（未接続店はスキップ）")
    ap.add_argument("--analyze", action="store_true", help="判断 MD 自動生成")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--list", action="store_true", help="店舗一覧と収集可否を表示して終了")
    ap.add_argument("--site777-only", action="store_true", help="Site Seven 接続店だけ")
    ap.add_argument("--sleep", type=float, default=1.5, help="HTTP リクエスト間隔（秒）")
    ap.add_argument("--between-stores", type=float, default=45.0, help="店と店のあいだの待機（秒）")
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

    day = args.day or default_day()
    targets = resolve_targets(args.store, site777_only=args.site777_only)
    print(
        json.dumps(
            {
                "day": day,
                "mode": args.mode,
                "targets": targets,
                "collect": args.collect,
                "analyze": args.analyze,
                "publish": args.publish,
                "sleep": args.sleep,
                "between_stores": args.between_stores,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    failures = 0
    collected: list[str] = []
    analyzed: list[str] = []
    skipped_collect: list[str] = []

    for i, store in enumerate(targets):
        if i and (args.collect or args.analyze):
            # 分析だけでも連続 brief/IO 負荷を軽くする
            gap = args.between_stores if args.collect else min(5.0, args.between_stores)
            if gap > 0:
                print(f"[wait] between stores {gap:.0f}s ...", flush=True)
                time.sleep(gap)

        if args.collect:
            if not can_collect(store):
                print(f"[skip-collect] {store}: Site Seven 未接続")
                skipped_collect.append(store)
                # 未接続でも分析フラグがあれば 分析不可 を書く
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
                    collected.append(store)

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
                analyzed.append(store)

    if args.publish:
        label_targets = targets if len(targets) <= 3 else f"{len(targets)}stores"
        msg = f"Run pachi {label_targets} {day} collect={int(args.collect)} analyze={int(args.analyze)}"
        if run(["./tools/publish.sh", msg]):
            failures += 1

    summary = {
        "ok": failures == 0,
        "failures": failures,
        "collected": collected,
        "analyzed": analyzed,
        "skipped_collect": skipped_collect,
        "day": day,
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
