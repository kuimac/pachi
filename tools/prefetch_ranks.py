#!/usr/bin/env python3
"""無料公開の出玉ランキング等を取得し CSV 化する（個人情報・認証は扱わない）。

取得後は ./tools/publish.sh か python3 tools/build_html.py で
docs/店舗/<店>/出玉ランキング.html（取得時刻付き）を更新する。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = ROOT / "tools" / "prefetch_snapshots"
TZ = ZoneInfo("Asia/Tokyo")
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

STORES: dict[str, dict[str, object]] = {
    "中山UNO": {
        "kind": "site777_rank",
        "url": "https://m.site777.jp/f/D0900.do?pmc=13003016&clc=01",
        "models_url": "https://m.site777.jp/f/D0300.do?pmc=13003016&clc=01&urt=400&pan=1",
        "csv_dir": "中山UNO",
        "expected_rate_hint": "4パチ",
    },
    "中山ZoRoN": {
        "kind": "site777_rank",
        "url": "https://m.site777.jp/f/D0900.do?pmc=13003032&clc=01",
        "models_url": "https://m.site777.jp/f/D0300.do?pmc=13003032&clc=01&urt=434&pan=1",
        "csv_dir": "中山ZoRoN",
        "expected_rate_hint": "500円/115玉",
    },
    "エスパス日拓西武新宿駅前店": {
        "kind": "site777_rank",
        "url": "https://m.site777.jp/f/D0900.do?pmc=13031023&clc=01",
        "models_url": "https://m.site777.jp/f/D0300.do?pmc=13031023&clc=01&urt=400&pan=1",
        "csv_dir": "エスパス日拓西武新宿駅前店",
        "expected_rate_hint": "4パチ",
    },
    "楽園町田店": {
        # Site Seven 無料出玉ランキング（全台）。DeltaNet 機種一覧は fetch_deltanet_tables.py。
        "kind": "site777_rank",
        "url": "https://m.site777.jp/f/D0900.do?pmc=22021031&clc=01",
        "models_url": "https://m.site777.jp/f/D0300.do?pmc=22021031&clc=01&urt=400&pan=1",
        "csv_dir": "楽園町田店",
        "expected_rate_hint": "4パチ",
    },
    "楽園渋谷駅前店": {
        "kind": "site777_rank",
        "url": "https://m.site777.jp/f/D0900.do?pmc=22021029&clc=01",
        "models_url": "https://m.site777.jp/f/D0300.do?pmc=22021029&clc=01&urt=400&pan=1",
        "csv_dir": "楽園渋谷駅前店",
        "expected_rate_hint": "4パチ",
    },
    "楽園渋谷道玄坂店": {
        "kind": "site777_rank",
        "url": "https://m.site777.jp/f/D0900.do?pmc=22021014&clc=01",
        "models_url": "https://m.site777.jp/f/D0300.do?pmc=22021014&clc=01&urt=400&pan=1",
        "csv_dir": "楽園渋谷道玄坂店",
        "expected_rate_hint": "4パチ",
    },
    "エスパス日拓渋谷駅前新館": {
        "kind": "site777_rank",
        "url": "https://m.site777.jp/f/D0900.do?pmc=13031030&clc=01",
        "models_url": "https://m.site777.jp/f/D0300.do?pmc=13031030&clc=01&urt=400&pan=1",
        "csv_dir": "エスパス日拓渋谷駅前新館",
        "expected_rate_hint": "4パチ",
    },
}


def now_tokyo() -> datetime:
    return datetime.now(TZ)


def fetch(url: str, timeout: int = 45) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = res.read()
            code = getattr(res, "status", 200) or 200
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b"", str(e)
    except Exception as e:  # noqa: BLE001
        return 0, b"", str(e)
    return code, data, "ok"


def decode_html(raw: bytes) -> str:
    for enc in ("cp932", "utf-8", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


def html_to_lines(html: str) -> list[str]:
    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&[^;]+;", " ", text)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln]


def parse_site777_rank(html: str, day: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    lines = html_to_lines(html)
    joined = "\n".join(lines)
    meta: dict[str, object] = {
        "ok": False,
        "paywall": False,
        "period": "",
        "rate_labels": [],
        "row_count": 0,
        "columns_ok": False,
        "units": [],
        "machines": [],
    }
    if any(k in joined for k in ("有料会員", "有料メニューログイン", "reCAPTCHA")) and "集計期間" not in joined:
        meta["paywall"] = True
        return [], meta
    m = re.search(r"集計期間[：:]\s*([^\n＜＞]+)", joined)
    if m:
        meta["period"] = m.group(1).strip().strip("<>＜＞")
    rates = sorted(set(re.findall(r"(?:4パチ|500円/115玉パチ|【4】パチ|100円/25玉)", joined)))
    meta["rate_labels"] = rates

    section_m = re.search(r"集計期間[：:]\s*[^\n]+\n", joined)
    section = joined[section_m.end() :] if section_m else joined
    section = re.split(r"表示説明|ホールトップ", section)[0]
    pat = re.compile(
        r"(?m)^(\d{1,2})\n"
        r"([\d,]+)G\n"
        r"(\d{4}/\d{1,2}/\d{1,2})\n"
        r"(\d+)\s*\n?番台\n"
        r"(.+?)\n"
        r"大当り回数\n?([\d,]+)\n"
        r"初当り回数\n?([\d,]+)\n"
        r"(.+?)\n"
        r"([+\-−]?[\d,]+)"
    )
    rows: list[dict[str, object]] = []
    for m in pat.finditer(section):
        rank, st, _d, dai, name, atari, hatsu, rate, saya = m.groups()
        rows.append(
            {
                "日付": day,
                "順位": int(rank),
                "台番号": dai,
                "機種": name.strip(),
                "累計スタート": int(st.replace(",", "")),
                "大当り回数": int(atari.replace(",", "")),
                "初当り回数": int(hatsu.replace(",", "")),
                "差玉": int(saya.replace(",", "").replace("−", "-")),
                "レート": rate.strip(),
            }
        )
    meta["row_count"] = len(rows)
    meta["columns_ok"] = len(rows) > 0
    meta["ok"] = bool(meta["period"]) and len(rows) > 0
    meta["units"] = [str(r["台番号"]) for r in rows]
    meta["machines"] = sorted({str(r["機種"]) for r in rows})
    return rows, meta


def parse_models_list(html: str) -> list[str]:
    lines = html_to_lines(html)
    names: list[str] = []
    for ln in lines:
        m = re.match(r"(.+?)\s*\[(\d+)\]\s*$", ln)
        if m:
            names.append(m.group(1).strip())
            continue
        if re.match(r"^[eｅEPＰPAひ]", ln) and len(ln) < 80 and "サイト" not in ln:
            if any(x in ln for x in ("物語", "エヴァ", "ゼロ", "喰種", "慶次", "北斗", "まどか", "牙狼")):
                names.append(ln.strip())
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def parse_deltanet_list(html: str, day: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    """機種一覧の有無だけスナップショット（詳細CSVは店依存のため行は空でも可）。"""
    lines = html_to_lines(html)
    joined = "\n".join(lines)
    meta: dict[str, object] = {
        "ok": False,
        "paywall": "ログイン" in joined and "機種" not in joined[:2000],
        "period": day,
        "rate_labels": [],
        "row_count": 0,
        "columns_ok": False,
        "units": [],
        "machines": [],
        "note": "DeltaNet list probe (free public page)",
    }
    machines = []
    for ln in lines:
        if re.search(r"[eｅEPＰ].{3,40}", ln) and "デルタ" not in ln:
            if any(k in ln for k in ("物語", "エヴァ", "ゼロ", "喰種", "Re:", "海物語", "北斗")):
                machines.append(ln.strip()[:80])
    machines = sorted(set(machines))[:80]
    meta["machines"] = machines
    meta["row_count"] = len(machines)
    meta["ok"] = "D0301" in html or "機種" in joined or len(machines) > 0
    meta["columns_ok"] = meta["ok"]
    return [], meta


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["日付", "順位", "台番号", "機種", "累計スタート", "大当り回数", "初当り回数", "差玉", "レート"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def load_snap(store: str) -> dict[str, object] | None:
    """直近の成功スナップショット（失敗 403 で上書きしない）。"""
    p = SNAP_DIR / store / "last.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_snap(store: str, snap: dict[str, object]) -> None:
    """毎回 last_attempt.json を書く。last.json は ok=True のときだけ更新。

    Cloud / ubuntu-latest Actions は Site Seven が 403 になりやすく、
    失敗で成功スナップショットを潰すと朝イチ差分が壊れる。
    """
    d = SNAP_DIR / store
    d.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snap, ensure_ascii=False, indent=2) + "\n"
    (d / "last_attempt.json").write_text(payload, encoding="utf-8")
    if snap.get("ok"):
        (d / "last.json").write_text(payload, encoding="utf-8")
    else:
        print(f"[snap] {store}: keep last.json (attempt failed; see last_attempt.json)")


def diff_report(store: str, prev: dict[str, object] | None, cur: dict[str, object], morning: bool) -> str:
    lines = [
        f"# {store} 無料データ差分",
        "",
        f"取得日時: {cur.get('fetched_at')}（Asia/Tokyo）",
        f"mode: {'morning' if morning else 'adhoc'}",
        "",
    ]
    if prev is None:
        lines += ["## 結果", "", "- **初回スナップショット**（比較対象なし）", ""]
        lines += ["## 今回", "", f"- 取得成否: `{cur.get('ok')}`", f"- 集計期間: `{cur.get('period')}`",
                  f"- 行数: `{cur.get('row_count')}`", f"- レート表記: `{cur.get('rate_labels')}`",
                  f"- 機種数: `{len(cur.get('machines') or [])}`", ""]
        return "\n".join(lines) + "\n"

    changes: list[str] = []
    if bool(prev.get("ok")) != bool(cur.get("ok")):
        changes.append(f"- 取得成否: `{prev.get('ok')}` → `{cur.get('ok')}`")
    if bool(prev.get("paywall")) != bool(cur.get("paywall")):
        changes.append(f"- 有料壁気配: `{prev.get('paywall')}` → `{cur.get('paywall')}`")
    if prev.get("period") != cur.get("period"):
        changes.append(f"- 集計期間: `{prev.get('period')}` → `{cur.get('period')}`")
    if prev.get("row_count") != cur.get("row_count"):
        changes.append(f"- ランキング行数: `{prev.get('row_count')}` → `{cur.get('row_count')}`")
    if prev.get("rate_labels") != cur.get("rate_labels"):
        changes.append(f"- レート表記: `{prev.get('rate_labels')}` → `{cur.get('rate_labels')}`")
    if bool(prev.get("columns_ok")) != bool(cur.get("columns_ok")):
        changes.append(f"- 列パース: `{prev.get('columns_ok')}` → `{cur.get('columns_ok')}`")

    prev_m = set(prev.get("machines") or [])
    cur_m = set(cur.get("machines") or [])
    added = sorted(cur_m - prev_m)
    removed = sorted(prev_m - cur_m)
    if added:
        changes.append(f"- 機種追加（最大20）: {', '.join(added[:20])}")
    if removed:
        changes.append(f"- 機種削除（最大20）: {', '.join(removed[:20])}")

    lines += ["## 結果", ""]
    if changes:
        lines.append("- **変更あり**")
        lines += changes
    else:
        lines.append("- **変更なし**（無料公開の取得成否・集計期間・行数・レート・機種セットは前回と同じ）")
    lines += ["", "## 今回", "", f"- 取得成否: `{cur.get('ok')}`", f"- 集計期間: `{cur.get('period')}`",
              f"- 行数: `{cur.get('row_count')}`", f"- 有料壁気配: `{cur.get('paywall')}`",
              f"- レート表記: `{cur.get('rate_labels')}`", f"- 機種数: `{len(cur_m)}`", ""]
    if cur.get("error"):
        lines += [f"- エラー: `{cur.get('error')}`", ""]
    return "\n".join(lines) + "\n"


def process_store(name: str, day: str, morning: bool, sleep_s: float) -> int:
    cfg = STORES[name]
    kind = str(cfg["kind"])
    url = str(cfg["url"])
    csv_dir = ROOT / str(cfg["csv_dir"])
    fetched_at = now_tokyo().strftime("%Y-%m-%d %H:%M")

    code, raw, err = fetch(url)
    time.sleep(sleep_s)
    html = decode_html(raw) if raw else ""
    rows: list[dict[str, object]] = []
    meta: dict[str, object]

    if code != 200 or not raw:
        meta = {
            "ok": False,
            "paywall": False,
            "period": "",
            "rate_labels": [],
            "row_count": 0,
            "columns_ok": False,
            "units": [],
            "machines": [],
            "error": f"http={code} {err}",
        }
    elif kind == "site777_rank":
        rows, meta = parse_site777_rank(html, day)
        models_url = cfg.get("models_url")
        if models_url:
            mcode, mraw, _ = fetch(str(models_url))
            time.sleep(sleep_s)
            if mcode == 200 and mraw:
                models = parse_models_list(decode_html(mraw))
                if models:
                    meta["machines"] = models
    else:
        rows, meta = parse_deltanet_list(html, day)

    meta["fetched_at"] = fetched_at
    meta["url"] = url
    meta["http_code"] = code
    meta["store"] = name
    meta["day"] = day
    if not meta.get("error") and err != "ok" and code == 0:
        meta["error"] = err

    if rows:
        write_csv(csv_dir / f"出玉ランキング_{day}.csv", rows)
        print(f"[ok] {name}: wrote {len(rows)} rows -> {csv_dir / f'出玉ランキング_{day}.csv'}")
    else:
        print(f"[warn] {name}: no rank rows (ok={meta.get('ok')} paywall={meta.get('paywall')} err={meta.get('error')})")

    prev = load_snap(name)
    report = diff_report(name, prev, meta, morning=morning)
    day_dir = ROOT / day / name
    day_dir.mkdir(parents=True, exist_ok=True)
    diff_path = day_dir / "無料データ差分.md"
    # 朝一は必ず書く（変更なしも明記）。adhoc は初回・変化時のみ。
    if morning or prev is None or "変更あり" in report or "初回" in report:
        diff_path.write_text(report, encoding="utf-8")
        print(f"[diff] {diff_path}")

    save_snap(name, meta)
    return 0 if meta.get("ok") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default="all", help="all or store name")
    ap.add_argument("--mode", choices=["morning", "adhoc"], default="adhoc")
    ap.add_argument("--day", default="", help="YYYY-MM-DD (default: today JST)")
    ap.add_argument("--sleep", type=float, default=2.0)
    args = ap.parse_args()
    day = args.day or now_tokyo().strftime("%Y-%m-%d")
    morning = args.mode == "morning"

    if args.store == "all":
        targets = list(STORES.keys())
    elif args.store in STORES:
        targets = [args.store]
    else:
        print(f"unknown store: {args.store}", file=sys.stderr)
        print("known:", ", ".join(STORES), file=sys.stderr)
        return 2

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for i, name in enumerate(targets):
        if i:
            time.sleep(args.sleep)
        failures += process_store(name, day, morning=morning, sleep_s=args.sleep)
    # morning: non-zero if any failure (so Actions can mark attention)
    if morning and failures:
        print(f"[morning] {failures} store(s) failed free fetch", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
