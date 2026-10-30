#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
PYTHON="${OPENPILOT_HOST_PYTHON:-$TASK_CACHE/host-venv/bin/python}"
BUILD="$TASK_CACHE/host-params"
ACADOS="$($PYTHON -c 'import acados; print(acados.DIR)')"
PYTHON_INCLUDE="$($PYTHON -c 'import sysconfig; print(sysconfig.get_paths()["include"])')"
NUMPY_INCLUDE="$($PYTHON -c 'import numpy; print(numpy.get_include())')"
cmake -S "$ROOT/android/app/src/main/cpp" -B "$BUILD" -G Ninja \
  -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DHOST_ACADOS_DIR="$ACADOS" \
  -DHOST_PYTHON_INCLUDE="$PYTHON_INCLUDE" -DHOST_NUMPY_INCLUDE="$NUMPY_INCLUDE"
cmake --build "$BUILD" --target params_c pose car acados_ocp_solver_long acados_ocp_solver_pyx -j4
STAGE="$TASK_CACHE/host-rednose"
mkdir -p "$STAGE"
rsync -a --delete --exclude '.git' --exclude '__pycache__' "$ROOT/rednose_repo/" "$STAGE/"
cp "$ROOT/tools/android/recipes/rednose/setup.py" "$STAGE/"
mkdir -p "$STAGE/eigen"
rsync -a "$ROOT/tools/android/.cache/native-deps/eigen/" "$STAGE/eigen/"
cd "$STAGE"
export PYTHONPATH="$(dirname "$(dirname "$(dirname "$NUMPY_INCLUDE")")")"
"$PYTHON" setup.py build_ext --inplace
STAGE="$TASK_CACHE/host-msgq"
mkdir -p "$STAGE"
rsync -a --delete --exclude '.git' --exclude '__pycache__' "$ROOT/tools/android/.cache/msgq/" "$STAGE/"
cp "$ROOT/tools/android/recipes/msgq/setup.py" "$STAGE/"
cd "$STAGE"
"$PYTHON" setup.py build_ext --inplace
echo 'Current-source host filters, params, MPC and rednose built'
