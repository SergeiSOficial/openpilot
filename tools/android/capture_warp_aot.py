"""Capture Android CPU camera-warp kernels using the repository's existing compiler."""
import ast
import importlib.util
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tinygrad_repo"), str(ROOT / "android/app/src/main/python")]
os.environ.update(DEV="CPU:CLANG", CACHELEVEL="0", CCACHE="0", PARALLEL="0")

def main():
  from android_runtime import aot
  output = ROOT / "tools/android/.cache/model-aot"
  kernels = output / "kernels"
  aot.capture(str(kernels))
  spec = importlib.util.spec_from_file_location("nv12_info", ROOT / "openpilot/system/camerad/cameras/nv12_info.py")
  nv12 = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(nv12)
  tree = ast.parse((ROOT / "openpilot/common/transformations/model.py").read_text())
  shape = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == "MEDMODEL_INPUT_SIZE" for target in node.targets))
  for width, height in ((1344, 760), (1928, 1208)):
    stride, y_height, uv_height, size = nv12.get_nv12_info(width, height)
    target = output / f"driving_warp_{width}x{height}_tinygrad.pkl"
    # ModelState copies only the padded Y/UV planes; the allocation has extra kernel padding.
    frame_copy_size = stride * (y_height + uv_height)
    sys.argv = ["compile_warp.py", "--frame", f"{width},{height},{stride},{y_height},{uv_height},{frame_copy_size}",
                "--warp-to", f"{shape[0]}x{shape[1]}", "--layout", "yuv420", "--frames", "2",
                "--output", str(target), "--retargetable", "--benchmark-runs", "1"]
    runpy.run_path(str(ROOT / "tinygrad_repo/examples/openpilot/compile_warp.py"), run_name="__main__")
  aot.manifest(str(kernels), str(output / "kernels.json"))
  subprocess.run(["clang", "-shared", "-fPIC", "-O2", "-ffreestanding", "-fno-math-errno", "-ffp-contract=off",
                  *map(str, sorted(kernels.glob("*.c"))), "-lm", "-o", str(output / "libopenpilot_kernels.so")], check=True)
  subprocess.run([sys.executable, str(ROOT / "tools/android/capture_model_aot.py"), "--verify"], check=True)
  print("Both camera warp artifacts compiled; driving-model AOT reference still passes")

if __name__ == "__main__":
  main()
