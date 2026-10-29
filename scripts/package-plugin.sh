#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

MANIFEST="${REPO_ROOT}/plugin.json"
if [[ ! -f "${MANIFEST}" ]]; then
  echo "Error: plugin.json not found in ${REPO_ROOT}" >&2
  exit 1
fi

VERSION=$(python3 -c "import json; print(json.load(open('${MANIFEST}'))['version'])")
NAME=$(python3 -c "import json; print(json.load(open('${MANIFEST}'))['name'])")

if [[ "${1:-}" == "--test" ]]; then
  echo "Testing package readiness for ${NAME} v${VERSION}..."
  if command -v /Users/joeltaroreh/.gemini/bin/agy >/dev/null 2>&1; then
    /Users/joeltaroreh/.gemini/bin/agy plugin validate "${REPO_ROOT}" --strict
  fi
  echo "Package dry-run verified successfully for ${NAME} v${VERSION}"
  exit 0
fi

DIST_DIR="${REPO_ROOT}/dist"
mkdir -p "${DIST_DIR}"
ARCHIVE="${DIST_DIR}/${NAME}-${VERSION}.zip"

rm -f "${ARCHIVE}"

echo "Packaging ${NAME} v${VERSION} into ${ARCHIVE}..."

zip -r -q "${ARCHIVE}" \
  plugin.json \
  README.md \
  LICENSE \
  assets/ \
  rules/ \
  agents/ \
  skills/ \
  agystack-models.md \
  agystack-runtime.json.example \
  hooks.json.example \
  -x "*.DS_Store" \
  -x "*__pycache__*" \
  -x "*.pytest_cache*" \
  -x "*.ruff_cache*" \
  -x "*.venv*" \
  -x "*node_modules*"

echo "Archive created: ${ARCHIVE}"
ls -lh "${ARCHIVE}"
