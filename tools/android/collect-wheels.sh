#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TOOLS="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}/chaquopy/server/pypi"
mkdir -p "$ROOT/tools/android/.cache/wheels"
find "$TOOLS/dist" -name '*.whl' -type f -exec cp -t "$ROOT/tools/android/.cache/wheels" {} +
python3 - "$ROOT/tools/android/.cache/wheels" <<'PY'
import pathlib, sys, zipfile
for path in pathlib.Path(sys.argv[1]).glob('*.whl'):
  with zipfile.ZipFile(path) as wheel:
    metadata = next(name for name in wheel.namelist() if name.endswith('.dist-info/WHEEL'))
    tags = [line for line in wheel.read(metadata).decode().splitlines() if line.startswith('Tag:')]
    if not tags or any('android_' not in tag and not tag.endswith('-none-any') for tag in tags):
      raise RuntimeError(f'Unexpected wheel platform in {path.name}: {tags}')
  print(path.name)
PY
