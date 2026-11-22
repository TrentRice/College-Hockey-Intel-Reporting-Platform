#!/bin/bash
# Builds the private data repo's first version from this Mac's data/ (docs/cloud.md, step 1).
#
#   deploy/make-data-repo.sh ../CHIRP-data
#
# Copies the scraped pages, processed tables and prediction-log backups, adds the nightly
# workflow from deploy/data-repo/, and makes the first commit. Pushing it is a separate step.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${1:?usage: deploy/make-data-repo.sh <new folder>}"
if [ -e "$DEST" ]; then echo "$DEST already exists; pick a new folder." >&2; exit 1; fi

mkdir -p "$DEST"
cp -R data/raw data/processed data/backups "$DEST"/
cp -R deploy/data-repo/. "$DEST"/
rm -rf "$DEST/processed/validation"
find "$DEST" \( -name .DS_Store -o -name .gitkeep -o -name '*.tmp' \) -delete

cd "$DEST"
git init -q -b main
git add -A
git commit -q -m "Initial data from the Mac"
echo "Created $(pwd): $(git ls-files | wc -l | tr -d ' ') files, $(du -sh .git | cut -f1) in git."
