#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
import os, pathlib, shlex, subprocess
family = 'aarch64' if 'aarch64' in os.environ['CC'] else 'x86_64'
macros = subprocess.check_output([os.environ['CC'], '-dM', '-E', '-x', 'c', '-'], input=b'').decode()
for required in ('#define __LDBL_MANT_DIG__ 113', '#define __LDBL_MAX_EXP__ 16384', '#define __SIZEOF_LONG_DOUBLE__ 16',
                 '#define __BYTE_ORDER__ __ORDER_LITTLE_ENDIAN__'):
  if required not in macros:
    raise RuntimeError(f'Unsupported Android long double ABI: missing {required}')
lines = ['[binaries]']
for name, var in [('c', 'CC'), ('cpp', 'CXX'), ('ar', 'AR'), ('strip', 'STRIP')]:
  lines.append(f'{name} = {shlex.split(os.environ[var])!r}')
lines += ['[host_machine]', "system = 'android'", f"cpu_family = '{family}'", f"cpu = '{family}'", "endian = 'little'",
          '[properties]', 'needs_exe_wrapper = true', "longdouble_format = 'IEEE_QUAD_LE'"]
pathlib.Path('android-cross.ini').write_text('\n'.join(lines) + '\n')
PY
python -m build --wheel --no-isolation -Cbuild-dir="$PWD/android-build" \
  -Csetup-args="--cross-file=$PWD/android-cross.ini" \
  -Csetup-args=-Dallow-noblas=true -Csetup-args=-Dcpu-dispatch=none
unzip -q dist/*.whl -d "$(dirname "$PREFIX")"
