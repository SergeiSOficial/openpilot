"""Fingerprint computational source and captured kernels, including uncommitted port changes."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUFFIXES = {".py", ".pyx", ".pxd", ".cc", ".c", ".h", ".hpp", ".capnp", ".dbc", ".toml", ".json", ".yaml"}
EXCLUDED = {"__pycache__", ".git", "tests", "test_models", "assets", "c_generated_code", "generated"}

def source_manifest():
  paths = []
  for folder in ("openpilot", "opendbc_repo/opendbc", "msgq_repo/msgq", "rednose_repo/rednose", "tinygrad_repo/tinygrad",
                 "android/app/src/main/python", "tools/android/.cache/model-aot/kernels"):
    directory = ROOT / folder
    paths.extend(path for path in directory.rglob("*") if path.is_file() and path.suffix in SUFFIXES
                 and not any(part in EXCLUDED for part in path.relative_to(directory).parts))
  paths.extend(ROOT / path for path in ("android/app/src/main/java/ai/comma/openpilot/sim/WorkerService.java",
      "android/app/src/main/java/ai/comma/openpilot/sim/DaemonSupervisor.java", "android/app/src/main/aidl/ai/comma/openpilot/sim/IWorker.aidl",
      "android/app/src/main/java/ai/comma/openpilot/sim/ModelAssets.java", "android/app/src/main/java/ai/comma/openpilot/sim/FixtureAssets.java",
      "android/app/src/main/cpp/CMakeLists.txt", "android/app/src/main/cpp/android_logging.cc",
      "tools/android/patches/msgq-android.patch", "tools/android/patches/schemas-android.patch", "tools/android/patches/tinygrad-android.patch"))
  return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(paths))}

def source_sha256():
  digest = hashlib.sha256()
  for name, checksum in sorted(source_manifest().items()):
    digest.update(f"{name}\0{checksum}\n".encode())
  return digest.hexdigest()
