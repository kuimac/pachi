#!/usr/bin/env python3
"""店舗一覧と Site Seven 取得対象の単一参照。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from prefetch_ranks import STORES as SITE777_RANK_STORES  # noqa: E402
from fetch_site777_all_units import STORES as SITE777_UNITS_STORES  # noqa: E402


def load_store_names() -> list[str]:
    path = ROOT / "店舗一覧.md"
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(.+)$", line.strip())
        if m:
            names.append(m.group(1).strip())
    return names


def site777_stores() -> list[str]:
    """出玉ランキング＋全台の両方に載っている店（collect 対象）。"""
    names = [n for n in SITE777_RANK_STORES if n in SITE777_UNITS_STORES]
    # 安定した表示順: 一覧の並びに寄せ、残りは末尾
    order = {n: i for i, n in enumerate(load_store_names())}
    return sorted(names, key=lambda n: (order.get(n, 10_000), n))


def info_only_stores() -> list[str]:
    s7 = set(site777_stores())
    return [n for n in load_store_names() if n not in s7]


def can_collect(store: str) -> bool:
    return store in SITE777_RANK_STORES and store in SITE777_UNITS_STORES


def resolve_targets(store_arg: str, *, site777_only: bool = False) -> list[str]:
    all_names = load_store_names()
    if store_arg == "all":
        targets = list(site777_stores() if site777_only else all_names)
    elif store_arg in ("site777", "s7"):
        targets = list(site777_stores())
    elif store_arg in ("info", "info_only"):
        targets = list(info_only_stores())
    else:
        if store_arg not in all_names and store_arg not in SITE777_RANK_STORES:
            raise SystemExit(f"unknown store: {store_arg}\nknown: {', '.join(all_names)}")
        targets = [store_arg]
    return targets


def main() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    payload = {
        "all": load_store_names(),
        "site777": site777_stores(),
        "info_only": info_only_stores(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("## all")
        for n in payload["all"]:
            flag = "site777" if n in payload["site777"] else "info"
            print(f"- {n}\t{flag}")
        print(f"\nsite777={len(payload['site777'])} info_only={len(payload['info_only'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
