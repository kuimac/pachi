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


BATCH_ALIASES = frozenset({"all", "site777", "s7", "info", "info_only"})


def require_one_store(store_arg: str) -> str:
    """収集・分析は1店だけ。複数店はスクリプトを店ごとに複数回叩く。"""
    all_names = load_store_names()
    if store_arg in BATCH_ALIASES:
        raise SystemExit(
            f"--store は1店の正規店名のみ（{store_arg} は不可）。"
            "複数店はスクリプトを店ごとに複数回叩く。"
            f"\nsite777: {', '.join(site777_stores())}"
            f"\nall: {', '.join(all_names)}"
        )
    if store_arg not in all_names and store_arg not in SITE777_RANK_STORES:
        raise SystemExit(f"unknown store: {store_arg}\nknown: {', '.join(all_names)}")
    return store_arg


def resolve_targets(store_arg: str, *, site777_only: bool = False) -> list[str]:
    """互換用。作業コマンドは require_one_store を使う。"""
    if store_arg in BATCH_ALIASES or site777_only:
        raise SystemExit(
            "バッチ指定は廃止。1店ずつスクリプトを叩く。"
            f"\nsite777: {', '.join(site777_stores())}"
        )
    return [require_one_store(store_arg)]


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
