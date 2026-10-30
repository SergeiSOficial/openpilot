"""Numerical build gate for representative operations and every real driving-model output."""
import hashlib
import json
import os
from pathlib import Path
import sys
from provenance import source_sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools/android/.cache/python"), str(ROOT / "android/app/src/main/python")]
os.environ.update(DEV="CPU:CLANG", CACHELEVEL="0", CCACHE="0", PARALLEL="0")

def main():
  from android_runtime.model_probe import run
  models = ROOT / "tools/android/.cache/model-aot"
  report = json.loads(run(str(models), str(models)))
  if not report["passed"]:
    raise RuntimeError("Driving-model numerical build gate failed")
  report.update(source_sha256=source_sha256(), sha256={name: hashlib.sha256((models / name).read_bytes()).hexdigest()
                for name in ("driving_tinygrad.pkl", "reference.npz", "kernels.json")})
  (models / "verification.json").write_text(json.dumps(report, indent=2)+"\n")
  print(json.dumps(report))

if __name__ == "__main__":
  main()
