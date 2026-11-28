#!/usr/bin/env python3
"""全台CSV＋出玉ランキングから判断 MD を自動生成する（エージェント不要）。

出力（YYYY-MM-DD/<店>/）:
  台分析.md / 天井ある台.md / 天井狙い目.md / 期待値が高い台.md
  午後狙い目.md or 朝イチ狙い目.md / 重要ポイント.md
  データ無しのときは 分析不可.md

例:
  python3 tools/analyze_store.py --store 楽園池袋店
  python3 tools/analyze_store.py --store all --mode afternoon
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import brief  # noqa: E402
from store_registry import can_collect, load_store_names, resolve_targets  # noqa: E402

TZ = ZoneInfo("Asia/Tokyo")


def now_tokyo() -> datetime:
    return datetime.now(TZ)


def default_day() -> str:
    n = now_tokyo()
    if n.hour < 10:
        return (n - timedelta(days=1)).strftime("%Y-%m-%d")
    return n.strftime("%Y-%m-%d")


def exchange_note(store: str) -> str:
    blocks = brief.load_store_blocks().get(store) or {}
    exch = blocks.get("交換", "—")
    cash = blocks.get("換金単価", "")
    lend = blocks.get("貸出", "")
    parts = [f"交換{exch}"]
    if cash:
        parts.append(f"換金単価{cash}")
    if lend:
        parts.append(f"貸出{lend}")
    parts.append("町田楽園の3.75円/発は町田のみ")
    return "・".join(parts)


def write_unavailable(store: str, day: str, mode: str, reason: str) -> Path:
    out = ROOT / day / store
    out.mkdir(parents=True, exist_ok=True)
    now = now_tokyo().strftime("%Y-%m-%d %H:%M")
    collect = "可" if can_collect(store) else "不可（Site Seven 未接続）"
    text = f"""# {store} {day} 分析不可

分析日時: {now}（Asia/Tokyo）

## 理由

{reason}

| 項目 | 値 |
| --- | --- |
| 自動収集 | {collect} |
| モード | {mode} |
| 換金 | {exchange_note(store)} |

## 次の一手

- Site Seven 接続店: `python3 tools/collect_store.py --store {store}` のあと再分析
- 未接続店: 一覧の無料取得範囲どおり。手動・他ソースが無い限り判断 MD は出さない
"""
    path = out / "分析不可.md"
    path.write_text(text, encoding="utf-8")
    return path


def st_of(row: dict) -> int | None:
    return row.get("start")


def hits_of(row: dict) -> int | None:
    return row.get("hits")


def st_disp(row: dict) -> str:
    v = st_of(row)
    if v is not None:
        return str(v)
    return "—（全台表未公開・液晶確認）"


def analyze_one(store: str, day: str, mode: str) -> int:
    now = now_tokyo().strftime("%Y-%m-%d %H:%M")
    out = ROOT / day / store
    out.mkdir(parents=True, exist_ok=True)

    try:
        rows, source = brief.load_units(store, day)
    except SystemExit as e:
        path = write_unavailable(store, day, mode, str(e))
        print(f"[skip] {store}: {e} -> {path}")
        # 未接続店の分析不可は正常終了。接続店の欠データは失敗（先に collect）
        return 0 if not can_collect(store) else 1
    if not rows:
        path = write_unavailable(
            store,
            day,
            mode,
            "全台CSV／出玉ランキングが無い、または台行が0。"
            + (" 収集パイプライン未接続。" if not can_collect(store) else " 先に collect_store を実行。"),
        )
        print(f"[skip] {store}: no units -> {path}")
        return 0 if not can_collect(store) else 1

    guides = brief.load_guides()
    blocks = brief.load_store_blocks().get(store) or {}
    rate_note = exchange_note(store)

    # model meta
    by_model: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_model[row["model"] or "—"].append(row)

    model_meta: dict[str, dict] = {}
    for model, units in by_model.items():
        g = brief.match_guide(model, guides) if model and model != "—" else None
        model_meta[model] = {
            "guide": g,
            "ceiling": brief.short_flag((g or {}).get("ceiling")),
            "yutime": brief.short_flag((g or {}).get("yutime")),
            "bd28": (g or {}).get("border_28") or "—",
            "bd_eq": (g or {}).get("border_eq") or "—",
            "has_ceil": brief.has_ceiling_or_yutime(g),
            "count": len(units),
        }

    ceiling_units = [r for r in rows if model_meta.get(r["model"] or "—", {}).get("has_ceil")]
    ceiling_models = sorted({r["model"] for r in ceiling_units if r["model"]})

    # cold order: low ST, low hits, known BD
    candidates = []
    for r in rows:
        st = st_of(r)
        ht = hits_of(r)
        meta = model_meta.get(r["model"] or "—", {})
        if st is None or meta.get("bd28") in (None, "—", ""):
            continue
        if st <= 200 and (ht is None or ht <= 2):
            candidates.append(r)
    candidates.sort(key=lambda r: (st_of(r) or 10**9, hits_of(r) or 0, int(r["unit"]) if str(r["unit"]).isdigit() else 0))
    order = candidates[:8]

    # ranking tops as avoid / right-check
    ranked = sorted(
        [r for r in rows if r.get("rank") is not None],
        key=lambda r: r["rank"] or 10**9,
    )
    avoid = ranked[:8]

    def order_table(items: list[dict]) -> str:
        lines = []
        for i, r in enumerate(items, 1):
            meta = model_meta.get(r["model"] or "—", {})
            bd = meta.get("bd28", "—")
            lines.append(
                f"| {i} | {r['unit']} | {r['model']} | 1000円実測。ST{st_disp(r)}・当{hits_of(r) if hits_of(r) is not None else '—'}。BD28≈{bd} | {bd}未満で即切（未測は切） |"
            )
        return "\n".join(lines) if lines else "| 1 | — | — | 到着後に番号確定 | — |"

    def ceiling_table() -> str:
        lines = []
        for r in sorted(ceiling_units, key=lambda x: (x["model"] or "", int(x["unit"]) if str(x["unit"]).isdigit() else 0)):
            meta = model_meta[r["model"]]
            g = meta["guide"] or {}
            lines.append(
                f"| {r['unit']} | {r['model']} | {g.get('ceiling') or meta['ceiling']} | {g.get('yutime') or meta['yutime']} | {st_disp(r)} | {hits_of(r) if hits_of(r) is not None else '—'} | 遊タイム残りは液晶 |"
            )
        return "\n".join(lines) if lines else "| — | — | — | — | — | — | 該当なし |"

    def ceiling_mini() -> str:
        lines = []
        for r in sorted(ceiling_units, key=lambda x: (x["model"] or "", int(x["unit"]) if str(x["unit"]).isdigit() else 0)):
            meta = model_meta[r["model"]]
            lines.append(
                f"| {r['unit']} | {r['model']} | {meta['ceiling']} / {meta['yutime']} | {st_disp(r)} | 液晶 |"
            )
        return "\n".join(lines) if lines else "| — | — | 該当なし | — | — |"

    # 台分析 sections
    sections = []
    for model in sorted(by_model.keys()):
        meta = model_meta[model]
        ceil_note = "あり" if meta["has_ceil"] else "なし"
        g = meta["guide"] or {}
        lines = []
        for r in sorted(by_model[model], key=lambda x: int(x["unit"]) if str(x["unit"]).isdigit() else 0):
            note = "回転次第" if not meta["has_ceil"] else "遊タイム残り液晶"
            if r.get("rank") is not None:
                note += f"／差玉順位{r['rank']}"
            lines.append(
                f"| {r['unit']} | {st_disp(r)} | {hits_of(r) if hits_of(r) is not None else '—'} | "
                f"{r['max_out'] if r.get('max_out') is not None else '—'} | — | — | {note} |"
            )
        sections.append(
            f"### {model}\n\n"
            f"天井/遊タイム: {ceil_note}（天井={g.get('ceiling') or meta['ceiling']}／"
            f"遊={g.get('yutime') or meta['yutime']}／BD28={meta['bd28']}）\n\n"
            f"| 台番号 | スタート | 大当り | 最高出玉 | 推定/250玉 | 実測/250玉 | 所見 |\n"
            f"| --- | --- | --- | --- | --- | --- | --- |\n"
            + "\n".join(lines)
        )

    model_sum = "\n".join(
        f"| {m} | {model_meta[m]['count']} | {model_meta[m]['ceiling']} | {model_meta[m]['yutime']} | BD28 {model_meta[m]['bd28']} |"
        for m in ceiling_models
    ) or "| — | — | — | — | 該当なし |"

    line_cands = [r for r in ceiling_units if hits_of(r) is not None and (hits_of(r) or 0) <= 2]
    line_cands.sort(key=lambda r: (hits_of(r) or 0, int(r["unit"]) if str(r["unit"]).isdigit() else 0))
    line_rows = []
    for i, r in enumerate(line_cands[:10], 1):
        meta = model_meta[r["model"]]
        line_rows.append(
            f"| {i} | {r['unit']} | {r['model']} | 当{hits_of(r)} / ST {st_disp(r)}。遊={meta['yutime']} | 液晶で残り確認 |"
        )
    if not line_rows:
        line_rows = ["| — | — | — | 線入り候補なし（ST未公開多） | 液晶巡回 |"]

    pick_name = "朝イチ狙い目.md" if mode == "morning" else "午後狙い目.md"
    pick_title = "朝イチ狙い目" if mode == "morning" else "午後狙い目"

    files: dict[str, str] = {}
    files["天井ある台.md"] = f"""# {store} {day} 天井ある台

分析日時: {now}（Asia/Tokyo）

**天井／遊タイム搭載機の全台**（ハイエナ候補だけに絞らない）。  
数値詳細は [台分析](台分析.md)。割り込み順は [天井狙い目](天井狙い目.md)。  
換金: {rate_note}。  
ソース: `{source}`

## 天井ある台（全台）

| 台番号 | 機種 | 天井 | 遊タイム | スタート | 大当り | 所見 |
| --- | --- | --- | --- | --- | --- | --- |
{ceiling_table()}

## 機種別サマリ

| 機種 | 台数 | 天井 | 遊タイム | メモ |
| --- | --- | --- | --- | --- |
{model_sum}
"""

    files["天井狙い目.md"] = f"""# {store} {day} 天井狙い目

分析日時: {now}（Asia/Tokyo）

全台一覧は [天井ある台](天井ある台.md)。ここは **割り込みで座る順** だけ。

## 線入りで座る順

| 順 | 台番号 | 機種 | 根拠 | やめ時 |
| --- | --- | --- | --- | --- |
{chr(10).join(line_rows)}
"""

    upper = []
    for i, r in enumerate(order, 1):
        upper.append(
            f"| {i} | {r['unit']} | {r['model']} | 当日ST {st_of(r) if st_of(r) is not None else '—'}・当{hits_of(r) if hits_of(r) is not None else '—'}。冷え／浅め | 結果台と混ぜない |"
        )
    for r in avoid[:5]:
        upper.append(
            f"| — | {r['unit']} | {r['model']} | 差玉順位{r.get('rank')}（結果） | 通常では座らない |"
        )

    files["期待値が高い台.md"] = f"""# {store} {day} 期待値が高い台

分析日時: {now}（Asia/Tokyo）

数値は [台分析](台分析.md)。ここは通常画面で座る順だけ。  
自動生成（`tools/analyze_store.py`）。換金: {rate_note}。ソース: `{source}`

## 通常画面での打つ順番

| 順 | 台番号 | 機種 | やること | やめ時 |
| --- | --- | --- | --- | --- |
{order_table(order)}

## 上位（根拠メモ）

| 順 | 台番号 | 機種 | 根拠 | 注意 |
| --- | --- | --- | --- | --- |
{chr(10).join(upper) if upper else '| — | — | — | 候補なし | — |'}

## 天井ある台

全表は [天井ある台](天井ある台.md)。

| 台番号 | 機種 | 天井/遊タイム | スタート | 所見 |
| --- | --- | --- | --- | --- |
{ceiling_mini()}

## 総評

- 通常測りは浅台・低当り優先。差玉上位は結果台として通常では座らない。
- 天井／遊タイム機は全台掲載。線は液晶確認。
- 推定/実測が無い台は 1000円実測で切る。
"""

    files[pick_name] = f"""# {store} {day} {pick_title}

分析日時: {now}（Asia/Tokyo）

数値は [台分析](台分析.md)。自動生成。換金: {rate_note}。

## 通常画面での打つ順番

| 順 | 台番号 | 機種 | やること | やめ時 |
| --- | --- | --- | --- | --- |
{order_table(order)}

## 天井ある台

| 台番号 | 機種 | 天井/遊タイム | スタート | 所見 |
| --- | --- | --- | --- | --- |
{ceiling_mini()}

## 総評

- {pick_title}も通常測りは上表優先。差玉上位は触らない。
- 遊タイム機は線入りだけ割り込み。
"""

    right_rows = []
    for i, r in enumerate(avoid[:5], 1):
        right_rows.append(
            f"| {i} | {r['unit']} | {r['model']} | 差玉順位{r.get('rank')} | ST{st_disp(r)} | 持ち越しなら消化確認 | 通常なら測り順へ |"
        )
    if not right_rows:
        right_rows = ["| 1 | — | — | — | — | 液晶確認 | 測り順へ |"]

    files["重要ポイント.md"] = f"""# {store} {day} 重要ポイント

分析日時: {now}（Asia/Tokyo）

営業: {blocks.get('営業時間', '—')}。朝入場: {blocks.get('朝の入場', '—')}。  
換金: {rate_note}。日次集計リセット: {blocks.get('日次集計リセット', '—')}。

## 開店で最初に見る台（右確認）

| 順 | 台番号 | 機種 | 前日の最後 | 閉店スタート | 画面が右打ちなら | 通常画面なら |
| --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(right_rows)}

## 通常画面での打つ順番

| 順 | 台番号 | 機種 | やること | やめ時 |
| --- | --- | --- | --- | --- |
{order_table(order)}

## 天井ある台

| 台番号 | 機種 | 天井/遊タイム | スタート | 所見 |
| --- | --- | --- | --- | --- |
{ceiling_mini()}

## 触らない / 注意

| 台番号 | 機種 | 理由 |
| --- | --- | --- |
{chr(10).join(f"| {r['unit']} | {r['model']} | 差玉上位の結果台 |" for r in avoid[:8]) or '| — | — | — |'}
"""

    files["台分析.md"] = f"""# {store} {day} 台分析

分析日時: {now}（Asia/Tokyo）

対象: **{len(rows)}台 / {len(by_model)}機種**。ソース `{source}`。  
**天井・遊タイムの有無を問わず4円全台。** 推定/実測は未整備なら `—`。  
換金: {rate_note}。自動生成（`tools/analyze_store.py`）。

## 機種別

{chr(10).join(sections)}

## 天井ある台

詳細は [天井ある台](天井ある台.md)。

| 台番号 | 機種 | 天井 | 遊タイム | スタート | 所見 |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(
    f"| {r['unit']} | {r['model']} | {model_meta[r['model']]['ceiling']} | {model_meta[r['model']]['yutime']} | {st_disp(r)} | 液晶 |"
    for r in sorted(ceiling_units, key=lambda x: (x['model'] or '', int(x['unit']) if str(x['unit']).isdigit() else 0))
) or '| — | — | — | — | — | 該当なし |'}

## 総評

- 通常測り候補: {', '.join(f"{r['unit']}" for r in order[:4]) or 'なし'}。
- 天井／遊タイム全台: {len(ceiling_units)}台。
"""

    for name, body in files.items():
        (out / name).write_text(body, encoding="utf-8")
        print(f"[ok] {store}: {out / name}")

    print(
        f"[done] {store} units={len(rows)} ceiling={len(ceiling_units)} order={len(order)} mode={mode}"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default="all", help="店名 / all / site777 / info")
    ap.add_argument("--day", default="")
    ap.add_argument("--mode", choices=["morning", "afternoon", "adhoc"], default="adhoc")
    ap.add_argument("--site777-only", action="store_true")
    args = ap.parse_args()
    day = args.day or default_day()
    mode = "morning" if args.mode == "morning" else "afternoon"
    targets = resolve_targets(args.store, site777_only=args.site777_only)
    failures = 0
    for store in targets:
        try:
            failures += analyze_one(store, day, mode)
        except SystemExit as e:
            print(e, file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
