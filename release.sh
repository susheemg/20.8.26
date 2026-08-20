#!/usr/bin/env bash
# Brata release cutter: verifies, commits, tags v<VERSION>, builds versioned zip.
set -euo pipefail
cd "$(dirname "$0")"
V=$(tr -d ' \n' < VERSION)
echo "Releasing v$V"
grep -q "\[$V\]" CHANGELOG.md || { echo "ERROR: CHANGELOG.md has no [$V] section"; exit 1; }
node --check app/static/app.js
python3 -c "import sys;sys.path.insert(0,'.');from app.bro_app import create_app;create_app('sqlite:///bro_demo.db')" >/dev/null 2>&1 || { echo "ERROR: app failed to boot"; exit 1; }
rm -f bro_unified.db
git add -A && git commit -m "release: v$V" || echo "(nothing new to commit)"
git tag -f "v$V" -m "Brata v$V"
ZIP="Brata_TPRM_v$V.zip"
rm -f "../$ZIP"
zip -rq "../$ZIP" . -x '*/__pycache__/*' -x '*.pyc' -x '.git/*' -x 'bro_unified.db' -x '*.zip'
echo "Built ../$ZIP · tagged v$V · now: git push && git push --tags"
