#!/usr/bin/env bash
set -euo pipefail
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
exec "${OPENPILOT_HOST_PYTHON:-$TASK_CACHE/host-venv/bin/python}" "$@"
