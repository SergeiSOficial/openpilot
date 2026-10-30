#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
GRAPH_VENV="$TASK_CACHE/qnn-graph-venv"
if [[ ! -x "$GRAPH_VENV/bin/python" ]]; then python3.12 -m venv "$GRAPH_VENV"; fi
if ! "$GRAPH_VENV/bin/python" -m pip --version >/dev/null 2>&1; then "$GRAPH_VENV/bin/python" -m ensurepip --upgrade; fi
"$GRAPH_VENV/bin/python" -m pip install --only-binary=:all: -r "$ROOT/tools/android/qnn-graph-requirements.txt"
"$GRAPH_VENV/bin/python" "$ROOT/tools/android/qnn_graph.py"
