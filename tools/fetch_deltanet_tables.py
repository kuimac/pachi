#!/usr/bin/env python3
"""楽園町田店など DeltaNet の機種別・全台表（D2501）をゆっくり取得して CSV 化する。

分析・判定はしない。混雑エラー時は待機して再試行する。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Tokyo")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# D2301 メニュー順に対応する dt（実ページ見出しで検証済みの範囲）
DT_METRICS: list[tuple[int, str]] = [
    (1, "累計スタート"),
    (2, "大当り回数"),
    (9, "初当り回数"),
    (0, "最高出玉"),
    (3, "大当り確率"),
    (10, "初当り確率"),
    (12, "チャンス中大当り確率"),
    (8, "スタート"),
]

DAY_LABELS_P1 = ["当日", "前日", "2日前", "3日前"]
DAY_LABELS_P2 = ["4日前", "5日前", "6日前", "7日前"]


def now_tokyo() -> datetime:
    return datetime.now(TZ)


def decode_html(raw: bytes) -> str:
    for enc in ("cp932", "utf-8", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


class Session:
    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def _store_cookies(self, headers) -> None:  # noqa: ANN001
        for raw in headers.get_all("Set-Cookie") or []:
            part = raw.split(";", 1)[0]
            if "=" in part:
                k, v = part.split("=", 1)
                self.cookies[k.strip()] = v.strip()

    def get(self, url: str, timeout: int = 45, referer: str | None = None) -> tuple[int, bytes, str]:
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.7",
        }
        if self.cookies:
            headers["Cookie"] = self._cookie_header()
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                data = res.read()
                self._store_cookies(res.headers)
                return getattr(res, "status", 200) or 200, data, "ok"
        except urllib.error.HTTPError as e:
            if e.fp:
                try:
                    body = e.read()
                except Exception:  # noqa: BLE001
                    body = b""
            else:
                body = b""
            return e.code, body, str(e)
        except Exception as e:  # noqa: BLE001
            return 0, b"", str(e)


def is_busy(html: str) -> bool:
    return "PNW500034" in html or "混み合って" in html


def html_to_lines(html: str) -> list[str]:
    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = unescape(text)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln]


def parse_models(html: str) -> list[tuple[str, str, int]]:
    """(mdc, name, count) from D0301."""
    out: list[tuple[str, str, int]] = []
    for m in re.finditer(
        r'D2301\.do\?([^"\']*?mdc=(\d+)[^"\']*)"[\s\S]*?([^<>]+?)\s*\[(\d+)\]',
        html,
        re.I,
    ):
        mdc = m.group(2)
        name = re.sub(r"\s+", " ", unescape(m.group(3))).strip()
        count = int(m.group(4))
        out.append((mdc, name, count))
    seen: set[str] = set()
    uniq: list[tuple[str, str, int]] = []
    for mdc, name, count in out:
        if mdc in seen:
            continue
        seen.add(mdc)
        uniq.append((mdc, name, count))
    return uniq


def parse_table(html: str) -> tuple[str, str, list[str], dict[str, list[str]]]:
    """Return metric_title, updated_at, day_headers, {dai: values}."""
    lines = html_to_lines(html)
    metric = ""
    updated = ""
    for i, ln in enumerate(lines):
        if ln == "データ更新時間" and i + 1 < len(lines):
            updated = lines[i + 1]
        if ln in {m for _, m in DT_METRICS} and not metric:
            metric = ln
    rows = re.findall(r"<tr[\s\S]*?</tr>", html, re.I)
    headers: list[str] = []
    data: dict[str, list[str]] = {}
    for tr in rows:
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", tr, re.I)
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", unescape(c))).strip() for c in cells]
        if not cells:
            continue
        if cells[0] in {"台番", "台番号"}:
            headers = cells[1:]
            continue
        if cells[0].isdigit() and headers:
            data[cells[0]] = cells[1 : 1 + len(headers)]
    return metric, updated, headers, data


def relative_dates(base: datetime) -> dict[str, str]:
    mapping = {
        "当日": base.strftime("%Y-%m-%d"),
        "前日": (base - timedelta(days=1)).strftime("%Y-%m-%d"),
    }
    for n in range(2, 8):
        mapping[f"{n}日前"] = (base - timedelta(days=n)).strftime("%Y-%m-%d")
    return mapping


def write_metric_csvs(
    store_dir: Path,
    machine: str,
    metric: str,
    by_dai_day: dict[str, dict[str, str]],
    base_day: datetime,
) -> int:
    """Write 正規店名/<機種>/<台>/metric.csv ; return unit count touched."""
    rel = relative_dates(base_day)
    count = 0
    for dai, day_vals in by_dai_day.items():
        folder = store_dir / machine / dai
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{metric}.csv"
        # merge with existing if present
        existing: dict[str, str] = {}
        if path.exists():
            with path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    d = (row.get("日付") or "").strip()
                    v = (row.get(metric) or "").strip()
                    if d:
                        existing[d] = v
        for label, val in day_vals.items():
            d = rel.get(label)
            if d and val != "":
                existing[d] = val.replace(",", "")
        rows = []
        for d in sorted(existing):
            delta = (base_day.date() - datetime.strptime(d, "%Y-%m-%d").date()).days
            if delta == 0:
                rel_label = "当日"
            elif delta == 1:
                rel_label = "前日"
            else:
                rel_label = f"{delta}日前"
            rows.append({"日付": d, "相対日": rel_label, metric: existing[d]})
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["日付", "相対日", metric])
            w.writeheader()
            w.writerows(rows)
        count += 1
    return count


def rebuild_summary(store_dir: Path, machine: str, units: list[str]) -> None:
    """Rebuild 大当り一覧.csv from component metric CSVs when possible."""
    metrics = [
        "累計スタート",
        "大当り回数",
        "初当り回数",
        "最高出玉",
        "大当り確率",
        "初当り確率",
        "チャンス中大当り確率",
        "スタート",
    ]
    for dai in units:
        folder = store_dir / machine / dai
        by_day: dict[str, dict[str, str]] = {}
        for metric in metrics:
            path = folder / f"{metric}.csv"
            if not path.exists():
                continue
            with path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    d = (row.get("日付") or "").strip()
                    if not d:
                        continue
                    by_day.setdefault(d, {"日付": d, "相対日": row.get("相対日", "")})
                    by_day[d][metric] = row.get(metric, "")
        if not by_day:
            continue
        fields = ["日付", "相対日", *metrics]
        with (folder / "大当り一覧.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for d in sorted(by_day):
                w.writerow({k: by_day[d].get(k, "") for k in fields})


def fetch_with_retry(
    session: Session,
    url: str,
    *,
    sleep_s: float,
    retries: int,
    referer: str | None = None,
) -> tuple[int, str, str]:
    last_err = ""
    for attempt in range(retries + 1):
        code, raw, err = session.get(url, referer=referer)
        html = decode_html(raw) if raw else ""
        if code == 200 and html and not is_busy(html):
            time.sleep(sleep_s)
            return code, html, "ok"
        last_err = f"http={code} busy={is_busy(html)} err={err}"
        wait = sleep_s * (2 + attempt)
        time.sleep(wait)
    return 0, "", last_err


def process_store(pmc: str, store: str, sleep_s: float, retries: int, max_models: int) -> dict[str, object]:
    session = Session()
    store_dir = ROOT / store
    store_dir.mkdir(parents=True, exist_ok=True)
    base = f"https://www.d-deltanet.com/pc"
    list_url = f"{base}/D0301.do?pmc={pmc}&clc=01&urt=400&pan=1"
    code, html, err = fetch_with_retry(session, list_url, sleep_s=sleep_s, retries=retries)
    result: dict[str, object] = {
        "store": store,
        "pmc": pmc,
        "ok": False,
        "fetched_at": now_tokyo().strftime("%Y-%m-%d %H:%M"),
        "models": 0,
        "units": 0,
        "updated_at": "",
        "errors": [],
        "model_names": [],
    }
    if not html:
        result["errors"] = [f"D0301 failed: {err}"]
        return result

    models = parse_models(html)
    # also page 2+
    pan = 2
    while True:
        more_url = f"{base}/D0301.do?pmc={pmc}&clc=01&urt=400&pan={pan}"
        c2, h2, e2 = fetch_with_retry(session, more_url, sleep_s=sleep_s, retries=retries, referer=list_url)
        if not h2 or is_busy(h2):
            break
        extra = parse_models(h2)
        if not extra:
            break
        existing = {m[0] for m in models}
        added = [m for m in extra if m[0] not in existing]
        if not added:
            break
        models.extend(added)
        pan += 1
        if pan > 8:
            break

    if max_models > 0:
        models = models[:max_models]

    result["models"] = len(models)
    unit_total = 0
    updated_at = ""
    base_day = now_tokyo().replace(hour=0, minute=0, second=0, microsecond=0)
    # If early morning before open, hall data is previous calendar day.
    if now_tokyo().hour < 10:
        base_day = base_day - timedelta(days=1)

    for mdc, name, _count in models:
        model_url = f"{base}/D2301.do?pmc={pmc}&clc=01&urt=400&mdc={mdc}&bn=1"
        c, h, e = fetch_with_retry(session, model_url, sleep_s=sleep_s, retries=retries, referer=list_url)
        if not h:
            result["errors"].append(f"mdc={mdc} D2301: {e}")  # type: ignore[union-attr]
            continue
        lines = html_to_lines(h)
        if not name:
            for ln in lines:
                if re.search(r"\[\d+\]", ln):
                    name = re.sub(r"\s*\[\d+\]\s*$", "", ln).strip()
                    break
            if not name:
                for ln in lines:
                    if any(k in ln for k in ("物語", "ゼロ", "エヴァ", "e ", "P ", "PA", "ｅ", "Ｐ")):
                        name = ln.strip()
                        break
        if not name:
            name = f"mdc_{mdc}"
        result["model_names"].append(name)  # type: ignore[union-attr]

        # collect metrics across pan1/pan2
        by_metric_dai: dict[str, dict[str, dict[str, str]]] = {}
        units: set[str] = set()
        for dt, metric_name in DT_METRICS:
            for pan_i, expected_headers in ((1, DAY_LABELS_P1), (2, DAY_LABELS_P2)):
                url = (
                    f"{base}/D2501.do?pmc={pmc}&mdc={mdc}&bn=1&soc=1&sw=1"
                    f"&pan={pan_i}&dan=1&urt=400&dt={dt}"
                )
                c3, h3, e3 = fetch_with_retry(
                    session, url, sleep_s=sleep_s, retries=retries, referer=model_url
                )
                if not h3:
                    result["errors"].append(f"{name} dt={dt} pan={pan_i}: {e3}")  # type: ignore[union-attr]
                    continue
                metric, updated, headers, data = parse_table(h3)
                if updated and not updated_at:
                    updated_at = updated
                    # align base_day to update date if present
                    m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", updated)
                    if m:
                        base_day = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=TZ)
                use_metric = metric or metric_name
                if not data:
                    continue
                bucket = by_metric_dai.setdefault(use_metric, {})
                for dai, vals in data.items():
                    units.add(dai)
                    day_map = bucket.setdefault(dai, {})
                    for lab, val in zip(headers or expected_headers, vals):
                        day_map[lab] = val

        for metric, by_dai in by_metric_dai.items():
            write_metric_csvs(store_dir, name, metric, by_dai, base_day)
        if units:
            rebuild_summary(store_dir, name, sorted(units, key=int))
            unit_total += len(units)
            print(f"[ok] {store} {name}: {len(units)} units, metrics={list(by_metric_dai)}")
        else:
            print(f"[warn] {store} {name}: no unit rows")

    result["units"] = unit_total
    result["updated_at"] = updated_at
    result["ok"] = unit_total > 0
    result["base_day"] = base_day.strftime("%Y-%m-%d")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pmc", default="22021031", help="DeltaNet hall code")
    ap.add_argument("--store", default="楽園町田店")
    ap.add_argument("--sleep", type=float, default=3.5)
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--max-models", type=int, default=0, help="0=all")
    args = ap.parse_args()
    result = process_store(args.pmc, args.store, args.sleep, args.retries, args.max_models)
    out = ROOT / "tools" / "prefetch_snapshots" / args.store
    out.mkdir(parents=True, exist_ok=True)
    import json

    (out / "deltanet_last.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
