# 中山UNO × DMM ぱちタウン台データ（併用）

更新: 2026-11-14（PA-89）

## 結論

| レイヤ | Cloud から | Mac 住宅 IP | 台番号 |
| --- | --- | --- | --- |
| DMM jackpot HTML（設置機種・最終更新日） | **取れる**（200） | 取れる | 設置台数のみ（番号なし） |
| DMM 出玉ランキング画像 | **取れる**（CDN JPEG） | 取れる | **あり**（期間 Top の番台） |
| P'sCUBE iframe 台別表 | **取れない**（Cloudflare 403） | **取れる想定**（Site Seven と同様） | **あり**（全台系） |

**Site Seven を置き換えない。** 中山UNO は Site Seven（ランキング＋全台）と DMM/PSCUBE を **併用**する。

## URL

- DMM: https://p-town.dmm.com/shops/kanagawa/4564/jackpot
- 実データ iframe: `https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c753211/`（HTML の `dedama-iframe` から抽出）

## 既存 Site Seven スキーマとの対応

既存 CSV（`中山UNO/全台データ_YYYY-MM-DD.csv`）:

`日付,台番号,機種,累計スタート,大当り回数,初当り回数,最高出玉,レート,mdc,設置台数`

DMM/PSCUBE 側（公式「データ検索」説明・P'sCUBE 掲載項目）:

| フィールド | Site Seven | DMM/PSCUBE |
| --- | --- | --- |
| 台番号 | ○ | ○（iframe / ランキング画像） |
| 機種 | ○ | ○（設置一覧・画像・表） |
| 累計スタート | ○ | ○（PSCUBE） |
| 大当り回数 | ○ | ○ |
| 初当り回数 | ○ | △（店舗公開次第） |
| 最高出玉 | ○ | △（最大放出数＝MY の場合あり） |
| 最終スタート | × | ○（PSCUBE） |
| 最大放出数 | × | ○（PSCUBE） |
| 差玉（日次ランキング） | ○（出玉ランキング CSV） | △（画像は期間集計 Top） |
| mdc / レート | ○ | ×（DMM machine_id は別系） |

## マージ方針（`tools/merge_uno_sources.py`）

1. キーは **同日・台番号**。
2. 数値は **Site Seven 優先**。空欄だけ PSCUBE で埋める。
3. PSCUBE 独自列（最終スタート・最大放出数）は追加列として残す。
4. `sources` 列に `site777` / `pscube` / `site777+pscube` を記録。
5. 出力は `中山UNO/dmm_ptown/全台データ_merged_YYYY-MM-DD.csv`（Site Seven の `全台データ_*.csv` は上書きしない）。
6. 天井／遊タイム機は落とさない（どちらか片方にあれば行を残す）。

## 実行

```bash
# Cloud でも DMM シェル＋画像は試せる（PSCUBE は 403 になりうる）
python3 tools/fetch_dmm_ptown.py --store 中山UNO

# Mac（Site Seven + DMM 併用）
./tools/mac_keepalive_fetch.sh --store 中山UNO --publish

# マージのみ
python3 tools/merge_uno_sources.py --day 2026-11-14
```

スナップショット: `tools/prefetch_snapshots/中山UNO/dmm_ptown_last.json`（成功時） / `dmm_ptown_last_attempt.json`（毎回）。

## Egress メモ

- Site Seven: Cloud / ubuntu GHA は 403 → Mac 必須（`docs/offline-fetch-fallback.md`）。
- PSCUBE: 同系統。Cloud 検証 IP は AWS `3.x` + Cloudflare challenge。
- DMM `p-town.dmm.com` 本体は Cloud から 200。認証不要（公開ページ）。
