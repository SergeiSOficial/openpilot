#!/usr/bin/env bash
set -euo pipefail
./configure --host="$HOST" --prefix="$PREFIX" --disable-multi-os-directory --disable-static
make -j4
make install
