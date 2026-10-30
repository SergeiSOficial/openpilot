#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}/host-params"
cmake -S "$ROOT/android/app/src/main/cpp" -B "$BUILD" -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
cmake --build "$BUILD" --target params_c -j4
