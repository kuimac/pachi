#!/usr/bin/env python3
"""池袋駅周辺の登録店から横断おすすめ一覧を生成（先入観なし＝差玉上位バイアス排除）。"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import brief  # noqa: E402
from analyze_store import (  # noqa: E402
    bd_pair,
    parse_float,
    sit_criteria_for,
    st_disp,
    st_of,
    hits_of,
)

TZ = ZoneInfo("Asia/Tokyo")

IKEBUKURO = [
    "楽園池袋店",
    "楽園池袋店グリーンサイド",
    "マルハン池袋店",
    "やすだ西池袋６号店",
    "プレゴ池袋南口店",
]

TARGET_MODELS = [
    ("ガンダムSEED", re.compile(r"SEED|ガンダムSEED", re.I)),
    ("リゼロ鬼がかり2", re.compile(r"鬼がかり")),
    ("プリンセスプリンシパル", re.compile(r"プリンシパル|Principal", re.I)),
    ("電音部", re.compile(r"電音部")),
]


def now_s() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def load_store(store: str, day: str):
    try:
        rows, src = brief.load_units(store, day)
        return rows, src, None
    except SystemExit as e:
        return [], "", str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-11-28")
    ap.add_argument("--out-docs", type=Path, required=True)
    ap.add_argument("--out-internal", type=Path, required=True)
    args = ap.parse_args()
    day = args.day
    guides = brief.load_guides()

    collected: dict[str, dict] = {}
    all_rows: list[tuple[str, dict, dict]] = []  # store, row, meta

    for store in IKEBUKURO:
        rows, src, err = load_store(store, day)
        blocks = brief.load_store_blocks().get(store) or {}
        collected[store] = {
            "ok": bool(rows),
            "n": len(rows),
            "src": src,
            "err": err,
            "exchange": blocks.get("交換", "—"),
        }
        for r in rows:
            model = r.get("model") or "—"
            g = brief.match_guide(model, guides) if model != "—" else None
            meta = {
                "guide": g,
                "ceiling": brief.short_flag((g or {}).get("ceiling")),
                "yutime": brief.short_flag((g or {}).get("yutime")),
                "bd28": (g or {}).get("border_28") or "—",
                "bd_eq": (g or {}).get("border_eq") or "—",
                "has_ceil": brief.has_ceiling_or_yutime(g),
            }
            all_rows.append((store, r, meta))

    # 1) 期待値が高い台: 浅ST・低当り・BD既知（差玉順位は使わない）
    ev = []
    for store, r, meta in all_rows:
        st = st_of(r)
        ht = hits_of(r)
        if st is None:
            continue
        if parse_float(meta["bd28"]) is None and parse_float(meta["bd_eq"]) is None:
            continue
        if st <= 200 and (ht is None or ht <= 2):
            ev.append((st, ht or 0, store, r, meta))
    ev.sort(key=lambda x: (x[0], x[1], x[2], x[3]["unit"]))

    # 2) BD超え: 推定/実測がCSVに無いため確定不可を明示。候補は測り待ち。
    bd_over: list[str] = []
    # 将来: 実測回転.csv があればここで判定

    # 3) 先入観なしおすすめ台: EV順から結果台（rank上位）を除外
    unbiased = []
    for st, ht, store, r, meta in ev:
        if r.get("rank") is not None and (r.get("rank") or 99) <= 10:
            continue
        unbiased.append((st, ht, store, r, meta))

    # 4) おすすめ店舗: 収集できた店＋浅台候補数
    store_scores = {}
    for store in IKEBUKURO:
        info = collected[store]
        cands = sum(1 for st, ht, s, r, m in unbiased if s == store)
        ceil_n = sum(1 for s, r, m in all_rows if s == store and m["has_ceil"])
        store_scores[store] = {
            "ok": info["ok"],
            "n": info["n"],
            "cands": cands,
            "ceil": ceil_n,
            "exchange": info["exchange"],
            "err": info["err"],
            "src": info["src"],
        }

    # 5) 機種横断 + 天井ある台
    model_sections = []
    for label, pat in TARGET_MODELS:
        hits = [(s, r, m) for s, r, m in all_rows if pat.search(r.get("model") or "")]
        hits.sort(key=lambda x: (x[0], x[1].get("model") or "", int(str(x[1]["unit"])) if str(x[1]["unit"]).isdigit() else 0))
        lines = []
        for s, r, m in hits:
            lines.append(
                f"| {s} | {r['unit']} | {r['model']} | {st_disp(r)} | {hits_of(r) if hits_of(r) is not None else '—'} | "
                f"{bd_pair(m)} | {'差玉'+str(r['rank']) if r.get('rank') is not None else '—'} |"
            )
        model_sections.append((label, lines, len(hits)))

    ceiling_rows = [(s, r, m) for s, r, m in all_rows if m["has_ceil"]]
    ceiling_rows.sort(key=lambda x: (x[0], x[1].get("model") or "", int(str(x[1]["unit"])) if str(x[1]["unit"]).isdigit() else 0))
    ceil_lines = []
    for s, r, m in ceiling_rows:
        sit = sit_criteria_for(r["model"], m)
        sit_start = sit["sit_start"]
        sit_col = f"ST≥{sit_start} / {sit['line_note']}" if sit_start is not None else sit["line_note"]
        ceil_lines.append(
            f"| {s} | {r['unit']} | {r['model']} | {st_disp(r)} | {hits_of(r) if hits_of(r) is not None else '—'} | "
            f"{bd_pair(m)} | {sit_col} |"
        )

    def ev_table(items, limit=15):
        out = []
        for i, (st, ht, store, r, meta) in enumerate(items[:limit], 1):
            out.append(
                f"| {i} | {store} | {r['unit']} | {r['model']} | ST{st}・当{ht} | {bd_pair(meta)} | "
                f"{bd_pair(meta)} 未満で切 |"
            )
        return out or ["| — | — | — | — | 候補なし | — | — |"]

    # store recommend order
    ranked_stores = sorted(
        [s for s in IKEBUKURO if store_scores[s]["ok"]],
        key=lambda s: (-store_scores[s]["cands"], -store_scores[s]["n"], s),
    )

    docs = f"""# 池袋駅周辺 おすすめ一覧（{day}）

分析日時: {now_s()}（Asia/Tokyo）

分析BD: **4パチ250玉交換**基準。表記は **等価 / 28玉を併記**。  
先入観なし＝機種人気・差玉上位バイアスを排し、BD立ちやすさ・浅ST・天井線で並べる。

## 取得できた店／できなかった店

| 店 | 取得 | 台数 | 交換 | メモ |
| --- | --- | --- | --- | --- |
{chr(10).join(
    f"| {s} | {'OK' if store_scores[s]['ok'] else '不可'} | {store_scores[s]['n'] or '—'} | {store_scores[s]['exchange']} | "
    f"{store_scores[s]['src'] or store_scores[s]['err'] or 'Site Seven未接続・情報のみ'} |"
    for s in IKEBUKURO
)}

## 1. 期待値が高い台

浅ST・低当り・BD既知（差玉順位は使わない）。

| 順 | 店 | 台番号 | 機種 | 根拠 | BD（等価/28玉） | やめ時 |
| --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(ev_table(ev))}

## 2. ボーダー超えてる台（250玉基準）

| 店 | 台番号 | 機種 | 推定or実測/250玉 | BD（等価/28玉） | 判定 |
| --- | --- | --- | --- | --- | --- |
| — | — | — | CSV上の推定/実測なし | — | **超過確定台なし**（現地1000円実測で等価・28玉両方と照合） |

## 3. 先入観なくおすすめ台

差玉上位を除外した浅台・低当り。

| 順 | 店 | 台番号 | 機種 | 根拠 | BD（等価/28玉） | やめ時 |
| --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(ev_table(unbiased))}

## 4. 先入観なくおすすめ店舗

| 順 | 店 | 理由 |
| --- | --- | --- |
{chr(10).join(
    f"| {i} | {s} | 取得台{store_scores[s]['n']}・浅台候補{store_scores[s]['cands']}・天井/遊タイム{store_scores[s]['ceil']}台。交換{store_scores[s]['exchange']} |"
    for i, s in enumerate(ranked_stores, 1)
) or '| — | — | 取得できた店なし |'}
{chr(10).join(
    f"| — | {s} | 取得不可（情報のみ） |"
    for s in IKEBUKURO if not store_scores[s]['ok']
)}

## 5. 機種全台＋天井ある台（店横断）

### ガンダムSEED / リゼロ鬼がかり2 / プリンセスプリンシパル / 電音部

"""
    parts = [docs]
    for label, lines, n in model_sections:
        body = "\n".join(lines) if lines else "| — | — | 設置なし／未取得 | — | — | — | — |"
        parts.append(
            f"#### {label}（{n}台）\n\n"
            "| 店 | 台番号 | 機種 | スタート | 大当り | BD（等価/28玉） | 差玉順位 |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            f"{body}\n"
        )
    parts.append(
        "### 天井ある台（座る基準付き）\n\n"
        "| 店 | 台番号 | 機種 | スタート | 大当り | BD（等価/28玉） | 座る基準（割り込み線） |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        + ("\n".join(ceil_lines) if ceil_lines else "| — | — | — | — | — | — | 該当なし |")
        + "\n\n## 運用メモ\n\n"
        "- 通常測りは上表の浅台優先。差玉上位は結果台。\n"
        "- 天井／遊タイムは **線入り＋座る基準**のみ割り込み。液晶必須。\n"
        "- BD表記は常に等価と28玉を併記。\n"
    )
    docs = "\n".join(parts)

    internal = f"""---
cursor:
  subagentId: "bc-155ff448-7ca2-50c6-9355-b45017b8482e"
---

# 池袋フル分析内部メモ（{day}）

生成: {now_s()}（Asia/Tokyo）

## 店舗

{chr(10).join(
    f"- {s}: ok={store_scores[s]['ok']} n={store_scores[s]['n']} src={store_scores[s]['src'] or store_scores[s]['err']}"
    for s in IKEBUKURO
)}

## スクリプト

- `tools/analyze_store.py`: 等価/28玉併記・天井座る基準
- `tools/ikebukuro_picks.py`: 本ドキュメント生成
- PR #63 は main マージ済。BD強化は後続ブランチ

## 件数

- EV候補: {len(ev)}
- 先入観なし台: {len(unbiased)}
- 天井台: {len(ceiling_rows)}
- BD超過確定: 0（実測/推定CSVなし）
"""

    args.out_docs.parent.mkdir(parents=True, exist_ok=True)
    args.out_internal.parent.mkdir(parents=True, exist_ok=True)
    args.out_docs.write_text(docs, encoding="utf-8")
    args.out_internal.write_text(internal, encoding="utf-8")
    print(f"[ok] docs -> {args.out_docs}")
    print(f"[ok] internal -> {args.out_internal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
