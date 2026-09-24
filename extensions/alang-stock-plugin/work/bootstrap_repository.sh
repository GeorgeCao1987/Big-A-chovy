#!/usr/bin/env bash
set -euo pipefail

REPO="${ALANG_REPO:-GeorgeCao1987/Big-A-chovy}"
REF="${ALANG_REF:-feature/alang-cloud-plugin-v2}"
DEST="${ALANG_DEST:-Big-A-chovy}"
RUNNER="extensions/alang-stock-plugin/work/runner.py"

receipt() {
  printf '{"alang_bootstrap":true,"event":"%s","repo":"%s","ref":"%s"}\n' "$1" "$REPO" "$REF"
}

if [[ -f "$DEST/$RUNNER" ]]; then
  receipt "reuse_existing"
  printf '%s\n' "$DEST"
  exit 0
fi

rm -rf "$DEST"
receipt "git_http1_start"

# The first path avoids Chromium/browser HTTP/2 entirely and forces Git to
# HTTP/1.1.  This is the preferred Work/cloud bootstrap.
if git -c http.version=HTTP/1.1 -c http.lowSpeedLimit=1 -c http.lowSpeedTime=60 \
  clone --depth 1 --single-branch --branch "$REF" \
  "https://github.com/$REPO.git" "$DEST"; then
  if [[ -f "$DEST/$RUNNER" ]]; then
    receipt "ready_git_http1"
    printf '%s\n' "$DEST"
    exit 0
  fi
fi

rm -rf "$DEST"
receipt "codeload_http1_fallback"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ZIP="$TMP/repo.zip"

# curl is explicitly pinned to HTTP/1.1 and retries transport failures.
curl --http1.1 -fL \
  --retry 5 --retry-all-errors --retry-delay 2 \
  --connect-timeout 20 --max-time 180 \
  "https://codeload.github.com/$REPO/zip/refs/heads/$REF" \
  -o "$ZIP"

python - "$ZIP" "$DEST" "$RUNNER" <<'PY'
import shutil, sys, tempfile, zipfile
from pathlib import Path

archive = Path(sys.argv[1])
dest = Path(sys.argv[2]).resolve()
runner_rel = Path(sys.argv[3])
with tempfile.TemporaryDirectory(prefix="alang_unzip_") as td:
    root = Path(td)
    with zipfile.ZipFile(archive) as zf:
        base = root.resolve()
        for item in zf.infolist():
            out = (root / item.filename).resolve()
            if base not in out.parents and out != base:
                raise RuntimeError(f"unsafe zip member: {item.filename}")
        zf.extractall(root)
    dirs = [p for p in root.iterdir() if p.is_dir()]
    if len(dirs) != 1:
        raise RuntimeError(f"unexpected archive layout: {len(dirs)} roots")
    src = dirs[0]
    if not (src / runner_rel).is_file():
        raise RuntimeError(f"expected runner missing: {runner_rel}")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(src), str(dest))
PY

if [[ ! -f "$DEST/$RUNNER" ]]; then
  echo "bootstrap failed: runner missing after extraction" >&2
  exit 2
fi

receipt "ready_codeload_http1"
printf '%s\n' "$DEST"
