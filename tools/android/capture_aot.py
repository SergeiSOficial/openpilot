"""Capture portable C kernels and test that recorded native kernels reproduce tensor results."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tinygrad_repo"), str(ROOT / "android/app/src/main/python")]
os.environ.update(DEV="CPU:CLANG", CACHELEVEL="0", CCACHE="0")

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--output", type=Path, default=ROOT / "tools/android/.cache/aot")
  parser.add_argument("--verify", action="store_true")
  args = parser.parse_args()
  args.output = args.output.resolve()
  from android_runtime import aot
  from tinygrad import Tensor
  import numpy as np
  library = args.output / "libprobe.so"
  if args.verify:
    aot.install(str(library))
  else:
    aot.capture(str(args.output))
  x = np.arange(32, dtype=np.float32).reshape(4, 8) / 32
  weights = np.arange(24, dtype=np.float32).reshape(8, 3) / 24
  result = (Tensor(x).matmul(Tensor(weights)).relu() + 0.25).numpy()
  np.testing.assert_allclose(result, np.maximum(x @ weights, 0) + 0.25, rtol=1e-5, atol=1e-6)
  if args.verify:
    (args.output / "tensor-verification.json").write_text(json.dumps({"passed": True, "operations": ["matmul", "relu", "add"],
        "rtol": 1e-5, "atol": 1e-6, "numpy": np.__version__}, indent=2)+"\n")
    print("Packaged tensor kernel dispatch matched NumPy")
    return
  aot.manifest(str(args.output), str(args.output / "manifest.json"))
  # Validate that exported symbols link independently of LLVM or tinygrad's ELF loader.
  subprocess.run(["clang", "-shared", "-fPIC", "-O2", "-ffreestanding", "-fno-math-errno", "-ffp-contract=off",
                  *map(str, args.output.glob("*.c")), "-lm", "-o", str(library)], check=True)
  loaded = ctypes.CDLL(str(library))
  for source in args.output.glob("*.c"):
    getattr(loaded, "op_" + source.stem)
  print(f"Tensor reference passed; {len(list(args.output.glob('*.c')))} exported kernels linked and loaded")
  subprocess.run([sys.executable, __file__, "--output", str(args.output), "--verify"], check=True)
  if args.output == ROOT / "tools/android/.cache/model-aot/kernels":
    aot.manifest(str(args.output), str(args.output.parent / "kernels.json"))
    import shutil
    target = args.output.parent / "libopenpilot_kernels.so"
    temporary = target.with_suffix(".tmp")
    shutil.copy2(library, temporary)
    temporary.replace(target)

if __name__ == "__main__":
  main()
