#!/usr/bin/env bash
# Android ARM64 application library only. No generated host executable/library.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
TOOLCHAIN="$TASK_CACHE/sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin"
OUTPUT="$ROOT/tools/android/.cache/tuned/jniLibs/arm64-v8a"
mkdir -p "$OUTPUT"
"$TASK_CACHE/host-venv/bin/python" - "$ROOT" <<'PY'
import pathlib,re,sys
root=pathlib.Path(sys.argv[1]);out=root/'tools/android/.cache/tuned/sources';out.mkdir(parents=True,exist_ok=True)
for source in (root/'tools/android/.cache/model-aot/kernels').glob('*.c'):
    # ModelState deliberately aliases recurrent input/output buffers. Preserve
    # that contract rather than allowing C restrict/type-alias assumptions.
    (out/source.name).write_text(re.sub(r'\brestrict\b','',source.read_text()),encoding='utf-8')
PY
"$TOOLCHAIN/aarch64-linux-android30-clang" -shared -fPIC -O3 -march=armv8.2-a+fp16 -mtune=cortex-a78 \
  -ffreestanding -fno-strict-aliasing -fno-math-errno -ffp-contract=off -Wl,--no-undefined \
  "$ROOT"/tools/android/.cache/tuned/sources/*.c -lm -o "$OUTPUT/libopenpilot_kernels_v82.so"
"$TASK_CACHE/host-venv/bin/python" - "$ROOT" "$OUTPUT" <<'PY'
import hashlib, json, pathlib, sys
root, output = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0,str(root/'tools/android'))
from validate_bundle import elf_exports
kernels=json.loads((root/'tools/android/.cache/model-aot/kernels.json').read_text())['kernels']
symbols=elf_exports(output/'libopenpilot_kernels_v82.so',183)
if not {'op_'+key for key in kernels} <= symbols: raise RuntimeError('Tuned Android kernel exports missing')
manifest={'target':'aarch64-linux-android30','ndk':'28.2.13676358','cpu_minimum':'armv8.2-a+fp16',
          'flags':['-O3','-march=armv8.2-a+fp16','-mtune=cortex-a78','-ffreestanding','-fno-strict-aliasing','-fno-math-errno','-ffp-contract=off'],
          'source_transform':'remove restrict because recurrent tensors alias input/output storage',
          'kernel_source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'tools/android/.cache/model-aot/kernels').glob('*.c'))},
          'library_sha256':hashlib.sha256((output/'libopenpilot_kernels_v82.so').read_bytes()).hexdigest(),
          'numerical_certified':False,'requires_on_target_numerical_gate':True}
(root/'tools/android/.cache/tuned/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Cross-built ARMv8.2 FP16 Android library; numerical gate remains mandatory')
PY
