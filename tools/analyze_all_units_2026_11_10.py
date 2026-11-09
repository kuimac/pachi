#!/usr/bin/env python3
"""2026-11-10 morning analysis helper from 2026-11-09 closed data.

Outputs JSON summaries under /tmp for MD authoring. Not a publish step.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_html import estimate_rate_from_history  # noqa: E402

DAY = "2026-11-09"
OUT = Path("/tmp/pachi-analysis-2026-11-10")
OUT.mkdir(parents=True, exist_ok=True)


def norm(name: str) -> str:
    s = name
    for a, b in [
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
    ]:
        s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def load_guides() -> dict[str, dict]:
    guides: dict[str, dict] = {}
    for folder in (ROOT / "攻略情報", ROOT / "機種スペック"):
        for path in folder.glob("*.md"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            meta: dict = {
                "name": path.stem,
                "path": str(path.relative_to(ROOT)),
                "border_28": None,
                "border_eq": None,
                "yutime": None,
                "ceiling": None,
                "has_yutime": False,
                "has_ceiling": False,
            }
            m = re.search(r"\|\s*3\.57円（28玉）\s*\|\s*([0-9.]+)", text)
            if m:
                meta["border_28"] = float(m.group(1))
            m = re.search(r"\|\s*4\.00円（等価）\s*\|\s*([0-9.]+)", text)
            if m:
                meta["border_eq"] = float(m.group(1))
            m = re.search(r"\|\s*遊タイム\s*\|\s*([^|]+)\|", text)
            if m:
                val = m.group(1).strip()
                meta["yutime"] = val
                if val and "非" not in val and val not in {"—", "-", "なし"}:
                    meta["has_yutime"] = True
                    nums = re.findall(r"(\d{2,4})\s*回転", val)
                    if not nums:
                        nums = re.findall(r"低確\s*(\d{2,4})", val)
                    if nums:
                        meta["yutime_n"] = int(nums[0])
            m = re.search(r"\|\s*天井\s*\|\s*([^|]+)\|", text)
            if m:
                val = m.group(1).strip()
                meta["ceiling"] = val
                if val and "非" not in val and val not in {"—", "-"}:
                    meta["has_ceiling"] = True
                    nums = re.findall(r"(\d{2,4})", val)
                    if nums:
                        meta["ceiling_n"] = int(nums[0])
            guides[path.stem] = meta
            guides[norm(path.stem)] = meta
    return guides


def match_guide(model: str, guides: dict[str, dict]) -> dict | None:
    if model in guides:
        return guides[model]
    n = norm(model)
    if n in guides:
        return guides[n]
    # substring / containment
    best = None
    best_score = 0
    for key, meta in guides.items():
        if not isinstance(key, str):
            continue
        kn = norm(key) if key == meta.get("name") else key
        if len(kn) < 6:
            continue
        score = 0
        if kn in n or n in kn:
            score = min(len(kn), len(n))
        # token overlap on distinctive chunks
        if score > best_score:
            best_score = score
            best = meta
    if best_score >= 12:
        return best
    # alias map for frequent short names
    aliases = {
        "鬼がかり2": "e Re:ゼロから始める異世界生活 鬼がかり2",
        "鬼がかり": "e Re:ゼロから始める異世界生活 鬼がかり2",
        "電音部": "Pドラムde電音部 超ドラ熱4500Ver",
        "リコリコm3": "eリコリス・リコイルM3",
        "はじまりの記憶": "e 新世紀エヴァンゲリオン ～はじまりの記憶～",
    }
    for a, full in aliases.items():
        if a in n and full in guides:
            return guides[full]
        if a in n and norm(full) in guides:
            return guides[norm(full)]
    return None


def parse_int(val: str | None) -> int | None:
    if val is None:
        return None
    s = str(val).strip().replace(",", "")
    if s in {"", "-", "—", "--"}:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def load_rank(store: str) -> dict[str, dict]:
    path = ROOT / store / f"出玉ランキング_{DAY}.csv"
    if not path.exists():
        path = ROOT / "2026-11-10" / store / f"出玉ランキング_{DAY}.csv"
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
        path = ROOT / "2026-11-10" / store / f"全台データ_{DAY}.csv"
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


def load_machida_deltanet(guides: dict[str, dict]) -> list[dict]:
    store = ROOT / "楽園町田店"
    units: list[dict] = []
    for model_dir in sorted(p for p in store.iterdir() if p.is_dir()):
        model = model_dir.name
        guide = match_guide(model, guides)
        for unit_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
            unit = unit_dir.name
            if not unit.isdigit():
                continue
            start = None
            hits = None
            first = None
            max_out = None
            start_path = unit_dir / "スタート.csv"
            if start_path.exists():
                for row in csv.DictReader(start_path.open(encoding="utf-8-sig")):
                    if (row.get("日付") or "").strip() == DAY:
                        start = parse_int(row.get("スタート"))
            hit_path = unit_dir / "大当り回数.csv"
            if hit_path.exists():
                for row in csv.DictReader(hit_path.open(encoding="utf-8-sig")):
                    if (row.get("日付") or "").strip() == DAY:
                        hits = parse_int(row.get("大当り回数"))
            list_path = unit_dir / "大当り一覧.csv"
            if list_path.exists():
                for row in csv.DictReader(list_path.open(encoding="utf-8-sig")):
                    if (row.get("日付") or "").strip() == DAY:
                        if start is None:
                            start = parse_int(row.get("スタート")) or parse_int(
                                row.get("累計スタート")
                            )
                        if hits is None:
                            hits = parse_int(row.get("大当り回数"))
                        first = parse_int(row.get("初当り回数"))
                        max_out = parse_int(row.get("最高出玉"))
            est = estimate_rate_from_history(unit_dir)
            measure = "—"
            meas_path = unit_dir / "実測回転.csv"
            if meas_path.exists():
                mrows = list(csv.DictReader(meas_path.open(encoding="utf-8-sig")))
                if mrows:
                    last = mrows[-1]
                    measure = (
                        f"{last.get('回転/250玉','').strip()}（"
                        f"{last.get('玉数','?').strip()}玉）"
                    )
            units.append(
                {
                    "store": "楽園町田店",
                    "model": model,
                    "unit": unit,
                    "start": start,
                    "hits": hits,
                    "first": first,
                    "max_out": max_out,
                    "estimated": est["text"] if est else "—",
                    "estimated_raw": est["rate"] if est else None,
                    "measure": measure,
                    "guide": guide["name"] if guide else None,
                    "border_28": guide.get("border_28") if guide else None,
                    "border_eq": guide.get("border_eq") if guide else None,
                    "has_yutime": bool(guide and guide.get("has_yutime")),
                    "has_ceiling": bool(guide and guide.get("has_ceiling")),
                    "yutime_n": guide.get("yutime_n") if guide else None,
                    "ceiling_n": guide.get("ceiling_n") if guide else None,
                    "yutime": guide.get("yutime") if guide else None,
                    "ceiling": guide.get("ceiling") if guide else None,
                }
            )
    return units


def annotate_site777(store: str, guides: dict[str, dict]) -> list[dict]:
    ranks = load_rank(store)
    units = []
    for row in load_all_units_site777(store):
        unit = row["unit"]
        rank = ranks.get(unit, {})
        start = row["start"] if row["start"] is not None else rank.get("start")
        hits = row["hits"] if row["hits"] is not None else rank.get("hits")
        model = row["model"] or rank.get("model") or ""
        guide = match_guide(model, guides)
        units.append(
            {
                "store": store,
                "model": model,
                "unit": unit,
                "start": start,
                "hits": hits,
                "first": row["first"] if row["first"] is not None else rank.get("first"),
                "max_out": row["max_out"],
                "diff": rank.get("diff"),
                "rank": rank.get("rank"),
                "estimated": "—",
                "measure": "—",
                "guide": guide["name"] if guide else None,
                "border_28": guide.get("border_28") if guide else None,
                "border_eq": guide.get("border_eq") if guide else None,
                "has_yutime": bool(guide and guide.get("has_yutime")),
                "has_ceiling": bool(guide and guide.get("has_ceiling")),
                "yutime_n": guide.get("yutime_n") if guide else None,
                "ceiling_n": guide.get("ceiling_n") if guide else None,
                "yutime": guide.get("yutime") if guide else None,
                "ceiling": guide.get("ceiling") if guide else None,
            }
        )
    return units


def island_stats(units: list[dict]) -> dict[str, dict]:
    by: dict[str, list] = defaultdict(list)
    for u in units:
        by[u["model"]].append(u)
    out = {}
    for model, rows in by.items():
        starts = [r["start"] for r in rows if isinstance(r["start"], int)]
        hits = [r["hits"] for r in rows if isinstance(r["hits"], int)]
        out[model] = {
            "n": len(rows),
            "start_avg": round(sum(starts) / len(starts), 1) if starts else None,
            "start_median": sorted(starts)[len(starts) // 2] if starts else None,
            "hit_avg": round(sum(hits) / len(hits), 1) if hits else None,
            "start_known": len(starts),
        }
    return out


def pick_candidates(units: list[dict], exchange25: bool = False) -> dict:
    """Morning picks: shallow non-result units, yutime near line, skip big winners."""
    ranked_winners = {
        u["unit"]
        for u in units
        if isinstance(u.get("rank"), int) and u["rank"] <= 10 and (u.get("diff") or 0) > 20000
    }
    # also mark by hits outliers within island
    by_model: dict[str, list] = defaultdict(list)
    for u in units:
        by_model[u["model"]].append(u)

    shallow = []
    yutime_near = []
    cold_shallow = []
    for model, rows in by_model.items():
        starts = [r for r in rows if isinstance(r["start"], int)]
        if not starts:
            # no start: use low hits + not top rank as weak signal only for listing
            continue
        starts_sorted = sorted(starts, key=lambda r: r["start"])
        avg = sum(r["start"] for r in starts_sorted) / len(starts_sorted)
        for r in starts_sorted:
            if r["unit"] in ranked_winners:
                r = {**r, "skip_reason": "差玉上位の結果台"}
            remain = None
            if r.get("has_yutime") and r.get("yutime_n") and isinstance(r["start"], int):
                remain = r["yutime_n"] - r["start"]
                r = {**r, "yutime_remain": remain}
            if r.get("has_ceiling") and r.get("ceiling_n") and isinstance(r["start"], int):
                r = {**r, "ceiling_remain": r["ceiling_n"] - r["start"]}
            # shallow = bottom quartile or < 0.5 * avg, and start < 250
            if r["start"] <= max(120, avg * 0.45) and r["start"] < 280:
                if r.get("skip_reason"):
                    continue
                border = r.get("border_eq") if exchange25 else r.get("border_28")
                item = {**r, "island_avg_start": round(avg, 1), "border_use": border}
                shallow.append(item)
                if (r.get("hits") or 0) <= 3:
                    cold_shallow.append(item)
            if (
                remain is not None
                and 0 < remain <= 120
                and not r.get("skip_reason")
            ):
                yutime_near.append({**r, "island_avg_start": round(avg, 1)})

    shallow.sort(key=lambda r: (r["start"], -(r.get("estimated_raw") or 0)))
    yutime_near.sort(key=lambda r: r.get("yutime_remain", 9999))
    cold_shallow.sort(key=lambda r: r["start"])

    # top result machines to avoid
    avoid = []
    for u in units:
        if isinstance(u.get("rank"), int) and u["rank"] <= 15:
            avoid.append(u)
        elif isinstance(u.get("diff"), int) and u["diff"] >= 30000:
            avoid.append(u)
    avoid = sorted(
        {u["unit"]: u for u in avoid}.values(),
        key=lambda r: (r.get("rank") or 99, -(r.get("diff") or 0)),
    )

    return {
        "shallow": shallow[:40],
        "yutime_near": yutime_near[:20],
        "cold_shallow": cold_shallow[:20],
        "avoid": avoid[:20],
        "winners": sorted(
            [u for u in units if u.get("unit") in ranked_winners],
            key=lambda r: r.get("rank") or 99,
        ),
    }


def unknown_models(units: list[dict]) -> list[str]:
    missing = []
    seen = set()
    for u in units:
        m = u["model"]
        if m in seen:
            continue
        seen.add(m)
        if not u.get("guide"):
            missing.append(m)
    return sorted(missing)


def main() -> None:
    guides = load_guides()
    summary = {}

    machida = load_machida_deltanet(guides)
    # merge rank/diff
    ranks = load_rank("楽園町田店")
    for u in machida:
        r = ranks.get(u["unit"])
        if r:
            u["rank"] = r.get("rank")
            u["diff"] = r.get("diff")
            if u["hits"] is None:
                u["hits"] = r.get("hits")
            if u["start"] is None:
                u["start"] = r.get("start")
    summary["楽園町田店"] = {
        "n": len(machida),
        "island": island_stats(machida),
        "picks": pick_candidates(machida, exchange25=False),
        "unknown": unknown_models(machida),
        "units": machida,
    }

    for store, eq in [
        ("中山UNO", True),
        ("中山ZoRoN", True),
        ("エスパス日拓西武新宿駅前店", False),
    ]:
        units = annotate_site777(store, guides)
        summary[store] = {
            "n": len(units),
            "start_known": sum(1 for u in units if isinstance(u["start"], int)),
            "island": island_stats(units),
            "picks": pick_candidates(units, exchange25=eq),
            "unknown": unknown_models(units),
            "units": units,
        }

    # partial stores: machine lists only
    for store in [
        "マルハン新宿東宝ビル店",
        "エスパス日拓新宿歌舞伎町店",
        "カレイド新宿店",
        "楽園池袋店",
    ]:
        path = ROOT / "2026-11-10" / store / f"設置機種一覧_{DAY}.csv"
        models = []
        for row in csv.DictReader(path.open(encoding="utf-8-sig")):
            model = (row.get("機種") or "").strip()
            if not model:
                continue
            guide = match_guide(model, guides)
            models.append(
                {
                    "model": model,
                    "guide": guide["name"] if guide else None,
                    "has_yutime": bool(guide and guide.get("has_yutime")),
                    "has_ceiling": bool(guide and guide.get("has_ceiling")),
                    "yutime": guide.get("yutime") if guide else None,
                    "ceiling": guide.get("ceiling") if guide else None,
                    "border_28": guide.get("border_28") if guide else None,
                    "border_eq": guide.get("border_eq") if guide else None,
                }
            )
        summary[store] = {
            "n_models": len(models),
            "models": models,
            "unknown": [m["model"] for m in models if not m["guide"]],
            "yutime_models": [m for m in models if m["has_yutime"] or m["has_ceiling"]],
        }

    # write compact picks without full units for readability, full dump separate
    compact = {}
    for store, data in summary.items():
        if "units" in data:
            compact[store] = {
                k: v for k, v in data.items() if k != "units"
            }
            # keep top islands by count
            islands = data["island"]
            top_islands = sorted(
                islands.items(), key=lambda kv: -kv[1]["n"]
            )[:25]
            compact[store]["island_top"] = dict(top_islands)
            # interesting models with shallow picks
            compact[store]["picks"] = data["picks"]
        else:
            compact[store] = data

    (OUT / "summary.json").write_text(
        json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "full.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )

    # print human overview
    for store, data in compact.items():
        print("====", store)
        if "n" in data:
            print(" units", data["n"], "start_known", data.get("start_known", "all?"))
            print(" unknown models", len(data.get("unknown", [])))
            picks = data["picks"]
            print(" shallow", len(picks["shallow"]), "yutime_near", len(picks["yutime_near"]))
            for s in picks["shallow"][:8]:
                print(
                    f"  SH {s['unit']} {s['model'][:40]} st={s['start']} hit={s.get('hits')} "
                    f"est={s.get('estimated')} yu={s.get('yutime_remain')} bd={s.get('border_use')}"
                )
            for s in picks["yutime_near"][:5]:
                print(
                    f"  YU {s['unit']} {s['model'][:40]} st={s['start']} remain={s.get('yutime_remain')}"
                )
            for s in picks["avoid"][:5]:
                print(
                    f"  AV {s['unit']} {s['model'][:40]} rank={s.get('rank')} diff={s.get('diff')} st={s.get('start')}"
                )
        else:
            print(" models", data["n_models"], "unknown", len(data["unknown"]))
            print(" yutime/ceiling known", len(data["yutime_models"]))
            for m in data["yutime_models"][:10]:
                print("  ", m["model"][:50], m.get("yutime") or m.get("ceiling"))


if __name__ == "__main__":
    main()
