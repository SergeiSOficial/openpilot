#!/usr/bin/env bash
# Cross-build the real Android application kernels, never a native host helper.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
TOOLCHAIN="$TASK_CACHE/sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin"
PYTHON="$TASK_CACHE/host-venv/bin/python"
"$PYTHON" "$ROOT/tools/android/parallel_kernels.py"
OUT="$ROOT/tools/android/.cache/parallel"
for pair in arm64-v8a:aarch64 x86_64:x86_64; do
  abi="${pair%:*}"
  target="${pair#*:}"
  mkdir -p "$OUT/jniLibs/$abi" "$OUT/objects/$abi"
  for file in "$OUT"/sources/*.c; do
    "$TOOLCHAIN/$target-linux-android30-clang" -c -fPIC -O2 -ffreestanding -fno-math-errno -ffp-contract=off \
      "$file" -o "$OUT/objects/$abi/$(basename "${file%.c}").o"
  done
  "$TOOLCHAIN/$target-linux-android30-clang++" -shared -fPIC -O2 -std=c++17 -static-libstdc++ \
    "$ROOT/android/app/src/main/cpp/kernel_pool.cc" "$OUT"/objects/"$abi"/*.o -lm -Wl,--no-undefined \
    -o "$OUT/jniLibs/$abi/libopenpilot_kernels_parallel.so"
done
mkdir -p "$OUT/objects/arm64-v82"
# Tune only independent compute loops. Keep queue moves, warps and all other
# kernels at the baseline settings, including their original alias behavior.
for file in "$OUT"/sources/*.c; do
  flags=(-O2)
  if grep -q op_parallel_launch "$file"; then
    flags=(-O3 -march=armv8.2-a+fp16 -mtune=cortex-a78)
  fi
  "$TOOLCHAIN/aarch64-linux-android30-clang" -c -fPIC "${flags[@]}" -ffreestanding -fno-math-errno -ffp-contract=off \
    "$file" -o "$OUT/objects/arm64-v82/$(basename "${file%.c}").o"
done
"$TOOLCHAIN/aarch64-linux-android30-clang++" -shared -fPIC -O2 -std=c++17 -static-libstdc++ \
  "$ROOT/android/app/src/main/cpp/kernel_pool.cc" "$OUT"/objects/arm64-v82/*.o -lm -Wl,--no-undefined \
  -o "$OUT/jniLibs/arm64-v8a/libopenpilot_kernels_parallel_v82.so"
"$PYTHON" - "$ROOT" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(root/'tools/android'))
from validate_bundle import elf_exports
out=root/'tools/android/.cache/parallel'
required={'op_'+key for key in json.loads((root/'tools/android/.cache/model-aot/kernels.json').read_text())['kernels']}
libraries={}
for abi,machine in [('arm64-v8a',183),('x86_64',62)]:
 library=out/f'jniLibs/{abi}/libopenpilot_kernels_parallel.so'
 if not required<=elf_exports(library,machine):raise RuntimeError('Parallel Android exports missing')
 libraries[abi]=hashlib.sha256(library.read_bytes()).hexdigest()
variant=out/'jniLibs/arm64-v8a/libopenpilot_kernels_parallel_v82.so'
if not required<=elf_exports(variant,183):raise RuntimeError('FP16 parallel Android exports missing')
libraries['arm64-v8a-fp16-compute-only']=hashlib.sha256(variant.read_bytes()).hexdigest()
(out/'manifest.json').write_text(json.dumps({'targets':['aarch64-linux-android30','x86_64-linux-android30'],'ndk':'28.2.13676358',
 'flags':['-O2','-ffreestanding','-fno-math-errno','-ffp-contract=off'],
 'proof_sha256':hashlib.sha256((out/'proof.json').read_bytes()).hexdigest(),
 'pool_source_sha256':hashlib.sha256((root/'android/app/src/main/cpp/kernel_pool.cc').read_bytes()).hexdigest(),
 'generator_sha256':hashlib.sha256((root/'tools/android/parallel_kernels.py').read_bytes()).hexdigest(),
 'compiled_kernel_source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((out/'sources').glob('*.c'))},
 'library_sha256':libraries,
 'source_transform':'split only independently proven output loops; fallback on buffer overlap',
 'fp16_variant':'O3 armv8.2-a+fp16 cortex-a78 only for independently proven half compute loops; other kernels unchanged O2',
 'numerical_certified':False,'requires_on_target_numerical_gate':True},indent=2)+'\n')
print('Cross-built parallel Android kernels; target numerical/sequence tests required')
PY
