#!/usr/bin/env python3
"""DMM ぱちタウン（中山UNO）の jackpot 枠を取得する。Site Seven と併用する副ソース。

構造（2026-11-14 Cloud 検証）:
  - DMM HTML 自体は Cloud から 200（設置機種・最終更新日・出玉ランキング画像）
  - 台番号別の数値表は iframe → P'sCUBE
    https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c753211/
  - PSCUBE は Cloudflare で Cloud/AWS IP が 403。Mac 住宅 IP で再試行する。

Site Seven を置き換えない。成功時のみ snapshot を更新し、失敗は last_attempt に残す。
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
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = ROOT / "tools" / "prefetch_snapshots"
TZ = ZoneInfo("Asia/Tokyo")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# shop_id → store folder / pscube hall code (filled from DMM HTML when present)
STORES: dict[str, dict[str, str]] = {
    "中山UNO": {
        "pref": "kanagawa",
        "shop_id": "4564",
        "jackpot_url": "https://p-town.dmm.com/shops/kanagawa/4564/jackpot",
        "machines_url": "https://p-town.dmm.com/shops/kanagawa/4564/machines",
        "csv_dir": "中山UNO",
        # fallback if HTML の iframe.src 抽出に失敗したとき
        "pscube_fallback": "https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c753211/",
    },
}


def now_tokyo() -> datetime:
    return datetime.now(TZ)


def fetch(url: str, *, referer: str | None = None, timeout: int = 45) -> tuple[int, bytes, dict[str, str], str]:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            meta = {k.lower(): v for k, v in res.headers.items()}
            return getattr(res, "status", 200) or 200, res.read(), meta, "ok"
    except urllib.error.HTTPError as e:
        body = e.read() if e.fp else b""
        meta = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        return e.code, body, meta, str(e)
    except Exception as e:  # noqa: BLE001
        return 0, b"", {}, str(e)


def decode_html(raw: bytes) -> str:
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_pscube_url(html: str, fallback: str) -> str:
    m = re.search(r"iframe\.src\s*=\s*'(https://www\.pscube\.jp[^']+)'", html)
    if m:
        return m.group(1).rstrip("/") + "/"
    m = re.search(r'(https://www\.pscube\.jp/dedamajyoho[^"\'\s]+)', html)
    if m:
        return m.group(1).rstrip("/") + "/"
    return fallback.rstrip("/") + "/"


def extract_update_date(html: str) -> str:
    m = re.search(r"最終更新日:\s*([^<]+)", html)
    return m.group(1).strip() if m else ""


def extract_installs(html: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for block in re.findall(r'<ul class="list-machinesettings">([\s\S]*?)</ul>', html):
        kind = "パチ"
        if "スロ" in block[:200] or "slot" in block[:200].lower():
            kind = "スロ"
        h4 = re.search(r"<h4[^>]*>([\s\S]*?)</h4>", block)
        if h4:
            label = re.sub(r"<[^>]+>", "", unescape(h4.group(1)))
            if "スロ" in label:
                kind = "スロ"
            elif "パチ" in label:
                kind = "パチ"
        for li in re.findall(r'<li class="item">([\s\S]*?)</li>', block):
            a = re.search(r'href="(/machines/(\d+))"[^>]*>([^<]+)', li)
            n = re.search(r'class="number"[^>]*>\s*(\d+)', li)
            if not a or not n:
                continue
            rows.append(
                {
                    "machine_id": a.group(2),
                    "機種": unescape(a.group(3)).strip(),
                    "設置台数": int(n.group(1)),
                    "区分": kind,
                    "machine_url": f"https://p-town.dmm.com{a.group(1)}",
                }
            )
    # de-dupe by machine_id keep first
    seen: set[str] = set()
    out: list[dict[str, object]] = []
    for r in rows:
        mid = str(r["machine_id"])
        if mid in seen:
            continue
        seen.add(mid)
        out.append(r)
    return out


def extract_ranking_image_urls(html: str) -> list[tuple[str, str]]:
    """(label, absolute_url)"""
    out: list[tuple[str, str]] = []
    for m in re.finditer(
        r'src="(/upload/shop_dedama_rankings/\d+/[^"]+)"[^>]*alt="([^"]*)"',
        html,
    ):
        path, alt = m.group(1), m.group(2)
        label = "pachi" if "パチンコ" in alt else "slot" if "パチスロ" in alt or "スロ" in alt else "rank"
        out.append((label, "https://p-town.dmm.com" + path))
    # unique by url
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for lab, url in out:
        if url in seen:
            continue
        seen.add(url)
        uniq.append((lab, url))
    return uniq


def parse_pscube_tables(html: str) -> list[dict[str, str]]:
    """Best-effort: 台番/台番号 ヘッダの表を行化する。HTML が CF 障害ページなら空。"""
    if "challenge-platform" in html or "Ray ID:" in html and "P'sCUBE" in html and "メンテナンス" in html:
        return []
    if "お知らせ" in html and "メンテナンス" in html and "台番" not in html:
        return []
    rows_html = re.findall(r"<tr[\s\S]*?</tr>", html, re.I)
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    for tr in rows_html:
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", tr, re.I)
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", unescape(c))).strip() for c in cells]
        if not cells:
            continue
        joined = "".join(cells)
        if any(h in cells[0] for h in ("台番", "台番号")) or ("台番" in joined and not headers):
            headers = [c.replace("台番", "台番号") if c in {"台番", "台番号"} else c for c in cells]
            # normalize first col
            if headers and headers[0] in {"台番", "台番号"}:
                headers[0] = "台番号"
            continue
        if not headers:
            continue
        first = cells[0]
        if not re.fullmatch(r"\d{1,4}", first):
            continue
        row = {headers[i]: (cells[i] if i < len(cells) else "") for i in range(len(headers))}
        rows.append(row)
    return rows


def write_installs_csv(path: Path, day: str, installs: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["日付", "区分", "機種", "設置台数", "machine_id", "machine_url", "source"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in installs:
            w.writerow(
                {
                    "日付": day,
                    "区分": r.get("区分", ""),
                    "機種": r.get("機種", ""),
                    "設置台数": r.get("設置台数", ""),
                    "machine_id": r.get("machine_id", ""),
                    "machine_url": r.get("machine_url", ""),
                    "source": "dmm_ptown",
                }
            )


def write_pscube_csv(path: Path, day: str, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Prefer known columns; keep extras
    preferred = [
        "日付",
        "台番号",
        "機種",
        "累計スタート",
        "最終スタート",
        "大当り回数",
        "初当り回数",
        "最大放出数",
        "差玉",
        "source",
    ]
    extras: list[str] = []
    for r in rows:
        for k in r:
            if k not in preferred and k not in extras:
                extras.append(k)
    fields = preferred + extras
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {"日付": day, "source": "dmm_pscube", **r}
            # normalize unit key
            if "台番号" not in out and "台番" in out:
                out["台番号"] = out.pop("台番")
            w.writerow(out)


def process_store(name: str, day: str, sleep_s: float) -> dict[str, object]:
    cfg = STORES[name]
    jackpot_url = cfg["jackpot_url"]
    out_dir = ROOT / cfg["csv_dir"] / "dmm_ptown"
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {
        "store": name,
        "source": "dmm_ptown",
        "ok": False,
        "dmm_shell_ok": False,
        "pscube_ok": False,
        "fetched_at": now_tokyo().strftime("%Y-%m-%d %H:%M"),
        "day": day,
        "jackpot_url": jackpot_url,
        "pscube_url": "",
        "update_date_label": "",
        "installs": 0,
        "pscube_units": 0,
        "ranking_images": [],
        "errors": [],
        "egress_note": "DMM shell: Cloud OK. PSCUBE: Cloud/AWS often CF 403; use Mac residential IP.",
    }

    code, raw, _meta, err = fetch(jackpot_url)
    time.sleep(sleep_s)
    if code != 200 or not raw:
        result["errors"].append(f"jackpot: http={code} {err}")  # type: ignore[union-attr]
        return result

    html = decode_html(raw)
    result["dmm_shell_ok"] = True
    result["update_date_label"] = extract_update_date(html)
    pscube_url = extract_pscube_url(html, cfg["pscube_fallback"])
    result["pscube_url"] = pscube_url

    # jackpot ページは新台寄りになりがち → 機種一覧ページを優先して設置を取る
    installs = extract_installs(html)
    machines_url = cfg.get("machines_url") or ""
    if machines_url:
        mcode, mraw, _, merr = fetch(machines_url, referer=jackpot_url)
        time.sleep(sleep_s)
        if mcode == 200 and mraw:
            m_installs = extract_installs(decode_html(mraw))
            if len(m_installs) >= len(installs):
                installs = m_installs
            result["machines_page_ok"] = True
            result["machines_installs"] = len(m_installs)
        else:
            result["machines_page_ok"] = False
            result["errors"].append(f"machines: http={mcode} {merr}")  # type: ignore[union-attr]
    result["installs"] = len(installs)
    installs_csv = out_dir / f"設置機種_{day}.csv"
    write_installs_csv(installs_csv, day, installs)
    result["installs_csv"] = str(installs_csv.relative_to(ROOT))

    # ranking images (period top; includes 台番号 visually)
    img_dir = out_dir / "ranking_images" / day
    img_dir.mkdir(parents=True, exist_ok=True)
    saved_imgs: list[dict[str, str]] = []
    for label, url in extract_ranking_image_urls(html):
        icode, ibody, _, ierr = fetch(url, referer=jackpot_url)
        time.sleep(min(sleep_s, 1.0))
        if icode != 200 or not ibody:
            result["errors"].append(f"rank_img {label}: http={icode} {ierr}")  # type: ignore[union-attr]
            continue
        # follow cdn may already be absolute; save bytes
        ext = ".jpg"
        path = img_dir / f"{label}{ext}"
        path.write_bytes(ibody)
        saved_imgs.append({"label": label, "url": url, "path": str(path.relative_to(ROOT))})
    result["ranking_images"] = saved_imgs

    # PSCUBE attempt
    pcode, praw, pmeta, perr = fetch(pscube_url, referer=jackpot_url)
    time.sleep(sleep_s)
    server = (pmeta.get("server") or "").lower()
    result["pscube_http"] = pcode
    result["pscube_server"] = server
    if pcode != 200 or not praw:
        result["errors"].append(f"pscube: http={pcode} server={server} {perr}")  # type: ignore[union-attr]
        # shell alone is still useful
        result["ok"] = bool(installs) or bool(saved_imgs)
        return result

    phtml = decode_html(praw)
    # save raw for Mac/debug when not CF wall
    raw_path = out_dir / f"pscube_raw_{day}.html"
    if "challenge-platform" in phtml or ("Ray ID:" in phtml and "台番" not in phtml):
        result["errors"].append("pscube: cloudflare/challenge or maintenance wall")  # type: ignore[union-attr]
        (out_dir / f"pscube_block_{day}.html").write_text(phtml[:8000], encoding="utf-8")
        result["ok"] = bool(installs) or bool(saved_imgs)
        return result

    raw_path.write_text(phtml, encoding="utf-8")
    rows = parse_pscube_tables(phtml)
    result["pscube_units"] = len(rows)
    if rows:
        pcsv = out_dir / f"台データ_{day}.csv"
        write_pscube_csv(pcsv, day, rows)
        result["pscube_csv"] = str(pcsv.relative_to(ROOT))
        result["pscube_ok"] = True
        result["pscube_columns"] = sorted({k for r in rows for k in r})
    else:
        result["errors"].append("pscube: 200 but no 台番号 table parsed (layout may need Mac sample)")  # type: ignore[union-attr]

    result["ok"] = bool(installs) or bool(saved_imgs) or bool(rows)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default="中山UNO")
    ap.add_argument("--day", default="")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()
    day = args.day or now_tokyo().strftime("%Y-%m-%d")
    targets = list(STORES) if args.store == "all" else [args.store]
    for t in targets:
        if t not in STORES:
            print("unknown", t, file=sys.stderr)
            return 2

    failures = 0
    for i, name in enumerate(targets):
        if i:
            time.sleep(args.sleep)
        result = process_store(name, day, args.sleep)
        snap = SNAP_DIR / name
        snap.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        (snap / "dmm_ptown_last_attempt.json").write_text(payload, encoding="utf-8")
        if result.get("ok"):
            (snap / "dmm_ptown_last.json").write_text(payload, encoding="utf-8")
        else:
            print(f"[snap] {name}: keep dmm_ptown_last.json (attempt failed)")
        print(
            json.dumps(
                {
                    k: result.get(k)
                    for k in (
                        "store",
                        "ok",
                        "dmm_shell_ok",
                        "pscube_ok",
                        "installs",
                        "pscube_units",
                        "pscube_http",
                        "errors",
                    )
                },
                ensure_ascii=False,
            )
        )
        # PSCUBE 未取得でも shell 成功なら exit 0（併用の副ソースとして有用）
        if not result.get("ok"):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
