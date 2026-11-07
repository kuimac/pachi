#!/usr/bin/env bash
# 分析結果を docs に反映し、main へ push して GitHub Pages を更新する。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MSG="${1:-}"
if [[ -z "$MSG" ]]; then
  echo "usage: ./tools/publish.sh \"Analyze <店舗> <YYYY-MM-DD> <mode>\"" >&2
  exit 2
fi

python3 tools/build_html.py

if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
  echo "no changes to publish"
  exit 0
fi

git add -A
# 秘密ファイルが混ざっていないか最低限確認
if git diff --cached --name-only | grep -E '(^|/)\.env$|\.pem$|credentials\.json$' >/dev/null; then
  echo "refusing to commit secret-like files" >&2
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
