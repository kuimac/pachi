#!/usr/bin/env python3
"""池袋駅周辺の登録店から横断おすすめ＋機種別ソート用一覧を生成。"""

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
    ("とある魔術の禁書目録3", re.compile(r"禁書目録3|禁書目録３")),
    ("エヴァはじまりの記憶", re.compile(r"はじまりの記憶")),
    ("エヴァ319RED", re.compile(r"319\s*RED|－319|−319|-319", re.I)),
]


def now_s() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def load_store(store: str, day: str):
    try:
        rows, src = brief.load_units(store, day)
        return rows, src, None
    except SystemExit as e:
        return [], "", str(e)


def recommend_key(row: dict, meta: dict):
    """おすすめ順: 浅ST・低当り優先。差玉順位は使わない。ST無しは後ろ。"""
    st = st_of(row)
    ht = hits_of(row)
    st_k = st if st is not None else 10**9
    ht_k = ht if ht is not None else 10**6
    unit = int(str(row["unit"])) if str(row.get("unit", "")).isdigit() else 10**9
    return (st_k, ht_k, unit)


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-11-28")
    ap.add_argument("--out-docs", type=Path, required=True)
    ap.add_argument("--out-internal", type=Path, required=True)
    ap.add_argument("--out-day-dir", type=Path, default=None, help="YYYY-MM-DD/池袋駅周辺 など")
    args = ap.parse_args()
    day = args.day
    guides = brief.load_guides()

    collected: dict[str, dict] = {}
    all_rows: list[tuple[str, dict, dict]] = []

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

    ev = []
    for store, r, meta in all_rows:
        st = st_of(r)
        ht = hits_of(r)
        if st is None:
            continue
        if parse_float(meta["bd28"]) is None and parse_float(meta["bd_eq"]) is None:
            continue
        if st <= 200 and (ht is None or ht <= 2):
            ev.append((store, r, meta))
    ev.sort(key=lambda x: recommend_key(x[1], x[2]))

    unbiased = [
        (s, r, m)
        for s, r, m in ev
        if not (r.get("rank") is not None and (r.get("rank") or 99) <= 10)
    ]

    store_scores = {}
    for store in IKEBUKURO:
        info = collected[store]
        cands = sum(1 for s, r, m in unbiased if s == store)
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

    ranked_stores = sorted(
        [s for s in IKEBUKURO if store_scores[s]["ok"]],
        key=lambda s: (-store_scores[s]["cands"], -store_scores[s]["n"], s),
    )

    def ev_rows(items, limit=20):
        out = []
        for i, (store, r, meta) in enumerate(items[:limit], 1):
            st = st_of(r)
            ht = hits_of(r) if hits_of(r) is not None else "—"
            out.append(
                [
                    str(i),
                    store,
                    str(r["unit"]),
                    r["model"],
                    f"ST{st}・当{ht}",
                    bd_pair(meta),
                    f"{bd_pair(meta)} 未満で切",
                ]
            )
        return out or [["—", "—", "—", "—", "候補なし", "—", "—"]]

    model_blocks = []
    for label, pat in TARGET_MODELS:
        hits = [(s, r, m) for s, r, m in all_rows if pat.search(r.get("model") or "")]
        hits.sort(key=lambda x: recommend_key(x[1], x[2]))
        body = []
        for i, (s, r, m) in enumerate(hits, 1):
            body.append(
                [
                    str(i),
                    s,
                    str(r["unit"]),
                    r["model"],
                    st_disp(r),
                    str(hits_of(r) if hits_of(r) is not None else "—"),
                    bd_pair(m),
                    f"差玉{r['rank']}" if r.get("rank") is not None else "—",
                ]
            )
        model_blocks.append((label, body, len(hits)))

    ceiling_rows = [(s, r, m) for s, r, m in all_rows if m["has_ceil"]]
    ceiling_rows.sort(key=lambda x: recommend_key(x[1], x[2]))
    ceil_body = []
    for i, (s, r, m) in enumerate(ceiling_rows, 1):
        sit = sit_criteria_for(r["model"], m)
        sit_start = sit["sit_start"]
        sit_col = (
            f"スタート{sit_start}回転以上 / {sit['line_note']}"
            if sit_start is not None
            else sit["line_note"]
        )
        ceil_body.append(
            [
                str(i),
                s,
                str(r["unit"]),
                r["model"],
                st_disp(r),
                str(hits_of(r) if hits_of(r) is not None else "—"),
                bd_pair(m),
                sit_col,
            ]
        )

    header = f"""# 池袋駅周辺 おすすめ一覧（{day}）

分析日時: {now_s()}（Asia/Tokyo）

分析BD: **4パチ250玉交換**基準。表記は **等価 / 28玉を併記**。  
先入観なし＝機種人気・差玉上位バイアスを排し、BD立ちやすさ・浅ST・天井線で並べる。  
機種別の列ソート可能表は [機種別一覧（ソート可）](機種別一覧.md)。

## 取得できた店／できなかった店

{md_table(
    ["店", "取得", "台数", "交換", "メモ"],
    [
        [
            s,
            "OK" if store_scores[s]["ok"] else "不可",
            str(store_scores[s]["n"] or "—"),
            store_scores[s]["exchange"],
            store_scores[s]["src"] or store_scores[s]["err"] or "Site Seven未接続・情報のみ",
        ]
        for s in IKEBUKURO
    ],
)}

## 1. 期待値が高い台

浅ST・低当り・BD既知（差玉順位は使わない）。

{md_table(["順", "店", "台番号", "機種", "根拠", "BD（等価/28玉）", "やめ時"], ev_rows(ev))}

## 2. ボーダー超えてる台（250玉基準）

{md_table(
    ["店", "台番号", "機種", "推定or実測/250玉", "BD（等価/28玉）", "判定"],
    [["—", "—", "—", "CSV上の推定/実測なし", "—", "**超過確定台なし**（現地1000円実測で等価・28玉両方と照合）"]],
)}

## 3. 先入観なくおすすめ台

差玉上位を除外した浅台・低当り。

{md_table(["順", "店", "台番号", "機種", "根拠", "BD（等価/28玉）", "やめ時"], ev_rows(unbiased))}

## 4. 先入観なくおすすめ店舗

{md_table(
    ["順", "店", "理由"],
    [
        [
            str(i),
            s,
            f"取得台{store_scores[s]['n']}・浅台候補{store_scores[s]['cands']}・天井/遊タイム{store_scores[s]['ceil']}台。交換{store_scores[s]['exchange']}",
        ]
        for i, s in enumerate(ranked_stores, 1)
    ]
    + [[ "—", s, "取得不可（情報のみ）"] for s in IKEBUKURO if not store_scores[s]["ok"]],
)}

## 5. 機種全台＋天井ある台（おすすめ順）

列見出しクリックでソートできる表は [機種別一覧](機種別一覧.md)（Pages）。ここはおすすめ順の要約。
"""

    parts = [header]
    for label, body, n in model_blocks:
        parts.append(f"### {label}（{n}台・おすすめ順）\n")
        parts.append(
            md_table(
                ["順", "店", "台番号", "機種", "スタート", "大当り", "BD（等価/28玉）", "差玉順位"],
                body or [["—", "—", "—", "設置なし／未取得", "—", "—", "—", "—"]],
            )
        )
        parts.append("")

    parts.append("### 天井ある台（おすすめ順・座る基準付き）\n")
    parts.append(
        md_table(
            ["順", "店", "台番号", "機種", "スタート", "大当り", "BD（等価/28玉）", "座る基準（何回転スタート以上／割り込み線）"],
            ceil_body or [["—", "—", "—", "—", "—", "—", "—", "該当なし"]],
        )
    )
    parts.append(
        "\n## 運用メモ\n\n"
        "- 通常測りは上表の浅台優先。差玉上位は結果台。\n"
        "- 天井／遊タイムは **線入り＋座る基準**のみ割り込み。液晶必須。\n"
        "- BD表記は常に等価と28玉を併記。\n"
    )
    docs = "\n".join(parts)

    # Day page: one big sortable-friendly MD (build_html makes all tables sortable)
    sortable_parts = [
        f"# 池袋駅周辺 機種別一覧（ソート可）（{day}）\n",
        f"分析日時: {now_s()}（Asia/Tokyo）\n",
        "各表の**列見出しをクリック**するとソートできる（Pages）。初期並びはおすすめ順（浅ST・低当り）。\n",
        f"要約: [おすすめ一覧](おすすめ.md)\n",
    ]
    for label, body, n in model_blocks:
        sortable_parts.append(f"## {label}（{n}台）\n")
        sortable_parts.append(
            md_table(
                ["おすすめ順", "店", "台番号", "機種", "スタート", "大当り", "BD等価", "BD28玉", "差玉順位"],
                [
                    [
                        r[0],
                        r[1],
                        r[2],
                        r[3],
                        r[4],
                        r[5],
                        (r[6].split(" / ")[0].replace("等価", "") if " / " in r[6] else r[6]),
                        (r[6].split(" / ")[1].replace("28玉", "") if " / " in r[6] else "—"),
                        r[7],
                    ]
                    for r in (body or [["—", "—", "—", "設置なし", "—", "—", "—", "—"]])
                ],
            )
        )
        sortable_parts.append("")
    sortable_parts.append(f"## 天井ある台（{len(ceil_body)}台）\n")
    sortable_parts.append(
        md_table(
            ["おすすめ順", "店", "台番号", "機種", "スタート", "大当り", "BD等価", "BD28玉", "座る基準"],
            [
                [
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    (r[6].split(" / ")[0].replace("等価", "") if " / " in r[6] else r[6]),
                    (r[6].split(" / ")[1].replace("28玉", "") if " / " in r[6] else "—"),
                    r[7],
                ]
                for r in (ceil_body or [["—", "—", "—", "—", "—", "—", "—", "該当なし"]])
            ],
        )
    )
    sortable_md = "\n".join(sortable_parts)

    sit_models = sorted({r["model"] for _, r, _ in unbiased[:15]})
    internal = f"""---
cursor:
  subagentId: "bc-155ff448-7ca2-50c6-9355-b45017b8482e"
---

# 池袋再取得・再分析（{day}）

生成: {now_s()}（Asia/Tokyo）

## 店舗

{chr(10).join(
    f"- {s}: ok={store_scores[s]['ok']} n={store_scores[s]['n']} src={store_scores[s]['src'] or store_scores[s]['err']}"
    for s in IKEBUKURO
)}

## 件数

- EV候補: {len(ev)}
- 先入観なし台: {len(unbiased)}
- 天井台: {len(ceiling_rows)}
- BD超過確定: 0

## 座る候補機種（攻略拡充対象）

{chr(10).join(f'- {m}' for m in sit_models) or '- （なし）'}
"""

    args.out_docs.parent.mkdir(parents=True, exist_ok=True)
    args.out_internal.parent.mkdir(parents=True, exist_ok=True)
    args.out_docs.write_text(docs, encoding="utf-8")
    args.out_internal.write_text(internal, encoding="utf-8")
    print(f"[ok] docs -> {args.out_docs}")
    print(f"[ok] internal -> {args.out_internal}")

    day_dir = args.out_day_dir or (ROOT / day / "池袋駅周辺")
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "おすすめ.md").write_text(docs, encoding="utf-8")
    (day_dir / "機種別一覧.md").write_text(sortable_md, encoding="utf-8")
    print(f"[ok] day -> {day_dir / 'おすすめ.md'}")
    print(f"[ok] day -> {day_dir / '機種別一覧.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
