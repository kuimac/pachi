#!/usr/bin/env python3
"""攻略情報の「盤面の場所」を機種ごとに詳しくし、専用SVGを付ける。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE_DIR = ROOT / "攻略情報"
BOARD_DIR = GUIDE_DIR / "images" / "boards"


@dataclass
class BoardProfile:
    family: str
    family_label: str
    lead: str
    rows: list[tuple[str, str, str]]
    notes: list[str]
    diagram: str  # standard|umi|eva|kyoraku|drum|hane|deka


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def read_field(text: str, label: str) -> str:
    match = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*([^|]+)\|", text)
    return match.group(1).strip() if match else ""


def classify(stem: str, text: str) -> BoardProfile:
    blob = nfkc(f"{stem}\n{text[:1200]}")
    maker = read_field(text, "メーカー") or ""
    typ = read_field(text, "タイプ") or ""
    rush = ""
    for key in ("RUSH", "ラッシュ", "遊タイム", "時短", "ST", "LT", "チャンスタイム", "インパクト"):
        if key in blob:
            rush = key
            break

    # --- 羽根モノ ---
    if any(k in blob for k in ("羽根モノ", "ハネモノ", "役物機", "スタートチャッカー")) or "ハネ" in stem:
        return BoardProfile(
            family="hane",
            family_label="羽根モノ",
            lead="常時左打ち。羽根開放と役物内のV入賞が本体。右打ち指示はない。",
            rows=[
                ("スタートチャッカー", "盤面下部（左右／中央）", "入賞で羽根が開く。中央入賞は開放回数が増える機種あり"),
                ("羽根", "役物の上部〜入り口", "開放中に玉を役物内へ送る"),
                ("Vゾーン", "役物内（回転体・穴・ホームランVなど）", "入賞で大当り。抜けやすい台は即やめ材料"),
                ("アタッカー", "盤面下部中央寄り", "ラウンド消化。開放を見て打ち出しを合わせる"),
                ("液晶", "盤面中央", "ラウンド表示・止め打ち目安。打ち分け指示は出ない"),
            ],
            notes=[
                "右打ちランプは使わない。常に左打ち。",
                "拾いと役物抜けの台差が大きい。1000円の鳴きとV到達を見て切る。",
            ],
            diagram="hane",
        )

    # --- 海物語系 ---
    if any(k in blob for k in ("海物語", "沖縄", "新海物語", "アグネス", "ブラックLT", "魚群")):
        return BoardProfile(
            family="umi",
            family_label="海物語系",
            lead="海物語系。魚群・ボタン演出より、液晶の「右打ち」表示と電チュー開放を優先して見る。",
            rows=[
                ("液晶（右打ち表示）", "盤面中央の液晶", "「右打ち」が出ているあいだが電サポ中。切替の最終判断"),
                ("ヘソ（始動口）", "盤面中央下寄り", "通常時の始動。左打ちの玉が落ちる位置"),
                ("電チュー", "盤面右側・海／魚群ゾーン下寄り", "右打ち時の始動口。羽根の開閉を目視"),
                ("右打ちランプ", "盤面右下〜電チュー周辺", "点灯＋液晶表示をセットで確認。ランプ単独では決めない"),
                ("アタッカー", "盤面下部中央寄り", "大当りラウンドの入賞口"),
                ("電サポ", "（状態）時短・ST・RUSH中", "部品ではない。液晶の右打ち表示中"),
                ("保留ランプ", "液晶下または盤面下部", "保留消化の目安。右打ち中も残保留に注意"),
            ],
            notes=[
                "魚群やボタン演出に目が行っても、打ち分けは液晶優先。",
                "海系は右打ち中の取りこぼしが回転率を崩しやすい。電チューの拾いを見る。",
            ],
            diagram="umi",
        )

    # --- エヴァ／超咆哮 ---
    if any(k in blob for k in ("エヴァンゲリオン", "エヴァ", "超咆哮", "インパクトモード", "未来への咆哮", "はじまりの記憶", "319 RED")):
        return BoardProfile(
            family="eva",
            family_label="エヴァ／超咆哮系",
            lead="エヴァ系（超咆哮筐体含む）。役物が大きくても、右打ち切替の本命は液晶表示。",
            rows=[
                ("液晶（右打ち表示）", "盤面中央の液晶", "チャンスタイム／インパクト／RUSH中の「右打ち」"),
                ("ヘソ（始動口）", "盤面中央下寄り", "通常時の始動"),
                ("電チュー", "盤面右下寄り", "右打ち中の始動口。役物の陰になりやすいので位置を先に把握"),
                ("右打ちランプ", "盤面下部〜電チュー付近", "点灯中は右打ち。液晶と矛盾したら液晶優先"),
                ("役物／ギミック", "液晶上〜中央", "演出用。打ち分けの判断材料にはしない"),
                ("アタッカー", "盤面下部中央寄り", "ラウンド消化"),
                ("電サポ", "（状態）チャンスタイム／インパクト／RUSH中", "部品ではない"),
            ],
            notes=[
                "役物動作中も右打ち指示が続いていないか液晶を見る。",
                "筐体が大きいので、隣台からでも電チュー位置を座前に確認する。",
            ],
            diagram="eva",
        )

    # --- ドラム／電音 ---
    if any(k in blob for k in ("電音部", "ドラム", "どらむ", "ドラムde")):
        return BoardProfile(
            family="drum",
            family_label="ドラム系",
            lead="ドラム筐体。リール演出に気を取られやすいが、右打ち切替は液晶と電チュー。",
            rows=[
                ("液晶／リール", "盤面中央（ドラム部）", "演出本体。右打ち表示もここを見る"),
                ("ヘソ（始動口）", "盤面中央下寄り", "通常時の始動"),
                ("電チュー", "盤面右下〜中央右", "遊タイム／RUSH中の始動口"),
                ("右打ちランプ", "電チュー横〜盤面下", "点灯＋液晶表示をセットで"),
                ("アタッカー", "盤面下部中央寄り", "ラウンド消化"),
                ("電サポ", "（状態）RUSH・遊タイム中など", "部品ではない。液晶の右打ち表示中"),
                ("遊タイム残表示", "液晶内（機種による）", "残り回転の確認。盤面ランプと取り違えない"),
            ],
            notes=[
                "ドラムの停止出目だけで打ち分けを変えない。",
                "遊タイム機は残り表示を座前に確認し、線以外で長居しない。",
            ],
            diagram="drum",
        )

    # --- 京楽（ランプ多め） ---
    if "京楽" in maker or "京楽" in blob or any(k in blob for k in ("まどか", "キュゥべえ", "シンフォギア", "かぐや様")):
        return BoardProfile(
            family="kyoraku",
            family_label="京楽系",
            lead="京楽系は盤面ランプが多く、演出ランプと右打ちランプを取り違えやすい。",
            rows=[
                ("液晶（右打ち表示）", "盤面中央の液晶", "切替の最終判断。演出色より表示文字を見る"),
                ("ヘソ（始動口）", "盤面中央下寄り（デカヘソ機は特大）", "通常時の始動"),
                ("電チュー", "盤面右下寄り", "右打ち時の始動口"),
                ("右打ちランプ", "電チュー付近〜盤面下のランプ群", "赤点灯が右打ちのことが多いが、機種差あり。液晶と併用"),
                ("演出ランプ", "盤面左右・上部", "信頼度演出用。右打ち判断に使わない"),
                ("アタッカー", "盤面下部中央寄り", "ラウンド消化"),
                ("電サポ", "（状態）時短・ST・RUSH中", "部品ではない"),
            ],
            notes=[
                "カラフルな点灯だけで右打ちに切り替えない。",
                "デカヘソ機は通常時の拾いが回転率に直結する。",
            ],
            diagram="kyoraku",
        )

    # --- リゼロ／鬼がかり ---
    if any(k in blob for k in ("鬼がかり", "リゼロ", "Re:ゼロ", "Re：ゼロ")):
        return BoardProfile(
            family="rezero",
            family_label="リゼロ／鬼がかり系",
            lead="リゼロ系。右打ち指示が液晶に大きく出る。先バレ／落ちブル演出と打ち分けを混同しない。",
            rows=[
                ("液晶（右打ち表示）", "盤面中央の液晶", "ラッシュ／時短中の「右打ち」。切替の本命"),
                ("ヘソ（始動口）", "盤面中央下寄り", "通常時の始動"),
                ("電チュー", "盤面右下（ボタン下〜右玉道の終点付近）", "ラッシュ・時短中の始動口"),
                ("右打ちランプ", "電チュー横〜盤面下", "点灯中は右打ち。液晶と併用"),
                ("プッシュボタン", "盤面手前中央", "演出用。打ち分けとは無関係"),
                ("アタッカー", "盤面下部中央寄り", "ラウンド消化。6000個級もここで確認"),
                ("電サポ", "（状態）ラッシュ／時短中", "部品ではない"),
            ],
            notes=[
                "先バレや落ちブルに気を取られても、右打ち切替は液晶優先。",
                "RUSH中に出玉が止まってもST再開なら右打ち継続。終了表示まで席を立たない。",
            ],
            diagram="standard",
        )

    # --- 牙狼 ---
    if "牙狼" in blob:
        return BoardProfile(
            family="garo",
            family_label="牙狼系",
            lead="牙狼系。金色演出や役物より、液晶の右打ち表示と電チューを見る。",
            rows=[
                ("液晶（右打ち表示）", "盤面中央の液晶", "RUSH／時短中の右打ち指示"),
                ("ヘソ（始動口）", "盤面中央下寄り", "通常時の始動"),
                ("電チュー", "盤面右下〜中央右", "右打ち時の始動口"),
                ("右打ちランプ", "電チュー付近", "点灯＋液晶をセットで"),
                ("役物", "液晶上部〜中央", "演出用"),
                ("アタッカー", "盤面下部中央寄り", "ラウンド消化"),
                ("電サポ", "（状態）RUSH・時短中", "部品ではない"),
            ],
            notes=[
                "大当り演出中も、終了後に通常へ戻ったかを液晶で確認する。",
            ],
            diagram="standard",
        )

    # --- デフォルト（メーカー味付け） ---
    denchu_place = "盤面右下〜中央右（液晶の右下寄り）"
    lamp_place = "電チュー付近、または盤面下部のランプ群"
    lead = "電サポは部品ではなく状態。目印は液晶の「右打ち」と右打ちランプ。"
    extra_notes = [
        "ヘソは中央下寄り、アタッカーは下部中央寄りが多い。",
        "迷ったら液晶の指示を優先。ランプだけ見て打ち方を決めない。",
    ]
    diagram = "standard"
    family = "standard"
    family_label = "標準ミドル／甘デジ"

    if "Sammy" in maker or "サミー" in maker:
        lead = "サミー系。液晶の右打ち表示を本命に、電チューの開放を目視する。"
        family_label = "サミー系"
    elif "SANKYO" in maker or "サンセイ" in maker:
        lead = "SANKYO／関連。フィーバー系も打ち分けは液晶優先。"
        family_label = "SANKYO系"
        denchu_place = "盤面右下（液晶右下〜右レール終点）"
    elif "ニューギン" in maker:
        lead = "ニューギン系。演出ボタン周辺のランプと右打ちランプを取り違えない。"
        family_label = "ニューギン系"
        diagram = "kyoraku"
    elif "ビスティ" in maker:
        lead = "ビスティ系。液晶表示と電チュー開放をセットで見る。"
        family_label = "ビスティ系"
    elif "藤商事" in maker or "JFJ" in maker:
        lead = "藤商事系。液晶の右打ち表示を最終判断にする。"
        family_label = "藤商事系"
    elif "三洋" in maker:
        lead = "三洋系。海以外も右打ち切替は液晶優先。"
        family_label = "三洋系"

    if "デカヘソ" in blob:
        family_label += "（デカヘソ）"
        diagram = "deka"
        extra_notes.insert(0, "デカヘソは通常時の拾いが命。座ったらまずヘソへの入りを見る。")

    rush_state = "時短・ST・RUSH中"
    if "遊タイム" in blob:
        rush_state = "時短・ST・RUSH・遊タイム中"
        extra_notes.append("遊タイム残は液晶表示で確認。深さだけで座らない。")

    return BoardProfile(
        family=family,
        family_label=family_label,
        lead=lead,
        rows=[
            ("液晶（右打ち表示）", "盤面中央の液晶", "「右打ち」表示中が電サポ中。切替の最終判断"),
            ("ヘソ（始動口）", "盤面中央下寄り" + ("（デカヘソ）" if "デカヘソ" in blob else ""), "通常時の始動口"),
            ("電チュー", denchu_place, "羽根が開く入賞口。右打ちの始動口"),
            ("右打ちランプ", lamp_place, "点灯中は右打ち。位置は機種差あり。液晶と併用"),
            ("アタッカー", "盤面下部中央寄り", "大当りラウンドの入賞口"),
            ("電サポ", f"（状態）{rush_state}", "部品ではない。液晶の右打ち表示中"),
            ("保留ランプ", "液晶下または盤面下部", "保留の目安。右打ち終了直後の残保留に注意"),
        ],
        notes=extra_notes,
        diagram=diagram,
    )


def svg_escape(text: str) -> str:
    return escape(text, quote=True)


def render_svg(title: str, profile: BoardProfile) -> str:
    """機種名入りの盤面ガイドSVG。"""
    kind = profile.diagram
    subtitle = f"{profile.family_label} · 電チュー / 右打ちランプ / 液晶表示"

    # common cabinet
    parts = []
    parts.append(
        f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 580" role="img">
<title>{svg_escape(title)} 盤面ガイド</title>
<desc>{svg_escape(subtitle)}</desc>
<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0 0 L10 5 L0 10 z" fill="#9c2f1a"/>
  </marker>
  <style>
    .bg {{ fill:#f3efe6; }}
    .frame {{ fill:#fffdf8; stroke:#241e1a; stroke-width:3; }}
    .glass {{ fill:#e8f0f5; stroke:#7a8a94; stroke-width:2; }}
    .part {{ fill:#f6efe4; stroke:#241e1a; stroke-width:2; }}
    .hot {{ fill:#ffe8a8; stroke:#9c2f1a; stroke-width:2.5; }}
    .lamp {{ fill:#ff5a3c; stroke:#7a1808; stroke-width:2; }}
    .yaku {{ fill:#dfe9f2; stroke:#3a5566; stroke-width:2; stroke-dasharray:6 4; }}
    .title {{ font:700 16px "Hiragino Sans","Yu Gothic",sans-serif; fill:#1e1a16; }}
    .sub {{ font:12px "Hiragino Sans","Yu Gothic",sans-serif; fill:#6f675e; }}
    .call {{ font:700 13px "Hiragino Sans","Yu Gothic",sans-serif; fill:#9c2f1a; }}
    .note {{ font:12px "Hiragino Sans","Yu Gothic",sans-serif; fill:#2f5d50; }}
    .line {{ stroke:#9c2f1a; stroke-width:1.7; fill:none; marker-end:url(#arrow); }}
    .muted {{ fill:#cfc5b6; stroke:#8a7f70; stroke-width:1.5; }}
  </style>
</defs>
<rect class="bg" width="760" height="580" rx="16"/>
<text class="title" x="24" y="36">{svg_escape(title[:42])}</text>
<text class="sub" x="24" y="56">{svg_escape(subtitle)}</text>
<!-- cabinet -->
<rect class="frame" x="110" y="78" width="360" height="450" rx="24"/>
"""
    )

    if kind == "hane":
        parts.append(
            """
<rect class="glass" x="140" y="110" width="300" height="150" rx="10"/>
<text class="sub" x="290" y="190" text-anchor="middle">液晶（ラウンド表示）</text>
<rect class="yaku" x="170" y="280" width="240" height="110" rx="12"/>
<text class="sub" x="290" y="330" text-anchor="middle">役物</text>
<ellipse class="hot" cx="290" cy="340" rx="28" ry="18"/>
<text class="call" x="290" y="345" text-anchor="middle" font-size="11">V</text>
<rect class="part" x="200" y="420" width="50" height="28" rx="6"/>
<rect class="part" x="270" y="412" width="40" height="36" rx="6"/>
<rect class="part" x="330" y="420" width="50" height="28" rx="6"/>
<text class="sub" x="290" y="470" text-anchor="middle">チャッカー / アタッカー</text>
<path class="line" d="M500 160 L440 160"/>
<text class="call" x="512" y="164">液晶</text>
<path class="line" d="M500 330 L420 330"/>
<text class="call" x="512" y="334">Vゾーン</text>
<path class="line" d="M500 430 L380 430"/>
<text class="call" x="512" y="434">スタートチャッカー</text>
<text class="note" x="500" y="500">常時左打ち · 右打ち指示なし</text>
"""
        )
    elif kind == "umi":
        parts.append(
            """
<rect class="glass" x="140" y="110" width="300" height="170" rx="10"/>
<text class="sub" x="290" y="175" text-anchor="middle">液晶</text>
<rect x="230" y="210" width="120" height="28" rx="6" fill="#9c2f1a"/>
<text x="290" y="229" text-anchor="middle" fill="#fffdf8" font-size="13" font-weight="700">右打ち</text>
<rect class="yaku" x="320" y="300" width="110" height="90" rx="10"/>
<text class="sub" x="375" y="350" text-anchor="middle">海ゾーン</text>
<rect class="hot" x="340" y="400" width="70" height="36" rx="8"/>
<text class="call" x="375" y="423" text-anchor="middle" font-size="11">電チュー</text>
<circle class="lamp" cx="420" cy="430" r="8"/>
<rect class="part" x="230" y="450" width="70" height="28" rx="6"/>
<text class="sub" x="265" y="490" text-anchor="middle">ヘソ</text>
<path class="line" d="M520 224 L360 224"/>
<text class="call" x="532" y="228">液晶の右打ち</text>
<path class="line" d="M520 350 L440 350"/>
<text class="call" x="532" y="354">魚群ゾーン下</text>
<path class="line" d="M520 418 L420 418"/>
<text class="call" x="532" y="422">電チュー</text>
<path class="line" d="M520 448 L430 448"/>
<text class="call" x="532" y="452">右打ちランプ</text>
"""
        )
    elif kind == "eva":
        parts.append(
            """
<rect class="yaku" x="150" y="100" width="280" height="70" rx="10"/>
<text class="sub" x="290" y="140" text-anchor="middle">役物／ギミック</text>
<rect class="glass" x="140" y="180" width="300" height="150" rx="10"/>
<text class="sub" x="290" y="240" text-anchor="middle">液晶</text>
<rect x="230" y="270" width="120" height="28" rx="6" fill="#9c2f1a"/>
<text x="290" y="289" text-anchor="middle" fill="#fffdf8" font-size="13" font-weight="700">右打ち</text>
<rect class="hot" x="340" y="360" width="70" height="40" rx="8"/>
<text class="call" x="375" y="385" text-anchor="middle" font-size="11">電チュー</text>
<circle class="lamp" cx="420" cy="400" r="8"/>
<rect class="part" x="230" y="430" width="70" height="28" rx="6"/>
<path class="line" d="M520 130 L440 130"/>
<text class="call" x="532" y="134">役物（演出）</text>
<path class="line" d="M520 284 L360 284"/>
<text class="call" x="532" y="288">液晶の右打ち</text>
<path class="line" d="M520 380 L420 380"/>
<text class="call" x="532" y="384">電チュー</text>
<text class="note" x="500" y="500">役物より液晶表示を優先</text>
"""
        )
    elif kind == "drum":
        parts.append(
            """
<rect class="glass" x="150" y="110" width="280" height="200" rx="12"/>
<rect class="muted" x="170" y="140" width="70" height="140" rx="6"/>
<rect class="muted" x="255" y="140" width="70" height="140" rx="6"/>
<rect class="muted" x="340" y="140" width="70" height="140" rx="6"/>
<text class="sub" x="290" y="330" text-anchor="middle">ドラム／リール</text>
<rect x="230" y="300" width="120" height="24" rx="6" fill="#9c2f1a"/>
<text x="290" y="317" text-anchor="middle" fill="#fffdf8" font-size="12" font-weight="700">右打ち</text>
<rect class="hot" x="340" y="360" width="70" height="40" rx="8"/>
<circle class="lamp" cx="420" cy="400" r="8"/>
<rect class="part" x="230" y="430" width="70" height="28" rx="6"/>
<path class="line" d="M520 220 L430 220"/>
<text class="call" x="532" y="224">リール演出</text>
<path class="line" d="M520 312 L360 312"/>
<text class="call" x="532" y="316">液晶の右打ち</text>
<path class="line" d="M520 380 L420 380"/>
<text class="call" x="532" y="384">電チュー</text>
"""
        )
    elif kind == "kyoraku":
        parts.append(
            """
<rect class="glass" x="140" y="110" width="300" height="170" rx="10"/>
<text class="sub" x="290" y="180" text-anchor="middle">液晶</text>
<rect x="230" y="220" width="120" height="28" rx="6" fill="#9c2f1a"/>
<text x="290" y="239" text-anchor="middle" fill="#fffdf8" font-size="13" font-weight="700">右打ち</text>
<circle class="muted" cx="160" cy="320" r="10"/>
<circle class="muted" cx="190" cy="300" r="8"/>
<circle class="muted" cx="420" cy="300" r="8"/>
<circle class="muted" cx="440" cy="330" r="10"/>
<text class="sub" x="290" y="340" text-anchor="middle">演出ランプ（多数）</text>
<rect class="hot" x="340" y="370" width="70" height="40" rx="8"/>
<circle class="lamp" cx="420" cy="410" r="9"/>
<rect class="part" x="230" y="440" width="70" height="28" rx="6"/>
<path class="line" d="M520 234 L360 234"/>
<text class="call" x="532" y="238">液晶の右打ち</text>
<path class="line" d="M520 320 L450 320"/>
<text class="call" x="532" y="324">演出ランプ≠右打ち</text>
<path class="line" d="M520 410 L430 410"/>
<text class="call" x="532" y="414">右打ちランプ</text>
"""
        )
    elif kind == "deka":
        parts.append(
            """
<rect class="glass" x="140" y="110" width="300" height="170" rx="10"/>
<text class="sub" x="290" y="180" text-anchor="middle">液晶</text>
<rect x="230" y="220" width="120" height="28" rx="6" fill="#9c2f1a"/>
<text x="290" y="239" text-anchor="middle" fill="#fffdf8" font-size="13" font-weight="700">右打ち</text>
<ellipse class="hot" cx="290" cy="420" rx="55" ry="32"/>
<text class="call" x="290" y="425" text-anchor="middle">デカヘソ</text>
<rect class="hot" x="350" y="350" width="60" height="36" rx="8"/>
<circle class="lamp" cx="420" cy="380" r="8"/>
<path class="line" d="M520 420 L360 420"/>
<text class="call" x="532" y="424">デカヘソ（通常時）</text>
<path class="line" d="M520 368 L420 368"/>
<text class="call" x="532" y="372">電チュー</text>
"""
        )
    else:  # standard
        parts.append(
            """
<rect class="glass" x="140" y="110" width="300" height="180" rx="10"/>
<text class="sub" x="290" y="185" text-anchor="middle">液晶</text>
<rect x="230" y="230" width="120" height="28" rx="6" fill="#9c2f1a"/>
<text x="290" y="249" text-anchor="middle" fill="#fffdf8" font-size="13" font-weight="700">右打ち</text>
<rect class="hot" x="340" y="330" width="70" height="42" rx="8"/>
<text class="call" x="375" y="355" text-anchor="middle" font-size="11">電チュー</text>
<circle class="lamp" cx="420" cy="370" r="9"/>
<rect class="part" x="230" y="400" width="70" height="30" rx="6"/>
<text class="sub" x="265" y="455" text-anchor="middle">ヘソ</text>
<rect class="part" x="250" y="470" width="90" height="28" rx="6"/>
<text class="sub" x="295" y="520" text-anchor="middle">アタッカー</text>
<path class="line" d="M520 244 L360 244"/>
<text class="call" x="532" y="248">液晶の右打ち</text>
<path class="line" d="M520 350 L420 350"/>
<text class="call" x="532" y="354">電チュー</text>
<path class="line" d="M520 372 L435 372"/>
<text class="call" x="532" y="376">右打ちランプ</text>
<path class="line" d="M520 415 L310 415"/>
<text class="call" x="532" y="419">ヘソ</text>
"""
        )

    parts.append("</svg>\n")
    return "".join(parts)


def section_markdown(profile: BoardProfile, image_rel: str, *, guide: bool) -> str:
    rows = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in profile.rows)
    notes = "\n".join(f"- {n}" for n in profile.notes)
    # 盤面図は 攻略情報/images/boards/ 直下
    img = image_rel
    return (
        f"{profile.lead}\n"
        f"\n"
        f"系列: **{profile.family_label}**（機種ごとの目安。個体差あり）\n"
        f"\n"
        f"| 項目 | 場所 | 見方 |\n"
        f"| --- | --- | --- |\n"
        f"{rows}\n"
        f"\n"
        f"![盤面ガイド]({img})\n"
        f"\n"
        f"{notes}\n"
    )


def replace_board_section(text: str, new_body: str) -> str:
    pattern = re.compile(r"(## 盤面の場所\n)(.*?)(?=\n## |\Z)", re.S)
    if not pattern.search(text):
        return text
    return pattern.sub(rf"\1\n{new_body.rstrip()}\n\n", text, count=1)


def safe_stem_filename(stem: str) -> str:
    # ファイル名はそのまま（既存MDと対応）。禁止文字だけ置換
    return re.sub(r'[\\/:*?"<>|]', "_", stem)


def main() -> None:
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    guides = sorted(GUIDE_DIR.glob("*.md"))
    updated_guide = 0
    for path in guides:
        if path.stem in {"パチンコ用語一覧", "オカルトパチンコ動作一覧"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "## 盤面の場所" not in text:
            continue
        profile = classify(path.stem, text)
        fname = safe_stem_filename(path.stem) + ".svg"
        svg_path = BOARD_DIR / fname
        title = path.stem
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if m:
            title = m.group(1).strip()
        svg_path.write_text(render_svg(title, profile), encoding="utf-8")

        guide_body = section_markdown(profile, f"images/boards/{fname}", guide=True)
        new_guide = replace_board_section(text, guide_body)
        if new_guide != text:
            path.write_text(new_guide, encoding="utf-8")
            updated_guide += 1

    print(f"board svgs -> {BOARD_DIR}")
    print(f"updated guides: {updated_guide}")


if __name__ == "__main__":
    main()
