"""Load Android extensions from the APK's native library directory."""
import importlib.util
import os
from pathlib import Path
import sys

def load_extension(module_name: str, library_name: str):
  root = Path(os.environ["OPENPILOT_ANDROID_NATIVE_DIR"])
  if not root.is_absolute() or Path(library_name).name != library_name:
    raise ValueError("Android extension path must be an APK library basename")
  spec = importlib.util.spec_from_file_location(module_name, root / library_name)
  if spec is None or spec.loader is None:
    raise ImportError(f"Cannot load Android extension {module_name}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[module_name] = module
  try:
    spec.loader.exec_module(module)
  except BaseException:
    sys.modules.pop(module_name, None)
    raise
  return module
