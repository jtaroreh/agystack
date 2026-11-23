#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TEST_MODE=false
OUTPUT_DIR=""

usage() {
  cat <<'EOF'
Usage: package-plugin.sh [--test] [--output-dir <dir>]

Options:
  --test               Validate plugin.json, run agy validate if installed, and verify archive invariants
  --output-dir <dir>   Write archive to <dir> instead of <repo>/dist
  -h, --help           Show this help message and exit
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --test)
      TEST_MODE=true
      shift
      ;;
    --output-dir)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "Error: --output-dir requires a directory argument" >&2
        exit 1
      fi
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --output-dir=*)
      OUTPUT_DIR="${1#--output-dir=}"
      if [[ -z "${OUTPUT_DIR}" ]]; then
        echo "Error: --output-dir requires a non-empty directory" >&2
        exit 1
      fi
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -n "${OUTPUT_DIR}" && "${OUTPUT_DIR}" != /* ]]; then
  OUTPUT_DIR="$(pwd)/${OUTPUT_DIR}"
fi

cd "${REPO_ROOT}" || exit 1

MANIFEST="${REPO_ROOT}/plugin.json"
if [[ ! -f "${MANIFEST}" ]]; then
  echo "Error: plugin.json not found in ${REPO_ROOT}" >&2
  exit 1
fi

MANIFEST_INFO=$(python3 -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
if not isinstance(data, dict):
    raise SystemExit("Error: plugin.json root must be a JSON object")
name = data.get("name")
version = data.get("version")
if not isinstance(name, str) or not name.strip():
    raise SystemExit("Error: plugin.json missing non-empty string \"name\"")
if not isinstance(version, str) or not version.strip():
    raise SystemExit("Error: plugin.json missing non-empty string \"version\"")
print(f"{name.strip()}\t{version.strip()}")
' "${MANIFEST}")
IFS=$'\t' read -r NAME VERSION <<< "${MANIFEST_INFO}"

build_archive() {
  local dest_dir="$1"
  mkdir -p "${dest_dir}"
  local archive="${dest_dir}/${NAME}-${VERSION}.zip"
  rm -f "${archive}"
  zip -r -q "${archive}" \
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
    -x "*node_modules*" \
    -x "*.test.ts" \
    -x "*.test-helper.ts" \
    -x "*/scripts/test/*" \
    -x "*/scripts/test/"
  printf '%s\n' "${archive}"
}

verify_archive() {
  local archive="$1"
  unzip -t "${archive}" >/dev/null
  python3 -c '
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as zf:
    names = zf.namelist()
required = [
    "plugin.json",
    "README.md",
    "LICENSE",
    "agystack-models.md",
    "agystack-runtime.json.example",
    "hooks.json.example",
    "skills/statechart/scripts/statechart",
    "skills/statechart/scripts/statechart.ts",
    "skills/statechart/scripts/pipeline.ts",
]
missing = [r for r in required if r not in names]
if missing:
    raise SystemExit(f"Error: archive missing required files: {missing}")
def is_forbidden(name: str) -> bool:
    parts = name.split("/")
    return (
        name.endswith(".test.ts")
        or name.endswith(".test-helper.ts")
        or "__pycache__" in parts
        or "node_modules" in parts
        or any(parts[i : i + 2] == ["scripts", "test"] for i in range(len(parts) - 1))
    )

forbidden = [n for n in names if is_forbidden(n)]
if forbidden:
    raise SystemExit(f"Error: archive contains forbidden entries: {forbidden[:10]}")
' "${archive}"
}

if [[ "${TEST_MODE}" == "true" ]]; then
  echo "Testing package readiness for ${NAME} v${VERSION}..."
  TMP_PKG_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_PKG_DIR}"' EXIT
  TEST_ARCHIVE="$(build_archive "${TMP_PKG_DIR}")"
  verify_archive "${TEST_ARCHIVE}"

  if command -v agy >/dev/null 2>&1; then
    agy plugin validate "${REPO_ROOT}" --strict
    echo "Package dry-run verified successfully for ${NAME} v${VERSION}"
  else
    echo "WARNING: agy CLI not found on PATH; skipping strict CLI validation." >&2
    echo "Package archive dry-run verified for ${NAME} v${VERSION} (strict CLI validation skipped)"
  fi
  exit 0
fi

DIST_DIR="${OUTPUT_DIR:-${REPO_ROOT}/dist}"
echo "Packaging ${NAME} v${VERSION} into ${DIST_DIR}/${NAME}-${VERSION}.zip..."
ARCHIVE="$(build_archive "${DIST_DIR}")"

echo "Archive created: ${ARCHIVE}"
ls -lh "${ARCHIVE}"
