#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
TOOLS="$TASK_CACHE/chaquopy"
export ANDROID_HOME="$TASK_CACHE/sdk"
export PIP_DEFAULT_TIMEOUT=120
export PIP_FIND_LINKS="$ROOT/tools/android/.cache/wheelhouse"
export PATH="$TASK_CACHE/wheels-venv/bin:$PATH"
[[ -f "$TOOLS/server/pypi/build-wheel.py" ]] || {
  git clone --depth 1 --branch 17.2.0 --filter=blob:none --sparse https://github.com/chaquo/chaquopy.git "$TOOLS"
  git -C "$TOOLS" sparse-checkout set server/pypi target
}
[[ -x "$TASK_CACHE/wheels-venv/bin/python" ]] || python3.12 -m venv "$TASK_CACHE/wheels-venv"
python -m pip install -r "$TOOLS/server/pypi/requirements.txt"
# The upstream Python 3.12 wheel tool defaults to NDK 27; use this project's pinned NDK.
python - "$TOOLS/target/android-env.sh" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
text = p.read_text()
old, new = 'ndk_version=27.3.13750724', 'ndk_version=28.2.13676358'
if old not in text and new not in text:
  raise RuntimeError('Unknown Chaquopy NDK selection; review the pinned build tool')
p.write_text(text.replace(old, new))
PY
python - "$TOOLS/server/pypi/build-wheel.py" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
text = p.read_text()
needle = '        for filename in os.listdir(reqs_lib_dir):\n'
guard = '            if filename.startswith("libpython") and filename != f"libpython{self.python}.so":\n                continue\n'
if guard not in text:
  if text.count(needle) != 1:
    raise RuntimeError('Unknown Chaquopy library alias creation; review the pinned build tool')
  p.write_text(text.replace(needle, needle + guard))
PY
TARGET="$TOOLS/maven/com/chaquo/python/target/3.12.15-0"
if [[ ! -d "$TARGET" ]]; then
  CACHED_TARGET="$ROOT/tools/android/.cache/chaquopy/maven/com/chaquo/python/target/3.12.15-0"
  if [[ -d "$CACHED_TARGET" ]]; then
    mkdir -p "$(dirname "$TARGET")"
    cp -a "$CACHED_TARGET" "$TARGET"
  else
    bash "$TOOLS/target/download-target.sh" "$TARGET"
  fi
fi
for package in "${@:-numpy}"; do
  [[ "$package" =~ ^[a-z0-9-]+$ ]] || { echo "Invalid recipe name: $package" >&2; exit 1; }
  # compiler-wrapper permits only sources and headers beneath the build-tool tree.
  RECIPE="$TOOLS/server/pypi/packages/openpilot-$package"
  mkdir -p "$RECIPE"
  cp "$ROOT/tools/android/recipes/$package/meta.yaml" "$RECIPE/"
  if [[ -d "$ROOT/tools/android/recipes/$package/patches" ]]; then
    mkdir -p "$RECIPE/patches"
    rsync -a --delete "$ROOT/tools/android/recipes/$package/patches/" "$RECIPE/patches/"
  fi
  if [[ "$package" == pycapnp ]]; then
    cp "$ROOT/tools/android/recipes/pycapnp/android-directory-handles.patch" "$RECIPE/"
    export OPENPILOT_CAPNP_PATCH="$RECIPE/android-directory-handles.patch"
  fi
  if [[ -f "$ROOT/tools/android/recipes/$package/LICENSE.TXT" ]]; then
    cp "$ROOT/tools/android/recipes/$package/LICENSE.TXT" "$RECIPE/"
  fi
  if [[ -f "$ROOT/tools/android/recipes/$package/LICENSE" ]]; then
    cp "$ROOT/tools/android/recipes/$package/LICENSE" "$RECIPE/"
  fi
  if [[ -f "$ROOT/tools/android/recipes/$package/build.sh" ]]; then
    cp "$ROOT/tools/android/recipes/$package/build.sh" "$RECIPE/"
    chmod +x "$RECIPE/build.sh"
  fi
  if [[ "$package" == msgq ]]; then
    python "$ROOT/tools/android/stage_msgq.py"
    mkdir -p "$RECIPE/source"
    cp -a "$ROOT/tools/android/.cache/msgq/." "$RECIPE/source/"
    cp "$ROOT/tools/android/recipes/msgq/setup.py" "$RECIPE/source/setup.py"
    printf '[build-system]\nrequires = ["setuptools", "Cython"]\nbuild-backend = "setuptools.build_meta"\n' > "$RECIPE/source/pyproject.toml"
    cp "$RECIPE/source/LICENSE" "$RECIPE/" 2>/dev/null || true
  fi
  if [[ "$package" == rednose ]]; then
    mkdir -p "$RECIPE/source"
    rsync -a --delete --exclude '.git' --exclude '__pycache__' "$ROOT/rednose_repo/" "$RECIPE/source/"
    cp "$ROOT/tools/android/recipes/rednose/setup.py" "$RECIPE/source/setup.py"
    printf '[build-system]\nrequires = ["setuptools", "Cython"]\nbuild-backend = "setuptools.build_meta"\n' > "$RECIPE/source/pyproject.toml"
    mkdir -p "$RECIPE/source/eigen"
    rsync -a "$ROOT/tools/android/.cache/native-deps/eigen/" "$RECIPE/source/eigen/"
  fi
  # Source archives are fetched and verified on Windows when WSL networking is slow.
  if [[ -d "$ROOT/tools/android/recipes/$package/build" ]]; then
    while IFS= read -r source; do
      relative="${source#"$ROOT/tools/android/recipes/$package/"}"
      mkdir -p "$RECIPE/$(dirname "$relative")"
      cp "$source" "$RECIPE/$relative"
    done < <(find "$ROOT/tools/android/recipes/$package/build" -maxdepth 2 -type f -name '*.tar.gz')
  fi
  for abi in x86_64 arm64-v8a; do
    python "$TOOLS/server/pypi/build-wheel.py" --python 3.12 --abi "$abi" "$RECIPE"
  done
done
