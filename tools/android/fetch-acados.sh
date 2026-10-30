#!/usr/bin/env bash
set -euo pipefail
CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
SOURCE="$CACHE/acados-src"
# The commit used by comma-deps-acados 0.2.2.post103 (dependencies/acados/build.sh).
COMMIT=8af9b0ad180940ef611884574a0b27a43504311d
if [[ ! -d "$SOURCE/.git" ]]; then
  mkdir -p "$SOURCE"
  git -C "$SOURCE" init -q
  git -C "$SOURCE" remote add origin https://github.com/acados/acados.git
fi
git -C "$SOURCE" fetch -q --depth 1 origin "$COMMIT"
git -C "$SOURCE" checkout -q --detach "$COMMIT"
git -C "$SOURCE" submodule update --init --depth 1 external/blasfeo external/hpipm external/qpoases
echo "Pinned acados source: $(git -C "$SOURCE" rev-parse HEAD)"
