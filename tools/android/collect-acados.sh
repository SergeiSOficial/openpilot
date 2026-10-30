#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
for abi in x86_64 arm64-v8a; do
  SOURCE="$CACHE/acados/$abi/install"
  DEST="$ROOT/tools/android/.cache/native-deps/acados/$abi"
  JNI="$ROOT/android/app/src/main/jniLibs/$abi"
  mkdir -p "$DEST/include" "$DEST/lib" "$JNI"
  rsync -a "$SOURCE/include/" "$DEST/include/"
  for name in acados hpipm blasfeo; do
    cp -L "$SOURCE/lib/lib$name.so" "$DEST/lib/lib$name.so"
    patchelf --set-soname "lib$name.so" "$DEST/lib/lib$name.so"
    patchelf --remove-rpath "$DEST/lib/lib$name.so"
    cp "$DEST/lib/lib$name.so" "$JNI/"
  done
done
