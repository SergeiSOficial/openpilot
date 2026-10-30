#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
PYTHON="${OPENPILOT_HOST_PYTHON:-$TASK_CACHE/host-venv/bin/python}"
ACADOS="$($PYTHON -c 'import acados; print(acados.DIR)')"
export LD_LIBRARY_PATH="$ACADOS/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$PYTHON" "$ROOT/tools/android/reference_replay.py" "$@"
