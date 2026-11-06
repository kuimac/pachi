#!/usr/bin/env python3
"""Markdown と CSV を html/ 以下の閲覧用ページに変換する。"""

from __future__ import annotations

import csv
import os
import re
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote

import markdown

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "html"
STORE = ROOT / "楽園町田店"

PROB_COLS = {"大当り確率", "初当り確率", "チャンス中大当り確率", "確率"}
COUNT_COLS = {"スタート", "累計スタート", "大当り回数", "初当り回数", "最高出玉", "回数"}
CHART_COLS = ["スタート", "大当り回数", "初当り回数", "最高出玉"]

KINDS = [
    ("やってはいけない", "caution"),
    ("触らない", "stop"),
    ("やめ時", "stop"),
    ("注意", "caution"),
    ("狙い目", "target"),
    ("測り方", "morning"),
    ("朝に測る", "morning"),
    ("朝イチ", "morning"),
    ("最初に見る", "important"),
    ("日中", "target"),
    ("ボーダー", "border"),
    ("基本情報", "spec"),
    ("スペック", "spec"),
    ("機種ごと", "spec"),
    ("天井", "caution"),
    ("モード", "spec"),
    ("打ち方", "target"),
    ("結論", "conclusion"),
    ("総評", "conclusion"),
    ("重要", "important"),
]

ALIASES = (
    ("鬼がかり", ("鬼がかり", "鬼がかり2")),
    ("リコリス", ("リコリコ", "リコリス")),
    ("電音部", ("電音部",)),
    ("ひぐらし", ("ひぐらし",)),
    ("カバネリ", ("カバネリ",)),
    ("異世界", ("リゼロ", "リゼロ2")),
    ("冴えない", ("冴えカノ",)),
    ("シンフォギア", ("シンフォギア",)),
    ("プリンセス", ("プリプリ",)),
    ("なのは", ("なのは",)),
    ("ドラム", ("電音部",)),
)

TODAY_ORDER = ["重要ポイント.md", "朝イチ狙い目.md", "台分析.md"]


def url_path(rel: str) -> str:
    parts = []
    for part in rel.split("/"):
        if part in ("", ".", ".."):
            parts.append(part)
        else:
            parts.append(quote(part, safe=""))
    return "/".join(parts)


def href(from_file: Path, to_file: Path, anchor: str = "") -> str:
    rel = os.path.relpath(to_file, from_file.parent)
    return url_path(rel) + anchor


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [name.strip() for name in (reader.fieldnames or [])]
        rows = []
        for raw in reader:
            row = {}
            for key, value in raw.items():
                if key is None:
                    continue
                row[key.strip()] = (value or "").strip()
            rows.append(row)
    return fieldnames, rows


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_date(value: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return value
    return f"{int(match.group(2))}/{int(match.group(3))}"


def fmt_time(value: str) -> str:
    if value in ("", "--", "—"):
        return "—"
    if re.fullmatch(r"\d{3,4}", value):
        text = value.zfill(4)
        return f"{text[:2]}:{text[2:]}"
    return value


def fmt_cell(column: str, value: str) -> str:
    if value in ("", "--"):
        return "—"
    if column in PROB_COLS and re.fullmatch(r"\d+", value):
        return f"1/{int(value):,}"
    if column in COUNT_COLS and re.fullmatch(r"-?\d+", value):
        return f"{int(value):,}"
    if column == "時間":
        return fmt_time(value)
    if column == "日付":
        return fmt_date(value)
    return value


def aliases_for(name: str) -> str:
    words = [name]
    for key, extra in ALIASES:
        if key == "異世界" and "鬼がかり" in name:
            continue
        if key in name:
            words.extend(extra)
    return " ".join(dict.fromkeys(words))


def section_kind(title: str) -> str:
    for key, kind in KINDS:
        if key in title:
            return kind
    return "plain"


def section_prose(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n+(.+?)(?=\n## |\Z)", text, re.S | re.M)
    if not match:
        return ""
    lines = []
    for line in match.group(1).splitlines():
        if not line.strip() or line.startswith("|") or line.startswith("- "):
            if lines:
                break
            continue
        lines.append(line.strip())
    return " ".join(lines)


def blurb(text: str, limit: int = 150) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("##"):
            break
        if line.startswith("#") or line.startswith("|") or line.startswith("- ") or not line.strip():
            continue
        lines.append(line.strip())
    summary = " ".join(lines) or section_prose(text, "総評")
    summary = re.sub(r"\s+", " ", summary)
    summary = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", summary)
    if len(summary) > limit:
        return summary[: limit - 1] + "…"
    return summary


def title_of(text: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.M)
    return match.group(1).strip() if match else fallback


def shell(from_file: Path, title: str, crumb: str, body: str, wide: bool = False) -> str:
    items = [
        ("目次", OUT / "index.html", ""),
        ("11/7の判断", OUT / "楽園町田店/2026-11-07/重要ポイント.html", ""),
        ("攻略", OUT / "index.html", "#guide"),
        ("スペック", OUT / "index.html", "#spec"),
        ("台データ", OUT / "index.html", "#machines"),
    ]
    nav = "".join(
        f'<a href="{href(from_file, path, anchor)}">{label}</a>'
        for label, path, anchor in items
    )
    css = href(from_file, OUT / "style.css")
    wide_class = " wide" if wide else ""
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<link rel="stylesheet" href="{css}">
</head>
<body class="{wide_class.strip()}">
<header class="top">
  <a class="brand" href="{href(from_file, OUT / 'index.html')}">楽園町田</a>
  <nav>{nav}</nav>
</header>
<main>
  <p class="crumb">{crumb}</p>
  {body}
</main>
</body>
</html>
"""


def crumb(from_file: Path, parts: list[tuple]) -> str:
    bits = []
    for part in parts:
        label, path = part[0], part[1]
        anchor = part[2] if len(part) > 2 else ""
        if path is None:
            bits.append(escape(label))
        else:
            bits.append(f'<a href="{href(from_file, path, anchor)}">{escape(label)}</a>')
    return " / ".join(bits)


def decorate_tables(fragment: str) -> str:
    def row(match: re.Match[str]) -> str:
        inner = match.group(1)
        today = False

        def cell(cell_match: re.Match[str]) -> str:
            nonlocal today
            content = cell_match.group(1)
            text = unescape(re.sub(r"<[^>]+>", "", content)).strip()
            classes = []
            if text == "当日":
                classes.append("today")
                today = True
            if text.startswith(("+", "＋")):
                classes.append("pos")
            elif text.startswith(("−", "-", "－")):
                classes.append("neg")
            if text.startswith("否"):
                classes.append("no")
            if re.fullmatch(r"[+＋−\-－]?[\d,]+(\.\d+)?(円(/千円|/朝)?)?", text):
                classes.append("num")
            if not classes:
                return cell_match.group(0)
            return f'<td class="{" ".join(classes)}">{content}</td>'

        inner = re.sub(r"<td>(.*?)</td>", cell, inner, flags=re.S)
        if today:
            return f'<tr class="is-today">{inner}</tr>'
        return f"<tr>{inner}</tr>"

    return re.sub(r"<tr>(.*?)</tr>", row, fragment, flags=re.S)


def link_units(fragment: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return fragment
    pattern = re.compile(r"(?<!\d)(" + "|".join(sorted(mapping, key=len, reverse=True)) + r")(?!\d)")
    parts = re.split(r"(<[^>]+>)", fragment)

    def replace(match: re.Match[str]) -> str:
        number = match.group(1)
        return f'<a class="unit-link" href="{escape(mapping[number], quote=True)}">{number}</a>'

    output = []
    for part in parts:
        if part.startswith("<"):
            output.append(part)
        else:
            output.append(pattern.sub(replace, part))
    return "".join(output)


def wrap_sections(fragment: str) -> tuple[str, str]:
    parts = re.split(r"(<h2>.*?</h2>)", fragment, flags=re.S)
    toc_items = []
    output = []
    if parts[0].strip():
        output.append(f'<div class="lede">{parts[0]}</div>')
    index = 1
    number = 1
    while index < len(parts):
        heading = parts[index]
        body = parts[index + 1] if index + 1 < len(parts) else ""
        text = unescape(re.sub(r"<[^>]+>", "", heading)).strip()
        kind = section_kind(text)
        hid = f"s{number}"
        heading = heading.replace("<h2>", f'<h2 id="{hid}">', 1)
        toc_items.append(f'<a href="#{hid}">{escape(text)}</a>')
        output.append(f'<section class="block {kind}">{heading}{body}</section>')
        number += 1
        index += 2
    toc_html = f'<nav class="toc">{"".join(toc_items)}</nav>' if toc_items else ""
    return toc_html, "\n".join(output)


def is_wide(fragment: str) -> bool:
    widths = []
    for row in re.findall(r"<tr>.*?</tr>", fragment, flags=re.S):
        widths.append(row.count("<th>") + row.count("<td>"))
    return max(widths, default=0) >= 7


def svg_bars(points: list[tuple[str, int | None]], label: str) -> str:
    width, height = 640, 196
    pad_l, pad_r, pad_t, pad_b = 8, 8, 22, 28
    count = len(points)
    if count == 0:
        return ""
    numbers = [value for _, value in points if value is not None]
    peak = max(numbers) if numbers else 1
    if peak <= 0:
        peak = 1
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    gap = 8 if count <= 10 else 4
    bar_w = max(2, (inner_w - gap * (count - 1)) / count)
    shapes = [
        f'<line x1="{pad_l}" y1="{pad_t + inner_h}" x2="{width - pad_r}" y2="{pad_t + inner_h}" stroke="#e4dcd0"/>'
    ]
    for index, (name, value) in enumerate(points):
        x = pad_l + index * (bar_w + gap)
        shown = 0 if value is None else value
        bar_h = inner_h * (shown / peak) if value is not None else 0
        if value == 0:
            bar_h = 2
        y = pad_t + inner_h - bar_h
        color = "#c4553a" if index == count - 1 else "#2f5d50"
        if value is None:
            color = "#d9d0c4"
        tip = f"{name} {fmt_int(value) if value is not None else '—'}"
        shapes.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(bar_h, 0):.1f}" rx="3" fill="{color}">'
            f"<title>{escape(tip)}</title></rect>"
        )
        if value not in (None, 0) and bar_w >= 28:
            shapes.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{max(y - 4, 12):.1f}" text-anchor="middle" font-size="11" fill="#1e1a16">{fmt_int(value)}</text>'
            )
        shapes.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 8}" text-anchor="middle" font-size="11" fill="#6f675e">{escape(name)}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">'
        + "".join(shapes)
        + "</svg>"
    )


def chart_block(rows: list[dict[str, str]], column: str) -> str:
    points = []
    for row in rows:
        day = row.get("相対日") or fmt_date(row.get("日付", ""))
        if row.get("日付"):
            day = fmt_date(row["日付"])
        points.append((day, to_int(row.get(column, ""))))
    note = "右端が当日。棒にカーソルを合わせると数値が出ます。"
    return (
        f'<section class="chart"><h3>{escape(column)}</h3><p>{note}</p>'
        f"{svg_bars(points, column)}</section>"
    )


def table_html(fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    heads = []
    for name in fieldnames:
        cls = ' class="num"' if name in COUNT_COLS or name in PROB_COLS or name == "時間" else ""
        heads.append(f"<th{cls}>{escape(name)}</th>")
    body = []
    for row in rows:
        today = row.get("相対日") == "当日"
        cells = []
        for name in fieldnames:
            value = fmt_cell(name, row.get(name, ""))
            classes = []
            if name in COUNT_COLS or name in PROB_COLS or name == "時間":
                classes.append("num")
            if name == "相対日" and value == "当日":
                classes.append("today")
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            cells.append(f"<td{class_attr}>{escape(value)}</td>")
        body.append(f'<tr class="{"is-today" if today else ""}">{"".join(cells)}</tr>')
    return (
        '<div class="table-wrap"><table class="sheet"><thead><tr>'
        + "".join(heads)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def history_html(rows: list[dict[str, str]]) -> str:
    days: list[tuple[str, str, list[dict[str, str]]]] = []
    for row in rows:
        if not days or days[-1][0] != row.get("日付", ""):
            days.append((row.get("日付", ""), row.get("相対日", ""), []))
        days[-1][2].append(row)
    blocks = []
    for index, (date, relative, items) in enumerate(days):
        closing = next((item for item in items if item.get("回数") == "-"), None)
        hits = [item for item in items if item.get("回数") not in ("-", "")]
        hits.sort(key=lambda item: to_int(item.get("回数")) or 0)
        close_text = fmt_cell("スタート", closing.get("スタート", "")) if closing else "—"
        summary = (
            f"{fmt_date(date)} {relative} · 当り {len(hits)}回 · 最終スタート {close_text}"
        )
        body_rows = []
        for hit in hits:
            body_rows.append(
                "<tr>"
                f'<td class="num">{escape(hit.get("回数", ""))}</td>'
                f'<td class="num">{escape(fmt_time(hit.get("時間", "")))}</td>'
                f'<td class="num">{escape(fmt_cell("スタート", hit.get("スタート", "")))}</td>'
                "</tr>"
            )
        if not body_rows:
            body_rows.append('<tr><td colspan="3">当りなし</td></tr>')
        opened = " open" if index >= len(days) - 2 else ""
        blocks.append(
            f"<details{opened}><summary>{escape(summary)}</summary>"
            '<div class="table-wrap"><table class="sheet"><thead><tr>'
            '<th class="num">回数</th><th class="num">時刻</th><th class="num">スタート</th>'
            f'</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div></details>'
        )
    return "\n".join(blocks)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def related_links(
    from_file: Path,
    stem: str,
    guides: dict[str, Path],
    specs: dict[str, Path],
    units_by_machine: dict[str, list[tuple[str, Path]]],
) -> str:
    links = []
    guide = guides.get(stem)
    spec = specs.get(stem)
    if guide and guide != from_file:
        links.append(f'<a href="{href(from_file, guide)}">攻略</a>')
    if spec and spec != from_file:
        links.append(f'<a href="{href(from_file, spec)}">スペック</a>')
    machine = stem if stem in units_by_machine else None
    if machine is None:
        for name in units_by_machine:
            if name.replace("ｅ", "e") == stem.replace("ｅ", "e"):
                machine = name
                break
    if machine:
        for number, page in units_by_machine[machine]:
            links.append(f'<a href="{href(from_file, page)}">{escape(number)}</a>')
    if not links:
        return ""
    return f'<div class="related">{"".join(links)}</div>'


def build_markdown(
    source: Path,
    dest: Path,
    group: str,
    group_anchor: str,
    unit_map: dict[str, str],
    guides: dict[str, Path],
    specs: dict[str, Path],
    units_by_machine: dict[str, list[tuple[str, Path]]],
) -> None:
    text = source.read_text(encoding="utf-8")
    title = title_of(text, source.stem)
    fragment = markdown.markdown(text, extensions=["tables", "sane_lists"])
    fragment = re.sub(r'href="([^"]+?)\.md"', lambda match: f'href="{url_path(match.group(1))}.html"', fragment)
    fragment = re.sub(r"^\s*<h1>.*?</h1>\s*", "", fragment, count=1, flags=re.S)
    toc_html, fragment = wrap_sections(fragment)
    wide = is_wide(fragment)
    def mark_dense(match: re.Match[str]) -> str:
        table = match.group(0)
        columns = table.split("</tr>", 1)[0].count("<th")
        if columns >= 6:
            table = table.replace("<table>", '<table class="dense">', 1)
        return f'<div class="table-wrap">{table}</div>'

    fragment = re.sub(r"<table>.*?</table>", mark_dense, fragment, flags=re.S)
    fragment = decorate_tables(fragment)
    fragment = link_units(fragment, unit_map)
    extra = related_links(dest, source.stem, guides, specs, units_by_machine)
    source_rel = escape(str(source.relative_to(ROOT)))
    body = (
        f"<h1>{escape(title)}</h1>{toc_html}{fragment}{extra}"
        f'<p class="foot">元ファイル <code>{source_rel}</code></p>'
    )
    page = shell(
        dest,
        title,
        crumb(
            dest,
            [
                ("目次", OUT / "index.html", ""),
                (group, OUT / "index.html", group_anchor),
            ],
        ),
        body,
        wide=wide,
    )
    write(dest, page)


def build_csv_page(
    source: Path,
    dest: Path,
    machine: str,
    number: str,
    unit_page: Path,
    guide: Path | None,
    spec: Path | None,
) -> None:
    fieldnames, rows = read_csv(source)
    title = f"{number} {source.stem}"
    charts = ""
    if source.stem != "大当り履歴データ":
        present = [column for column in CHART_COLS if column in fieldnames]
        if source.stem in COUNT_COLS and source.stem in fieldnames:
            present = [source.stem]
        if present:
            charts = f'<div class="charts">{"".join(chart_block(rows, column) for column in present)}</div>'
    if source.stem == "大当り履歴データ":
        data = (
            '<p class="section-label">日付ごとの当り</p>'
            "<p>回数の「-」は、その日の最終スタートとして上の行にまとめています。時刻は当日の当り時刻です。</p>"
            + history_html(rows)
        )
    else:
        note = ""
        if any(name in PROB_COLS for name in fieldnames):
            note = "<p>確率は分母です。772 なら 1/772 と表示しています。</p>"
        data = note + table_html(fieldnames, rows)
    links = [f'<a href="{href(dest, unit_page)}">この台のまとめ</a>']
    if guide:
        links.append(f'<a href="{href(dest, guide)}">攻略</a>')
    if spec:
        links.append(f'<a href="{href(dest, spec)}">スペック</a>')
    body = (
        f'<p class="kicker">{escape(machine)}</p><h1>{escape(number)} {escape(source.stem)}</h1>'
        f'<div class="related">{"".join(links)}</div>{charts}{data}'
        f'<p class="foot">元ファイル <code>{escape(str(source.relative_to(ROOT)))}</code></p>'
    )
    page = shell(
        dest,
        f"{title} / {machine}",
        crumb(
            dest,
            [
                ("目次", OUT / "index.html", ""),
                ("台データ", OUT / "index.html", "#machines"),
                (machine, guide or spec or unit_page, ""),
                (number, unit_page, ""),
                (source.stem, None),
            ],
        ),
        body,
        wide=True,
    )
    write(dest, page)


def build_unit_page(
    machine: str,
    number: str,
    folder: Path,
    dest: Path,
    siblings: list[tuple[str, Path]],
    guide: Path | None,
    spec: Path | None,
    csv_pages: list[tuple[str, Path]],
) -> None:
    files = {path.stem: path for path in folder.glob("*.csv")}
    summary_name = "大当り一覧"
    fieldnames, rows = read_csv(files[summary_name]) if summary_name in files else ([], [])
    latest = rows[-1] if rows else {}
    first = rows[0] if rows else {}
    span = ""
    if first and latest:
        span = f'{escape(first.get("日付", ""))} 〜 {escape(latest.get("日付", ""))}（{escape(latest.get("相対日", ""))}）'
    stats = []
    for column, label in (
        ("スタート", "最終スタート"),
        ("累計スタート", "累計スタート"),
        ("大当り回数", "大当り回数"),
        ("初当り回数", "初当り回数"),
        ("最高出玉", "最高出玉"),
        ("大当り確率", "大当り確率"),
        ("初当り確率", "初当り確率"),
        ("チャンス中大当り確率", "チャンス中確率"),
    ):
        if column not in latest:
            continue
        stats.append(
            f'<div class="stat"><span>{escape(label)}</span><b>{escape(fmt_cell(column, latest.get(column, "")))}</b></div>'
        )
    graph_rows = read_csv(files["出玉推移グラフ"])[1] if "出玉推移グラフ" in files else rows
    charts = "".join(chart_block(graph_rows, column) for column in CHART_COLS)
    history = ""
    if "大当り履歴データ" in files:
        _, history_rows = read_csv(files["大当り履歴データ"])
        history = (
            '<p class="section-label">大当り履歴</p>'
            "<p>当日と前日を開いています。回数の「-」は最終スタートです。</p>"
            + history_html(history_rows)
        )
    daily = table_html(fieldnames, rows) if rows else ""
    links = []
    if guide:
        links.append(f'<a href="{href(dest, guide)}">攻略</a>')
    if spec:
        links.append(f'<a href="{href(dest, spec)}">スペック</a>')
    index = next(i for i, (num, _) in enumerate(siblings) if num == number)
    pager = ['<div class="pager">']
    if index > 0:
        prev_num, prev_page = siblings[index - 1]
        pager.append(f'<a href="{href(dest, prev_page)}">← {escape(prev_num)}</a>')
    else:
        pager.append("<span></span>")
    if index + 1 < len(siblings):
        next_num, next_page = siblings[index + 1]
        pager.append(f'<a href="{href(dest, next_page)}">{escape(next_num)} →</a>')
    pager.append("</div>")
    sources = "".join(f'<a href="{href(dest, page)}">{escape(name)}</a>' for name, page in csv_pages)
    body = (
        f'<p class="kicker">{escape(machine)}</p><h1>台 {escape(number)}</h1>'
        f"<p>{span}</p>"
        f'<div class="related">{"".join(links)}</div>'
        f'<div class="stats">{"".join(stats)}</div>'
        f'<div class="charts">{charts}</div>'
        '<p class="section-label">日別</p>'
        "<p>確率は分母です。772 なら 1/772 と表示しています。</p>"
        f"{daily}{history}"
        '<p class="section-label">元のCSV</p>'
        f'<div class="sources">{sources}</div>'
        + "".join(pager)
    )
    page = shell(
        dest,
        f"{number} {machine}",
        crumb(
            dest,
            [
                ("目次", OUT / "index.html", ""),
                ("台データ", OUT / "index.html", "#machines"),
                (machine, guide or spec or (OUT / "index.html"), "#machines" if not (guide or spec) else ""),
                (number, None),
            ],
        ),
        body,
        wide=True,
    )
    write(dest, page)


def build_index(
    today_pages: list[tuple[str, str, Path]],
    guide_cards: list[tuple[str, str, Path, Path | None, list[tuple[str, Path]]]],
    spec_cards: list[tuple[str, str, Path, Path | None, list[tuple[str, Path]]]],
    machines: list[tuple[str, Path | None, Path | None, list[tuple[str, Path, dict[str, str]]]]],
) -> None:
    dest = OUT / "index.html"

    def card(kicker: str, title: str, summary: str, page: Path, find: str, extra: str = "") -> str:
        return (
            f'<a class="card" data-find="{escape(find)}" href="{href(dest, page)}">'
            f'<span class="kicker">{escape(kicker)}</span><h3>{escape(title)}</h3>'
            f"<p>{escape(summary)}</p>{extra}</a>"
        )

    today_html = []
    for label, summary, page in today_pages:
        today_html.append(card("11月7日", label, summary, page, f"{label} {summary}"))

    guide_html = []
    for title, summary, page, spec, units, machine_id in guide_cards:
        extra_bits = []
        if spec:
            extra_bits.append(f'<a href="{href(dest, spec)}">スペック</a>')
        if units and machine_id:
            extra_bits.append(f'<a href="#{machine_id}">台 {len(units)}</a>')
        extra = f'<div class="links">{"".join(extra_bits)}</div>' if extra_bits else ""
        find = aliases_for(title) + " " + " ".join(num for num, _ in units)
        guide_html.append(
            f'<div class="card" data-find="{escape(find)}">'
            f'<a href="{href(dest, page)}"><span class="kicker">攻略</span><h3>{escape(title)}</h3>'
            f"<p>{escape(summary)}</p></a>{extra}</div>"
        )

    spec_html = []
    for title, summary, page, guide, units in spec_cards:
        extra = ""
        if guide:
            extra = f'<div class="links"><a href="{href(dest, guide)}">攻略</a></div>'
        find = aliases_for(title) + " " + " ".join(num for num, _ in units)
        spec_html.append(
            f'<div class="card" data-find="{escape(find)}">'
            f'<a href="{href(dest, page)}"><span class="kicker">スペック</span><h3>{escape(title)}</h3>'
            f"<p>{escape(summary)}</p></a>{extra}</div>"
        )

    machine_ids = {name: f"m{index}" for index, (name, _, _, _) in enumerate(machines)}
    machine_html = []
    for name, guide, spec, units in machines:
        links = []
        if guide:
            links.append(f'<a href="{href(dest, guide)}">攻略</a>')
        if spec:
            links.append(f'<a href="{href(dest, spec)}">スペック</a>')
        chips = []
        for number, page, latest in units:
            start = fmt_cell("スタート", latest.get("スタート", ""))
            wins = fmt_cell("大当り回数", latest.get("大当り回数", ""))
            best = fmt_cell("最高出玉", latest.get("最高出玉", ""))
            chips.append(
                f'<a class="unit" data-find="{escape(number)}" href="{href(dest, page)}">'
                f"<strong>{escape(number)}</strong>"
                f"<small>スタート {escape(start)} · 大当り {escape(wins)}</small>"
                f"<small>最高出玉 {escape(best)}</small></a>"
            )
        machine_html.append(
            f'<section class="machine" id="{escape(machine_ids[name])}" data-find="{escape(aliases_for(name))}">'
            f"<h3>{escape(name)} <span class=\"sublinks\">{''.join(links)}</span></h3>"
            f'<div class="units">{"".join(chips)}</div></section>'
        )

    body = f"""
<h1>楽園町田店の控え</h1>
<p class="intro">攻略、スペック、11月7日の判断、各台のCSVをブラウザで読めるようにしてあります。台番号は各ページからその台の履歴へ飛べます。</p>
<input class="search" id="q" type="search" placeholder="台番号、機種名（なのは、鬼がかり、1088）" autocomplete="off">
<p id="empty" class="empty" hidden>一致するページがありません。</p>
<p class="section-label" id="today">11月7日の判断</p>
<div class="doc-grid" id="today-cards">{''.join(today_html)}</div>
<p class="section-label" id="guide">攻略情報</p>
<div class="cards" id="guide-cards">{''.join(guide_html)}</div>
<p class="section-label" id="spec">機種スペック</p>
<div class="cards" id="spec-cards">{''.join(spec_html)}</div>
<p class="section-label" id="machines">台データ（当日）</p>
<div id="machine-list">{''.join(machine_html)}</div>
<p class="foot">表示を作り直すときは <code>python3 tools/build_html.py</code></p>
<script>
const q = document.getElementById('q');
const empty = document.getElementById('empty');
q.addEventListener('input', () => {{
  const query = q.value.trim().toLowerCase();
  let shown = 0;
  document.querySelectorAll('.machine').forEach((sec) => {{
    const nameHit = !query || sec.dataset.find.toLowerCase().includes(query);
    let any = false;
    sec.querySelectorAll('.unit').forEach((unit) => {{
      const hit = nameHit || unit.dataset.find.toLowerCase().includes(query);
      unit.hidden = !!query && !hit;
      if (!unit.hidden) any = true;
    }});
    sec.hidden = !!query && !any;
    if (!sec.hidden) shown += 1;
  }});
  document.querySelectorAll('.doc-grid .card, .cards .card').forEach((card) => {{
    const hit = !query || card.dataset.find.toLowerCase().includes(query);
    card.hidden = !hit;
    if (hit) shown += 1;
  }});
  [
    ['today', 'today-cards'],
    ['guide', 'guide-cards'],
    ['spec', 'spec-cards'],
    ['machines', 'machine-list'],
  ].forEach(([labelId, boxId]) => {{
    const label = document.getElementById(labelId);
    const box = document.getElementById(boxId);
    if (!label || !box) return;
    const any = [...box.children].some((el) => !el.hidden);
    label.hidden = !!query && !any;
  }});
  empty.hidden = shown !== 0;
}});
</script>
"""
    page = shell(dest, "楽園町田店の控え", "目次", body, wide=True)
    write(dest, page)


def main() -> None:
    for path in OUT.rglob("*.html"):
        path.unlink()

    guide_sources = sorted((ROOT / "攻略情報").glob("*.md"))
    spec_sources = sorted((ROOT / "機種スペック").glob("*.md"), key=lambda path: (path.stem != "パチンコ用語一覧", path.stem))
    today_dir = STORE / "2026-11-07"
    today_sources = [today_dir / name for name in TODAY_ORDER if (today_dir / name).exists()]

    machines: list[tuple[str, list[tuple[str, Path]]]] = []
    for machine_dir in STORE.iterdir():
        if not machine_dir.is_dir() or re.fullmatch(r"\d{4}-\d{2}-\d{2}", machine_dir.name):
            continue
        units = []
        for unit_dir in machine_dir.iterdir():
            if unit_dir.is_dir() and unit_dir.name.isdigit():
                units.append((unit_dir.name, unit_dir))
        units.sort(key=lambda item: int(item[0]))
        if units:
            machines.append((machine_dir.name, units))
    machines.sort(key=lambda item: int(item[1][0][0]))

    guide_out = {path.stem: OUT / "攻略情報" / f"{path.stem}.html" for path in guide_sources}
    spec_out = {path.stem: OUT / "機種スペック" / f"{path.stem}.html" for path in spec_sources}
    units_by_machine = {
        name: [(number, OUT / "楽園町田店" / name / number / "index.html") for number, _ in units]
        for name, units in machines
    }
    unit_map_base = {
        number: page
        for units in units_by_machine.values()
        for number, page in units
    }

    def unit_map_for(dest: Path) -> dict[str, str]:
        return {number: href(dest, page) for number, page in unit_map_base.items()}

    for source in guide_sources:
        dest = guide_out[source.stem]
        build_markdown(
            source, dest, "攻略情報", "#guide", unit_map_for(dest), guide_out, spec_out, units_by_machine
        )
    for source in spec_sources:
        dest = spec_out[source.stem]
        build_markdown(
            source, dest, "機種スペック", "#spec", unit_map_for(dest), guide_out, spec_out, units_by_machine
        )
    for source in today_sources:
        dest = OUT / "楽園町田店" / "2026-11-07" / f"{source.stem}.html"
        build_markdown(
            source, dest, "11月7日の判断", "#today", unit_map_for(dest), guide_out, spec_out, units_by_machine
        )

    index_machines = []
    for name, units in machines:
        guide = guide_out.get(name)
        spec = spec_out.get(name)
        sibling_pages = units_by_machine[name]
        index_units = []
        for number, folder in units:
            unit_page = OUT / "楽園町田店" / name / number / "index.html"
            csv_pages = []
            for csv_path in sorted(folder.glob("*.csv")):
                csv_dest = unit_page.parent / f"{csv_path.stem}.html"
                build_csv_page(csv_path, csv_dest, name, number, unit_page, guide, spec)
                csv_pages.append((csv_path.stem, csv_dest))
            build_unit_page(name, number, folder, unit_page, sibling_pages, guide, spec, csv_pages)
            latest = {}
            summary = folder / "大当り一覧.csv"
            if summary.exists():
                _, rows = read_csv(summary)
                if rows:
                    latest = rows[-1]
            index_units.append((number, unit_page, latest))
        index_machines.append((name, guide, spec, index_units))

    today_pages = []
    for source in today_sources:
        text = source.read_text(encoding="utf-8")
        today_pages.append((source.stem, blurb(text), OUT / "楽園町田店/2026-11-07" / f"{source.stem}.html"))

    guide_cards = []
    for source in guide_sources:
        text = source.read_text(encoding="utf-8")
        units = units_by_machine.get(source.stem, [])
        machine_id = next((f"m{index}" for index, (name, *_) in enumerate(index_machines) if name == source.stem), "")
        guide_cards.append((title_of(text, source.stem), blurb(text), guide_out[source.stem], spec_out.get(source.stem), units, machine_id))

    spec_cards = []
    for source in spec_sources:
        text = source.read_text(encoding="utf-8")
        units = units_by_machine.get(source.stem, [])
        spec_cards.append((title_of(text, source.stem), blurb(text), spec_out[source.stem], guide_out.get(source.stem), units))

    build_index(today_pages, guide_cards, spec_cards, index_machines)
    html_count = sum(1 for _ in OUT.rglob("*.html"))
    print(f"wrote {html_count} html files under {OUT}")


if __name__ == "__main__":
    main()
