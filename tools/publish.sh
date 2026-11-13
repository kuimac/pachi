#!/usr/bin/env bash
# 分析結果を docs に反映し、main へ push して GitHub Pages を更新する。
# build_html.py が店舗下層の全台一覧・出玉ランキングも最新 CSV で再生成する。
# 攻略の設置店舗は全台CSVから更新してから HTML 化する。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MSG="${1:-}"
if [[ -z "$MSG" ]]; then
  echo "usage: ./tools/publish.sh \"Analyze <店舗> <YYYY-MM-DD> <mode>\"" >&2
  exit 2
fi

PY=python3
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
fi
"$PY" tools/update_guide_installs.py
"$PY" tools/build_html.py

if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
  echo "no changes to publish"
  exit 0
fi

git add -A
# 秘密・個人情報が混ざっていないか最低限確認（公開リポジトリ）
if git diff --cached --name-only | grep -E '(^|/)\.env$|\.pem$|credentials\.json$|(^|/)プレイ履歴\.local\.md$|\.local\.md$|\.ck$' >/dev/null; then
  echo "refusing to commit secret/personal-like files" >&2
  git reset >/dev/null
  exit 1
fi
if git diff --cached -U0 | grep -E '^\+.*(/Users/[^/]+/|@gmail\.com|JSESSIONID)' >/dev/null; then
  echo "refusing to commit personal path / email / session cookie content" >&2
  git reset >/dev/null
  exit 1
fi

git commit -m "$(cat <<EOF
${MSG}

EOF
)"

git push -u origin HEAD

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "pushed ${BRANCH}. Pages: https://kuimac.github.io/pachi/"
