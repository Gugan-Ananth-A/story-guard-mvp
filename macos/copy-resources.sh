#!/bin/bash
# Copy the Python engine and the driver into the app bundle.
# engine/ keeps the repo shape so Path(__file__).parents[2] resolves templates and prompts.
set -euo pipefail

ROOT="$(cd "${SRCROOT}/.." && pwd)"
DEST="${TARGET_BUILD_DIR}/${UNLOCALIZED_RESOURCES_FOLDER_PATH}"

mkdir -p "${DEST}/engine/src" "${DEST}"

rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' \
  "${ROOT}/src/story_guard/" "${DEST}/engine/src/story_guard/"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' \
  "${ROOT}/templates/" "${DEST}/engine/templates/"
rsync -a --delete --exclude '.DS_Store' \
  "${ROOT}/prompts/" "${DEST}/engine/prompts/"
rsync -a --delete --exclude '.DS_Store' \
  "${ROOT}/fixtures/" "${DEST}/engine/fixtures/"
cp "${ROOT}/pyproject.toml" "${DEST}/engine/pyproject.toml"
cp "${SRCROOT}/driver.py" "${DEST}/driver.py"
cp "${SRCROOT}/driver_test.py" "${DEST}/driver_test.py"

STAMP="$(
  DEST_ENGINE="${DEST}/engine" python3 -c '
import hashlib, os
root = os.environ["DEST_ENGINE"]
rows = []
for dirpath, dirnames, filenames in os.walk(root):
    dirnames.sort()
    for name in sorted(filenames):
        if name == ".bundle-stamp" or name == ".DS_Store":
            continue
        path = os.path.join(dirpath, name)
        stat = os.stat(path)
        rel = os.path.relpath(path, root)
        rows.append(f"{rel} {stat.st_size} {stat.st_mtime_ns}")
print(hashlib.sha256("\n".join(rows).encode()).hexdigest())
'
)"
printf '%s\n' "${STAMP}" > "${DEST}/engine/.bundle-stamp"
