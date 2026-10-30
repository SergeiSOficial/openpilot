#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
export ANDROID_HOME="$TASK_CACHE/sdk"
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
PYTHON="${OPENPILOT_BUILD_PYTHON:-$TASK_CACHE/host-venv/bin/python}"
STAGE_ARGS=()
if [[ " $* " == *" -PqualifiedCpu "* ]]; then STAGE_ARGS+=(--qualified-cpu); fi
if [[ " $* " == *" -PqnnQuantized "* ]]; then STAGE_ARGS+=(--qnn-quantized); fi
for argument in "$@"; do
  case "$argument" in
    -PqnnModel=road) STAGE_ARGS+=(--model road);;
    -PqnnModel=cabin) STAGE_ARGS+=(--model cabin);;
    -PqnnModel=*) echo "qnnModel must be road or cabin" >&2; exit 1;;
    -PqnnGraphRoot=*) STAGE_ARGS+=(--graph-root "${argument#-PqnnGraphRoot=}");;
  esac
done
"$PYTHON" "$ROOT/tools/android/stage_acceleration.py" "${STAGE_ARGS[@]}"
"$PYTHON" "$ROOT/tools/android/validate_bundle.py"
MIRROR="$(realpath -m "${OPENPILOT_ANDROID_BUILD_MIRROR:-$TASK_CACHE/project-acceleration}")"
[[ "$(dirname "$MIRROR")" == "$(realpath "$TASK_CACHE")" && "$(basename "$MIRROR")" =~ ^project-[a-z0-9-]+$ ]] || exit 1
mkdir -p "$MIRROR"
rsync -a --delete --exclude '.gradle/' --exclude 'build/' --exclude '.cxx/' --exclude 'local.properties' "$ROOT/android/" "$MIRROR/android/"
mkdir -p "$MIRROR/tools/android/.cache" "$MIRROR/openpilot"
rsync -a --exclude '.cache/' --exclude 'recipes/' --exclude '__pycache__/' "$ROOT/tools/android/" "$MIRROR/tools/android/"
for name in python wheels msgq native-deps model-aot generated live-deps acceleration-assets tuned parallel qnn-deps qnn-assets; do
  if [[ -d "$ROOT/tools/android/.cache/$name" ]]; then
    rsync -a --delete "$ROOT/tools/android/.cache/$name/" "$MIRROR/tools/android/.cache/$name/"
  fi
done
cp "$ROOT/tools/android/.cache/runtime-requirements.txt" "$MIRROR/tools/android/.cache/"
rsync -a --delete "$ROOT/openpilot/common/" "$MIRROR/openpilot/common/"
rsync -a --delete --exclude '.git' "$ROOT/rednose_repo/" "$MIRROR/rednose_repo/"
cd "$MIRROR"
bash android/gradlew -p android -I "$MIRROR/tools/android/acceleration.init.gradle" -PbuildPython="$PYTHON" \
  -PwithModel -PprebuiltNative --offline --console plain :app:assembleDebug :app:assembleDebugAndroidTest "$@"
OUTPUT="$ROOT/artifacts/android/acceleration/build"
if [[ " $* " == *" -PmodernQnn "* ]]; then OUTPUT="$ROOT/artifacts/android/qnn/build"; fi
if [[ " $* " == *" -PqnnQuantized "* ]]; then OUTPUT="$ROOT/artifacts/android/qnn-experiment/build"; fi
if [[ " $* " == *" -PqnnCpuEmulator "* ]]; then OUTPUT="$ROOT/artifacts/android/qnn-experiment-emulator/build"; fi
OUTPUT="${OPENPILOT_ANDROID_BUILD_OUTPUT:-$OUTPUT}"
mkdir -p "$OUTPUT"
rsync -a "$MIRROR/android/app/build/outputs/" "$OUTPUT/"
