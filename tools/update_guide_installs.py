#!/usr/bin/env python3
"""攻略情報の「設置店舗」を全台CSVから更新する。

各店の最新 `全台データ_*.csv` を読み、機種→店舗の対応を攻略 MD へ書く。
取得日時は prefetch snapshot / 生データ取得結果（Asia/Tokyo）。mtime は使わない。

使い方:
  python3 tools/update_guide_installs.py
  python3 tools/update_guide_installs.py --dry-run

全台取得後は publish 前に実行する（fetch_site777 / publish からも呼ぶ想定）。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE_DIR = ROOT / "攻略情報"
SNAP_DIR = ROOT / "tools" / "prefetch_snapshots"
SECTION = "設置店舗"
SECTION_RE = re.compile(
    rf"(?:^|\n)## {re.escape(SECTION)}\n.*?(?=\n## |\Z)",
    re.S,
)


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def canon(text: str) -> str:
    return nfkc(text).casefold()


def csv_day(path: Path) -> str:
    match = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", path.name)
    return match.group(1) if match else ""


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def normalize_fetched_at(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"（Asia/Tokyo）|\(Asia/Tokyo\)", "", text).strip()
    if not text:
        return ""
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text}（Asia/Tokyo）"
    return text


def store_fetch_at(store: str, day: str) -> str:
    memo = ROOT / day / store / "生データ取得結果.md"
    if memo.is_file():
        match = re.search(r"取得日時:\s*(.+)$", memo.read_text(encoding="utf-8"), re.M)
        if match:
            return normalize_fetched_at(match.group(1))
    units = load_json(SNAP_DIR / store / "site777_all_units_last.json")
    if str(units.get("day") or "") == day and units.get("fetched_at"):
        return normalize_fetched_at(str(units["fetched_at"]))
    rank = load_json(SNAP_DIR / store / "last.json")
    if str(rank.get("day") or "") == day and rank.get("fetched_at"):
        return normalize_fetched_at(str(rank["fetched_at"]))
    return f"{day}（取得時刻不明・Asia/Tokyo）"


def latest_all_unit_csvs() -> dict[str, tuple[str, Path]]:
    by_store: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for path in ROOT.glob("*/全台データ_*.csv"):
        if path.parts[0].startswith("20"):
            continue
        by_store[path.parent.name].append((csv_day(path), path))
    for day_dir in ROOT.glob("20??-??-??"):
        for path in day_dir.glob("*/全台データ_*.csv"):
            by_store[path.parent.name].append((csv_day(path), path))
    latest: dict[str, tuple[str, Path]] = {}
    for store, items in by_store.items():
        items = [(day, path) for day, path in items if day]
        if not items:
            continue
        items.sort()
        latest[store] = items[-1]
    return latest


def guide_keys(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    keys = {canon(path.stem)}
    title = text.splitlines()[0] if text else ""
    if title.startswith("# "):
        keys.add(canon(title[2:]))
    formal = re.search(r"\|\s*型式名\s*\|\s*([^|]+)\|", text)
    if formal:
        keys.add(canon(formal.group(1)))
    # ホール短縮・全角半角ゆれ
    for key in list(keys):
        keys.add(re.sub(r"\s+", "", key))
        keys.add(key.replace("!", "！").replace("！", "!"))
    return {k for k in keys if k}


def collect_installs() -> tuple[dict[str, dict[str, dict[str, object]]], str]:
    """canon機種キー → store → {count, fetched_at, day, csv_name}"""
    latest = latest_all_unit_csvs()
    installs: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    max_day = ""
    for store, (day, path) in sorted(latest.items()):
        max_day = max(max_day, day)
        fetched = store_fetch_at(store, day)
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        counts: dict[str, int] = defaultdict(int)
        names: dict[str, str] = {}
        for row in rows:
            name = (row.get("機種") or "").strip()
            if not name:
                continue
            key = canon(name)
            counts[key] += 1
            names[key] = name
            counts[re.sub(r"\s+", "", key)] += 0  # ensure variant key exists for lookup
        for key, count in counts.items():
            if count <= 0:
                continue
            installs[key][store] = {
                "count": count,
                "fetched_at": fetched,
                "day": day,
                "csv_name": names.get(key, ""),
            }
    return installs, max_day


def render_section(
    store_map: dict[str, dict[str, object]],
    *,
    checked: str,
) -> str:
    lines = [
        f"## {SECTION}",
        "",
        "台入れ替えがあるため、各店の**全台データ取得時点**の設置。取得日時は Asia/Tokyo。",
        "",
    ]
    if not store_map:
        lines += [
            f"直近の全台CSVにこの機種の設置は見当たらない（最終確認日: {checked}）。",
            "",
        ]
        return "\n".join(lines)
    lines += [
        "| 店舗 | 台数 | データ取得日時 |",
        "| --- | --- | --- |",
    ]
    for store in sorted(store_map):
        row = store_map[store]
        lines.append(
            f"| {store} | {row['count']} | {row['fetched_at']} |"
        )
    lines.append("")
    return "\n".join(lines)


def upsert_section(text: str, section: str) -> str:
    text = text.replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    if SECTION_RE.search(text):
        return SECTION_RE.sub("\n" + section.rstrip() + "\n", text, count=1)
    # 注意の直前。無ければ末尾
    note = re.search(r"\n## 注意\n", text)
    if note:
        return text[: note.start()] + "\n" + section + text[note.start() :]
    return text.rstrip() + "\n\n" + section


def match_installs(
    keys: set[str],
    installs: dict[str, dict[str, dict[str, object]]],
) -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    for key in keys:
        if key in installs:
            for store, row in installs[key].items():
                prev = found.get(store)
                if prev is None or int(row["count"]) > int(prev["count"]):
                    found[store] = row
        # substring for 型式名 in longer CSV labels
        for ikey, stores in installs.items():
            if len(key) >= 8 and (key in ikey or ikey in key):
                for store, row in stores.items():
                    prev = found.get(store)
                    if prev is None or int(row["count"]) > int(prev["count"]):
                        found[store] = row
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    installs, checked = collect_installs()
    updated = 0
    for path in sorted(GUIDE_DIR.glob("*.md")):
        keys = guide_keys(path)
        store_map = match_installs(keys, installs)
        section = render_section(store_map, checked=checked or "—")
        old = path.read_text(encoding="utf-8")
        new = upsert_section(old, section)
        if new == old:
            continue
        updated += 1
        if args.dry_run:
            print(f"[dry] {path.name}: {len(store_map)} stores")
        else:
            path.write_text(new, encoding="utf-8")
            print(f"[ok] {path.name}: {len(store_map)} stores")
    print(f"{'would update' if args.dry_run else 'updated'} {updated} guides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
