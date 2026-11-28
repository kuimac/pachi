#!/usr/bin/env python3
"""Site Seven 無料枠の機種別全台表（D3210）を取得して CSV 化する。分析はしない。

取得後は ./tools/publish.sh か python3 tools/build_html.py で
docs/店舗/<店>/全台一覧.html（取得時刻付き）を更新する。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Tokyo")
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

STORES: dict[str, dict[str, str]] = {
    "中山UNO": {"pmc": "13003016", "urt": "400", "rate": "4パチ"},
    "中山ZoRoN": {"pmc": "13003032", "urt": "434", "rate": "500円/115玉パチ"},
    "エスパス日拓西武新宿駅前店": {"pmc": "13031023", "urt": "400", "rate": "4パチ"},
    "楽園町田店": {"pmc": "22021031", "urt": "400", "rate": "4パチ"},
    "楽園渋谷駅前店": {"pmc": "22021029", "urt": "400", "rate": "4パチ"},
    "楽園渋谷道玄坂店": {"pmc": "22021014", "urt": "400", "rate": "4パチ"},
    "エスパス日拓渋谷駅前新館": {"pmc": "13031030", "urt": "400", "rate": "4パチ"},
    "楽園池袋店": {"pmc": "22021016", "urt": "400", "rate": "4パチ"},
}


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

    def get(self, url: str, timeout: int = 45) -> tuple[int, bytes, str]:
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,*/*",
            "Accept-Language": "ja",
        }
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                for raw in res.headers.get_all("Set-Cookie") or []:
                    part = raw.split(";", 1)[0]
                    if "=" in part:
                        k, v = part.split("=", 1)
                        self.cookies[k.strip()] = v.strip()
                return getattr(res, "status", 200) or 200, res.read(), "ok"
        except urllib.error.HTTPError as e:
            body = e.read() if e.fp else b""
            return e.code, body, str(e)
        except Exception as e:  # noqa: BLE001
            return 0, b"", str(e)


def html_to_lines(html: str) -> list[str]:
    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = unescape(text)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln]


def parse_models(html: str) -> list[tuple[str, str, int]]:
    """(mdc, name, count)"""
    out: list[tuple[str, str, int]] = []
    # Prefer D3210 / D2300 anchors with trailing [n]
    for m in re.finditer(
        r'(?:D3210|D2300)\.do\?([^"\']*?mdc=(\d+)[^"\']*)"[^>]*>[\s\S]*?([^<>]+?)\s*\[(\d+)\]',
        html,
        re.I,
    ):
        mdc, name, count = m.group(2), unescape(m.group(3)).strip(), int(m.group(4))
        name = re.sub(r"\s+", " ", name)
        out.append((mdc, name, count))
    if out:
        # unique preserve
        seen: set[str] = set()
        uniq = []
        for row in out:
            if row[0] in seen:
                continue
            seen.add(row[0])
            uniq.append(row)
        return uniq

    # Fallback: lines + mdc from hrefs in order
    mdcs = []
    for href in re.findall(r'href="([^"]+)"', html):
        href = unescape(href)
        if "mdc=" in href and ("D3210" in href or "D2300" in href or "D0300" not in href):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse("http://x/" + href).query)
            mdc = (qs.get("mdc") or [""])[0]
            if mdc and mdc not in mdcs:
                mdcs.append(mdc)
    names = []
    for ln in html_to_lines(html):
        m = re.match(r"(.+?)\s*\[(\d+)\]\s*$", ln)
        if m:
            names.append((m.group(1).strip(), int(m.group(2))))
    for i, mdc in enumerate(mdcs):
        name, count = names[i] if i < len(names) else (f"mdc_{mdc}", 0)
        out.append((mdc, name, count))
    return out


def parse_d3210(html: str) -> tuple[str, list[dict[str, str]]]:
    """Return machine name hint and rows."""
    lines = html_to_lines(html)
    machine = ""
    for i, ln in enumerate(lines):
        if ln.isdigit() and i > 0 and "台" in lines[i + 1 : i + 3]:
            # previous non-menu line may be machine
            pass
    # title pattern: 出玉情報｜店｜機種｜
    m = re.search(r"出玉情報｜[^｜]+｜([^｜]+)｜", html)
    if m:
        machine = unescape(m.group(1)).strip()
    rows_html = re.findall(r"<tr[\s\S]*?</tr>", html, re.I)
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    for tr in rows_html:
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", tr, re.I)
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", unescape(c))).strip() for c in cells]
        if not cells:
            continue
        if cells[0] in {"台番", "台番号"}:
            headers = cells
            continue
        if not headers or not cells[0].isdigit():
            continue
        row = {headers[i]: cells[i] if i < len(cells) else "" for i in range(len(headers))}
        rows.append(row)
    return machine, rows


FIELDS = ["日付", "台番号", "機種", "累計スタート", "大当り回数", "初当り回数", "最高出玉", "レート", "mdc", "設置台数"]


def fetch(session: Session, url: str, sleep_s: float) -> tuple[int, str, str]:
    code, raw, err = session.get(url)
    time.sleep(sleep_s)
    return code, decode_html(raw) if raw else "", err


def is_junk_model_name(name: str) -> bool:
    n = (name or "").strip()
    if not n or len(n) > 80:
        return True
    if n.startswith("!--") or "microad" in n.lower() or "script" in n.lower():
        return True
    return False


def list_models(session: Session, pmc: str, urt: str, sleep_s: float, errors: list[str]) -> list[tuple[str, str, int]]:
    base = "https://m.site777.jp/f"
    models: list[tuple[str, str, int]] = []
    pan = 1
    while pan <= 10:
        url = f"{base}/D0300.do?pmc={pmc}&clc=01&urt={urt}&pan={pan}"
        code, html, err = fetch(session, url, sleep_s)
        if code != 200 or not html:
            errors.append(f"D0300 pan={pan}: http={code} {err}")
            break
        chunk = parse_models(html)
        if not chunk:
            break
        existing = {m[0] for m in models}
        added = [m for m in chunk if m[0] not in existing and not is_junk_model_name(m[1])]
        if not added:
            break
        models.extend(added)
        pan += 1
    return models


def fetch_model_units(
    session: Session,
    *,
    pmc: str,
    urt: str,
    rate: str,
    day: str,
    mdc: str,
    machine: str,
    expected: int,
    sleep_s: float,
) -> tuple[list[dict[str, object]], str | None]:
    """Return (rows, error_or_None)."""
    base = "https://m.site777.jp/f"
    url = f"{base}/D3210.do?pmc={pmc}&soc=1&sw=1&pan=1&urt={urt}&dtdd=0&mdc={mdc}&bn=1"
    code, html, err = fetch(session, url, sleep_s)
    if code != 200 or not html:
        return [], f"{machine or mdc}: http={code} {err}"
    if "有料コンテンツです" in html and "台番" not in html:
        return [], f"{machine or mdc}: paywall"
    parsed_name, rows = parse_d3210(html)
    machine_name = parsed_name or machine or f"mdc_{mdc}"
    if not rows:
        return [], f"{machine_name}: no free unit rows"
    out: list[dict[str, object]] = []
    for row in rows:
        dai = row.get("台番") or row.get("台番号") or ""
        out.append(
            {
                "日付": day,
                "台番号": dai,
                "機種": machine_name,
                "累計スタート": (row.get("累計スタート") or "").replace(",", ""),
                "大当り回数": (row.get("大当り回数") or "").replace(",", ""),
                "初当り回数": (row.get("初当り回数") or "").replace(",", ""),
                "最高出玉": (row.get("最高出玉") or "").replace(",", ""),
                "レート": rate,
                "mdc": mdc,
                "設置台数": expected,
            }
        )
    return out, None


def write_units_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (str(x["機種"]), int(str(x["台番号"]) or 0))):
            w.writerow(r)


def process_store(
    name: str,
    day: str,
    sleep_s: float,
    *,
    retries: int = 3,
    retry_backoff_s: float = 60.0,
) -> dict[str, object]:
    """全台取得。509 等は欠落機種だけ待機リトライしてマージする。"""
    cfg = STORES[name]
    pmc, urt, rate = cfg["pmc"], cfg["urt"], cfg["rate"]
    session = Session()
    result: dict[str, object] = {
        "store": name,
        "ok": False,
        "fetched_at": now_tokyo().strftime("%Y-%m-%d %H:%M"),
        "day": day,
        "models": 0,
        "units": 0,
        "rate": rate,
        "errors": [],
        "retries_used": 0,
    }
    errors: list[str] = []
    models = list_models(session, pmc, urt, sleep_s, errors)
    result["catalog_models"] = len(models)

    by_mdc: dict[str, list[dict[str, object]]] = {}
    pending = list(models)
    attempt = 0
    max_attempts = max(1, retries)

    while pending and attempt < max_attempts:
        if attempt:
            wait = retry_backoff_s * attempt
            print(f"[retry] {name}: wait {wait:.0f}s then retry {len(pending)} models (attempt {attempt + 1}/{max_attempts})")
            time.sleep(wait)
            result["retries_used"] = attempt
        next_pending: list[tuple[str, str, int]] = []
        for mdc, machine, expected in pending:
            rows, err = fetch_model_units(
                session,
                pmc=pmc,
                urt=urt,
                rate=rate,
                day=day,
                mdc=mdc,
                machine=machine,
                expected=expected,
                sleep_s=sleep_s,
            )
            if err:
                next_pending.append((mdc, machine, expected))
                if attempt == max_attempts - 1:
                    errors.append(err)
                else:
                    print(f"[defer] {name} {machine or mdc}: {err}")
                continue
            machine_name = str(rows[0]["機種"]) if rows else machine
            by_mdc[mdc] = rows
            print(f"[ok] {name} {machine_name}: {len(rows)} units (expected {expected})")
        pending = next_pending
        attempt += 1

    all_rows: list[dict[str, object]] = []
    for rows in by_mdc.values():
        all_rows.extend(rows)

    out_dir = ROOT / name
    path = out_dir / f"全台データ_{day}.csv"
    write_units_csv(path, all_rows)

    result["errors"] = errors
    result["models"] = len({str(r["機種"]) for r in all_rows})
    result["units"] = len(all_rows)
    result["ok"] = len(all_rows) > 0
    result["csv"] = str(path.relative_to(ROOT))
    result["model_names"] = sorted({str(r["機種"]) for r in all_rows})
    result["missing_models"] = [m[1] for m in pending] if pending else []
    result["fetched_at"] = now_tokyo().strftime("%Y-%m-%d %H:%M")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default="all")
    ap.add_argument("--day", default="")
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--retries", type=int, default=3, help="欠落機種の再試行回数（509対策）")
    ap.add_argument("--retry-backoff", type=float, default=60.0, help="再試行前の待機秒（回数×この値）")
    args = ap.parse_args()
    day = args.day or now_tokyo().strftime("%Y-%m-%d")
    # early morning: hall data still previous calendar day
    if not args.day and now_tokyo().hour < 10:
        from datetime import timedelta

        day = (now_tokyo() - timedelta(days=1)).strftime("%Y-%m-%d")

    targets = list(STORES) if args.store == "all" else [args.store]
    for t in targets:
        if t not in STORES:
            print("unknown", t, file=sys.stderr)
            return 2

    snap = ROOT / "tools" / "prefetch_snapshots"
    snap.mkdir(parents=True, exist_ok=True)
    failures = 0
    for i, name in enumerate(targets):
        if i:
            time.sleep(args.sleep)
        result = process_store(
            name,
            day,
            args.sleep,
            retries=args.retries,
            retry_backoff_s=args.retry_backoff,
        )
        (snap / name).mkdir(parents=True, exist_ok=True)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        # 失敗で成功スナップショットを潰さない（Cloud/GHA の 403 対策）
        (snap / name / "site777_all_units_last_attempt.json").write_text(payload, encoding="utf-8")
        if result.get("ok"):
            (snap / name / "site777_all_units_last.json").write_text(payload, encoding="utf-8")
        else:
            print(f"[snap] {name}: keep site777_all_units_last.json (attempt failed)")
        summary = {k: result[k] for k in ("store", "ok", "units", "models", "csv", "retries_used", "missing_models")}
        print(json.dumps(summary, ensure_ascii=False))
        if not result.get("ok") or result.get("missing_models"):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
