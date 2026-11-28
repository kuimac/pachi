#!/usr/bin/env python3
"""店舗の Site Seven 収集を一発でやる（分析MDは書かない）。

やること:
  1. 出玉ランキング取得（prefetch_ranks）
  2. 全台表取得（fetch_site777_all_units・509リトライ付き）
  3. 設置機種 CSV 作成
  4. 日次フォルダへ CSV 複製＋生データ取得結果.md
  5. （任意）中山UNO の DMM 併用
  6. （任意）publish.sh

エージェントのトークンを使わず、Mac 住宅 IP で回す前提。

例:
  python3 tools/collect_store.py --store 楽園池袋店
  python3 tools/collect_store.py --store 楽園池袋店 --publish
  python3 tools/run_pachi.py --store 楽園池袋店 --collect --analyze --publish
  # 複数店は店ごとに叩く（間に sleep）
  for s in 楽園池袋店 楽園町田店; do
    python3 tools/collect_store.py --store "$s"; sleep 45
  done
  ./tools/mac_keepalive_fetch.sh --store 楽園町田店 --publish
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Tokyo")

# Site Seven 登録店は store_registry（prefetch / fetch と同期）
sys.path.insert(0, str(ROOT / "tools"))
from store_registry import require_one_store, site777_stores  # noqa: E402

SITE777_STORES = site777_stores()


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


def write_models_csv(store: str, day: str) -> Path | None:
    src = ROOT / store / f"全台データ_{day}.csv"
    if not src.is_file():
        return None
    rows = list(csv.DictReader(src.open(encoding="utf-8")))
    ctr: Counter[str] = Counter()
    mdc: dict[str, str] = {}
    for r in rows:
        name = r.get("機種") or ""
        ctr[name] += 1
        mdc[name] = r.get("mdc") or mdc.get(name, "")
    out = ROOT / store / f"設置機種_4パチ_{day}.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["機種", "設置台数", "mdc"])
        w.writeheader()
        for name, n in sorted(ctr.items(), key=lambda x: (-x[1], x[0])):
            w.writerow({"機種": name, "設置台数": n, "mdc": mdc.get(name, "")})
    return out


def copy_day_artifacts(store: str, day: str, fetched_at: str, units: int, models: int, rank_rows: int, extra_notes: list[str]) -> Path:
    day_dir = ROOT / day / store
    day_dir.mkdir(parents=True, exist_ok=True)
    store_dir = ROOT / store
    for name in (
        f"出玉ランキング_{day}.csv",
        f"全台データ_{day}.csv",
        f"設置機種_4パチ_{day}.csv",
    ):
        src = store_dir / name
        if src.is_file():
            shutil.copy2(src, day_dir / name)

    notes = "\n".join(f"- {n}" for n in extra_notes) if extra_notes else "- （特記なし）"
    memo = f"""# {store} 生データ取得結果

取得日時: {fetched_at}（Asia/Tokyo）

## 取得内容

- Site Seven 出玉ランキング（4パチ）
- Site Seven 機種別全台表（509 は欠落機種リトライ）
- `tools/collect_store.py` による自動収集

## 件数

| 項目 | 値 |
| --- | --- |
| 出玉ランキング | {rank_rows} |
| 全台データ行 | {units} |
| 設置機種（4パチ） | {models} |

## 保存パス

- `{store}/出玉ランキング_{day}.csv`
- `{store}/全台データ_{day}.csv`
- `{store}/設置機種_4パチ_{day}.csv`
- `{day}/{store}/` にも同CSV

## メモ

{notes}
"""
    path = day_dir / "生データ取得結果.md"
    path.write_text(memo, encoding="utf-8")
    return path


def rank_row_count(store: str, day: str) -> int:
    p = ROOT / store / f"出玉ランキング_{day}.csv"
    if not p.is_file():
        return 0
    with p.open(encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)


def load_units_snap(store: str) -> dict:
    p = ROOT / "tools" / "prefetch_snapshots" / store / "site777_all_units_last_attempt.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def collect_one(
    store: str,
    *,
    day: str,
    mode: str,
    sleep: float,
    retries: int,
    retry_backoff: float,
    with_dmm_uno: bool,
) -> int:
    rc = 0
    rc |= run(
        [
            sys.executable,
            "tools/prefetch_ranks.py",
            "--store",
            store,
            "--mode",
            mode,
            "--day",
            day,
            "--sleep",
            str(sleep),
        ]
    )
    rc |= run(
        [
            sys.executable,
            "tools/fetch_site777_all_units.py",
            "--store",
            store,
            "--day",
            day,
            "--sleep",
            str(sleep),
            "--retries",
            str(retries),
            "--retry-backoff",
            str(retry_backoff),
        ]
    )

    if with_dmm_uno and store == "中山UNO":
        run([sys.executable, "tools/fetch_dmm_ptown.py", "--store", "中山UNO", "--day", day])
        run([sys.executable, "tools/merge_uno_sources.py", "--day", day])

    models_path = write_models_csv(store, day)
    snap = load_units_snap(store)
    units = int(snap.get("units") or 0)
    models = int(snap.get("models") or 0)
    fetched_at = str(snap.get("fetched_at") or now_tokyo().strftime("%Y-%m-%d %H:%M"))
    missing = snap.get("missing_models") or []
    notes = []
    if snap.get("retries_used"):
        notes.append(f"全台リトライ使用: {snap.get('retries_used')} 回")
    if missing:
        notes.append("未回収機種: " + ", ".join(str(x) for x in missing[:20]))
        rc = 1
    if models_path:
        notes.append(f"設置機種CSV: {models_path.relative_to(ROOT)}")
    copy_day_artifacts(
        store,
        day,
        fetched_at,
        units=units,
        models=models,
        rank_rows=rank_row_count(store, day),
        extra_notes=notes,
    )
    print(
        json.dumps(
            {
                "store": store,
                "day": day,
                "units": units,
                "models": models,
                "rank_rows": rank_row_count(store, day),
                "missing_models": missing,
                "ok": units > 0 and not missing,
            },
            ensure_ascii=False,
        )
    )
    return 0 if units > 0 and not missing else (rc or 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True, help="正規店名（1店のみ。複数店はスクリプトを複数回叩く）")
    ap.add_argument("--day", default="", help="YYYY-MM-DD（省略時は JST・10時前は前日）")
    ap.add_argument("--mode", choices=["morning", "adhoc"], default="adhoc")
    ap.add_argument("--sleep", type=float, default=1.5, help="HTTP リクエスト間隔（秒）")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--retry-backoff", type=float, default=60.0)
    ap.add_argument("--publish", action="store_true", help="取得後に publish.sh")
    ap.add_argument("--no-dmm-uno", action="store_true", help="中山UNO の DMM 併用をスキップ")
    args = ap.parse_args()

    day = args.day or default_day()
    try:
        store = require_one_store(args.store)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    if store not in site777_stores():
        print(f"Site Seven 未接続: {store}", file=sys.stderr)
        print("known site777:", ", ".join(site777_stores()), file=sys.stderr)
        return 2

    code = collect_one(
        store,
        day=day,
        mode=args.mode,
        sleep=args.sleep,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
        with_dmm_uno=not args.no_dmm_uno,
    )
    if code:
        return code

    if args.publish:
        msg = f"Collect {store} {day} ({args.mode})"
        pub = run(["./tools/publish.sh", msg])
        if pub:
            return pub

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
