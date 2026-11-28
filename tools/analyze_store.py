#!/usr/bin/env python3
"""全台CSV＋出玉ランキングから判断 MD を自動生成する（エージェント不要）。

出力（YYYY-MM-DD/<店>/）:
  台分析.md / 天井ある台.md / 天井狙い目.md / 期待値が高い台.md
  午後狙い目.md or 朝イチ狙い目.md / 重要ポイント.md
  データ無しのときは 分析不可.md

例:
  python3 tools/analyze_store.py --store 楽園池袋店
  python3 tools/analyze_store.py --store 楽園町田店 --mode afternoon
  # 複数店は店ごとに叩く
  for s in 楽園池袋店 楽園町田店; do
    python3 tools/analyze_store.py --store "$s" --mode afternoon
  done
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import brief  # noqa: E402
from store_registry import can_collect, require_one_store  # noqa: E402

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
    parts.append("分析BDは4パチ250玉交換基準・等価と28玉を併記")
    parts.append("町田楽園の3.75円/発は町田のみ")
    return "・".join(parts)


def bd_pair(meta: dict) -> str:
    """等価と28玉を必ず併記。"""
    eq = meta.get("bd_eq") or "—"
    b28 = meta.get("bd28") or "—"
    return f"等価{eq} / 28玉{b28}"


def bd_stop(meta: dict) -> str:
    eq = meta.get("bd_eq") or "—"
    b28 = meta.get("bd28") or "—"
    return f"等価{eq}未満または28玉{b28}未満で即切（未測は切・分析は250玉交換基準）"


def parse_float(val) -> float | None:
    if val is None or val in ("", "—", "-"):
        return None
    try:
        return float(str(val).replace("約", "").strip())
    except ValueError:
        return None


def trigger_rotations(text: str) -> int | None:
    """遊タイム／天井テキストから発動回転を拾う。"""
    if not text:
        return None
    patterns = [
        r"低確率(?:状態)?(?:を)?\s*(\d+)\s*回転",
        r"低確\s*\*?\*?(\d+)\s*回転",
        r"(\d+)\s*回転\s*(?:消化|で遊タイム|で発動|→)",
        r"大当り間\s*\*?\*?(\d+)\s*回転",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return None


def sit_remain_default(trigger: int | None, model: str, yutime: str) -> int | None:
    """ガイドに数値線が無いときの簡易残回転（過去運用）。"""
    name = model or ""
    yt = yutime or ""
    if "アグネス" in name or (trigger == 239):
        return 100
    if "電音" in name or "1500個" in yt or (trigger and trigger >= 500):
        return 200
    if trigger and trigger >= 800:
        return 150
    if trigger and trigger >= 200:
        return 100
    if trigger:
        return max(30, trigger // 3)
    return None


def sit_criteria_for(model: str, meta: dict) -> dict:
    """座る基準（割り込み線・スタート何回転以上）。"""
    g = meta.get("guide") or {}
    yutime = g.get("yutime") or meta.get("yutime") or ""
    ceiling = g.get("ceiling") or meta.get("ceiling") or ""
    guide_name = g.get("name") or ""
    line_note = ""
    remain: int | None = None
    trigger = trigger_rotations(str(yutime)) or trigger_rotations(str(ceiling))

    guide_path = ROOT / "攻略情報" / f"{guide_name}.md" if guide_name else None
    if guide_path and guide_path.is_file():
        text = guide_path.read_text(encoding="utf-8", errors="ignore")
        if "## ハイエナ基準" in text:
            chunk = text.split("## ハイエナ基準", 1)[1].split("\n## ", 1)[0]
            m = re.search(r"残り[がおおよそ\s]*(\d+)\s*回転", chunk)
            if m:
                remain = int(m.group(1))
                line_note = f"ガイド線入り: 残≤約{remain}"
            m2 = re.search(r"残[≤≦]?\s*(\d+)", chunk)
            if remain is None and m2:
                remain = int(m2.group(1))
                line_note = f"ガイド簡易線: 残≤{remain}"
            m3 = re.search(r"スタート\s*(\d+)\s*から", chunk)
            start_from = int(m3.group(1)) if m3 else None
            if start_from is not None and trigger:
                remain = max(0, trigger - start_from)
                line_note = f"ガイド: スタート{start_from}〜（残≤{remain}）"

    if remain is None:
        remain = sit_remain_default(trigger, model, str(yutime))
        if remain is not None:
            line_note = f"運用簡易線: 残≤約{remain}"

    sit_start: int | None = None
    if trigger is not None and remain is not None:
        sit_start = max(0, trigger - remain)

    if sit_start is not None:
        sit_text = (
            f"割り込み: 線入り（残≤約{remain}）のみ。"
            f"スタート{sit_start}回転以上相当＋液晶確認。"
            f"{line_note}"
        )
    elif remain is not None:
        sit_text = f"割り込み: 線入り（残≤約{remain}）＋液晶のみ。ST未公開時は残表示必須。{line_note}"
    else:
        sit_text = "割り込み: 線入り時のみ（数値線未掲載）。液晶残が浅いときだけ。線外は本命にしない"

    return {
        "trigger": trigger,
        "remain": remain,
        "sit_start": sit_start,
        "text": sit_text,
        "line_note": line_note or "線入り時のみ",
    }


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

    # sit criteria per ceiling model
    sit_by_model: dict[str, dict] = {}
    for model in ceiling_models:
        sit_by_model[model] = sit_criteria_for(model, model_meta[model])

    # cold order: low ST, low hits, known BD（等価または28玉）
    candidates = []
    for r in rows:
        st = st_of(r)
        ht = hits_of(r)
        meta = model_meta.get(r["model"] or "—", {})
        if st is None:
            continue
        if parse_float(meta.get("bd28")) is None and parse_float(meta.get("bd_eq")) is None:
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
            lines.append(
                f"| {i} | {r['unit']} | {r['model']} | 1000円実測。ST{st_disp(r)}・当{hits_of(r) if hits_of(r) is not None else '—'}。"
                f"BD {bd_pair(meta)} | {bd_stop(meta)} |"
            )
        return "\n".join(lines) if lines else "| 1 | — | — | 到着後に番号確定 | — |"

    def ceiling_table() -> str:
        lines = []
        for r in sorted(ceiling_units, key=lambda x: (x["model"] or "", int(x["unit"]) if str(x["unit"]).isdigit() else 0)):
            meta = model_meta[r["model"]]
            g = meta["guide"] or {}
            sit = sit_by_model.get(r["model"]) or sit_criteria_for(r["model"], meta)
            sit_start = sit["sit_start"]
            sit_col = f"ST≥{sit_start}" if sit_start is not None else "液晶残"
            lines.append(
                f"| {r['unit']} | {r['model']} | {g.get('ceiling') or meta['ceiling']} | {g.get('yutime') or meta['yutime']} | "
                f"{st_disp(r)} | {hits_of(r) if hits_of(r) is not None else '—'} | {bd_pair(meta)} | "
                f"{sit_col} / {sit['line_note']} |"
            )
        return "\n".join(lines) if lines else "| — | — | — | — | — | — | — | 該当なし |"

    def ceiling_mini() -> str:
        lines = []
        for r in sorted(ceiling_units, key=lambda x: (x["model"] or "", int(x["unit"]) if str(x["unit"]).isdigit() else 0)):
            meta = model_meta[r["model"]]
            sit = sit_by_model.get(r["model"]) or {}
            sit_start = sit.get("sit_start")
            note = f"座る基準ST≥{sit_start}" if sit_start is not None else "線入り＋液晶"
            lines.append(
                f"| {r['unit']} | {r['model']} | {meta['ceiling']} / {meta['yutime']} | {st_disp(r)} | "
                f"{bd_pair(meta)} | {note} |"
            )
        return "\n".join(lines) if lines else "| — | — | 該当なし | — | — | — |"

    # 台分析 sections
    sections = []
    for model in sorted(by_model.keys()):
        meta = model_meta[model]
        ceil_note = "あり" if meta["has_ceil"] else "なし"
        g = meta["guide"] or {}
        sit = sit_by_model.get(model)
        sit_line = f"／座る基準: {sit['text']}" if sit else ""
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
            f"遊={g.get('yutime') or meta['yutime']}／BD {bd_pair(meta)}{sit_line}）\n\n"
            f"| 台番号 | スタート | 大当り | 最高出玉 | 推定/250玉 | 実測/250玉 | 所見 |\n"
            f"| --- | --- | --- | --- | --- | --- | --- |\n"
            + "\n".join(lines)
        )

    model_sum = "\n".join(
        (
            f"| {m} | {model_meta[m]['count']} | {model_meta[m]['ceiling']} | {model_meta[m]['yutime']} | "
            f"{bd_pair(model_meta[m])} | "
            f"{('ST≥' + str(sit_by_model[m]['sit_start'])) if sit_by_model.get(m, {}).get('sit_start') is not None else sit_by_model.get(m, {}).get('line_note', '線入り')} |"
        )
        for m in ceiling_models
    ) or "| — | — | — | — | — | 該当なし |"

    line_cands = [r for r in ceiling_units if hits_of(r) is not None and (hits_of(r) or 0) <= 2]
    line_cands.sort(key=lambda r: (hits_of(r) or 0, int(r["unit"]) if str(r["unit"]).isdigit() else 0))
    line_rows = []
    for i, r in enumerate(line_cands[:10], 1):
        meta = model_meta[r["model"]]
        sit = sit_by_model.get(r["model"]) or {}
        sit_start = sit.get("sit_start")
        sit_bit = f"座る基準ST≥{sit_start}" if sit_start is not None else sit.get("line_note", "線入り")
        line_rows.append(
            f"| {i} | {r['unit']} | {r['model']} | 当{hits_of(r)} / ST {st_disp(r)}。{sit_bit}。BD {bd_pair(meta)} | 液晶で残り確認・線外は切 |"
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
換金: {rate_note}。BDは **等価と28玉を併記**（分析の玉基準は4パチ250玉交換）。  
ソース: `{source}`

## 天井ある台（全台）

| 台番号 | 機種 | 天井 | 遊タイム | スタート | 大当り | BD（等価/28玉） | 座る基準 |
| --- | --- | --- | --- | --- | --- | --- | --- |
{ceiling_table()}

## 機種別サマリ

| 機種 | 台数 | 天井 | 遊タイム | BD（等価/28玉） | 座る基準 |
| --- | --- | --- | --- | --- | --- |
{model_sum}
"""

    files["天井狙い目.md"] = f"""# {store} {day} 天井狙い目

分析日時: {now}（Asia/Tokyo）

全台一覧は [天井ある台](天井ある台.md)。ここは **割り込みで座る順** だけ。  
BDは等価/28玉併記。線外は本命にしない。

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

| 台番号 | 機種 | 天井/遊タイム | スタート | BD（等価/28玉） | 座る基準 |
| --- | --- | --- | --- | --- | --- |
{ceiling_mini()}

## 総評

- 通常測りは浅台・低当り優先。差玉上位は結果台として通常では座らない。
- 天井／遊タイム機は全台掲載。線入り＋座る基準のみ割り込み。液晶必須。
- BDは等価と28玉を併記。推定/実測が無い台は 1000円実測で切る（250玉交換基準）。
"""

    files[pick_name] = f"""# {store} {day} {pick_title}

分析日時: {now}（Asia/Tokyo）

数値は [台分析](台分析.md)。自動生成。換金: {rate_note}。BDは等価/28玉併記。

## 通常画面での打つ順番

| 順 | 台番号 | 機種 | やること | やめ時 |
| --- | --- | --- | --- | --- |
{order_table(order)}

## 天井ある台

| 台番号 | 機種 | 天井/遊タイム | スタート | BD（等価/28玉） | 座る基準 |
| --- | --- | --- | --- | --- | --- |
{ceiling_mini()}

## 総評

- {pick_title}も通常測りは上表優先。差玉上位は触らない。
- 遊タイム機は線入り＋座る基準だけ割り込み。
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

| 台番号 | 機種 | 天井/遊タイム | スタート | BD（等価/28玉） | 座る基準 |
| --- | --- | --- | --- | --- | --- |
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
換金: {rate_note}。BDは等価/28玉併記。自動生成（`tools/analyze_store.py`）。

## 機種別

{chr(10).join(sections)}

## 天井ある台

詳細は [天井ある台](天井ある台.md)。

| 台番号 | 機種 | 天井 | 遊タイム | スタート | BD（等価/28玉） | 座る基準 |
| --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(
    (
        f"| {r['unit']} | {r['model']} | {model_meta[r['model']]['ceiling']} | {model_meta[r['model']]['yutime']} | "
        f"{st_disp(r)} | {bd_pair(model_meta[r['model']])} | "
        f"{('ST≥' + str(sit_by_model[r['model']]['sit_start'])) if sit_by_model.get(r['model'], {}).get('sit_start') is not None else sit_by_model.get(r['model'], {}).get('line_note', '線入り')} |"
    )
    for r in sorted(ceiling_units, key=lambda x: (x['model'] or '', int(x['unit']) if str(x['unit']).isdigit() else 0))
) or '| — | — | — | — | — | — | 該当なし |'}

## 総評

- 通常測り候補: {', '.join(f"{r['unit']}" for r in order[:4]) or 'なし'}。
- 天井／遊タイム全台: {len(ceiling_units)}台（座る基準付き）。
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
    ap.add_argument("--store", required=True, help="正規店名（1店のみ。複数店はスクリプトを複数回叩く）")
    ap.add_argument("--day", default="")
    ap.add_argument("--mode", choices=["morning", "afternoon", "adhoc"], default="adhoc")
    args = ap.parse_args()
    day = args.day or default_day()
    mode = "morning" if args.mode == "morning" else "afternoon"
    store = require_one_store(args.store)
    try:
        return analyze_one(store, day, mode)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
