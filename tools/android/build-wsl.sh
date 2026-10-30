#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
export ANDROID_HOME="$TASK_CACHE/sdk"
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
PYTHON="${OPENPILOT_BUILD_PYTHON:-$TASK_CACHE/host-venv/bin/python}"
[[ -x "$PYTHON" ]] || { echo 'Set OPENPILOT_BUILD_PYTHON to a Python 3.12 interpreter.' >&2; exit 1; }
if [[ " $* " == *" -PwithModel "* ]]; then
  if [[ " $* " == *" -PliveShadow "* ]]; then
    "$PYTHON" "$ROOT/tools/android/validate_live_bundle.py" --check-source
  else
    "$PYTHON" "$ROOT/tools/android/validate_bundle.py" --check-source
  fi
fi
command -v rsync >/dev/null || { echo 'Install rsync in WSL first.' >&2; exit 1; }
MIRROR="$TASK_CACHE/project"
mkdir -p "$MIRROR"
[[ "$(realpath "$MIRROR")" == "$(realpath "$TASK_CACHE")/project" ]] || { echo 'Unexpected build mirror path.' >&2; exit 1; }
# All --delete operations below are confined to fixed generated folders in this task's build mirror.
rsync -a --delete --exclude '.gradle/' --exclude 'build/' --exclude '.cxx/' --exclude 'local.properties' "$ROOT/android/" "$MIRROR/android/"
mkdir -p "$MIRROR/tools/android/.cache" "$MIRROR/openpilot"
rsync -a --exclude '.cache/' --exclude 'recipes/' --exclude '__pycache__/' "$ROOT/tools/android/" "$MIRROR/tools/android/"
for name in python wheels msgq native-deps model-aot generated live-deps; do
  if [[ -d "$ROOT/tools/android/.cache/$name" ]]; then
    rsync -a --delete "$ROOT/tools/android/.cache/$name/" "$MIRROR/tools/android/.cache/$name/"
  fi
done
if [[ -f "$ROOT/tools/android/.cache/runtime-requirements.txt" ]]; then
  cp "$ROOT/tools/android/.cache/runtime-requirements.txt" "$MIRROR/tools/android/.cache/"
fi
rsync -a --delete "$ROOT/openpilot/common/" "$MIRROR/openpilot/common/"
rsync -a --delete --exclude '.git' "$ROOT/rednose_repo/" "$MIRROR/rednose_repo/"
cd "$MIRROR"
bash android/gradlew -p android -PbuildPython="$PYTHON" --console plain "$@"
OUTPUT="$ROOT/android/app/build/outputs"
mkdir -p "$OUTPUT"
[[ "$(realpath "$OUTPUT")" == "$ROOT/android/app/build/outputs" ]] || { echo 'Unexpected output directory.' >&2; exit 1; }
rsync -a "$MIRROR/android/app/build/outputs/" "$OUTPUT/"
