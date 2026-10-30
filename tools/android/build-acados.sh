#!/usr/bin/env bash
set -euo pipefail
CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
NDK="$CACHE/sdk/ndk/28.2.13676358"
SOURCE="$CACHE/acados-src"
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == 8af9b0ad180940ef611884574a0b27a43504311d ]] || { echo 'Unexpected acados source revision.' >&2; exit 1; }
for abi in x86_64 arm64-v8a; do
  BUILD="$CACHE/acados/$abi/build"
  INSTALL="$CACHE/acados/$abi/install"
  cmake -S "$SOURCE" -B "$BUILD" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI="$abi" -DANDROID_PLATFORM=android-30 \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
    -DACADOS_WITH_QPOASES=OFF -DACADOS_WITH_OPENMP=OFF -DBLASFEO_TARGET=GENERIC -DHPIPM_TARGET=GENERIC -DTARGET=GENERIC \
    -DACADOS_INSTALL_DIR="$INSTALL" -DCMAKE_INSTALL_PREFIX="$INSTALL" -DCMAKE_INSTALL_LIBDIR=lib \
    '-DCMAKE_C_FLAGS=-include stdlib.h'
  cmake --build "$BUILD" -j4
  cmake --install "$BUILD"
done
