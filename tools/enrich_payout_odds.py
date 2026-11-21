#!/usr/bin/env python3
"""攻略MDに独立セクション『出玉確率』を追加する。

算出（近似・幾何モデル）:
  - ラッシュ突入率 p … スペック／大当り詳細から抽出（なければ算出不可）
  - 継続率 c … ST/RUSH継続率
  - 平均出玉 A … RUSH中の代表出玉（中央寄り）
  - 初当り1回あたり総出玉が閾値以上になる確率:
      非RUSHでは通常出玉のみ（多くの機種で3万未達）
      RUSH時は連チャン数 N ~ Geo(継続率c)（N=1,2,…、P(N=n)=c^(n-1)(1-c)）
      総出玉 ≈ N * A  （近似。初当り出玉差は無視しうる範囲で丸める）
      P(総出玉>=T) ≈ p * c^(k-1)  where k = ceil(T / A)
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE_DIR = ROOT / "攻略情報"
OUT_CSV = ROOT / ".cache" / "payout_odds_summary.csv"
SECTION = "## 出玉確率／期待出玉"
SKIP_NAMES = {
    "パチンコ用語一覧.md",
    "オカルトパチンコ動作一覧.md",
}

PRIORITY_SUBSTR = [
    "鬼がかり2",
    "アリシゼーション",
    "禁書目録3",
    "プリンシパル",
    "東京喰種",
    "はじまりの記憶",
    "未来への咆哮",
    "319 RED",
    "リコリス",
    "SEED",
    "アサルトリリィ",
    "電音部",
    "必殺仕事人",
]


@dataclass
class Odds:
    machine: str
    path: str
    rush_entry_pct: float | None
    cont_pct: float | None
    avg_payout: float | None
    p30_pct: float | None
    p50_pct: float | None
    status: str
    note: str


def pct_fmt(x: float | None) -> str:
    if x is None:
        return "—"
    if x >= 10:
        return f"約{x:.1f}%"
    if x >= 1:
        return f"約{x:.2f}%"
    if x >= 0.1:
        return f"約{x:.2f}%"
    if x >= 0.01:
        return f"約{x:.3f}%"
    if x > 0:
        # 1/N 表記の方が直感的
        n = max(int(round(100.0 / x)), 1)
        return f"約{x:.4f}%（≒1/{n}）"
    return "約0%"

def parse_pcts(text: str) -> list[tuple[str, float]]:
    hits: list[tuple[str, float]] = []
    for m in re.finditer(
        r"(.{0,40}?)(?:約)?(\d+(?:\.\d+)?)\s*%(.{0,40})",
        text,
    ):
        left, num, right = m.group(1), float(m.group(2)), m.group(3)
        ctx = (left + right).replace("\n", " ")
        hits.append((ctx, num))
    return hits


def pick_rush_entry(text: str, hits: list[tuple[str, float]]) -> float | None:
    # explicit table rows
    for pat in [
        r"RUSH突入率\s*\|\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"ラッシュ突入率\s*\|\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"ST突入\s*\|\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"突入率\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"トータル突入\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"初当り後は(?:約)?(\d+(?:\.\d+)?)%\s*で(?:RUSH|LT|ラッシュ)",
        r"大当り後は(?:約)?(\d+(?:\.\d+)?)%\s*で(?:RUSH|LT|ラッシュ)",
        r"(?:RUSH|ラッシュ|LT)突入\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"突入\s*(?:約)?(\d+(?:\.\d+)?)\s*%\s*/",
    ]:
        m = re.search(pat, text)
        if m:
            return float(m.group(1))

    # ST / RUSH 100%
    if re.search(r"ST\s*\|\s*突入\s*100\s*%", text) or re.search(
        r"突入\s*100\s*%", text
    ):
        if re.search(r"(ST|RUSH|電サポ)", text):
            return 100.0

    scored: list[tuple[float, float]] = []
    for ctx, num in hits:
        if num <= 0 or num > 100:
            continue
        cl = ctx.lower()
        if any(k in ctx for k in ("ボーダー", "回転", "等価", "交換", "削り")):
            continue
        score = 0.0
        if any(k in ctx for k in ("突入率", "トータル突入", "ST突入", "RUSH突入", "ラッシュ突入")):
            score += 5
        if "突入" in ctx and any(k in ctx for k in ("RUSH", "ラッシュ", "LT", "ST")):
            score += 4
        if "50%" in ctx or num == 50:
            score += 0.5
        if "継続" in ctx:
            score -= 3
        if score > 0:
            scored.append((score, num))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    return None


def pick_cont(text: str, hits: list[tuple[str, float]]) -> float | None:
    for pat in [
        r"RUSH継続率\s*\|\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"継続率\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"トータル継続\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"継続\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
        r"ST\d+\s*/\s*継続\s*(?:約)?(\d+(?:\.\d+)?)\s*%",
    ]:
        m = re.search(pat, text)
        if m:
            v = float(m.group(1))
            if 40 <= v <= 99.5:
                return v
    scored: list[tuple[float, float]] = []
    for ctx, num in hits:
        if not (40 <= num <= 99.5):
            continue
        if "継続" not in ctx:
            continue
        if any(k in ctx for k in ("ボーダー", "引き戻し")) and "継続" not in ctx[:10]:
            continue
        score = 3.0
        if any(k in ctx for k in ("RUSH", "ラッシュ", "ST", "LT")):
            score += 2
        if "トータル" in ctx:
            score += 1
        scored.append((score, num))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    return None


def pick_avg_payout(text: str) -> float | None:
    """RUSH中の代表出玉。小当り出玉や賞球を避け、1000個以上を優先。"""
    # Prefer 大当り詳細 / スペック出玉行
    focus_chunks: list[str] = []
    for heading in ("## 大当り詳細", "## スペック"):
        idx = text.find(heading)
        if idx >= 0:
            nxt = text.find("\n## ", idx + 4)
            focus_chunks.append(text[idx : nxt if nxt > 0 else idx + 3500])
    focus = "\n".join(focus_chunks) if focus_chunks else text

    vals: list[float] = []
    # 450or1500or3000or6000個
    for m in re.finditer(r"約?(\d{3,5}(?:\s*or\s*\d{3,5})+)個", focus):
        for part in re.findall(r"\d{3,5}", m.group(1)):
            v = float(part)
            if 400 <= v <= 20000:
                vals.append(v)
    for m in re.finditer(r"(.{0,40})約?(\d{3,5})\s*個(.{0,40})", focus):
        ctx = m.group(1) + m.group(3)
        if any(k in ctx for k in ("賞球", "ボーダー", "回転", "交換", "削り", "カウント", "代表出玉")):
            continue
        v = float(m.group(2))
        if not (400 <= v <= 20000):
            continue
        # RUSH中の出玉を優先するため、通常時の小さい玉は落とす
        if v <= 600 and any(k in ctx for k in ("通常", "3R", "チャンスタイム", "ヘソ")):
            continue
        if any(k in ctx for k in ("RUSH", "ラッシュ", "ST", "LT", "10R", "BONUS", "電チュー", "出玉", "大当り", "モード")):
            vals.append(v)
        elif v >= 1000:
            vals.append(v)

    if not vals:
        # fallback: any >=1000 in focus
        for m in re.finditer(r"約?(\d{3,5})\s*個", focus):
            v = float(m.group(1))
            if 1000 <= v <= 20000:
                vals.append(v)
    if not vals:
        return None
    rushish = [v for v in vals if v >= 1000]
    use = rushish or vals
    # 代表は中央値ではなく平均（1500と6000が混在する機種で過大/過小を抑える）
    return float(sum(use) / len(use))

def calc_reach(p_rush: float, c: float, avg: float, threshold: float) -> float:
    """Return percent 0-100."""
    if avg <= 0:
        return 0.0
    k = int(math.ceil(threshold / avg))
    k = max(k, 1)
    # P(N>=k) = c^(k-1) for Geo starting at 1 with continue c
    c_unit = c / 100.0
    p_unit = p_rush / 100.0
    if c_unit >= 1:
        c_unit = 0.999
    if c_unit <= 0:
        p_given = 1.0 if k <= 1 else 0.0
    else:
        p_given = c_unit ** (k - 1)
    # non-rush contribution: only if single non-rush payout could reach (rare)
    return 100.0 * p_unit * p_given


def build_section(o: Odds) -> str:
    lines = [
        SECTION,
        "",
        "初当り1回あたりの目安（スペックからの**近似**）。連チャン数は継続率の幾何分布、総出玉は「連チャン数×RUSH中の代表出玉」で概算。取りこぼし・モード分岐・上乗せループは粗く丸めている。",
        "",
        "| 項目 | 値 |",
        "| --- | --- |",
        f"| ラッシュ突入率 | {pct_fmt(o.rush_entry_pct)} |",
        f"| 3万発出る確率 | {pct_fmt(o.p30_pct)} |",
        f"| 5万発出る確率 | {pct_fmt(o.p50_pct)} |",
        "",
    ]
    prem = []
    if o.rush_entry_pct is not None:
        prem.append(f"突入率 {pct_fmt(o.rush_entry_pct)}")
    if o.cont_pct is not None:
        prem.append(f"継続率 {pct_fmt(o.cont_pct)}")
    if o.avg_payout is not None:
        prem.append(f"代表出玉 約{int(o.avg_payout)}個/当り")
    if prem:
        lines.append("- 前提: " + " / ".join(prem))
    lines.append(f"- 状態: {o.status}。{o.note}".rstrip("。") + "。")
    lines.append("")
    return "\n".join(lines)


def compute_for_text(name: str, path: Path, text: str) -> Odds:
    hits = parse_pcts(text)
    rush = pick_rush_entry(text, hits)
    cont = pick_cont(text, hits)
    avg = pick_avg_payout(text)

    # if entry missing but continuation exists and machine is always-ST style
    if rush is None and cont is not None and re.search(r"突入\s*100\s*%|ST\s*10\s*回|電サポ\s*100", text):
        rush = 100.0

    note_parts: list[str] = []
    status = "算出"

    if rush is None:
        status = "算出不可"
        note_parts.append("ラッシュ突入率がスペックから取れない")
    if cont is None:
        status = "算出不可" if status == "算出不可" else "一部のみ"
        note_parts.append("継続率が取れないため3万/5万は未算出" if rush is not None else "継続率不足")
    if avg is None:
        status = "算出不可" if rush is None else "一部のみ"
        note_parts.append("代表出玉が取れない")

    p30 = p50 = None
    if rush is not None and cont is not None and avg is not None:
        p30 = calc_reach(rush, cont, avg, 30000)
        p50 = calc_reach(rush, cont, avg, 50000)
        note_parts.append("近似（幾何・代表出玉）")
        status = "近似算出"
    elif rush is not None and (cont is None or avg is None):
        note_parts.append("突入率のみ記載")

    if not note_parts:
        note_parts.append("スペック記載ベース")

    return Odds(
        machine=name,
        path=str(path.relative_to(ROOT)),
        rush_entry_pct=rush,
        cont_pct=cont,
        avg_payout=avg,
        p30_pct=p30,
        p50_pct=p50,
        status=status,
        note="、".join(note_parts),
    )


def strip_section(text: str) -> str:
    """既存の出玉確率セクションを除いてから再算出する（自己参照汚染防止）。"""
    for title in (SECTION, "## 出玉確率"):
        if title in text:
            text = re.sub(
                rf"{re.escape(title)}\n.*?(?=\n## |\Z)",
                "",
                text,
                count=1,
                flags=re.S,
            )
    return text


def upsert_section(text: str, section: str) -> str:
    text = strip_section(text)
    if SECTION in text:
        return re.sub(
            rf"{re.escape(SECTION)}\n.*?(?=\n## |\Z)",
            section.rstrip() + "\n\n",
            text,
            count=1,
            flags=re.S,
        )
    # place after 大当り詳細 if present, else after スペック, else after title
    if "## 大当り詳細" in text:
        m = re.search(r"(## 大当り詳細\n.*?)(\n## )", text, flags=re.S)
        if m:
            return text[: m.end(1)] + "\n" + section + "\n" + text[m.start(2) + 1 :]
    if "## スペック" in text:
        m = re.search(r"(## スペック\n.*?)(\n## )", text, flags=re.S)
        if m:
            return text[: m.end(1)] + "\n" + section + "\n" + text[m.start(2) + 1 :]
    # after first heading block
    parts = text.split("\n", 1)
    if len(parts) == 1:
        return text + "\n\n" + section
    return parts[0] + "\n\n" + section + "\n" + parts[1]


def guide_sort_key(p: Path) -> tuple[int, str]:
    name = p.name
    for i, s in enumerate(PRIORITY_SUBSTR):
        if s in name:
            return (0, f"{i:02d}-{name}")
    return (1, name)


def main() -> None:
    guides = [
        p
        for p in GUIDE_DIR.glob("*.md")
        if p.name not in SKIP_NAMES and p.is_file()
    ]
    guides = sorted(guides, key=guide_sort_key)
    rows: list[Odds] = []
    for p in guides:
        raw = p.read_text(encoding="utf-8")
        text = strip_section(raw)
        o = compute_for_text(p.stem, p, text)
        section = build_section(o)
        new_text = upsert_section(text, section)
        if new_text != raw:
            p.write_text(new_text, encoding="utf-8")
        rows.append(o)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))

    ok = sum(1 for r in rows if r.p30_pct is not None)
    rush_only = sum(1 for r in rows if r.rush_entry_pct is not None and r.p30_pct is None)
    fail = sum(1 for r in rows if r.rush_entry_pct is None)
    print(f"guides={len(rows)} full={ok} rush_only={rush_only} no_rush={fail}")
    print(f"wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
