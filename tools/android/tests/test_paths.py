import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

class AndroidPathTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    # Paths needs only the PC flag; do not load target hardware or native dependencies.
    hardware = types.ModuleType("openpilot.common.hardware")
    hardware.PC = True
    spec = importlib.util.spec_from_file_location("android_path_test", ROOT / "openpilot/common/hardware/hw.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"openpilot.common.hardware": hardware}):
      spec.loader.exec_module(module)
    cls.Paths = module.Paths

  def test_android_paths_stay_inside_session(self):
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENPILOT_ANDROID_ROOT": directory, "OPENPILOT_PREFIX": "worker"}):
      for path in (self.Paths.comma_home(), self.Paths.swaglog_root(), self.Paths.download_cache_root(),
                   self.Paths.persist_root(), self.Paths.config_root(), self.Paths.shm_path()):
        self.assertTrue(Path(path).is_relative_to(directory), path)
      self.assertTrue(self.Paths.swaglog_ipc().startswith("ipc://" + str(Path(directory))))

  def test_relative_android_root_is_rejected(self):
    with patch.dict(os.environ, {"OPENPILOT_ANDROID_ROOT": "relative/session"}):
      with self.assertRaises(ValueError):
        self.Paths.shm_path()

  def test_desktop_shared_memory_default_is_preserved(self):
    with patch.dict(os.environ):
      os.environ.pop("OPENPILOT_ANDROID_ROOT", None)
      expected = "/tmp" if sys.platform == "darwin" else "/dev/shm"
      self.assertEqual(self.Paths.shm_path(), expected)

if __name__ == "__main__":
  unittest.main()
