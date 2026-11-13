#!/usr/bin/env python3
"""Write 2026-11-13 morning analysis MDs for Shibuya 3 stores."""
from __future__ import annotations

import csv
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from brief import load_guides, match_guide, short_flag  # noqa: E402

DAY = "2026-11-13"
AT = "2026-11-13 10:01（Asia/Tokyo）"
HAJ = "ｅ 新世紀エヴァンゲリオン ～はじまりの記憶～"
DATA_NOTE = (
    "Site Seven 集計期間は **11/12(木)**（取得 2026-11-13 09:57〜）。"
    "日付フォルダは朝イチ対象日 `2026-11-13`。"
)
STORES = ["楽園渋谷駅前店", "楽園渋谷道玄坂店", "エスパス日拓渋谷駅前新館"]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


def load_units(store: str) -> list[dict]:
    path = ROOT / store / f"全台データ_{DAY}.csv"
    rows = []
    for r in csv.DictReader(path.open(encoding="utf-8-sig")):
        st = (r.get("累計スタート") or "").strip()
        try:
            start = int(st.replace(",", "")) if st not in {"", "-", "—", "--"} else None
        except ValueError:
            start = None
        try:
            hits = int(str(r.get("大当り回数") or "0").replace(",", "").replace("--", "0") or 0)
        except ValueError:
            hits = 0
        try:
            max_out = int(str(r.get("最高出玉") or "0").replace(",", "").replace("--", "0") or 0)
        except ValueError:
            max_out = 0
        rows.append(
            {
                "unit": (r.get("台番号") or "").strip(),
                "model": (r.get("機種") or "").strip(),
                "start": start,
                "hits": hits,
                "max_out": max_out,
            }
        )
    return rows


def load_rank(store: str) -> list[dict]:
    path = ROOT / store / f"出玉ランキング_{DAY}.csv"
    out = []
    for r in csv.DictReader(path.open(encoding="utf-8-sig")):
        out.append(
            {
                "rank": (r.get("順位") or "").strip(),
                "unit": (r.get("台番号") or "").strip(),
                "model": (r.get("機種") or "").strip(),
                "start": (r.get("累計スタート") or "").strip(),
                "hits": (r.get("大当り回数") or "").strip(),
                "diff": (r.get("差玉") or "").strip(),
            }
        )
    return out


def copy_csvs(store: str) -> None:
    day_dir = ROOT / DAY / store
    day_dir.mkdir(parents=True, exist_ok=True)
    for name in (f"全台データ_{DAY}.csv", f"出玉ランキング_{DAY}.csv"):
        src = ROOT / store / name
        if src.exists():
            shutil.copy2(src, day_dir / name)


def right_table(rows: list[tuple[str, str, str]]) -> str:
    lines = [
        "| 順 | 台番号 | 機種 | メモ |",
        "| --- | --- | --- | --- |",
    ]
    for i, (unit, model, memo) in enumerate(rows, 1):
        lines.append(f"| {i} | {unit} | {model} | {memo} |")
    return "\n".join(lines)


def normal_table(rows: list[tuple]) -> str:
    lines = [
        "| 順 | 台番号 | 機種 | やること | やめ時 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i, row in enumerate(rows, 1):
        unit, model, do, stop = row[0], row[1], row[2], row[3]
        lines.append(f"| {i} | {unit} | {model} | {do} | {stop} |")
    return "\n".join(lines)


def avoid_table(rows: list[tuple[str, str, str]]) -> str:
    lines = [
        "| 台番号 | 機種 | 理由 |",
        "| --- | --- | --- |",
    ]
    for unit, model, reason in rows:
        lines.append(f"| {unit} | {model} | {reason} |")
    return "\n".join(lines)


def important_right_table(rows: list[tuple[str, str, str, str]]) -> str:
    lines = [
        "| 順 | 台番号 | 機種 | 前日の最後 | 画面が右打ちなら | 通常画面なら |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, (unit, model, last, action) in enumerate(rows, 1):
        lines.append(
            f"| {i} | {unit} | {model} | {last} | 右残し確認→通常待ち | {action} |"
        )
    return "\n".join(lines)


def rank_table(ranks: list[dict], n: int = 10) -> str:
    lines = [
        "| 順位 | 台番号 | 機種 | ST | 差玉 | 扱い |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for r in ranks[:n]:
        lines.append(
            f"| {r['rank']} | {r['unit']} | {r['model']} | {r['start']} | {r['diff']} | 右のみ（結果） |"
        )
    return "\n".join(lines)


def ceiling_label(guide: dict | None) -> str:
    if not guide:
        return "攻略なし／天井・遊タイム未確認"
    c = short_flag(guide.get("ceiling"))
    y = short_flag(guide.get("yutime"))
    bd = guide.get("border_28") or "—"
    bits = []
    if c not in {"—", "非搭載"}:
        bits.append(f"天井: {guide.get('ceiling','').strip()}")
    else:
        bits.append(f"天井: {c}")
    if y not in {"—", "非搭載"}:
        bits.append(f"遊タイム: {guide.get('yutime','').strip()}")
    else:
        bits.append(f"遊タイム: {y}")
    return f"{' / '.join(bits)}。ボーダー目安 約{bd}（28玉）"


def note_for(u: dict, avoid: set[str], guide: dict | None) -> str:
    if u["unit"] in avoid:
        return "差玉上位結果。右以外触らない"
    st = u["start"]
    if st is None:
        return "スタート不明。液晶確認"
    y = (guide or {}).get("yutime") or ""
    c = (guide or {}).get("ceiling") or ""
    has_yu = y and "非" not in y and y not in {"—", "-", "なし", "調査中"}
    has_c = c and "非" not in c and c not in {"—", "-", "なし", "調査中"}
    if has_yu or has_c:
        # remaining estimate only if we know threshold
        import re

        nums = re.findall(r"(\d{2,4})", y or c)
        thr = int(nums[0]) if nums else None
        if thr and st >= thr - 80:
            return f"遊タイム／天井線寄り（ST{st}）。液晶の残り確認"
        if thr and st >= thr // 2:
            return "中盤。深さだけでは座らない。回転／残り次第"
        if u["hits"] <= 2 and st <= 500:
            return "浅・冷え寄り。通常測り候補（遊タイム機も回転確認）"
        return "遊タイム／天井機。深さだけでは座らない。回転次第"
    if u["hits"] <= 3 and st <= 500:
        return "通常測り候補（浅・冷え寄り）"
    if u["hits"] <= 5 and st <= 900:
        return "次点。回転次第"
    if u["max_out"] >= 15000 or u["hits"] >= 20:
        return "出玉寄り。通常優先から外す"
    return "深さ/火のあと寄り。深さだけでは座らない。回転次第"


def model_section(model: str, units: list[dict], avoid: set[str], guides: dict) -> str:
    guide = match_guide(model, guides)
    rows = [u for u in units if u["model"] == model]
    rows.sort(key=lambda u: (u["start"] is None, u["start"] if u["start"] is not None else 10**9, u["hits"]))
    lines = [
        f"### {model}",
        "",
        ceiling_label(guide),
        "",
        "| 台番号 | スタート | 大当り | 最高出玉 | 推定/250玉 | 実測/250玉 | 所見 |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    show = rows
    trunc = False
    if len(rows) > 40:
        # keep shallow-ish + avoid + first 30
        keep = []
        seen = set()
        for u in rows:
            if u["unit"] in avoid or (u["start"] is not None and u["start"] <= 1200) or u["hits"] <= 2:
                keep.append(u)
                seen.add(u["unit"])
        for u in rows:
            if u["unit"] in seen:
                continue
            keep.append(u)
            seen.add(u["unit"])
            if len(keep) >= 35:
                break
        show = keep
        trunc = len(rows) > len(show)
    for u in show:
        st = "—" if u["start"] is None else str(u["start"])
        lines.append(
            f"| {u['unit']} | {st} | {u['hits']} | {u['max_out']} | —（履歴有料／未換算） | — | {note_for(u, avoid, guide)} |"
        )
    if trunc:
        lines.append("")
        lines.append(f"ほか {len(rows) - len(show)} 台は島平均〜深め。深さだけでは座らない。回転次第。")
    lines.append("")
    return "\n".join(lines)


def build_dai(store: str, units: list[dict], avoid: set[str], guides: dict, priority: str) -> str:
    by_model: dict[str, int] = defaultdict(int)
    for u in units:
        by_model[u["model"]] += 1
    # prioritize はじまり / 遊タイム / high count
    def sort_key(m: str) -> tuple:
        g = match_guide(m, guides)
        yu = (g or {}).get("yutime") or ""
        ce = (g or {}).get("ceiling") or ""
        has = 0
        if yu and "非" not in yu and yu not in {"—", "-"}:
            has = 0
        elif ce and "非" not in ce and ce not in {"—", "-"}:
            has = 0
        else:
            has = 1
        pri = 0 if ("はじまり" in m or "アグネス" in m or "スペシャル" in m or "season2" in m or "ARBC" in m or "HCL" in m) else 1
        return (pri, has, -by_model[m], m)

    models = sorted(by_model, key=sort_key)
    parts = [
        f"# {store} {DAY} 台分析",
        "",
        f"分析日時: {AT}",
        "",
        f"対象: Site Seven 全台 **{len(units)}台**（無料枠でスタート判明の機種）。数値はこの表だけ。",
        DATA_NOTE,
        "天井・遊タイムの有無を問わず4円全台を機種ごとに載せる。天井なしは深さ除外せず、判明スタートとボーダーで所見。",
        "",
        "## 機種別",
        "",
    ]
    for m in models:
        parts.append(model_section(m, units, avoid, guides))
    parts.extend(
        [
            "## 総評",
            "",
            f"- {priority}",
            "- 出玉ランキングは結果確認用。狙い順に混ぜない。",
            f"- 無料枠の全台表は機種により制限あり（今回 {len(units)} 台）。",
            "",
        ]
    )
    return "\n".join(parts)


def main() -> None:
    guides = load_guides()
    picks = {
        "楽園渋谷駅前店": {
            "rate": "28玉",
            "priority": "11/13渋谷向け最有力。はじまり浅（1095当0〜）が厚い",
            "border_stop": "19未満で即切",
            "open": "10:00（抽選あり）",
            "reset": "日次リセットする傾向。閉店スタート持ち越し前提にしない。液晶必須",
            "right": [
                ("2144 / 2086 / 2128", "e東京喰種", "差玉1・4・8位。右のみ"),
                ("1094 / 1090 / 1045", HAJ, "差玉上位の結果はじまり。右のみ"),
                ("1054", "P新世紀エヴァンゲリオン１５　未来への咆哮", "差玉3位。右のみ"),
                ("1019 / 1026", "Ｐ 新世紀エヴァンゲリオン -319 RED-", "差玉6・10位。右のみ"),
            ],
            "normal": [
                ("1095", HAJ, "1000円実測。液晶で通常確認（ST321・当0）", "19未満で即切"),
                ("1083", HAJ, "同上（ST398・当1）", "19未満で切"),
                ("1047", HAJ, "同上（ST436・当1）", "19未満で切"),
                ("1093", HAJ, "同上（ST450・当1）", "19未満で切"),
                ("1098", HAJ, "同上（ST616・当1）", "19未満で切"),
                ("1101", HAJ, "同上（ST630・当1）", "19未満で切"),
                ("2156", "e Re：ゼロから始める異世界生活 season2 M13", "天井・遊タイム調査中。相対浅（ST308・当2）。液晶確認→測り", "19.5目安未満で切"),
                ("2109", "eリコリス・リコイルM3", "相対浅（ST150・当0）。回転必須", "18.6未満で切"),
            ],
            "avoid_extra": [
                ("1092", HAJ, "当7・出玉寄り。通常優先から外す"),
                ("1089 / 1090 / 1045", HAJ, "差玉上位／出玉寄り"),
                ("2155 / 2152", "e Re：ゼロから始める異世界生活 season2 M13", "火寄り"),
            ],
            "imp_right": [
                ("2144", "e東京喰種", "差玉1位 +74740", "通常なら見送り（結果）"),
                ("1094", HAJ, "差玉2位 +58070", "通常なら見送り"),
                ("1054", "P新世紀エヴァンゲリオン１５　未来への咆哮", "差玉3位 +55270", "通常なら見送り"),
            ],
        },
        "楽園渋谷道玄坂店": {
            "rate": "28玉",
            "priority": "はじまり設置少。遊タイム機（アグネスプレミア）とseason2浅を併記",
            "border_stop": "19未満で即切（アグネスは18.3目安）",
            "open": "10:00前後",
            "reset": "日次リセット。ST0表示は現在スタートを液晶で確定",
            "right": [
                ("176 / 163 / 170 / 151", "e東京喰種", "差玉上位。右のみ"),
                ("630", "eとある魔術の禁書目録3", "差玉2位。右のみ"),
                ("111", "e Re:ゼロから始める異世界生活 鬼がかり2", "差玉4位。右のみ"),
                ("202", "Pとある科学の超電磁砲FSB", "差玉5位。右のみ"),
            ],
            "normal": [
                ("130", HAJ, "1000円実測（ST523・当1）。液晶で通常確認", "19未満で即切"),
                ("128", HAJ, "次点（ST374・当5）。火あと寄りだが相対浅", "19未満で切"),
                ("123", "e Re：ゼロから始める異世界生活 season2 M13", "ST16・当0。調査中機。液晶確認→測り", "19.5目安未満で切"),
                ("122", "e Re：ゼロから始める異世界生活 season2 M13", "ST267・当2。同上", "19.5目安未満で切"),
                ("60", "PA大海物語アグネスプレミアRBA", "ST0表示。遊タイム機。液晶で現在ST／残り確認後に測り", "18.3未満で切"),
                ("61", "PA大海物語アグネスプレミアRBA", "ST0表示。同上", "18.3未満で切"),
                ("676", "eリコリス・リコイルM3", "相対浅（ST38・当0）", "18.6未満で切"),
            ],
            "avoid_extra": [
                ("131 / 127", HAJ, "深め／出玉寄り。優先下げ"),
                ("125 / 126", "e Re：ゼロから始める異世界生活 season2 M13", "火・深い"),
                ("58 / 57", "PA大海物語アグネスプレミアRBA", "出玉寄り"),
            ],
            "imp_right": [
                ("176", "e東京喰種", "差玉1位 +44960", "通常なら見送り"),
                ("630", "eとある魔術の禁書目録3", "差玉2位 +39520", "通常なら見送り"),
                ("163", "e東京喰種", "差玉3位 +34240", "通常なら見送り"),
            ],
        },
        "エスパス日拓渋谷駅前新館": {
            "rate": "28玉",
            "priority": "はじまり212が相対浅。ARBC遊タイム線（110）と未来への咆哮浅を併記。結果帯は鬼がかり／牙狼／喰種",
            "border_stop": "19未満で即切（ARBCは18.0目安）",
            "open": "10:00前後",
            "reset": "液晶確認必須",
            "right": [
                ("184 / 223", "e Re:ゼロから始める異世界生活 鬼がかり2", "差玉1・2位。右のみ"),
                ("1098", "eとある魔術の禁書目録3", "差玉3位。右のみ"),
                ("1054 / 1022 / 1043", "e牙狼12黄金騎士極限", "差玉上位。右のみ"),
                ("1146 / 1145", "e東京喰種", "差玉上位。右のみ"),
            ],
            "normal": [
                ("212", HAJ, "1000円実測（ST470・当1）。島内最浅帯", "19未満で即切"),
                ("210", HAJ, "同上（ST726・当0）", "19未満で切"),
                ("241", HAJ, "同上（ST767・当1）", "19未満で切"),
                ("248", HAJ, "次点（ST733・当3）", "19未満で切"),
                ("143", "P新世紀エヴァンゲリオン１５　未来への咆哮", "相対浅（ST217・当0）。回転必須", "19.1未満で切"),
                ("110", "PA大海物語５ ARBC", "遊タイム機。ST15・当0。液晶で残り／通常確認→測り", "18.0未満で切"),
                ("149", "Ｐ 新世紀エヴァンゲリオン -319 RED-", "相対浅（ST752・当1）", "17.5未満で切"),
            ],
            "avoid_extra": [
                ("211 / 247 / 245", HAJ, "出玉寄り。通常優先から外す"),
                ("1236〜1250帯", "P大海物語5スペシャル", "遊タイム機だが累計2000超が多く深さ寄り。残り液晶必須"),
                ("1221", "eF妖怪ウォッチ", "差玉9位結果"),
            ],
            "imp_right": [
                ("184", "e Re:ゼロから始める異世界生活 鬼がかり2", "差玉1位 +73010", "通常なら見送り"),
                ("223", "e Re:ゼロから始める異世界生活 鬼がかり2", "差玉2位 +70550", "通常なら見送り"),
                ("1098", "eとある魔術の禁書目録3", "差玉3位 +69860", "通常なら見送り"),
            ],
        },
    }

    counts: dict[str, int] = {}
    for store in STORES:
        meta = picks[store]
        copy_csvs(store)
        units = load_units(store)
        ranks = load_rank(store)
        counts[store] = len(units)
        avoid = {r["unit"] for r in ranks[:12]}
        p = picks[store]
        normal = p["normal"]
        avoid_rows = [(r["unit"], r["model"], f"差玉{r['rank']}位 +{r['diff']}") for r in ranks[:8]]
        avoid_rows.extend(p.get("avoid_extra", []))

        write(
            ROOT / DAY / store / "朝イチ狙い目.md",
            f"""# {store} {DAY} 朝イチ狙い目

分析日時: {AT}

{DATA_NOTE}
{meta['rate']}。{meta['priority']}。
数値の列は [台分析](台分析.md)。ここは通常画面で座る順だけ。
出玉ランキングは**結果順**であり狙い目ではない。スケジュール未起動。

## 通常画面での打つ順番

右残し・天井／遊タイム線のあと、**通常画面だけ**の座る／測る順。

{normal_table(normal)}

- やめ時: {meta['border_stop']}
- 250玉実測は信頼低。継続判断は1000玉寄り。
- {meta['reset']}

## 参照

- [重要ポイント](重要ポイント.md) / [期待値が高い台](期待値が高い台.md) / [台分析](台分析.md)
""",
        )

        write(
            ROOT / DAY / store / "重要ポイント.md",
            f"""# {store} {DAY} 重要ポイント

分析日時: {AT}

{DATA_NOTE}
開店目安: {meta['open']}。{meta['reset']}。
台の指定は台番号＋機種名。出玉ランキングは結果確認用。

## 開店で最初に見る台（右確認）

{important_right_table(p['imp_right'])}

## 通常画面での打つ順番

上の右確認が全部通常だったあと、この順で座る／測る（[朝イチ狙い目](朝イチ狙い目.md) と同順）。

{normal_table(normal)}

## 触らない / 注意

{avoid_table(avoid_rows)}

## 右確認メモ（結果帯）

{right_table(p['right'])}

関連: [台分析](台分析.md) / [期待値が高い台](期待値が高い台.md)
""",
        )

        write(
            ROOT / DAY / store / "期待値が高い台.md",
            f"""# {store} {DAY} 期待値が高い台

分析日時: {AT}

数値の列は [台分析](台分析.md) / [朝イチ狙い目](朝イチ狙い目.md)。ここは通常画面の優先だけ。

## 通常画面での打つ順番

{normal_table(normal)}

## 触らない

差玉上位の結果台は右以外触らない（重要ポイントの「触らない」参照）。
""",
        )

        write(
            ROOT / DAY / store / "午後狙い目.md",
            f"""# {store} {DAY} 午後狙い目

分析日時: {AT}

朝イチ時点の持ち越し。当日の出玉が動いたら差玉上位を「触らない」へ移し、通常順を差し替える。
{DATA_NOTE}

## 右確認（先）

{right_table(p['right'])}

## 通常画面での打つ順番

{normal_table(normal)}

## 触らない

{avoid_table(avoid_rows)}

## 出玉ランキング要約（上位・結果確認用）

{rank_table(ranks)}

CSV: `{store}/出玉ランキング_{DAY}.csv` / `{store}/全台データ_{DAY}.csv`
""",
        )

        write(ROOT / DAY / store / "台分析.md", build_dai(store, units, avoid, guides, meta["priority"]))

        write(
            ROOT / DAY / store / "生データ取得結果.md",
            f"""# {store} 生データ取得結果

取得日時: 2026-11-13 09:57〜09:59（Asia/Tokyo）

- ホール集計期間（Site Seven）: `11/12(木)`
- 全台: `{store}/全台データ_{DAY}.csv`（{len(units)}台）
- ランキング: `{store}/出玉ランキング_{DAY}.csv`（30行）
- ソース: Site Seven 無料枠
- 分析: 朝イチ狙い目／重要ポイント／台分析／期待値／午後狙い目
""",
        )

    write(
        ROOT / DAY / "店舗横断優先メモ-渋谷.md",
        f"""# {DAY} 店舗横断 優先メモ（渋谷3店・朝イチ）

分析日時: {AT}

{DATA_NOTE}
**11/13 は渋谷駅周辺予定**。スケジュール未起動。換金は3店とも28玉。

## データ範囲

| 店舗 | 全台 | 主な根拠 | 制約 |
| --- | --- | --- | --- |
| 楽園渋谷駅前店 | {counts['楽園渋谷駅前店']}台 | はじまり1095/1083/1047当0〜1浅 | 11/13向け最有力 |
| エスパス日拓渋谷駅前新館 | {counts['エスパス日拓渋谷駅前新館']}台 | はじまり212＋ARBC110遊タイム | 鬼がかり／牙狼／喰種の大火多 |
| 楽園渋谷道玄坂店 | {counts['楽園渋谷道玄坂店']}台 | はじまり130/128＋アグネスST0液晶 | はじまり設置少。遊タイム線は液晶必須 |

## 打つなら（短い優先）

1. **楽園渋谷駅前店** … はじまり **1095 / 1083 / 1047 / 1093 / 1098 / 1101**。次点 season2 **2156**、リコ **2109**。
2. **エスパス渋谷新館** … はじまり **212 / 210 / 241**。遊タイム **ARBC 110**。未来への咆哮 **143**。
3. **楽園渋谷道玄坂店** … はじまり **130 / 128**。season2 **123 / 122**。アグネス **60 / 61（液晶）**。

出玉ランキングは結果確認用（右以外触らない）。詳細は各店の朝イチ狙い目／重要ポイント。
""",
    )


if __name__ == "__main__":
    main()
