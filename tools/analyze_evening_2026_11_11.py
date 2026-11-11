#!/usr/bin/env python3
"""2026-11-11 evening picks from Site Seven free all-units + ranks."""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_all_units_2026_11_10 import (  # noqa: E402
    annotate_site777,
    island_stats,
    load_guides,
    match_guide,
    parse_int,
    pick_candidates,
    unknown_models,
)

DAY = "2026-11-11"
OUT = Path("/tmp/pachi-analysis-2026-11-11")
OUT.mkdir(parents=True, exist_ok=True)

# monkeypatch day paths used by analyze helper
import analyze_all_units_2026_11_10 as base  # noqa: E402

base.DAY = DAY


def load_rank(store: str) -> dict[str, dict]:
    path = ROOT / store / f"出玉ランキング_{DAY}.csv"
    if not path.exists():
        path = ROOT / DAY / store / f"出玉ランキング_{DAY}.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for row in csv.DictReader(path.open(encoding="utf-8-sig")):
        unit = (row.get("台番号") or "").strip()
        if not unit:
            continue
        out[unit] = {
            "rank": parse_int(row.get("順位")),
            "model": (row.get("機種") or "").strip(),
            "start": parse_int(row.get("累計スタート")),
            "hits": parse_int(row.get("大当り回数")),
            "first": parse_int(row.get("初当り回数")),
            "diff": parse_int(row.get("差玉")),
        }
    return out


def load_all_units_site777(store: str) -> list[dict]:
    path = ROOT / store / f"全台データ_{DAY}.csv"
    if not path.exists():
        path = ROOT / DAY / store / f"全台データ_{DAY}.csv"
    rows = []
    for row in csv.DictReader(path.open(encoding="utf-8-sig")):
        rows.append(
            {
                "unit": (row.get("台番号") or "").strip(),
                "model": (row.get("機種") or "").strip(),
                "start": parse_int(row.get("累計スタート")),
                "hits": parse_int(row.get("大当り回数")),
                "first": parse_int(row.get("初当り回数")),
                "max_out": parse_int(row.get("最高出玉")),
                "rate": (row.get("レート") or "").strip(),
                "mdc": (row.get("mdc") or "").strip(),
                "installed": parse_int(row.get("設置台数")),
            }
        )
    return rows


base.load_rank = load_rank
base.load_all_units_site777 = load_all_units_site777


def hajimari_shallow(units: list[dict], winners: set[str], limit: int = 12) -> list[dict]:
    rows = [
        u
        for u in units
        if "はじまり" in (u.get("model") or "")
        and isinstance(u.get("start"), int)
        and u["unit"] not in winners
        and (u.get("diff") or 0) < 15000
    ]
    rows.sort(key=lambda r: (r["start"], r.get("hits") or 0))
    return rows[:limit]


def main() -> None:
    guides = load_guides()
    stores = [
        ("楽園渋谷駅前店", False),
        ("中山UNO", True),
        ("楽園町田店", False),
        ("エスパス日拓渋谷駅前新館", False),
        ("中山ZoRoN", True),
        ("楽園渋谷道玄坂店", False),
        ("エスパス日拓西武新宿駅前店", False),
    ]
    compact = {}
    for store, eq in stores:
        units = annotate_site777(store, guides)
        picks = pick_candidates(units, exchange25=eq)
        winners = {u["unit"] for u in picks["winners"]}
        # also exclude top10 rank with any positive diff
        for u in units:
            if isinstance(u.get("rank"), int) and u["rank"] <= 12:
                winners.add(u["unit"])
        haj = hajimari_shallow(units, winners)
        # prefer cold shallow among known guide machines
        cold = [
            u
            for u in picks["cold_shallow"]
            if u["unit"] not in winners and (u.get("hits") or 0) <= 2 and u["start"] <= 150
        ][:15]
        compact[store] = {
            "n": len(units),
            "start_known": sum(1 for u in units if isinstance(u["start"], int)),
            "unknown": unknown_models(units),
            "island_top": dict(
                sorted(island_stats(units).items(), key=lambda kv: -kv[1]["n"])[:20]
            ),
            "hajimari": haj,
            "cold_shallow": cold,
            "shallow": picks["shallow"][:25],
            "yutime_near": picks["yutime_near"][:15],
            "avoid": picks["avoid"][:15],
            "rank_top": sorted(
                [u for u in units if isinstance(u.get("rank"), int)],
                key=lambda r: r.get("rank") or 99,
            )[:15],
        }
        print("====", store, "n", compact[store]["n"], "start_known", compact[store]["start_known"])
        print(" unknown", len(compact[store]["unknown"]))
        for s in haj[:8]:
            print(
                f"  HAJ {s['unit']} st={s['start']} hit={s.get('hits')} {s['model'][:50]}"
            )
        for s in cold[:6]:
            if "はじまり" in s["model"]:
                continue
            print(
                f"  COLD {s['unit']} st={s['start']} hit={s.get('hits')} {s['model'][:50]}"
            )
        for s in compact[store]["avoid"][:6]:
            print(
                f"  AV {s['unit']} rank={s.get('rank')} diff={s.get('diff')} {s['model'][:40]}"
            )

    (OUT / "summary.json").write_text(
        json.dumps(compact, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("wrote", OUT / "summary.json")


if __name__ == "__main__":
    main()
