"""Stage the real model, reference output and Python sources for the model gate APK."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from provenance import source_sha256

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "tools/android/.cache"

def main():
  python = CACHE / "python"
  python.mkdir(exist_ok=True)
  shutil.copytree(ROOT / "tinygrad_repo/tinygrad", python / "tinygrad", dirs_exist_ok=True,
                  ignore=shutil.ignore_patterns("__pycache__"))
  patch = ROOT / "tools/android/patches/tinygrad-android.patch"
  directory = "--directory=tools/android/.cache/python"
  subprocess.run(["git", "apply", "--check", directory, str(patch)], cwd=ROOT, check=True)
  subprocess.run(["git", "apply", directory, str(patch)], cwd=ROOT, check=True)
  if not (python / "tinygrad/runtime/ops_disk.py").read_text().startswith("from __future__ import annotations"):
    raise RuntimeError("tinygrad Android patch was not applied to the staged package")
  helpers = python / "examples/openpilot"
  helpers.mkdir(parents=True, exist_ok=True)
  (python / "examples/__init__.py").touch()
  (helpers / "__init__.py").touch()
  shutil.copy2(ROOT / "tinygrad_repo/examples/openpilot/helpers.py", helpers)
  vendor = python / "openpilot_android_vendor"
  vendor.mkdir(exist_ok=True)
  (vendor / "__init__.py").touch()
  shutil.copy2(ROOT / "tinygrad_repo/examples/openpilot/helpers.py", vendor / "helpers.py")
  assets = ROOT / "android/app/src/main/assets/generated/model"
  assets.mkdir(parents=True, exist_ok=True)
  files = {}
  metadata = {
    "source_sha256": source_sha256(),
    "channel": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
    "openpilot": {
      "version": (ROOT / "openpilot/common/version.h").read_text().split('"')[1],
      "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
      "git_origin": subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=ROOT, text=True).strip(),
      "git_commit_date": subprocess.check_output(["git", "show", "-s", "--format=%cI", "HEAD"], cwd=ROOT, text=True).strip(),
      "build_style": "android-simulation", "release_notes": "Recorded simulation build",
    },
  }
  (assets / "build.json").write_text(json.dumps(metadata, indent=2) + "\n")
  files["build.json"] = hashlib.sha256((assets / "build.json").read_bytes()).hexdigest()
  schemas = [*sorted((ROOT / "openpilot/cereal").glob("*.capnp")), ROOT / "opendbc_repo/opendbc/car/car.capnp"]
  for source in schemas:
    content = source.read_text().replace('"/include/c++.capnp"', '"/capnp/c++.capnp"')
    target = assets / source.name
    target.write_text(content, encoding="utf-8", newline="\n")
    files[source.name] = hashlib.sha256(target.read_bytes()).hexdigest()
  names = ["driving_tinygrad.pkl", "reference.npz", "provenance.json", "kernels.json"]
  names += [path.name for path in sorted((CACHE / "model-aot").glob("driving_warp_*_tinygrad.pkl"))]
  for name in names:
    source = CACHE / "model-aot" / name
    shutil.copy2(source, assets / name)
    files[name] = hashlib.sha256(source.read_bytes()).hexdigest()
  (assets / "manifest.json").write_text(json.dumps({"schema": 1, "sha256": files}, indent=2) + "\n")
  print("Staged real driving model and Python runtime sources")

if __name__ == "__main__":
  main()
