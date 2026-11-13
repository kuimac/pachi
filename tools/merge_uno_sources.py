#!/usr/bin/env python3
"""中山UNO: Site Seven 全台CSV と DMM/PSCUBE 台データを台番号で併用マージする。

方針（置き換えない）:
  - キー: 台番号（同一日）
  - Site Seven 側の数値（累計スタート・大当り・初当り・最高出玉）を優先
  - PSCUBE にあって Site Seven に無い列（最終スタート・最大放出数 など）を埋める
  - 機種名は Site Seven 優先、欠落時のみ DMM/PSCUBE
  - 出所を source / sources 列に残す
  - どちらか片方だけでも行を残す（天井機を落とさない）
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Tokyo")
STORE = "中山UNO"

SITE777_FIELDS = [
    "日付",
    "台番号",
    "機種",
    "累計スタート",
    "大当り回数",
    "初当り回数",
    "最高出玉",
    "レート",
    "mdc",
    "設置台数",
]


def now_tokyo() -> datetime:
    return datetime.now(TZ)


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def norm_unit(v: str) -> str:
    s = (v or "").strip()
    if s.isdigit():
        return str(int(s))  # strip leading zeros carefully? keep as int string without pad
    return s


def prefer(*vals: str) -> str:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s and s not in {"--", "-", "—", "nan", "None"}:
            return s
    return ""


def merge_day(day: str) -> dict[str, object]:
    site_path = ROOT / STORE / f"全台データ_{day}.csv"
    pscube_path = ROOT / STORE / "dmm_ptown" / f"台データ_{day}.csv"
    installs_path = ROOT / STORE / "dmm_ptown" / f"設置機種_{day}.csv"

    site_rows = load_csv(site_path)
    pscube_rows = load_csv(pscube_path)
    installs = load_csv(installs_path)

    by_unit: dict[str, dict[str, str]] = {}

    for r in site_rows:
        u = norm_unit(r.get("台番号", ""))
        if not u:
            continue
        by_unit[u] = {
            "日付": day,
            "台番号": u,
            "機種": r.get("機種", ""),
            "累計スタート": r.get("累計スタート", ""),
            "最終スタート": "",
            "大当り回数": r.get("大当り回数", ""),
            "初当り回数": r.get("初当り回数", ""),
            "最高出玉": r.get("最高出玉", ""),
            "最大放出数": "",
            "差玉": "",
            "レート": r.get("レート", ""),
            "mdc": r.get("mdc", ""),
            "設置台数": r.get("設置台数", ""),
            "source_site777": "1",
            "source_pscube": "0",
            "sources": "site777",
        }

    for r in pscube_rows:
        u = norm_unit(r.get("台番号") or r.get("台番") or "")
        if not u:
            continue
        cur = by_unit.get(u)
        if cur is None:
            cur = {
                "日付": day,
                "台番号": u,
                "機種": "",
                "累計スタート": "",
                "最終スタート": "",
                "大当り回数": "",
                "初当り回数": "",
                "最高出玉": "",
                "最大放出数": "",
                "差玉": "",
                "レート": "",
                "mdc": "",
                "設置台数": "",
                "source_site777": "0",
                "source_pscube": "1",
                "sources": "pscube",
            }
            by_unit[u] = cur
        else:
            cur["source_pscube"] = "1"
            if "pscube" not in cur["sources"]:
                cur["sources"] = cur["sources"] + "+pscube" if cur["sources"] else "pscube"

        # Site Seven 優先で数値を埋める（空のときだけ PSCUBE）
        cur["機種"] = prefer(cur.get("機種", ""), r.get("機種", ""))
        cur["累計スタート"] = prefer(cur.get("累計スタート", ""), r.get("累計スタート", ""))
        cur["大当り回数"] = prefer(cur.get("大当り回数", ""), r.get("大当り回数", ""))
        cur["初当り回数"] = prefer(cur.get("初当り回数", ""), r.get("初当り回数", ""))
        cur["最高出玉"] = prefer(cur.get("最高出玉", ""), r.get("最高出玉", ""), r.get("最大放出数", ""))
        # PSCUBE 独自
        cur["最終スタート"] = prefer(cur.get("最終スタート", ""), r.get("最終スタート", ""))
        cur["最大放出数"] = prefer(cur.get("最大放出数", ""), r.get("最大放出数", ""))
        cur["差玉"] = prefer(cur.get("差玉", ""), r.get("差玉", ""))

    out_rows = [by_unit[k] for k in sorted(by_unit.keys(), key=lambda x: int(x) if x.isdigit() else 0)]
    out_dir = ROOT / STORE / "dmm_ptown"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"全台データ_merged_{day}.csv"
    fields = [
        "日付",
        "台番号",
        "機種",
        "累計スタート",
        "最終スタート",
        "大当り回数",
        "初当り回数",
        "最高出玉",
        "最大放出数",
        "差玉",
        "レート",
        "mdc",
        "設置台数",
        "source_site777",
        "source_pscube",
        "sources",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)

    # 既存の分析互換: Site Seven が空で PSCUBE だけある日は 全台データ_{day}.csv を作らない
    # （Site Seven を置き換えない）。merged のみ副ソースとして置く。
    summary = {
        "store": STORE,
        "day": day,
        "merged_at": now_tokyo().strftime("%Y-%m-%d %H:%M"),
        "site777_rows": len(site_rows),
        "pscube_rows": len(pscube_rows),
        "install_rows": len(installs),
        "merged_rows": len(out_rows),
        "both": sum(1 for r in out_rows if r["source_site777"] == "1" and r["source_pscube"] == "1"),
        "site777_only": sum(1 for r in out_rows if r["source_site777"] == "1" and r["source_pscube"] != "1"),
        "pscube_only": sum(1 for r in out_rows if r["source_site777"] != "1" and r["source_pscube"] == "1"),
        "csv": str(out_path.relative_to(ROOT)),
        "policy": "site777_preferred_numeric; pscube_fills_gaps; no_blind_replace",
    }
    (out_dir / f"merge_summary_{day}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--day", default="")
    args = ap.parse_args()
    day = args.day or now_tokyo().strftime("%Y-%m-%d")
    summary = merge_day(day)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
