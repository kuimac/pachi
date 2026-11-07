#!/usr/bin/env python3
"""Markdown と CSV を docs/ 以下の閲覧用ページに変換する。GitHub Pages はこのフォルダを公開する。"""

from __future__ import annotations

import csv
import json
import os
import re
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote

import markdown

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs"
STORES_FILE = ROOT / "店舗一覧.md"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

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

DETAIL_ORDER = [
    "重要ポイント.md",
    "朝イチ狙い目.md",
    "午後狙い目.md",
    "期待値が高い台.md",
    "台分析.md",
]


def load_store_names() -> list[str]:
    """店舗一覧.md の ## 見出しを正規店名として読む。"""
    if not STORES_FILE.exists():
        return []
    names = []
    for line in STORES_FILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^##\s+(.+)$", line.strip())
        if match:
            names.append(match.group(1).strip())
    return names


def load_store_aliases() -> dict[str, str]:
    """別名 → 正規店名。正規店名自身もキーに含める。"""
    if not STORES_FILE.exists():
        return {}
    aliases: dict[str, str] = {}
    current = ""
    for line in STORES_FILE.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##\s+(.+)$", line.strip())
        if heading:
            current = heading.group(1).strip()
            aliases[current] = current
            aliases[current.replace("店", "")] = current
            continue
        if not current:
            continue
        alias_line = re.match(r"^-\s*別名:\s*(.+)$", line.strip())
        if alias_line:
            for alias in re.split(r"[,、]", alias_line.group(1)):
                name = alias.strip()
                if name:
                    aliases[name] = current
    return aliases


def guess_region(store: str) -> str:
    if "町田" in store:
        return "町田"
    if "中山" in store:
        return "中山"
    return "その他"


def guess_station(store: str) -> str:
    if "町田" in store:
        return "町田駅"
    if "中山" in store:
        return "中山駅"
    return "未設定"


def load_store_field(label: str, fallback) -> dict[str, str]:
    """店舗一覧の `- {label}:` を正規店名 → 値で読む。未記載は fallback(店名)。"""
    values: dict[str, str] = {}
    if not STORES_FILE.exists():
        return values
    current = ""
    pattern = re.compile(rf"^-\s*{re.escape(label)}:\s*(.+)$")
    for line in STORES_FILE.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##\s+(.+)$", line.strip())
        if heading:
            current = heading.group(1).strip()
            values[current] = fallback(current)
            continue
        if not current:
            continue
        match = pattern.match(line.strip())
        if match:
            values[current] = match.group(1).strip()
    return values


def load_store_regions() -> dict[str, str]:
    return load_store_field("地域", guess_region)


def load_store_stations() -> dict[str, str]:
    return load_store_field("最寄り駅", guess_station)


def date_label(iso: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso)
    if not match:
        return iso
    return f"{int(match.group(2))}月{int(match.group(3))}日"


def analysis_datetime(text: str) -> str | None:
    """本文先頭の『分析日時: …』を返す。無ければ None。"""
    match = re.search(r"^分析日時:\s*(.+)$", text, re.M)
    if not match:
        return None
    return match.group(1).strip()


def analysis_time_label(text: str, day: str) -> str:
    """カード等に出す日時。分析日時があればそれを使い、なければ日付だけ。"""
    stamped = analysis_datetime(text)
    if stamped:
        # 「2026-11-07 01:33（Asia/Tokyo）」→「11月7日 01:33」
        match = re.match(
            r"(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}:\d{2})",
            stamped,
        )
        if match:
            return f"{int(match.group(2))}月{int(match.group(3))}日 {match.group(4)}"
        return stamped
    return date_label(day)


def discover_day_stores() -> list[tuple[str, str, Path]]:
    """(日付, 店舗, フォルダ) を新しい日付順で返す。同一日内は店舗名昇順。"""
    by_date: dict[str, list[tuple[str, str, Path]]] = {}
    for day_dir in ROOT.iterdir():
        if not day_dir.is_dir() or not DATE_RE.fullmatch(day_dir.name):
            continue
        for store_dir in day_dir.iterdir():
            if store_dir.is_dir() and any(store_dir.glob("*.md")):
                by_date.setdefault(day_dir.name, []).append((day_dir.name, store_dir.name, store_dir))
    ordered: list[tuple[str, str, Path]] = []
    for day in sorted(by_date, reverse=True):
        ordered.extend(sorted(by_date[day], key=lambda item: item[1]))
    return ordered


def list_machines(store: str) -> list[tuple[str, list[tuple[str, Path]]]]:
    store_dir = ROOT / store
    if not store_dir.is_dir():
        return []
    machines: list[tuple[str, list[tuple[str, Path]]]] = []
    for machine_dir in store_dir.iterdir():
        if not machine_dir.is_dir() or DATE_RE.fullmatch(machine_dir.name):
            continue
        units = []
        for unit_dir in machine_dir.iterdir():
            if unit_dir.is_dir() and unit_dir.name.isdigit():
                units.append((unit_dir.name, unit_dir))
        units.sort(key=lambda item: int(item[0]))
        if units:
            machines.append((machine_dir.name, units))
    machines.sort(key=lambda item: int(item[1][0][0]))
    return machines


def site_name(name: str) -> str:
    """GitHub Pages が配信できるパスにする。末尾の . と全角英字を避ける。"""
    chars = []
    for ch in name.rstrip("."):
        code = ord(ch)
        if 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:
            chars.append(chr(code - 0xFEE0))
        else:
            chars.append(ch)
    cleaned = "".join(chars)
    return cleaned or name


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


def table_value(text: str, label: str) -> str:
    """Markdown 表の `| label | value |` から value を取る。"""
    pattern = re.compile(
        rf"^\|\s*{re.escape(label)}\s*\|\s*([^|]+?)\s*\|",
        re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


TAG_CLASS = {
    "スマパチ": "sumapachi",
    "甘デジ": "amadig",
    "ライト": "light",
    "ライトミドル": "light-middle",
    "ミドル": "middle",
    "ハイミドル": "high-middle",
    "ハイレンジ": "high-range",
    "遊タイム": "yu-time",
    "ジンベェタイム": "jinbe",
    "LT": "lt",
    "V-ST": "vst",
    "ST": "st",
    "確変ループ": "kakuhen",
    "c時短": "c-jitan",
    "天井": "tenjo",
}


def tag_class(tag: str) -> str:
    slug = TAG_CLASS.get(tag)
    return f"tag tag-{slug}" if slug else "tag"


def spec_tags(text: str) -> list[str]:
    """機種スペック MD からカード用の属性ラベルを抽出する。"""
    type_val = table_value(text, "タイプ")
    yu_val = table_value(text, "遊タイム")
    lt_val = table_value(text, "ラッキートリガー") or table_value(text, "LT")
    ceiling_val = table_value(text, "天井")

    tags: list[str] = []

    def add(tag: str) -> None:
        if tag and tag not in tags:
            tags.append(tag)

    if "スマパチ" in type_val:
        add("スマパチ")

    for label in ("甘デジ", "ライトミドル", "ハイミドル", "ハイレンジ", "ミドル", "ライト"):
        if label == "ライト" and any(t in tags for t in ("ライトミドル", "甘デジ")):
            continue
        if label == "ミドル" and any(
            t in tags for t in ("ライトミドル", "ハイミドル", "ハイレンジ")
        ):
            continue
        if label in type_val:
            add(label)
            break

    def is_absent(val: str) -> bool:
        return bool(re.search(r"非搭載|なし|無し|^[-—]$", val.strip()))

    if "遊タイム" in type_val:
        add("遊タイム")
    elif yu_val and not is_absent(yu_val):
        add("遊タイム")
    if "ジンベェタイム" in type_val:
        add("ジンベェタイム")

    if lt_val and is_absent(lt_val):
        pass
    elif lt_val:
        add("LT")
    elif re.search(r"ラッキートリガー|(?<![A-Za-z])LT(?![A-Za-z])|LT\d", type_val):
        add("LT")

    if re.search(r"V-?ST", type_val):
        add("V-ST")
    elif re.search(r"(?<![A-Za-z])ST(?![A-Za-z])|ST機|ST（", type_val):
        add("ST")
    elif "確変ループ" in type_val:
        add("確変ループ")

    if re.search(r"c時短|ｃ時短", type_val):
        add("c時短")

    if ceiling_val and not is_absent(ceiling_val):
        add("天井")
    elif "天井" in type_val and "非搭載" not in type_val:
        add("天井")

    return tags[:6]


def blurb(text: str, limit: int = 150) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("##"):
            break
        if (
            line.startswith("#")
            or line.startswith("|")
            or line.startswith("- ")
            or line.startswith("分析日時:")
            or not line.strip()
        ):
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


def load_machine_borders() -> list[dict[str, object]]:
    """攻略情報の等価ボーダー一覧。機種名サジェスト用。"""
    guide_dir = ROOT / "攻略情報"
    if not guide_dir.is_dir():
        return []
    items: list[dict[str, object]] = []
    seen: set[str] = set()
    for path in sorted(guide_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"\|\s*4\.00円（等価）\s*\|\s*([^|]+)\|", text)
        if not match:
            continue
        raw = match.group(1).strip()
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", raw)]
        if not nums:
            continue
        if len(nums) >= 2 and re.search(r"[〜～~\-－]", raw):
            border = round((nums[0] + nums[1]) / 2, 1)
        else:
            border = nums[0]
        title = title_of(text, path.stem)
        key = re.sub(r"[:：]", ":", site_name(path.stem)).casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "name": title,
                "border": border,
                "find": aliases_for(title),
            }
        )
    items.sort(key=lambda row: str(row["name"]))
    return items


def table_sort_script() -> str:
    return """
<script>
(() => {
  const parse = (text) => {
    const raw = (text || '').replace(/\\s+/g, ' ').trim();
    if (!raw || raw === '—' || raw === '-' || raw === '－') return { n: null, s: '' };
    const cleaned = raw
      .replace(/,/g, '')
      .replace(/[＋]/g, '+')
      .replace(/[−－]/g, '-')
      .replace(/円(\\/千円|\\/朝)?$/u, '')
      .replace(/%$/u, '')
      .replace(/個$/u, '')
      .replace(/回$/u, '')
      .replace(/G$/iu, '');
    if (/^[+-]?\\d+(\\.\\d+)?$/.test(cleaned)) return { n: Number(cleaned), s: raw };
    return { n: null, s: raw.toLowerCase() };
  };
  const cellText = (td) => (td ? td.innerText || td.textContent || '' : '');
  document.querySelectorAll('table').forEach((table) => {
    const headRow = table.tHead && table.tHead.rows[0];
    const body = table.tBodies[0];
    if (!headRow || !body || body.rows.length < 2) return;
    table.classList.add('sortable');
    [...headRow.cells].forEach((th, col) => {
      if (th.colSpan > 1) return;
      th.tabIndex = 0;
      th.setAttribute('role', 'button');
      th.setAttribute('aria-sort', 'none');
      const activate = () => {
        const asc = th.dataset.sort !== 'asc';
        [...headRow.cells].forEach((cell) => {
          delete cell.dataset.sort;
          cell.setAttribute('aria-sort', 'none');
        });
        th.dataset.sort = asc ? 'asc' : 'desc';
        th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        const rows = [...body.rows].map((row, index) => {
          const value = parse(cellText(row.cells[col]));
          return { row, index, value };
        });
        rows.sort((a, b) => {
          const an = a.value.n;
          const bn = b.value.n;
          let cmp = 0;
          if (an != null && bn != null) cmp = an - bn;
          else if (an != null) cmp = -1;
          else if (bn != null) cmp = 1;
          else cmp = a.value.s.localeCompare(b.value.s, 'ja');
          if (cmp === 0) cmp = a.index - b.index;
          return asc ? cmp : -cmp;
        });
        rows.forEach(({ row }) => body.appendChild(row));
      };
      th.addEventListener('click', activate);
      th.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          activate();
        }
      });
    });
  });
})();
</script>
"""


def rotation_calc_markup(compact: bool = False) -> str:
    """1000円あたり回転数の入力 UI。compact=True はトップ埋め込み用。"""
    note = (
        '<p class="calc-note">通常時だけ数える。電サポ中は入れない。'
        "4円・100円25玉なら、玉250＝現金1000円。</p>"
        if not compact
        else '<p class="calc-note">通常時のみ。(現在−初期) ÷ (玉数÷250)</p>'
    )
    return f"""
<section class="calc" id="rotation-calc" aria-labelledby="calc-title">
  <div class="calc-head">
    <h2 id="calc-title">回転率計算</h2>
    <p class="calc-formula"><code>(現在スタート − 初期スタート) ÷ (玉数 ÷ 250)</code></p>
  </div>
  <div class="calc-grid">
    <label class="calc-field">
      <span>初期スタート</span>
      <input id="calc-initial" type="number" inputmode="decimal" step="1" min="0" placeholder="例 120" autocomplete="off">
    </label>
    <label class="calc-field">
      <span>使った玉数</span>
      <div class="calc-row">
        <input id="calc-balls" type="number" inputmode="decimal" step="125" min="0" placeholder="例 250" autocomplete="off">
        <button type="button" class="calc-btn" data-add-balls="125" title="125玉を足す">+125</button>
      </div>
    </label>
    <label class="calc-field">
      <span>現在スタート</span>
      <input id="calc-current" type="number" inputmode="decimal" step="1" min="0" placeholder="例 138" autocomplete="off">
    </label>
  </div>
  <div class="calc-result" aria-live="polite">
    <div class="stat">
      <b id="calc-rate">—</b>
      <span>1000円あたり回転数</span>
    </div>
    <div class="stat">
      <b id="calc-diff">—</b>
      <span>増えたスタート</span>
    </div>
    <div class="stat">
      <b id="calc-units">—</b>
      <span>使った1000円単位</span>
    </div>
  </div>
  {note}
</section>
<script>
(() => {{
  const initial = document.getElementById('calc-initial');
  const balls = document.getElementById('calc-balls');
  const current = document.getElementById('calc-current');
  const rateEl = document.getElementById('calc-rate');
  const diffEl = document.getElementById('calc-diff');
  const unitsEl = document.getElementById('calc-units');
  if (!initial || !balls || !current || !rateEl) return;

  const num = (el) => {{
    const v = el.value.trim();
    if (v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }};

  const fmt = (n, digits = 1) => {{
    if (!Number.isFinite(n)) return '—';
    const fixed = n.toFixed(digits);
    return fixed.replace(/\\.0+$/, '').replace(/(\\.[0-9]*?)0+$/, '$1');
  }};

  const render = () => {{
    const a = num(initial);
    const b = num(balls);
    const c = num(current);
    if (a === null || b === null || c === null || b <= 0) {{
      rateEl.textContent = '—';
      diffEl.textContent = '—';
      unitsEl.textContent = '—';
      rateEl.parentElement.classList.remove('good', 'bad');
      return;
    }}
    const diff = c - a;
    const units = b / 250;
    const rate = diff / units;
    diffEl.textContent = fmt(diff, 1);
    unitsEl.textContent = fmt(units, 2);
    rateEl.textContent = fmt(rate, 1);
    rateEl.parentElement.classList.toggle('good', rate >= 18);
    rateEl.parentElement.classList.toggle('bad', rate > 0 && rate < 16);
  }};

  [initial, balls, current].forEach((el) => {{
    el.addEventListener('input', render);
    el.addEventListener('change', render);
  }});

  document.querySelectorAll('[data-add-balls]').forEach((btn) => {{
    btn.addEventListener('click', () => {{
      const base = num(balls) ?? 0;
      balls.value = String(base + Number(btn.dataset.addBalls));
      balls.focus();
      render();
    }});
  }});
  render();
}})();
</script>
"""


def exchange_profit_markup(
    machines: list[dict[str, object]] | None = None,
    compact: bool = False,
) -> str:
    """4パチ・交換率ごとの期待収支。機種名サジェストで等価ボーダーを入れられる。"""
    machines = machines if machines is not None else load_machine_borders()
    machines_json = json.dumps(machines, ensure_ascii=False)
    note = (
        "<p class=\"calc-note\">貸玉4円。交換単価は玉数から換算（28玉→約3.57円）。"
        "各交換のボーダーは <code>等価ボーダー × √(4 ÷ 交換単価)</code>。"
        "期待差玉は <code>回転数 × 250 × (1/ボーダー − 1/回転率)</code>。"
        "機種名で検索すると攻略情報の等価ボーダーが入る。手入力でも上書きできる。</p>"
        if not compact
        else "<p class=\"calc-note\">機種名で検索可。ボーダーは √換算。単位は玉（下段は円）。</p>"
    )
    spins_ui = ""
    if not compact:
        spins_ui = """
    <div class="calc-presets" role="group" aria-label="回転数の目安">
      <button type="button" class="calc-btn" data-set-spins="800">800回転（約4時間）</button>
      <button type="button" class="calc-btn" data-set-spins="2000">2000回転（約10時間）</button>
    </div>"""
    return f"""
<section class="calc" id="profit-calc" aria-labelledby="profit-title">
  <div class="calc-head">
    <h2 id="profit-title">4パチ 交換率別の期待収支</h2>
    <p class="calc-formula"><code>差玉 = 回転数 × 250 × (1/ボーダー − 1/回転率)</code></p>
  </div>
  <div class="calc-field calc-machine">
    <span>機種名</span>
    <div class="suggest" id="profit-suggest">
      <input id="profit-machine" type="search" inputmode="search" placeholder="鬼がかり、なのは、電音部…" autocomplete="off" spellcheck="false" aria-autocomplete="list" aria-controls="profit-suggest-list" aria-expanded="false">
      <ul id="profit-suggest-list" class="suggest-list" role="listbox" hidden></ul>
    </div>
    <p class="calc-picked" id="profit-picked" hidden></p>
  </div>
  <div class="calc-grid calc-grid-profit">
    <label class="calc-field">
      <span>等価ボーダー</span>
      <input id="profit-border" type="number" inputmode="decimal" step="0.1" min="1" placeholder="機種を選ぶか手入力" autocomplete="off">
    </label>
    <label class="calc-field">
      <span>実測回転率（/1000円）</span>
      <input id="profit-rate" type="number" inputmode="decimal" step="0.1" min="1" placeholder="例 18.0" autocomplete="off">
    </label>
    <label class="calc-field">
      <span>通常回転数</span>
      <div class="calc-row">
        <input id="profit-spins" type="number" inputmode="decimal" step="1" min="1" value="800" autocomplete="off">
        <button type="button" class="calc-btn" data-set-spins="800" title="800回転">800</button>
        <button type="button" class="calc-btn" data-set-spins="2000" title="2000回転">2000</button>
      </div>
    </label>
  </div>
  {spins_ui}
  <div class="calc-result" aria-live="polite">
    <div class="stat">
      <b id="profit-eq-border">—</b>
      <span>等価ボーダー</span>
    </div>
    <div class="stat">
      <b id="profit-ball-28">—</b>
      <span>28玉の差玉</span>
    </div>
    <div class="stat">
      <b id="profit-yen-28">—</b>
      <span>28玉の収支円</span>
    </div>
  </div>
  <div class="table-wrap">
    <table class="profit-table" id="profit-table">
      <thead>
        <tr>
          <th>回転率</th>
          <th class="num">2.5円<br><small>40玉</small></th>
          <th class="num">3.0円<br><small>33玉</small></th>
          <th class="num">3.3円<br><small>30玉</small></th>
          <th class="num">3.5円<br><small>28玉</small></th>
          <th class="num">4.0円<br><small>25玉</small></th>
        </tr>
      </thead>
      <tbody id="profit-body"></tbody>
    </table>
  </div>
  <p class="calc-caption" id="profit-caption">通常時の期待収支一覧（単位: 玉 / 下段は円）</p>
  {note}
</section>
<script>
(() => {{
  const MACHINES = {machines_json};
  const borderEl = document.getElementById('profit-border');
  const rateEl = document.getElementById('profit-rate');
  const spinsEl = document.getElementById('profit-spins');
  const machineEl = document.getElementById('profit-machine');
  const suggestRoot = document.getElementById('profit-suggest');
  const suggestList = document.getElementById('profit-suggest-list');
  const pickedEl = document.getElementById('profit-picked');
  const body = document.getElementById('profit-body');
  const eqBorder = document.getElementById('profit-eq-border');
  const ball28 = document.getElementById('profit-ball-28');
  const yen28 = document.getElementById('profit-yen-28');
  const caption = document.getElementById('profit-caption');
  if (!borderEl || !rateEl || !spinsEl || !body) return;

  const EXCHANGES = [
    {{ label: '2.5', balls: 40 }},
    {{ label: '3.0', balls: 33 }},
    {{ label: '3.3', balls: 30 }},
    {{ label: '3.5', balls: 28 }},
    {{ label: '4.0', balls: 25 }}
  ];
  const RATES = [16,17,18,19,20,21,22,23,24,25,26,27,28,29,30];
  let activeIndex = -1;
  let matches = [];

  const num = (el) => {{
    const v = el.value.trim();
    if (v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }};

  const yenOf = (balls) => 100 / balls;
  const borderAt = (borderEq, yen) => borderEq * Math.sqrt(4 / yen);
  const netBalls = (spins, rate, border) => spins * 250 * (1 / border - 1 / rate);

  const fmtBalls = (n) => {{
    if (!Number.isFinite(n)) return '—';
    const rounded = Math.round(n);
    if (rounded > 0) return '+' + rounded.toLocaleString('ja-JP');
    return rounded.toLocaleString('ja-JP');
  }};
  const fmtYen = (n) => {{
    if (!Number.isFinite(n)) return '—';
    const rounded = Math.round(n);
    if (rounded > 0) return '+' + rounded.toLocaleString('ja-JP') + '円';
    return rounded.toLocaleString('ja-JP') + '円';
  }};
  const cellClass = (n) => (n > 0 ? 'pos' : n < 0 ? 'neg' : '');

  const normalize = (text) => (text || '').toLowerCase().replace(/\\s+/g, '');

  const filterMachines = (query) => {{
    const q = normalize(query);
    if (!q) return MACHINES.slice(0, 12);
    return MACHINES.filter((m) => normalize(m.find || m.name).includes(q)).slice(0, 12);
  }};

  const hideSuggest = () => {{
    if (!suggestList || !machineEl) return;
    suggestList.hidden = true;
    suggestList.innerHTML = '';
    machineEl.setAttribute('aria-expanded', 'false');
    activeIndex = -1;
    matches = [];
  }};

  const showSuggest = (items) => {{
    if (!suggestList || !machineEl) return;
    matches = items;
    activeIndex = items.length ? 0 : -1;
    suggestList.innerHTML = '';
    if (!items.length) {{
      hideSuggest();
      return;
    }}
    items.forEach((m, index) => {{
      const li = document.createElement('li');
      li.setAttribute('role', 'option');
      li.id = 'profit-opt-' + index;
      li.dataset.index = String(index);
      if (index === activeIndex) li.setAttribute('aria-selected', 'true');
      li.innerHTML = `<span class="suggest-name">${{m.name}}</span>`
        + `<span class="suggest-border">${{m.border}}</span>`;
      li.addEventListener('mousedown', (event) => {{
        event.preventDefault();
        pickMachine(m);
      }});
      suggestList.appendChild(li);
    }});
    suggestList.hidden = false;
    machineEl.setAttribute('aria-expanded', 'true');
  }};

  const pickMachine = (m) => {{
    if (!m) return;
    if (machineEl) machineEl.value = m.name;
    borderEl.value = String(m.border);
    if (pickedEl) {{
      pickedEl.hidden = false;
      pickedEl.textContent = `${{m.name}} → 等価ボーダー ${{m.border}}`;
    }}
    hideSuggest();
    render();
    rateEl.focus();
  }};

  const moveActive = (delta) => {{
    if (!matches.length || !suggestList) return;
    activeIndex = (activeIndex + delta + matches.length) % matches.length;
    [...suggestList.children].forEach((li, index) => {{
      if (index === activeIndex) li.setAttribute('aria-selected', 'true');
      else li.removeAttribute('aria-selected');
    }});
    const active = suggestList.children[activeIndex];
    if (active) active.scrollIntoView({{ block: 'nearest' }});
  }};

  const render = () => {{
    const borderEq = num(borderEl);
    const rate = num(rateEl);
    const spins = num(spinsEl);
    body.innerHTML = '';
    if (eqBorder) eqBorder.textContent = borderEq != null ? String(borderEq) : '—';
    if (ball28) ball28.textContent = '—';
    if (yen28) yen28.textContent = '—';
    if (ball28) ball28.parentElement.classList.remove('good', 'bad');
    if (yen28) yen28.parentElement.classList.remove('good', 'bad');

    if (borderEq == null || borderEq <= 0 || spins == null || spins <= 0) {{
      body.innerHTML = '<tr><td colspan="6">機種を選ぶか等価ボーダーを入れると表が出ます。</td></tr>';
      return;
    }}
    if (caption) {{
      const hours = spins / 200;
      caption.textContent = `通常時 ${{spins}} 回転（約${{hours}}時間）の期待収支一覧（単位: 玉 / 下段は円）`;
    }}

    if (rate != null && rate > 0) {{
      const b28 = borderAt(borderEq, yenOf(28));
      const n28 = netBalls(spins, rate, b28);
      const y28 = n28 * yenOf(28);
      if (ball28) {{
        ball28.textContent = fmtBalls(n28);
        ball28.parentElement.classList.toggle('good', n28 > 0);
        ball28.parentElement.classList.toggle('bad', n28 < 0);
      }}
      if (yen28) {{
        yen28.textContent = fmtYen(y28);
        yen28.parentElement.classList.toggle('good', y28 > 0);
        yen28.parentElement.classList.toggle('bad', y28 < 0);
      }}
    }}

    const highlight = rate != null && rate > 0 ? rate : null;
    const rows = [...RATES];
    if (highlight != null && !rows.some((r) => Math.abs(r - highlight) < 0.05)) {{
      rows.push(highlight);
      rows.sort((a, b) => a - b);
    }}

    for (const r of rows) {{
      const tr = document.createElement('tr');
      const isHit = highlight != null && Math.abs(r - highlight) < 0.05;
      if (isHit) tr.classList.add('is-today');
      const th = document.createElement('th');
      th.scope = 'row';
      th.textContent = Number.isInteger(r) ? String(r) : r.toFixed(1);
      if (isHit) th.textContent += ' ←実測';
      tr.appendChild(th);
      for (const ex of EXCHANGES) {{
        const yen = yenOf(ex.balls);
        const border = borderAt(borderEq, yen);
        const ballsNet = netBalls(spins, r, border);
        const yenNet = ballsNet * yen;
        const td = document.createElement('td');
        td.className = `num ${{cellClass(ballsNet)}}`;
        td.innerHTML = `<span class="profit-balls">${{fmtBalls(ballsNet)}}</span>`
          + `<span class="profit-yen">${{fmtYen(yenNet)}}</span>`;
        td.title = `ボーダー ${{border.toFixed(2)}}`;
        tr.appendChild(td);
      }}
      body.appendChild(tr);
    }}
  }};

  if (machineEl && suggestList) {{
    machineEl.addEventListener('input', () => {{
      if (pickedEl) {{
        pickedEl.hidden = true;
        pickedEl.textContent = '';
      }}
      showSuggest(filterMachines(machineEl.value));
    }});
    machineEl.addEventListener('focus', () => {{
      showSuggest(filterMachines(machineEl.value));
    }});
    machineEl.addEventListener('keydown', (event) => {{
      if (suggestList.hidden && (event.key === 'ArrowDown' || event.key === 'Enter')) {{
        showSuggest(filterMachines(machineEl.value));
      }}
      if (suggestList.hidden) return;
      if (event.key === 'ArrowDown') {{
        event.preventDefault();
        moveActive(1);
      }} else if (event.key === 'ArrowUp') {{
        event.preventDefault();
        moveActive(-1);
      }} else if (event.key === 'Enter') {{
        event.preventDefault();
        if (activeIndex >= 0) pickMachine(matches[activeIndex]);
      }} else if (event.key === 'Escape') {{
        hideSuggest();
      }}
    }});
    document.addEventListener('click', (event) => {{
      if (suggestRoot && !suggestRoot.contains(event.target)) hideSuggest();
    }});
  }}

  [borderEl, rateEl, spinsEl].forEach((el) => {{
    el.addEventListener('input', render);
    el.addEventListener('change', render);
  }});
  borderEl.addEventListener('input', () => {{
    if (pickedEl && !pickedEl.hidden) {{
      pickedEl.textContent = (pickedEl.textContent.split('→')[0] || '').trim()
        + (borderEl.value ? ` → 等価ボーダー ${{borderEl.value}}（手入力）` : '');
    }}
  }});
  document.querySelectorAll('#profit-calc [data-set-spins]').forEach((btn) => {{
    btn.addEventListener('click', () => {{
      spinsEl.value = btn.dataset.setSpins;
      spinsEl.focus();
      render();
    }});
  }});

  const calcInputs = ['calc-initial', 'calc-balls', 'calc-current']
    .map((id) => document.getElementById(id))
    .filter(Boolean);
  calcInputs.forEach((el) => el.addEventListener('input', () => {{
    const calcRate = document.getElementById('calc-rate');
    if (!calcRate) return;
    const text = calcRate.textContent.trim();
    const n = Number(text);
    if (Number.isFinite(n) && text !== '—') {{
      rateEl.value = String(n);
      render();
    }}
  }}));
  render();
}})();
</script>
"""


def build_tools_page(machines: list[dict[str, object]] | None = None) -> Path:
    """tools/ 直下を index にし、/tools/ が 404 にならないようにする。"""
    machines = machines if machines is not None else load_machine_borders()
    dest = OUT / "tools" / "index.html"
    page = shell(
        dest,
        "計算ツール",
        crumb(dest, [("目次", OUT / "index.html", ""), ("計算ツール", None)]),
        f"""
<h1>計算ツール</h1>
<p class="intro">回転率の実測と、4パチ交換率ごとの期待収支を出します。使った玉数は +125 で足せます。等価ボーダーは機種名で検索できます。</p>
{rotation_calc_markup(compact=False)}
{exchange_profit_markup(machines, compact=False)}
""",
        wide=True,
    )
    write(dest, page)

    # 旧URL（tools/回転率.html）からの誘導
    legacy = OUT / "tools" / "回転率.html"
    write(
        legacy,
        """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=./">
<link rel="canonical" href="./">
<title>計算ツール</title>
</head>
<body>
<p><a href="./">計算ツールへ</a></p>
</body>
</html>
""",
    )
    return dest


def shell(from_file: Path, title: str, crumb: str, body: str, wide: bool = False) -> str:
    items = [
        ("計算", OUT / "tools" / "index.html", ""),
        ("目次", OUT / "index.html", ""),
        ("日付", OUT / "index.html", "#dates"),
        ("攻略", OUT / "index.html", "#guide"),
        ("スペック", OUT / "index.html", "#spec"),
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
  <a class="brand" href="{href(from_file, OUT / 'index.html')}">控え</a>
  <nav>{nav}</nav>
</header>
<main>
  <p class="crumb">{crumb}</p>
  {body}
</main>
{table_sort_script()}
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
    key = site_name(stem)
    guide = guides.get(key)
    spec = specs.get(key)
    if guide and guide != from_file:
        links.append(f'<a href="{href(from_file, guide)}">攻略</a>')
    if spec and spec != from_file:
        links.append(f'<a href="{href(from_file, spec)}">スペック</a>')
    machine = key if key in units_by_machine else None
    if machine:
        for number, page in units_by_machine[machine]:
            links.append(f'<a href="{href(from_file, page)}">{escape(number)}</a>')
    if not links:
        return ""
    return f'<div class="related">{"".join(links)}</div>'


def build_markdown(
    source: Path,
    dest: Path,
    crumb_parts: list[tuple],
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
    page = shell(dest, title, crumb(dest, crumb_parts), body, wide=wide)
    write(dest, page)


def build_csv_page(
    source: Path,
    dest: Path,
    store: str,
    machine: str,
    number: str,
    unit_page: Path,
    guide: Path | None,
    spec: Path | None,
    store_page: Path | None = None,
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
    trail = [
        ("目次", OUT / "index.html", ""),
        (store, store_page, ""),
        (machine, guide or spec or unit_page, ""),
        (number, unit_page, ""),
        (source.stem, None),
    ]
    page = shell(dest, f"{title} / {machine}", crumb(dest, trail), body, wide=True)
    write(dest, page)


def build_unit_page(
    store: str,
    machine: str,
    number: str,
    folder: Path,
    dest: Path,
    siblings: list[tuple[str, Path]],
    guide: Path | None,
    spec: Path | None,
    csv_pages: list[tuple[str, Path]],
    store_page: Path | None = None,
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
    trail = [
        ("目次", OUT / "index.html", ""),
        (store, store_page, ""),
        (machine, guide or spec or (store_page or OUT / "index.html"), ""),
        (number, None),
    ]
    page = shell(dest, f"{number} {machine}", crumb(dest, trail), body, wide=True)
    write(dest, page)


def machine_sections_html(
    dest: Path,
    machines: list[tuple[str, Path | None, Path | None, list[tuple[str, Path, dict[str, str]]]]],
) -> str:
    blocks = []
    for index, (name, guide, spec, units) in enumerate(machines):
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
        blocks.append(
            f'<section class="machine" id="m{index}" data-find="{escape(aliases_for(name))}">'
            f"<h3>{escape(name)} <span class=\"sublinks\">{''.join(links)}</span></h3>"
            f'<div class="units">{"".join(chips)}</div></section>'
        )
    return "".join(blocks)


def search_script(section_pairs: list[tuple[str, str]]) -> str:
    pairs = ",\n    ".join(f"['{label}', '{box}']" for label, box in section_pairs)
    return f"""
<script>
const q = document.getElementById('q');
const empty = document.getElementById('empty');
if (q) q.addEventListener('input', () => {{
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
    {pairs}
  ].forEach(([labelId, boxId]) => {{
    const label = document.getElementById(labelId);
    const box = document.getElementById(boxId);
    if (!label || !box) return;
    const any = [...box.children].some((el) => !el.hidden);
    label.hidden = !!query && !any;
  }});
  if (empty) empty.hidden = shown !== 0;
}});
</script>
"""


def build_store_page(
    day: str,
    store: str,
    detail_pages: list[tuple[str, str, Path, str]],
    machines: list[tuple[str, Path | None, Path | None, list[tuple[str, Path, dict[str, str]]]]],
) -> Path:
    dest = OUT / day / store / "index.html"
    day_page = OUT / day / "index.html"

    def card(kicker: str, title: str, summary: str, page: Path, find: str) -> str:
        return (
            f'<a class="card" data-find="{escape(find)}" href="{href(dest, page)}">'
            f'<span class="kicker">{escape(kicker)}</span><h3>{escape(title)}</h3>'
            f"<p>{escape(summary)}</p></a>"
        )

    detail_html = "".join(
        card(when, label, summary, page, f"{label} {summary}")
        for label, summary, page, when in detail_pages
    )
    times = [when for *_, when in detail_pages if when != date_label(day)]
    intro_when = times[0] if times else date_label(day)
    machine_html = machine_sections_html(dest, machines)
    body = f"""
<h1>{escape(store)}</h1>
<p class="intro">分析日時 {escape(intro_when)} の判断と、この店舗の台データです。</p>
<input class="search" id="q" type="search" placeholder="台番号、機種名（なのは、鬼がかり、1088）" autocomplete="off">
<p id="empty" class="empty" hidden>一致するページがありません。</p>
<p class="section-label" id="details">判断</p>
<div class="doc-grid" id="detail-cards">{detail_html}</div>
<p class="section-label" id="machines">台データ</p>
<div id="machine-list">{machine_html}</div>
<p class="foot">表示を作り直すときは <code>python3 tools/build_html.py</code></p>
{search_script([("details", "detail-cards"), ("machines", "machine-list")])}
"""
    page = shell(
        dest,
        f"{store} / {date_label(day)}",
        crumb(
            dest,
            [
                ("目次", OUT / "index.html", ""),
                (date_label(day), day_page, ""),
                (store, None),
            ],
        ),
        body,
        wide=True,
    )
    write(dest, page)
    return dest


def build_date_page(day: str, store_cards: list[tuple[str, str, Path, str]]) -> Path:
    dest = OUT / day / "index.html"

    cards = []
    for store, summary, page, when in store_cards:
        cards.append(
            f'<a class="card" data-find="{escape(store)}" href="{href(dest, page)}">'
            f'<span class="kicker">{escape(when)}</span><h3>{escape(store)}</h3>'
            f"<p>{escape(summary)}</p></a>"
        )
    body = f"""
<h1>{escape(date_label(day))}</h1>
<p class="intro">この日に分析した店舗です。店舗を選ぶと判断と台データへ進みます。</p>
<div class="doc-grid">{''.join(cards)}</div>
<p class="foot">表示を作り直すときは <code>python3 tools/build_html.py</code></p>
"""
    page = shell(
        dest,
        date_label(day),
        crumb(dest, [("目次", OUT / "index.html", ""), (date_label(day), None)]),
        body,
        wide=True,
    )
    write(dest, page)
    return dest


def date_cards_sort_script() -> str:
    return """
<script>
(() => {
  const box = document.getElementById('date-cards');
  const bar = document.getElementById('date-sort');
  if (!box || !bar) return;
  const cards = [...box.querySelectorAll('.card')];
  cards.forEach((card, index) => { card.dataset.order = String(index); });
  const keyOf = (card, mode) => {
    if (mode === 'region') return card.dataset.region || 'その他';
    if (mode === 'station') return card.dataset.station || '未設定';
    return '';
  };
  const apply = (mode) => {
    bar.querySelectorAll('button').forEach((btn) => {
      const on = btn.dataset.sort === mode;
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    const sorted = [...cards].sort((a, b) => {
      if (mode === 'region' || mode === 'station') {
        const cmp = keyOf(a, mode).localeCompare(keyOf(b, mode), 'ja');
        if (cmp !== 0) return cmp;
      }
      return Number(a.dataset.order) - Number(b.dataset.order);
    });
    sorted.forEach((card) => box.appendChild(card));
  };
  bar.addEventListener('click', (event) => {
    const btn = event.target.closest('button[data-sort]');
    if (!btn) return;
    apply(btn.dataset.sort);
  });
})();
</script>
"""


def build_index(
    store_cards: list[tuple[str, str, str, Path, str]],
    guide_cards: list[tuple[str, str, Path, Path | None, list[tuple[str, Path]]]],
    spec_cards: list[
        tuple[str, str, Path, Path | None, list[tuple[str, Path]], list[str]]
    ],
    explain_cards: list[tuple[str, str, Path]] | None = None,
    store_regions: dict[str, str] | None = None,
    store_stations: dict[str, str] | None = None,
) -> None:
    """store_cards: (day, store, summary, store_page, when)
    explain_cards: (title, summary, page)
    """
    dest = OUT / "index.html"
    regions = store_regions or {}
    stations = store_stations or {}
    explain_cards = explain_cards or []

    explain_html = []
    for title, summary, page in explain_cards:
        explain_html.append(
            f'<a class="card" data-find="{escape(title)} {escape(summary)}" href="{href(dest, page)}">'
            f'<span class="kicker">解説</span><h3>{escape(title)}</h3>'
            f"<p>{escape(summary)}</p></a>"
        )

    date_html = []
    for day, store, summary, page, when in store_cards:
        region = regions.get(store) or guess_region(store)
        station = stations.get(store) or guess_station(store)
        date_html.append(
            f'<a class="card" data-find="{escape(day)} {escape(store)} {escape(region)} {escape(station)} {escape(summary)}" '
            f'data-region="{escape(region)}" data-station="{escape(station)}" href="{href(dest, page)}">'
            f'<span class="kicker">{escape(when)} · {escape(region)} · {escape(station)}</span>'
            f"<h3>{escape(store)}</h3>"
            f"<p>{escape(summary)}</p></a>"
        )

    guide_html = []
    for title, summary, page, spec, units in guide_cards:
        extra_bits = []
        if spec:
            extra_bits.append(f'<a href="{href(dest, spec)}">スペック</a>')
        if units:
            extra_bits.append(f"<span>台 {len(units)}</span>")
        extra = f'<div class="links">{"".join(extra_bits)}</div>' if extra_bits else ""
        find = aliases_for(title) + " " + " ".join(num for num, _ in units)
        guide_html.append(
            f'<div class="card" data-find="{escape(find)}">'
            f'<a href="{href(dest, page)}"><span class="kicker">攻略</span><h3>{escape(title)}</h3>'
            f"<p>{escape(summary)}</p></a>{extra}</div>"
        )

    spec_html = []
    for title, summary, page, guide, units, tags in spec_cards:
        extra = ""
        if guide:
            extra = f'<div class="links"><a href="{href(dest, guide)}">攻略</a></div>'
        find = " ".join(
            [aliases_for(title), *tags, *(num for num, _ in units)]
        )
        tags_html = (
            '<div class="tags">'
            + "".join(
                f'<span class="{tag_class(tag)}">{escape(tag)}</span>' for tag in tags
            )
            + "</div>"
            if tags
            else ""
        )
        spec_html.append(
            f'<div class="card" data-find="{escape(find)}">'
            f'<a href="{href(dest, page)}"><span class="kicker">スペック</span><h3>{escape(title)}</h3>'
            f"<p>{escape(summary)}</p>{tags_html}</a>{extra}</div>"
        )

    explain_block = ""
    search_pairs = [("dates", "date-cards"), ("guide", "guide-cards"), ("spec", "spec-cards")]
    if explain_html:
        explain_block = (
            '<p class="section-label" id="explain">解説</p>'
            f'<div class="doc-grid" id="explain-cards">{"".join(explain_html)}</div>'
        )
        search_pairs = [("explain", "explain-cards"), *search_pairs]

    tool_page = OUT / "tools" / "index.html"
    machines = load_machine_borders()
    tools_block = (
        '<p class="section-label" id="tools">ツール</p>'
        f'{rotation_calc_markup(compact=True)}'
        f'{exchange_profit_markup(machines, compact=True)}'
        f'<p class="calc-more"><a href="{href(dest, tool_page)}">計算ツールを開く</a></p>'
    )

    body = f"""
<h1>控え</h1>
<p class="intro">日付から店舗、詳細へと進みます。攻略とスペックは店舗共通です。</p>
{tools_block}
<input class="search" id="q" type="search" placeholder="日付、店舗、地域、駅、機種名（町田駅、中山、なのは）" autocomplete="off">
<p id="empty" class="empty" hidden>一致するページがありません。</p>
{explain_block}
<div class="section-head" id="dates">
  <p class="section-label">分析日</p>
  <div class="sort-bar" id="date-sort" role="group" aria-label="分析日の並び">
    <button type="button" data-sort="newest" aria-pressed="true">新しい順</button>
    <button type="button" data-sort="region" aria-pressed="false">地域順</button>
    <button type="button" data-sort="station" aria-pressed="false">最寄り駅順</button>
  </div>
</div>
<div class="doc-grid" id="date-cards">{''.join(date_html)}</div>
<p class="section-label" id="guide">攻略情報</p>
<div class="cards" id="guide-cards">{''.join(guide_html)}</div>
<p class="section-label" id="spec">機種スペック</p>
<div class="cards" id="spec-cards">{''.join(spec_html)}</div>
<p class="foot">表示を作り直すときは <code>python3 tools/build_html.py</code></p>
{search_script(search_pairs)}
{date_cards_sort_script()}
"""
    page = shell(dest, "控え", "目次", body, wide=True)
    write(dest, page)


def main() -> None:
    for path in OUT.rglob("*.html"):
        path.unlink()

    guide_sources = sorted((ROOT / "攻略情報").glob("*.md"))
    explain_dir = ROOT / "解説"
    explain_sources = sorted(explain_dir.glob("*.md")) if explain_dir.is_dir() else []
    _spec_first = ("パチンコ用語一覧", "オカルトパチンコ動作一覧")
    spec_sources = sorted(
        (ROOT / "機種スペック").glob("*.md"),
        key=lambda path: (
            _spec_first.index(path.stem) if path.stem in _spec_first else len(_spec_first),
            path.stem,
        ),
    )
    day_stores = discover_day_stores()
    store_names = load_store_names()
    for _, store, _ in day_stores:
        if store not in store_names:
            store_names.append(store)

    guide_out = {
        site_name(path.stem): OUT / "攻略情報" / f"{site_name(path.stem)}.html" for path in guide_sources
    }
    explain_out = {
        site_name(path.stem): OUT / "解説" / f"{site_name(path.stem)}.html" for path in explain_sources
    }
    spec_out = {
        site_name(path.stem): OUT / "機種スペック" / f"{site_name(path.stem)}.html" for path in spec_sources
    }

    # 台データ HTML は店舗直下に置き、日付をまたいで共有する。
    # パンくずは直近の分析日の店舗ページへ戻す。
    latest_store_page: dict[str, Path] = {}
    for day, store, _ in day_stores:
        latest_store_page.setdefault(store, OUT / day / store / "index.html")

    store_machine_index: dict[str, list[tuple[str, Path | None, Path | None, list[tuple[str, Path, dict[str, str]]]]]] = {}
    units_by_store_machine: dict[str, dict[str, list[tuple[str, Path]]]] = {}
    unit_map_base: dict[str, Path] = {}

    for store in store_names:
        machines = list_machines(store)
        units_by_machine: dict[str, list[tuple[str, Path]]] = {}
        index_machines = []
        store_page = latest_store_page.get(store)
        for name, units in machines:
            key = site_name(name)
            guide = guide_out.get(key)
            spec = spec_out.get(key)
            sibling_pages = [
                (number, OUT / store / site_name(name) / number / "index.html") for number, _ in units
            ]
            units_by_machine[key] = sibling_pages
            index_units = []
            for number, folder in units:
                unit_page = OUT / store / key / number / "index.html"
                csv_pages = []
                for csv_path in sorted(folder.glob("*.csv")):
                    csv_dest = unit_page.parent / f"{csv_path.stem}.html"
                    build_csv_page(
                        csv_path,
                        csv_dest,
                        store,
                        name,
                        number,
                        unit_page,
                        guide,
                        spec,
                        store_page,
                    )
                    csv_pages.append((csv_path.stem, csv_dest))
                build_unit_page(
                    store,
                    name,
                    number,
                    folder,
                    unit_page,
                    sibling_pages,
                    guide,
                    spec,
                    csv_pages,
                    store_page,
                )
                latest = {}
                summary = folder / "大当り一覧.csv"
                if summary.exists():
                    _, rows = read_csv(summary)
                    if rows:
                        latest = rows[-1]
                index_units.append((number, unit_page, latest))
                unit_map_base[number] = unit_page
            index_machines.append((name, guide, spec, index_units))
        store_machine_index[store] = index_machines
        units_by_store_machine[store] = units_by_machine

    # 攻略・スペックは全店舗の台番号をリンク対象にする
    all_units_by_machine: dict[str, list[tuple[str, Path]]] = {}
    for units_by_machine in units_by_store_machine.values():
        for key, units in units_by_machine.items():
            all_units_by_machine.setdefault(key, []).extend(units)

    def unit_map_for(dest: Path) -> dict[str, str]:
        return {number: href(dest, page) for number, page in unit_map_base.items()}

    for source in guide_sources:
        dest = guide_out[site_name(source.stem)]
        build_markdown(
            source,
            dest,
            [("目次", OUT / "index.html", ""), ("攻略情報", OUT / "index.html", "#guide")],
            unit_map_for(dest),
            guide_out,
            spec_out,
            all_units_by_machine,
        )
    for source in explain_sources:
        dest = explain_out[site_name(source.stem)]
        build_markdown(
            source,
            dest,
            [("目次", OUT / "index.html", ""), ("解説", OUT / "index.html", "#explain")],
            unit_map_for(dest),
            guide_out,
            spec_out,
            all_units_by_machine,
        )
    for source in spec_sources:
        dest = spec_out[site_name(source.stem)]
        build_markdown(
            source,
            dest,
            [("目次", OUT / "index.html", ""), ("機種スペック", OUT / "index.html", "#spec")],
            unit_map_for(dest),
            guide_out,
            spec_out,
            all_units_by_machine,
        )

    stores_by_day: dict[str, list[tuple[str, str, Path]]] = {}
    for day, store, folder in day_stores:
        stores_by_day.setdefault(day, []).append((day, store, folder))

    index_store_cards: list[tuple[str, str, str, Path, str]] = []
    for day, entries in stores_by_day.items():
        day_store_cards: list[tuple[str, str, Path, str]] = []
        for _, store, folder in entries:
            detail_sources = [folder / name for name in DETAIL_ORDER if (folder / name).exists()]
            for path in sorted(folder.glob("*.md")):
                if path not in detail_sources:
                    detail_sources.append(path)

            units_by_machine = units_by_store_machine.get(store, {})
            detail_pages: list[tuple[str, str, Path, str]] = []
            for source in detail_sources:
                dest = OUT / day / store / f"{source.stem}.html"
                build_markdown(
                    source,
                    dest,
                    [
                        ("目次", OUT / "index.html", ""),
                        (date_label(day), OUT / day / "index.html", ""),
                        (store, OUT / day / store / "index.html", ""),
                    ],
                    unit_map_for(dest),
                    guide_out,
                    spec_out,
                    units_by_machine,
                )
                text = source.read_text(encoding="utf-8")
                when = analysis_time_label(text, day)
                detail_pages.append((source.stem, blurb(text), dest, when))

            store_page = build_store_page(
                day, store, detail_pages, store_machine_index.get(store, [])
            )
            summary = " · ".join(label for label, *_ in detail_pages) or "詳細なし"
            store_when = next(
                (when for *_, when in detail_pages if when != date_label(day)),
                date_label(day),
            )
            day_store_cards.append((store, summary, store_page, store_when))
            index_store_cards.append((day, store, summary, store_page, store_when))

        build_date_page(day, day_store_cards)

    # トップは新しい分析日時順で店舗カードを出す（日付ページと同じ見た目）
    def _when_sort_key(item: tuple[str, str, str, Path, str]) -> str:
        day, _store, _summary, _page, when = item
        m = re.search(r"(\d{1,2}):(\d{2})", when)
        hhmm = f"{int(m.group(1)):02d}{int(m.group(2)):02d}" if m else "0000"
        return f"{day}-{hhmm}"

    index_store_cards.sort(key=_when_sort_key, reverse=True)

    explain_cards = []
    for source in explain_sources:
        text = source.read_text(encoding="utf-8")
        key = site_name(source.stem)
        explain_cards.append((title_of(text, source.stem), blurb(text), explain_out[key]))

    guide_cards = []
    for source in guide_sources:
        text = source.read_text(encoding="utf-8")
        key = site_name(source.stem)
        units = all_units_by_machine.get(key, [])
        guide_cards.append(
            (title_of(text, source.stem), blurb(text), guide_out[key], spec_out.get(key), units)
        )

    spec_cards = []
    for source in spec_sources:
        text = source.read_text(encoding="utf-8")
        key = site_name(source.stem)
        units = all_units_by_machine.get(key, [])
        tags = [] if key in _spec_first else spec_tags(text)
        spec_cards.append(
            (
                title_of(text, source.stem),
                blurb(text),
                spec_out[key],
                guide_out.get(key),
                units,
                tags,
            )
        )

    machines = load_machine_borders()
    build_tools_page(machines)
    build_index(
        index_store_cards,
        guide_cards,
        spec_cards,
        explain_cards,
        load_store_regions(),
        load_store_stations(),
    )
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    for path in sorted(OUT.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    html_count = sum(1 for _ in OUT.rglob("*.html"))
    print(f"wrote {html_count} html files under {OUT}")


if __name__ == "__main__":
    main()

