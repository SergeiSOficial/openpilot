"""Reviewed stdlib-only tests. No model/native runtime is imported or executed."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[3]/"android/app/src/main/python/android_runtime/live.py"
spec = importlib.util.spec_from_file_location("android_live_policy",SOURCE)
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class LivePolicyTest(unittest.TestCase):
  def test_missing_report_preserves_last_heartbeat_without_refreshing_it(self):
    previous={"state":"running","report_monotonic_ns":100}
    with tempfile.TemporaryDirectory() as directory:
      self.assertEqual(live._camera_state(Path(directory),previous),previous)

  def test_partial_or_empty_report_cannot_erase_last_heartbeat(self):
    previous={"state":"running","report_monotonic_ns":100}
    for content in ("{", "{}", "[]", "null"):
      with patch.object(Path,"read_text",return_value=content):
        self.assertEqual(live._camera_state(Path("unused"),previous),previous)

  def test_terminal_camera_report_replaces_cached_running_state(self):
    with patch.object(Path,"read_text",return_value='{"state":"failed","report_monotonic_ns":200}'):
      self.assertEqual(live._camera_state(Path("unused"),{"state":"running"})["state"],"failed")
  def frame(self, frame_id=1, timestamp=1_000_000_000):
    return SimpleNamespace(frame_id=frame_id,timestamp_sof=timestamp,valid=True)

  def test_untrusted_clock_is_rejected(self):
    frame=self.frame();frame.valid=False
    self.assertEqual(live.pair_eligible(frame,self.frame(),1_020_000_000,(0,0)),(False,"untrusted_sensor_clock"))

  def test_accepts_fresh_independent_bench_pair(self):
    self.assertEqual(live.pair_eligible(self.frame(),self.frame(timestamp=970_000_000),1_020_000_000,(0,0)),(True,"fresh_bench_pair"))

  def test_reused_secondary_is_rejected(self):
    self.assertEqual(live.pair_eligible(self.frame(2),self.frame(1),1_020_000_000,(1,1)),(False,"repeated_frame"))

  def test_missing_pair_is_rejected(self):
    self.assertFalse(live.pair_eligible(self.frame(),None,1_020_000_000,(0,0))[0])

  def test_stale_sensor_frame_is_rejected(self):
    self.assertEqual(live.pair_eligible(self.frame(),self.frame(),1_300_000_000,(0,0))[1],"stale_or_untrusted_clock")

  def test_future_sensor_clock_is_rejected(self):
    self.assertEqual(live.pair_eligible(self.frame(timestamp=1_100_000_000),self.frame(),1_020_000_000,(0,0))[1],"stale_or_untrusted_clock")

  def test_large_cross_camera_skew_is_rejected(self):
    self.assertEqual(live.pair_eligible(self.frame(),self.frame(timestamp=900_000_000),1_020_000_000,(0,0))[1],"pair_skew")

  def test_percentile_and_deadline_counts_are_actual_samples(self):
    summary=live.timing_summary([10,20,30,40,200])
    self.assertEqual(summary["p95_ms"],200)
    self.assertEqual(summary["over_50_ms"],1)
    self.assertEqual(summary["samples"],5)

  def test_no_samples_cannot_claim_timing(self):
    self.assertEqual(live.timing_summary([]),{"samples":0})


if __name__ == "__main__":
  unittest.main()
