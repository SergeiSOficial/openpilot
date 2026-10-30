#!/usr/bin/env bash
set -euo pipefail
toolchain="$(realpath "$(dirname "$AR")/..")"
grep -Eq '^ *# *define +_LIBCPP_VERSION +190000$' "$toolchain/sysroot/usr/include/c++/v1/__config"
mkdir -p "$PREFIX/lib"
cp "$toolchain/sysroot/usr/lib/$HOST/libc++_shared.so" "$PREFIX/lib/"
