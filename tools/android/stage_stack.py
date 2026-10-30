"""Stage repository Python code and data without desktop binaries or vehicle transports."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tools/android/.cache/python"
EXCLUDED = {".git", "__pycache__", ".pytest_cache", "assets", "tests", "test_models", "c_generated_code", "pandad", "boardd"}
EXTENSIONS = {".py", ".capnp", ".json", ".dbc", ".yaml", ".yml", ".h", ".txt", ".csv", ".pxd", ".toml"}

def stage(source, dest):
  for path in source.rglob("*"):
    relative = path.relative_to(source)
    if any(part in EXCLUDED for part in relative.parts) or not path.is_file() or path.suffix not in EXTENSIONS:
      continue
    target = dest / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)

def main():
  for source, name in ((ROOT / "openpilot", "openpilot"), (ROOT / "opendbc_repo/opendbc", "opendbc")):
    destination = OUT / name
    if destination.exists():
      if not destination.resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError("Python staging directory escaped its build cache")
      shutil.rmtree(destination)
    stage(source, destination)
  # card uses these wire-format conversions; the launcher and USB transport are omitted.
  wire = OUT / "openpilot/selfdrive/pandad"
  wire.mkdir(parents=True, exist_ok=True)
  for name in ("__init__.py", "pandad_api_impl.py"):
    shutil.copy2(ROOT / "openpilot/selfdrive/pandad" / name, wire / name)
  patch = ROOT / "tools/android/patches/schemas-android.patch"
  subprocess.run(["git", "apply", "--check", "--directory=tools/android/.cache/python", str(patch)], cwd=ROOT, check=True)
  subprocess.run(["git", "apply", "--directory=tools/android/.cache/python", str(patch)], cwd=ROOT, check=True)
  rednose = OUT / "rednose"
  if rednose.exists():
    if not rednose.resolve().is_relative_to(OUT.resolve()):
      raise RuntimeError("Generated rednose package escaped the staging directory")
    shutil.rmtree(rednose)  # Its Python and native code must come from the same Android wheel.
  # ModelAssets installs the verified artifact once; avoid a second 64 MB copy in Python assets.
  duplicate = OUT / "openpilot/selfdrive/modeld/models/driving_tinygrad.pkl"
  if duplicate.exists():
    duplicate.unlink()
  print("Staged openpilot and opendbc Python sources")

if __name__ == "__main__":
  main()
