"""Capture, link and verify real driving-model kernels without runtime compilation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tinygrad_repo"), str(ROOT / "android/app/src/main/python")]
os.environ.update(DEV="CPU:CLANG", CACHELEVEL="0", CCACHE="0", PARALLEL="0")

def evaluate(model, library=None):
  import numpy as np
  from android_runtime import aot
  if library is not None:
    aot.install(str(library))
  from examples.openpilot.helpers import allocate_inputs, load_pickle
  from tinygrad.engine.realize import lower_and_compile
  artifact = load_pickle(model, out_of_band=True)
  artifact["run"].captured._linear = lower_and_compile(artifact["run"].captured._linear)
  inputs = allocate_inputs(artifact["input_specs"])
  outputs = allocate_inputs(artifact["output_specs"])
  artifact["run"](output_buffers=outputs, **inputs)
  return {name: tensor.numpy().copy() for name, tensor in outputs.items()}

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--verify", action="store_true")
  args = parser.parse_args()
  import numpy as np
  from android_runtime import aot
  out = ROOT / "tools/android/.cache/model-aot"
  kernels = out / "kernels"
  out.mkdir(parents=True, exist_ok=True)
  model = out / "driving_tinygrad.pkl"
  library = out / "libopenpilot_kernels.so"
  reference = out / "reference.npz"
  if args.verify:
    actual = evaluate(model, library)
    with np.load(reference) as expected:
      assert set(actual) == set(expected.files)
      for name, values in actual.items():
        np.testing.assert_allclose(values, expected[name], atol=1e-5, rtol=1e-4, err_msg=name)
    print("Real driving-model AOT dispatch matched the host reference")
    return
  aot.capture(str(kernels))
  onnx = ROOT / "openpilot/selfdrive/modeld/models/driving_supercombo.onnx"
  sys.argv = ["compile_onnx.py", str(onnx), str(model), "--retargetable", "--out-of-band", "--benchmark-runs", "1"]
  runpy.run_path(str(ROOT / "tinygrad_repo/examples/openpilot/compile_onnx.py"), run_name="__main__")
  np.savez(reference, **evaluate(model))
  sources = sorted(kernels.glob("*.c"))
  subprocess.run(["clang", "-shared", "-fPIC", "-O2", "-ffreestanding", "-fno-math-errno", "-ffp-contract=off",
                  *map(str, sources), "-lm", "-o", str(library)], check=True)
  aot.manifest(str(kernels), str(out / "kernels.json"))
  (out / "provenance.json").write_text(json.dumps({
    "model_sha256": hashlib.sha256(onnx.read_bytes()).hexdigest(),
    "tinygrad_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT / "tinygrad_repo", text=True).strip(),
    "compiler": subprocess.check_output(["clang", "--version"], text=True).splitlines()[0],
  }, indent=2) + "\n")
  subprocess.run([sys.executable, __file__, "--verify"], check=True)

if __name__ == "__main__":
  main()
