#!/usr/bin/env python3
"""Write 2026-11-11 evening analysis MDs from fetched CSVs."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-11-11"
AT = "2026-11-11 19:20（Asia/Tokyo）"
HAJ = "ｅ 新世紀エヴァンゲリオン ～はじまりの記憶～"


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
        rows.append(
            {
                "unit": (r.get("台番号") or "").strip(),
                "model": (r.get("機種") or "").strip(),
                "start": start,
                "hits": hits,
                "max_out": (r.get("最高出玉") or "").strip(),
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


def haj_rows(units: list[dict], avoid: set[str]) -> list[dict]:
    rows = [
        u
        for u in units
        if "はじまり" in u["model"]
        and isinstance(u["start"], int)
        and u["unit"] not in avoid
        and not (u["hits"] >= 20 or (u.get("max_out") not in {"", "--", "—", "-", "0", "10", "20"} and _imax(u.get("max_out")) >= 15000))
    ]
    # softer filter: exclude only avoid set + huge max_out
    rows = [
        u
        for u in units
        if "はじまり" in u["model"] and isinstance(u["start"], int) and u["unit"] not in avoid
    ]
    rows.sort(key=lambda u: (u["start"], u["hits"]))
    return rows


def _imax(v) -> int:
    try:
        return int(str(v).replace(",", ""))
    except Exception:
        return 0


def avoid_units(ranks: list[dict], n: int = 12) -> set[str]:
    return {r["unit"] for r in ranks[:n]}


def rank_table(ranks: list[dict], n: int = 12) -> str:
    lines = [
        "| 順位 | 台番号 | 機種 | ST | 差玉 | 扱い |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for r in ranks[:n]:
        lines.append(
            f"| {r['rank']} | {r['unit']} | {r['model']} | {r['start']} | {r['diff']} | 右のみ（結果） |"
        )
    return "\n".join(lines)


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
        "| 順 | 台番号 | 機種 | 当日スタート | 大当り | 推定/250玉 | 実測/250玉 | やること | やめ時 |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for i, row in enumerate(rows, 1):
        unit, model, start, hits, do, stop = row
        lines.append(
            f"| {i} | {unit} | {model} | {start} | {hits} | —（履歴有料／未換算） | — | {do} | {stop} |"
        )
    return "\n".join(lines)


def avoid_table(rows: list[tuple[str, str, str]]) -> str:
    lines = [
        "| 台番号 | 機種 | 理由 |",
        "| --- | --- | --- |",
    ]
    for unit, model, reason in rows:
        lines.append(f"| {unit} | {model} | {reason} |")
    return "\n".join(lines)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


def afternoon_md(
    store: str,
    units_n: int,
    note: str,
    right: list[tuple[str, str, str]],
    normal: list[tuple],
    avoid: list[tuple[str, str, str]],
    ranks: list[dict],
    border_note: str,
) -> str:
    return f"""# {store} {DAY} 午後狙い目（夜更新）

分析日時: {AT}

取得: Site Seven 出玉ランキング＋機種別全台表（集計 **{DAY}**・取得19時台）。{note}
対象台数: **{units_n}台**（無料枠でスタート判明は機種により限定。はじまり中心）。
天井／遊タイムの有無にかかわらず4円全台を対象。深さだけでは落とさない。
出玉ランキング上位は**結果順**であり狙い目ではない。
スケジュール（1時間おき／12:30）は未起動。

## 右確認（先）

{right_table(right)}

## 通常画面での打つ順番

右残し・天井／遊タイム線のあと、**通常画面だけ**の座る／測る順。結果台は入れない。

{normal_table(normal)}

- {border_note}
- 250玉実測は信頼低。継続判断は1000玉寄り。
- ST0／未更新表示は液晶の現在スタートを優先。

## 触らない

{avoid_table(avoid)}

## 出玉ランキング要約（上位）

{rank_table(ranks)}

CSV: `{store}/出玉ランキング_{DAY}.csv` / `{store}/全台データ_{DAY}.csv`
"""


def expect_md(store: str, body: str) -> str:
    return f"""# {store} {DAY} 期待値が高い台（夜更新）

分析日時: {AT}

数値の列は [台分析](台分析.md) / [午後狙い目](午後狙い目.md)。ここは通常画面の優先だけ。

## 通常画面での打つ順番

{body}

## 触らない

差玉上位の結果台は右以外触らない（午後狙い目の「触らない」参照）。
"""


def dai_haj_section(units: list[dict], avoid: set[str], title_extra: str = "") -> str:
    rows = haj_rows(units, avoid)
    lines = [
        f"### {HAJ}{title_extra}",
        "",
        "天井/遊タイム: なし（回転 vs ボーダー主根拠）。ボーダー目安 約19（28玉）／等価店は約18台。",
        "",
        "| 台番号 | スタート | 大当り | 最高出玉 | 推定/250玉 | 実測/250玉 | 所見 |",
        "| --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for u in rows[:20]:
        note = "通常測り候補" if u["unit"] not in avoid and u["hits"] <= 3 and u["start"] <= 400 else "深さ/火のあと寄り。回転次第"
        if u["unit"] in avoid:
            note = "差玉上位結果。右以外触らない"
        lines.append(
            f"| {u['unit']} | {u['start']} | {u['hits']} | {u['max_out']} | — | — | {note} |"
        )
    if len(rows) > 20:
        lines.append("")
        lines.append(f"ほか {len(rows)-20} 台は島平均〜深め。深さだけでは座らない。回転次第。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    stores_meta = {
        "楽園渋谷駅前店": {
            "rate": "28玉",
            "eq": False,
            "priority": "11/13渋谷向け最有力",
            "border": "ボーダー目安: はじまり約19（28玉）",
            "extra_note": "はじまり島の当0浅台が厚い。",
        },
        "中山UNO": {
            "rate": "等価",
            "eq": True,
            "priority": "等価で浅台厚い",
            "border": "ボーダー目安: はじまり約18（等価）",
            "extra_note": "はじまり180帯が当0浅。",
        },
        "楽園町田店": {
            "rate": "28玉・換金3.75円",
            "eq": False,
            "priority": "換金3.75。はじまりは夕方深め",
            "border": "ボーダー目安: はじまり約19／リコ約18.6（28玉）。換金3.75円",
            "extra_note": "DeltaNetで鬼・リコの累計ST補完あり（更新 2026/11/11 18:50）。",
        },
        "エスパス日拓渋谷駅前新館": {
            "rate": "28玉",
            "eq": False,
            "priority": "渋谷候補の次点",
            "border": "ボーダー目安: はじまり約19（28玉）",
            "extra_note": "牙狼／喰種の大火が多い。",
        },
        "中山ZoRoN": {
            "rate": "500円/115玉",
            "eq": True,
            "priority": "夕方ははじまり深め",
            "border": "ボーダー目安: はじまりはレート換算で厳しめ。回転必須",
            "extra_note": "40/42は結果帯。",
        },
        "楽園渋谷道玄坂店": {
            "rate": "28玉",
            "eq": False,
            "priority": "はじまり設置少",
            "border": "ボーダー目安: はじまり約19（28玉）",
            "extra_note": "130はST0表示＝液晶必須。",
        },
        "エスパス日拓西武新宿駅前店": {
            "rate": "28玉",
            "eq": False,
            "priority": "はじまり浅は限定",
            "border": "ボーダー目安: はじまり約19（28玉）",
            "extra_note": "喰種／鬼がかり結果が多い。",
        },
    }

    # per-store curated picks
    picks = {
        "楽園渋谷駅前店": {
            "right": [
                ("2010", "eカケグルイ 7500ver", "差玉1位。右のみ"),
                ("2144 / 2088", "e東京喰種", "差玉2・3位。右のみ"),
                ("1090", HAJ, "差玉4位の結果はじまり。右のみ"),
            ],
            "normal_units": ["1100", "1092", "1093", "1089", "1085", "1084"],
            "avoid_extra": [("2167 / 2161 / 2160", "e Re:ゼロから始める異世界生活 鬼がかり2", "差玉上位結果")],
        },
        "中山UNO": {
            "right": [
                ("392", "e獣王-獅子の一撃-", "差玉1位。右のみ"),
                ("271", "eF妖怪ウォッチ", "差玉2位。右のみ"),
                ("311", "e Re:ゼロから始める異世界生活 鬼がかり2", "差玉3位。右のみ"),
                ("181", HAJ, "差玉4位の結果はじまり。右のみ"),
            ],
            "normal_units": ["180", "182", "179", "303", "304", "306"],
            "avoid_extra": [("159", "e 化物語 鬼99ver.", "差玉5位結果"), ("299", "e東京喰種", "差玉6位結果")],
        },
        "楽園町田店": {
            "right": [
                ("1268 / 1255 / 1256", "e Re:ゼロから始める異世界生活 鬼がかり2", "差玉上位結果。右のみ"),
                ("1280", "e東京喰種", "差玉2位。右のみ"),
                ("1224", "eF妖怪ウォッチ", "差玉6位。右のみ"),
                ("1179", "eリコリス・リコイルM3", "差玉寄り結果（累計火）。右のみ"),
            ],
            "normal_units": ["1166", "1163", "1167"],
            "normal_extra": [
                ("1178", "eリコリス・リコイルM3", "676（DeltaNet累計）", "1", "現地ST確認→浅ければ1000円", "19未満で切。1179結果除外"),
                ("1264", "e Re:ゼロから始める異世界生活 鬼がかり2", "1483（DeltaNet累計）", "3", "深いが島内相対浅。回転測りのみ", "19未満で切。結果帯除外"),
            ],
            "avoid_extra": [
                ("1267", "e Re:ゼロから始める異世界生活 鬼がかり2", "現ST浅いが累計深＋火あり。右確認優先で通常優先にしない"),
                ("1180 / 1177", "eリコリス・リコイルM3", "累計火寄り"),
            ],
        },
        "エスパス日拓渋谷駅前新館": {
            "right": [
                ("1030 / 1034 / 1252", "e牙狼12黄金騎士極限", "差玉上位。右のみ"),
                ("1151 / 1259", "e東京喰種", "差玉上位。右のみ"),
                ("145", "Ｐ 新世紀エヴァンゲリオン -319 RED-", "差玉6位。右のみ"),
            ],
            "normal_units": ["246", "210", "240", "242"],
            "avoid_extra": [("160 / 211", HAJ, "出玉寄り。通常優先から外す")],
        },
        "中山ZoRoN": {
            "right": [
                ("15", "e牙狼12黄金騎士極限", "差玉1位。右のみ"),
                ("12", "ｅ 東京喰種 超デカ超一撃ver.", "差玉2位。右のみ"),
                ("42 / 40", HAJ, "差玉上位の結果はじまり。右のみ"),
            ],
            "normal_units": ["38", "37", "41", "39"],
            "avoid_extra": [("36", "Ｐ 新世紀エヴァンゲリオン -319 RED-", "差玉6位結果")],
        },
        "楽園渋谷道玄坂店": {
            "right": [
                ("161 / 176 / 135", "e東京喰種", "差玉上位。右のみ"),
                ("755", "デジハネP北斗の拳 慈母", "差玉2位。右のみ"),
                ("110 / 108", "e Re:ゼロから始める異世界生活 鬼がかり2", "差玉上位結果。右のみ"),
            ],
            "normal_units": ["130", "127"],
            "avoid_extra": [("128", HAJ, "出玉寄り"), ("131", HAJ, "深い")],
        },
        "エスパス日拓西武新宿駅前店": {
            "right": [
                ("1088 / 1085", "e東京喰種", "差玉上位。右のみ"),
                ("1142 / 1140", "e Re:ゼロから始める異世界生活 鬼がかり2", "差玉上位。右のみ"),
                ("1302", "P沖ドキ！LG", "ST196で差玉上位。右確認"),
            ],
            "normal_units": ["1111", "1110", "1108"],
            "avoid_extra": [("1112", HAJ, "深い")],
        },
    }

    unit_map = {}
    rank_map = {}
    for store in stores_meta:
        units = load_units(store)
        ranks = load_rank(store)
        unit_map[store] = {u["unit"]: u for u in units}
        rank_map[store] = ranks
        avoid = avoid_units(ranks)
        meta = stores_meta[store]
        p = picks[store]
        normal_rows = []
        for uid in p["normal_units"]:
            u = unit_map[store].get(uid)
            if not u:
                continue
            st = u["start"] if u["start"] is not None else "—"
            do = "1000円実測。液晶で通常確認"
            if store == "楽園渋谷道玄坂店" and uid == "130":
                do = "ST0表示。液晶で現在スタート確定後に1000円"
            stop = "19未満で即切" if not meta["eq"] else "18未満で即切"
            normal_rows.append((uid, u["model"], st, u["hits"], do, stop))
        for extra in p.get("normal_extra", []):
            normal_rows.append(extra)

        avoid_rows = []
        for r in ranks[:8]:
            avoid_rows.append((r["unit"], r["model"], f"差玉{r['rank']}位 +{r['diff']}"))
        avoid_rows.extend(p.get("avoid_extra", []))

        note = f"{meta['rate']}。{meta['extra_note']} {meta['priority']}。"
        md = afternoon_md(
            store,
            len(units),
            note,
            p["right"],
            normal_rows,
            avoid_rows,
            ranks,
            meta["border"],
        )
        write(ROOT / DAY / store / "午後狙い目.md", md)

        # 期待値
        body_lines = [
            "| 順 | 台番号 | 機種 | やること | やめ時 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for i, row in enumerate(normal_rows, 1):
            body_lines.append(f"| {i} | {row[0]} | {row[1]} | {row[4]} | {row[5]} |")
        write(ROOT / DAY / store / "期待値が高い台.md", expect_md(store, "\n".join(body_lines)))

        # 台分析（はじまり中心＋町田は追加）
        dai = [
            f"# {store} {DAY} 台分析（夜更新）",
            "",
            f"分析日時: {AT}",
            "",
            f"対象: Site Seven 全台 **{len(units)}台**（スタート無料判明は機種限定）。数値はこの表だけ。",
            "天井なし台も深さ除外せず、判明スタートとボーダーで所見。",
            "",
            "## 機種別",
            "",
            dai_haj_section(units, avoid),
        ]
        if store == "楽園町田店":
            dai.append("### eリコリス・リコイルM3（DeltaNet累計）\n")
            dai.append("天井/遊タイム: なし。ボーダー約18.6（28玉）。\n")
            dai.append("| 台番号 | 累計スタート | 現ST | 大当り | 推定/250玉 | 実測/250玉 | 所見 |")
            dai.append("| --- | ---: | ---: | ---: | --- | --- | --- |")
            rico = [
                ("1178", 676, 558, 1, "島内最浅累計・冷え。測り"),
                ("1175", 1226, 157, 20, "火のあと。優先下げ"),
                ("1182", 1293, 138, 8, "次点候補"),
                ("1176", 1398, 132, 9, "次点"),
                ("1179", 1500, 29, 45, "結果帯。触らない"),
                ("1181", 1639, 339, 35, "火寄り"),
                ("1180", 1674, 115, 28, "火寄り"),
                ("1177", 2091, 430, 27, "深い・火"),
            ]
            for u, cum, st, h, note2 in rico:
                dai.append(f"| {u} | {cum} | {st} | {h} | — | — | {note2} |")
            dai.append("")
            dai.append("### e Re:ゼロから始める異世界生活 鬼がかり2（DeltaNet累計）\n")
            dai.append("天井/遊タイム: なし。ボーダー約18.0（28玉）。\n")
            dai.append("| 台番号 | 累計スタート | 現ST | 大当り | 推定/250玉 | 実測/250玉 | 所見 |")
            dai.append("| --- | ---: | ---: | ---: | --- | --- | --- |")
            oni = [
                ("1264", 1483, 125, 3, "島内相対浅・冷え寄り。測り次点"),
                ("1266", 1663, 1328, 3, "現ST深い"),
                ("1257", 1721, 87, 16, "差玉寄り。右以外触らない"),
                ("1267", 1890, 19, 9, "現ST浅いが累計深。右確認優先"),
                ("1268", 3339, 273, 46, "差玉1位結果。触らない"),
                ("1255", None, 42, 44, "差玉3位結果。触らない"),
            ]
            # fix 1255/1268 cum from rank if needed
            for u, cum, st, h, note2 in oni:
                cum_s = cum if cum is not None else "—"
                dai.append(f"| {u} | {cum_s} | {st} | {h} | — | — | {note2} |")
            dai.append("")
            dai.append("その他機種の無料スタートは `--` が多い。ランキング結果台は右のみ。深さだけでは対象外にしない。\n")
        dai.append("## 総評\n")
        dai.append(f"- 通常測りの主軸ははじまり浅台。{meta['priority']}。")
        dai.append("- 出玉ランキングは結果確認用。狙い順に混ぜない。")
        write(ROOT / DAY / store / "台分析.md", "\n".join(dai))

    # unavailable
    unavail = {
        "PIA町田": "台DATA ONLINE 非公開（店舗情報のみ／403）",
        "マルハン新宿東宝ビル店": "DMM台データWeb アプリ誘導／Web全台CSVなし",
        "エスパス日拓新宿歌舞伎町店": "DMM台データWeb アプリ誘導／Web全台CSVなし",
        "カレイド新宿店": "Web全台CSV経路なし（アプリ/pscube寄り）",
        "楽園池袋店": "DMMぱちタウン中心で深い履歴・全台CSV不可",
    }
    for store, reason in unavail.items():
        write(
            ROOT / DAY / store / "分析不可.md",
            f"""# {store} {DAY} 分析不可

分析日時: {AT}

- 理由: {reason}
- 台番号つきの通常測り順は作れない（液晶前提）。
- スケジュール未起動。
""",
        )
        write(
            ROOT / DAY / store / "生データ取得結果.md",
            f"""# {store} 生データ取得結果（夜再取得）

取得日時: {AT}

- 取得: 不可
- 理由: {reason}
- 分析: 不可（理由のみ）
""",
        )
        write(
            ROOT / DAY / store / "期待値が高い台.md",
            f"""# {store} {DAY} 期待値が高い台

分析日時: {AT}

取得不可のため台番号つきの期待値順は書けない。

## 通常画面での打つ順番

| 順 | 台番号 | 機種 | やること | やめ時 |
| --- | --- | --- | --- | --- |
| 1 | （現地で番号確定） | （設置機種を液晶確認） | データなし。回転実測のみ | ボーダー未満で切 |

理由: {reason}
""",
        )

    # raw results update for ok stores
    counts = {s: len(load_units(s)) for s in stores_meta}
    for store, n in counts.items():
        extra = ""
        if store == "楽園町田店":
            extra = """
## DeltaNet

- 取得: OK（主要12機種 / 182台指標。更新 `2026/11/11 18:50`）
- 保存先: `楽園町田店/<機種>/<台番号>/`
"""
        write(
            ROOT / DAY / store / "生データ取得結果.md",
            f"""# {store} 生データ取得結果（夜再取得）

取得日時: {AT}

- ホール集計期間（Site Seven）: `{DAY}` 営業中〜夜
- 全台: `{store}/全台データ_{DAY}.csv`（{n}台）
- ランキング: `{store}/出玉ランキング_{DAY}.csv`（30行）
- ソース: Site Seven 無料枠
- 分析: 午後狙い目／台分析／期待値（夜更新）
{extra}""",
        )

    write(
        ROOT / DAY / "生データ取得結果.md",
        f"""# 生データ取得結果（全店舗・夜再取得）

取得日時: {AT}

日付フォルダ: `{DAY}`

Site Seven 集計: **{DAY} 営業中〜夜**（朝の前日集計から取り直し）。

## 取得できた店舗

| 店舗 | 全台台数 | ランキング | 主な保存 | ソース |
| --- | ---: | ---: | --- | --- |
| 中山UNO | {counts['中山UNO']} | 30 | `中山UNO/全台データ_{DAY}.csv` | Site Seven |
| 中山ZoRoN | {counts['中山ZoRoN']} | 30 | `中山ZoRoN/全台データ_{DAY}.csv` | Site Seven |
| エスパス日拓西武新宿駅前店 | {counts['エスパス日拓西武新宿駅前店']} | 30 | `エスパス日拓西武新宿駅前店/全台データ_{DAY}.csv` | Site Seven |
| 楽園町田店 | {counts['楽園町田店']} | 30 | `楽園町田店/全台データ_{DAY}.csv` | Site Seven＋DeltaNet補完 |
| 楽園渋谷駅前店 | {counts['楽園渋谷駅前店']} | 30 | `楽園渋谷駅前店/全台データ_{DAY}.csv` | Site Seven |
| 楽園渋谷道玄坂店 | {counts['楽園渋谷道玄坂店']} | 30 | `楽園渋谷道玄坂店/全台データ_{DAY}.csv` | Site Seven |
| エスパス日拓渋谷駅前新館 | {counts['エスパス日拓渋谷駅前新館']} | 30 | `エスパス日拓渋谷駅前新館/全台データ_{DAY}.csv` | Site Seven |

## 取得不可

| 店舗 | 理由 |
| --- | --- |
| PIA町田 | 台DATA ONLINE 非公開 |
| マルハン新宿東宝ビル店 | DMM台データWeb アプリ誘導 |
| エスパス日拓新宿歌舞伎町店 | 同上 |
| カレイド新宿店 | Web全台CSV経路なし |
| 楽園池袋店 | 同上 |
""",
    )

    write(
        ROOT / DAY / "店舗横断優先メモ.md",
        f"""# {DAY} 店舗横断 優先メモ（夜更新）

分析日時: {AT}

データは **{DAY} 営業中〜夜**（Site Seven 無料枠。町田は DeltaNet 主要機種補完）。スケジュール未起動。
11/13 は渋谷駅周辺予定。

## データ範囲

| 店舗 | 全台 | 主な根拠 | 制約 |
| --- | --- | --- | --- |
| 楽園渋谷駅前店 | {counts['楽園渋谷駅前店']}台 | はじまり当0浅が厚い | 11/13向け最有力 |
| 中山UNO | {counts['中山UNO']}台 | はじまり180帯当0 | 等価 |
| 楽園町田店 | {counts['楽園町田店']}台 | はじまり1166帯＋リコ1178 | 換金3.75。はじまりは夕方深め |
| エスパス日拓渋谷駅前新館 | {counts['エスパス日拓渋谷駅前新館']}台 | はじまり246 | 牙狼／喰種大火多 |
| 楽園渋谷道玄坂店 | {counts['楽園渋谷道玄坂店']}台 | はじまり130/127 | 設置少。130はST0液晶必須 |
| エスパス日拓西武新宿駅前店 | {counts['エスパス日拓西武新宿駅前店']}台 | はじまり1111 | 結果台多 |
| 中山ZoRoN | {counts['中山ZoRoN']}台 | はじまり38/37 | 夕方深め。40/42結果 |
| マルハン東宝／エスパス歌舞伎町／カレイド／楽園池袋／PIA | 不可 | — | 理由のみ |

## 打つなら（短い優先）

1. **楽園渋谷駅前店** … はじまり **1100 / 1092 / 1093 / 1089**（当0浅）。11/13向け。
2. **中山UNO** … はじまり **180 / 182 / 179 / 303**（当0浅）。等価。
3. **エスパス渋谷新館** … はじまり **246 / 210 / 240**。
4. **楽園渋谷道玄坂店** … はじまり **127**（＋130は液晶）。
5. **楽園町田店** … はじまり **1166 / 1163**、リコ **1178**（DeltaNet）。換金3.75。
6. **西武新宿** … はじまり **1111**。
7. **ZoRoN** … はじまり **38 / 37**（結果の40/42は除外）。
8. 不可5店 … 触れないか液晶だけ。

詳細は各店の午後狙い目。出玉ランキングは結果確認用。
""",
    )


if __name__ == "__main__":
    main()
