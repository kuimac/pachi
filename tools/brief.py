#!/usr/bin/env python3
"""分析エージェント向けの短い要約。店舗一覧・攻略・台CSVは読ませず、この出力だけを渡す。"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STORES_FILE = ROOT / "店舗一覧.md"
SNAP_DIR = ROOT / "tools" / "brief_snapshots"

STORE_FIELDS = (
    "別名",
    "地域",
    "最寄り駅",
    "営業時間",
    "朝の入場",
    "交換",
    "貸出",
    "日次集計リセット",
    "台スタートリセット",
    "データ更新目安",
    "無料取得範囲",
    "右打ち持ち越し",
    "分析URL",
    "レート注記",
)

GUIDE_ALIASES = {
    "鬼がかり2": "e Re:ゼロから始める異世界生活 鬼がかり2",
    "鬼がかり": "e Re:ゼロから始める異世界生活 鬼がかり2",
    "電音部": "Pドラムde電音部 超ドラ熱4500Ver",
    "リコリコm3": "eリコリス・リコイルM3",
    "はじまりの記憶": "e 新世紀エヴァンゲリオン ～はじまりの記憶～",
    "アグネスプレミア": "PA大海物語Withアグネス・ラム Premium Edition",
    "大海物語アグネスプレミア": "PA大海物語Withアグネス・ラム Premium Edition",
    "大海物語5 hcl": "P大海物語５ HCL",
    "大海物語５ hcl": "P大海物語５ HCL",
    "ニュートキオv1": "PニュートキオV1",
    "大海物語5 arbc": "PA大海物語５ ARBC",
    "大海物語５ arbc": "PA大海物語５ ARBC",
}


def now_tokyo() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M")


def today_tokyo() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")


def norm(name: str) -> str:
    s = name
    for a, b in (
        ("：", ":"),
        ("～", "〜"),
        ("－", "-"),
        ("　", " "),
        ("／", "/"),
        ("ｅ", "e"),
        ("Ｐ", "P"),
        ("Ａ", "A"),
        ("ｖｅｒ", "ver"),
        ("Ｖｅｒ", "Ver"),
        ("．", "."),
    ):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def parse_int(val: str | None) -> int | None:
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("−", "-")
    if s in {"", "-", "—", "--"}:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def load_store_blocks() -> dict[str, dict[str, str]]:
    blocks: dict[str, dict[str, str]] = {}
    current = ""
    if not STORES_FILE.exists():
        return blocks
    for line in STORES_FILE.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##\s+(.+)$", line.strip())
        if heading:
            current = heading.group(1).strip()
            blocks[current] = {}
            continue
        if not current:
            continue
        match = re.match(r"^-\s*([^:：]+)\s*[:：]\s*(.+)$", line.strip())
        if match:
            blocks[current][match.group(1).strip()] = match.group(2).strip()
    return blocks


def resolve_store(query: str, blocks: dict[str, dict[str, str]]) -> str:
    q = query.strip()
    if q in blocks:
        return q
    exact: list[str] = []
    for name, fields in blocks.items():
        aliases = [a.strip() for a in re.split(r"[,、]", fields.get("別名", "")) if a.strip()]
        if q in aliases:
            exact.append(name)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise SystemExit(f"店名が複数に一致: {', '.join(exact)}")
    nq = norm(q)
    fuzzy = [name for name in blocks if nq and nq in norm(name)]
    if len(fuzzy) == 1:
        return fuzzy[0]
    names = "、".join(blocks)
    raise SystemExit(f"店が見つからない: {query}\n正規店名: {names}")


def _prefer_text(old: str, new: str) -> str:
    """空より実値、非搭載より搭載の記述を残す。"""
    new = new.strip()
    if not new:
        return old
    if not old:
        return new
    if "非" in old and "非" not in new:
        return new
    return old


def load_guides() -> dict[str, dict]:
    guides: dict[str, dict] = {}
    for folder in (ROOT / "攻略情報",):
        if not folder.is_dir():
            continue
        for path in folder.glob("*.md"):
            if path.name == "パチンコ用語一覧.md":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            meta = guides.get(path.stem) or guides.get(norm(path.stem))
            if meta is None:
                meta = {"name": path.stem, "ceiling": "", "yutime": "", "border_28": None, "border_eq": None}
            if folder.name == "攻略情報":
                meta["name"] = path.stem
            m = re.search(r"\|\s*3\.57円（28玉）\s*\|\s*([0-9.]+)", text)
            if m and not meta["border_28"]:
                meta["border_28"] = m.group(1)
            m = re.search(r"\|\s*4\.00円（等価）\s*\|\s*([0-9.]+)", text)
            if m and not meta["border_eq"]:
                meta["border_eq"] = m.group(1)
            m = re.search(r"\|\s*遊タイム\s*\|\s*([^|]+)\|", text)
            if m:
                meta["yutime"] = _prefer_text(meta["yutime"], m.group(1))
            m = re.search(r"\|\s*天井\s*\|\s*([^|]+)\|", text)
            if m:
                meta["ceiling"] = _prefer_text(meta["ceiling"], m.group(1))
            m = re.search(r"\|\s*型式名\s*\|\s*([^|]+)\|", text)
            if m:
                formal = m.group(1).strip()
                meta["formal"] = formal
            guides[path.stem] = meta
            guides[norm(path.stem)] = meta
            guides[norm(meta["name"])] = meta
            if meta.get("formal"):
                guides[norm(meta["formal"])] = meta
                guides[meta["formal"]] = meta
    return guides


def match_guide(model: str, guides: dict[str, dict]) -> dict | None:
    if model in guides:
        return guides[model]
    n = norm(model)
    if n in guides:
        return guides[n]
    best = None
    best_score = 0
    seen: set[int] = set()
    for key, meta in guides.items():
        if id(meta) in seen:
            continue
        if key != meta.get("name"):
            continue
        seen.add(id(meta))
        kn = norm(meta["name"])
        if len(kn) < 6:
            continue
        if kn in n or n in kn:
            score = min(len(kn), len(n))
            if score > best_score:
                best_score = score
                best = meta
    if best_score >= 12:
        return best
    for alias, full in GUIDE_ALIASES.items():
        if alias in n and (full in guides or norm(full) in guides):
            return guides.get(full) or guides.get(norm(full))
    return None


def short_flag(value: str | None) -> str:
    text = (value or "—").strip()
    if not text or text in {"—", "-", "なし"}:
        return "—"
    if "非搭載" in text or text.startswith("非"):
        return "非搭載"
    if len(text) > 24:
        return text[:23] + "…"
    return text


def feature_present(value: str | None) -> bool:
    """天井・遊タイムが搭載扱い（非搭載・なし・調査中は除外）。"""
    text = (value or "").strip()
    if not text or text in {"—", "-", "なし", "無し"}:
        return False
    if "非搭載" in text or text.startswith("非"):
        return False
    if "調査中" in text or text in {"不明", "未確認"}:
        return False
    return True


def has_ceiling_or_yutime(guide: dict | None) -> bool:
    if not guide:
        return False
    return feature_present(guide.get("ceiling")) or feature_present(guide.get("yutime"))


def find_dated_csv(store: str, kind: str, day: str | None) -> Path | None:
    """kind は 全台データ / 出玉ランキング。店フォルダを日付フォルダより優先。"""
    patterns = []
    if day:
        patterns.append(ROOT / store / f"{kind}_{day}.csv")
        patterns.append(ROOT / day / store / f"{kind}_{day}.csv")
        for path in patterns:
            if path.exists():
                return path
        return None
    found: list[Path] = []
    for base in (ROOT / store,):
        if base.is_dir():
            found.extend(base.glob(f"{kind}_*.csv"))
    for day_dir in ROOT.glob("20??-??-??"):
        nested = day_dir / store
        if nested.is_dir():
            found.extend(nested.glob(f"{kind}_*.csv"))
    if not found:
        return None

    def day_key(path: Path) -> str:
        m = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", path.name)
        return m.group(1) if m else ""

    # 同じ日付なら店フォルダ（パスが短い方）を優先
    found.sort(key=lambda p: (day_key(p), -len(p.parts)))
    return found[-1]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def index_unit_dirs(store: str) -> dict[str, Path]:
    base = ROOT / store
    found: dict[str, Path] = {}
    if not base.is_dir():
        return found
    for model_dir in base.iterdir():
        if not model_dir.is_dir():
            continue
        for unit_dir in model_dir.iterdir():
            if unit_dir.is_dir() and unit_dir.name.isdigit():
                found.setdefault(unit_dir.name, unit_dir)
    return found


def measure_text(folder: Path | None) -> str:
    if folder is None:
        return "—"
    path = folder / "実測回転.csv"
    if not path.exists():
        return "—"
    rows = read_rows(path)
    if not rows:
        return "—"
    last = rows[-1]
    rate = (last.get("回転/250玉") or "").strip() or "—"
    balls = parse_int(last.get("玉数"))
    if balls is None:
        trust = "信頼不明"
    elif balls >= 2000:
        trust = "信頼高"
    elif balls >= 1000:
        trust = "信頼中"
    else:
        trust = "信頼低"
    moved = (last.get("移転後") or "").strip().lower()
    suffix = "・移転後" if moved in {"yes", "y", "1", "true"} else ""
    ball_label = f"{balls}玉" if balls is not None else "?玉"
    return f"{rate}（{ball_label}・{trust}{suffix}）"


def estimate_text(folder: Path | None) -> str:
    if folder is None or not (folder / "大当り履歴データ.csv").exists():
        return "—"
    sys.path.insert(0, str(ROOT / "tools"))
    from build_html import estimate_rate_from_history  # noqa: WPS433

    estimated = estimate_rate_from_history(folder)
    if not estimated:
        return "—"
    return str(estimated["text"])


def load_units(store: str, day: str | None) -> tuple[list[dict], str]:
    all_path = find_dated_csv(store, "全台データ", day)
    rank_path = find_dated_csv(store, "出玉ランキング", day)
    source = all_path or rank_path
    if source is None:
        raise SystemExit(f"全台データも出玉ランキングも無い: {store} day={day or '最新'}")
    rows = read_rows(source)
    ranks: dict[str, dict[str, str]] = {}
    if rank_path and rank_path != source:
        for row in read_rows(rank_path):
            unit = (row.get("台番号") or "").strip()
            if unit:
                ranks[unit] = row
    elif source == rank_path:
        for row in rows:
            unit = (row.get("台番号") or "").strip()
            if unit:
                ranks[unit] = row
    note = str(source.relative_to(ROOT))
    if all_path is None:
        note += "（全台では無い。ランキングのみ）"
    unit_dirs = index_unit_dirs(store)
    parsed = []
    for row in rows:
        unit = (row.get("台番号") or "").strip()
        if not unit:
            continue
        rank = ranks.get(unit, {})
        parsed.append(
            {
                "unit": unit,
                "model": (row.get("機種") or rank.get("機種") or "").strip(),
                "start": parse_int(row.get("累計スタート")),
                "hits": parse_int(row.get("大当り回数")),
                "first": parse_int(row.get("初当り回数")),
                "max_out": parse_int(row.get("最高出玉")),
                "diff": parse_int(rank.get("差玉") if rank else row.get("差玉")),
                "rank": parse_int(rank.get("順位") if rank else row.get("順位")),
                "folder": unit_dirs.get(unit),
            }
        )
    parsed.sort(key=lambda r: int(r["unit"]) if str(r["unit"]).isdigit() else 0)
    return parsed, note


def cmd_store(query: str) -> int:
    blocks = load_store_blocks()
    name = resolve_store(query, blocks)
    fields = blocks[name]
    print(f"正規店名\t{name}")
    for label in STORE_FIELDS:
        if label in fields:
            print(f"{label}\t{fields[label]}")
    return 0


def cmd_units(query: str, day: str | None) -> int:
    blocks = load_store_blocks()
    name = resolve_store(query, blocks)
    rows, source = load_units(name, day)
    guides = load_guides()
    by_model: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_model[row["model"]].append(row)
    print(f"# {name} units={len(rows)} source={source}")
    print("# 機種\t台数\t等価BD\t28玉BD\t天井\t遊タイム\t攻略")
    missing: list[str] = []
    for model in sorted(by_model):
        guide = match_guide(model, guides) if model else None
        if guide is None:
            missing.append(model or "（機種名なし）")
        print(
            "\t".join(
                [
                    model or "—",
                    str(len(by_model[model])),
                    (guide or {}).get("border_eq") or "—",
                    (guide or {}).get("border_28") or "—",
                    short_flag((guide or {}).get("ceiling")),
                    short_flag((guide or {}).get("yutime")),
                    "あり" if guide else "なし",
                ]
            )
        )
    if missing:
        print("# 攻略なし\t" + "、".join(missing))
    else:
        print("# 攻略なし\tなし")
    print("# 台\t台番号\t機種\tST\t当\t初\t最高\t差玉\t順位\t推定\t実測")
    for row in rows:
        folder = row["folder"]
        print(
            "\t".join(
                [
                    "台",
                    row["unit"],
                    row["model"] or "—",
                    _num(row["start"]),
                    _num(row["hits"]),
                    _num(row["first"]),
                    _num(row["max_out"]),
                    _num(row["diff"]),
                    _num(row["rank"]),
                    estimate_text(folder),
                    measure_text(folder),
                ]
            )
        )
    return 0


def _num(value: int | None) -> str:
    return "—" if value is None else str(value)


def _snap_path(store: str) -> Path:
    return SNAP_DIR / f"{store}.json"


def _dump_snap(store: str, day: str, source: str, rows: list[dict]) -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "store": store,
        "day": day,
        "saved_at": now_tokyo(),
        "source": source,
        "units": {
            row["unit"]: {
                "model": row["model"],
                "start": row["start"],
                "hits": row["hits"],
                "diff": row["diff"],
            }
            for row in rows
        },
    }
    _snap_path(store).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _day_of_source(source: str, fallback: str) -> str:
    m = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv", source)
    return m.group(1) if m else fallback


def cmd_diff(query: str, day: str | None, save: bool, start_delta: int) -> int:
    blocks = load_store_blocks()
    name = resolve_store(query, blocks)
    rows, source = load_units(name, day)
    current_day = _day_of_source(source, day or today_tokyo())
    path = _snap_path(name)
    prev = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    print(f"# {name} diff day={current_day} source={source}")
    if prev is None:
        print("基準なし。比較できない。")
        if save:
            _dump_snap(name, current_day, source, rows)
            print(f"基準を保存した\t{path.relative_to(ROOT)}")
        else:
            print("保存するなら --save")
        return 0
    if prev.get("day") != current_day:
        print(f"基準日が違う\t基準={prev.get('day')} 現在={current_day}")
        print("台一覧は出していない。同じ日の差分にするか、--save で基準を上書きする。")
        if save:
            _dump_snap(name, current_day, source, rows)
            print(f"基準を上書きした\t{path.relative_to(ROOT)}")
        return 0

    prev_units: dict = prev.get("units") or {}
    cur_units = {row["unit"]: row for row in rows}
    added = [cur_units[u] for u in cur_units if u not in prev_units]
    dropped = [u for u in prev_units if u not in cur_units]
    started = []
    for unit, row in cur_units.items():
        old = prev_units.get(unit)
        if not old or row["start"] is None or old.get("start") is None:
            continue
        delta = row["start"] - int(old["start"])
        if delta >= start_delta:
            started.append((delta, old, row))
    started.sort(key=lambda item: -item[0])

    def emit(title: str, lines: list[str]) -> None:
        if not lines:
            return
        print(f"## {title}\t{len(lines)}")
        for line in lines[:12]:
            print(line)
        if len(lines) > 12:
            print(f"... 他{len(lines) - 12}")

    add_lines = [f"+ {r['unit']}\t{r['model']}\tST={_num(r['start'])}\t当={_num(r['hits'])}" for r in added]
    drop_lines = [
        f"- {u}\t{prev_units[u].get('model','')}\tST={_num(prev_units[u].get('start'))}"
        for u in sorted(dropped, key=lambda x: int(x) if str(x).isdigit() else 0)
    ]
    start_lines = [
        f"ST {row['unit']}\t{row['model']}\t{old.get('start')}→{row['start']}（+{delta}）\t当 {_num(old.get('hits'))}→{_num(row['hits'])}"
        for delta, old, row in started
    ]
    emit("新規", add_lines)
    emit("脱落", drop_lines)
    emit(f"スタート+{start_delta}以上", start_lines)
    if not add_lines and not drop_lines and not start_lines:
        print("変更なし")
    if save:
        _dump_snap(name, current_day, source, rows)
        print(f"基準を更新した\t{path.relative_to(ROOT)} {now_tokyo()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="分析用の短い要約を出す")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_store = sub.add_parser("store", help="店1件の判断に使う項目だけ")
    p_store.add_argument("name")

    p_units = sub.add_parser("units", help="全台の数値と機種ボーダー")
    p_units.add_argument("name")
    p_units.add_argument("--day", default=None, help="YYYY-MM-DD。省略時は最新")

    p_diff = sub.add_parser("diff", help="前回保存との台差分")
    p_diff.add_argument("name")
    p_diff.add_argument("--day", default=None)
    p_diff.add_argument("--save", action="store_true", help="今回を次回の基準にする")
    p_diff.add_argument("--start-delta", type=int, default=50)

    args = parser.parse_args()
    if args.cmd == "store":
        return cmd_store(args.name)
    if args.cmd == "units":
        return cmd_units(args.name, args.day)
    return cmd_diff(args.name, args.day, args.save, args.start_delta)


if __name__ == "__main__":
    raise SystemExit(main())
