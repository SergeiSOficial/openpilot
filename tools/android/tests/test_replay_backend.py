"""Verify bounded waits, Binder environment transfer and fixture integrity without an emulator."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "android/app/src/main/python"))
from android_runtime.replay import AndroidBackend, AndroidProcess, FixtureFrames


class Supervisor:
  def __init__(self, state="running"):
    self.state, self.environment = state, None

  def health(self):
    return json.dumps({"modeld": {"state": self.state, "error": "worker exited"}})

  def startWorker(self, name, environment):
    self.environment = json.loads(environment)
    return 17


class ReplayBackendTest(unittest.TestCase):
  @contextmanager
  def backend(self, state="running"):
    with tempfile.TemporaryDirectory() as directory:
      yield AndroidBackend(Path(directory), Supervisor(state))

  def test_worker_death_interrupts_an_unready_fifo(self):
    read, write = os.pipe()
    try:
      with self.backend("dead") as backend:
        event = type("Event", (), {"fd": read})()
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "Required worker modeld failed"):
          backend.wait_for_events([event])
        self.assertLess(time.monotonic()-start, 1)
    finally:
      os.close(read)
      os.close(write)

  def test_monotonic_timeout_is_bounded_and_does_not_consume_ready_events(self):
    read, write = os.pipe()
    try:
      with self.backend() as backend:
        event = type("Event", (), {"fd": read})()
        start = time.monotonic()
        with self.assertRaises(TimeoutError), backend.step_context("modeld", 0.03):
          backend.wait_for_events([event])
        self.assertLess(time.monotonic()-start, 1)
        os.write(write, b"x")
        self.assertEqual(backend.wait_for_events([event]), 0)
        self.assertEqual(os.read(read, 1), b"x")
    finally:
      os.close(read)
      os.close(write)

  def test_native_fake_event_settings_are_explicitly_transferred(self):
    with self.backend() as backend, patch.dict(os.environ, {"OPENPILOT_PREFIX": "session1"}, clear=True):
      process = AndroidProcess(backend, "modeld")
      process.start()
      self.assertEqual(backend.supervisor.environment["CEREAL_FAKE"], "1")
      self.assertEqual(backend.supervisor.environment["CEREAL_FAKE_PREFIX"], "modeld")
      self.assertEqual(backend.supervisor.environment["OPENPILOT_PREFIX"], "session1")

  def test_canonical_frame_depadding_and_corruption(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      (root / "road").mkdir()
      raw = bytes(range(24))
      path = root / "road/0001.nv12"
      path.write_bytes(raw)
      info = {"width": 4, "height": 2, "stride": 8, "y_height": 2, "uv_height": 1,
              "buffer_size": 24, "sha256": {"1": hashlib.sha256(raw).hexdigest()}}
      frames = FixtureFrames(root, "road", info)
      self.assertEqual(frames.get(1).tolist(), [0, 1, 2, 3, 8, 9, 10, 11, 16, 17, 18, 19])
      path.write_bytes(b"corrupt")
      with self.assertRaisesRegex(ValueError, "Corrupted fixture buffer"):
        frames.get(1)


if __name__ == "__main__":
  unittest.main()
