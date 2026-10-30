#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
PYTHON="${OPENPILOT_BUILD_PYTHON:-$HOME/.local/share/uv/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12}"
[[ -x "$PYTHON" ]] || PYTHON=python3.12
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Host generation requires Python 3.12"'
"$PYTHON" "$ROOT/tools/android/host_requirements.py"
[[ -x "$TASK_CACHE/host-venv/bin/python" ]] || "$PYTHON" -m venv "$TASK_CACHE/host-venv"
"$TASK_CACHE/host-venv/bin/python" -m pip install --cache-dir "$TASK_CACHE/pip-cache" --require-hashes \
  -r "$ROOT/tools/android/.cache/host-requirements.txt"
printf 'Host tools installed locally: %s\n' "$TASK_CACHE/host-venv"
