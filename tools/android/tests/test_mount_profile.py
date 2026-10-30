"""Reviewed stdlib-only tests with synthetic fixtures; no native or device code."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "mount_profile.py"
spec = importlib.util.spec_from_file_location("android_mount_profile_tool", SOURCE)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def observations():
  # Deliberately synthetic unit-test data, never an installation-ready measurement.
  gravity = 9.80665
  return {"device_model": "SM-F926B", "calibration_id": "synthetic-unit-test-only",
          "rotation_android_to_sensor": [[0, -1, 0], [1, 0, 0], [0, 0, 1]],
          "gravity_observations": [
            {"android": [0, -gravity, 0], "expected_sensor": [gravity, 0, 0]},
            {"android": [gravity, 0, 0], "expected_sensor": [0, gravity, 0]},
            {"android": [0, 0, -gravity], "expected_sensor": [0, 0, -gravity]}],
          "rotation_observations": [
            {"axis": "x", "android": [0, -0.2, 0], "expected_sensor": [0.2, 0, 0]},
            {"axis": "y", "android": [-0.3, 0, 0], "expected_sensor": [0, -0.3, 0]},
            {"axis": "z", "android": [0, 0, 0.4], "expected_sensor": [0, 0, 0.4]}]}


class MountProfileTest(unittest.TestCase):
  def test_complete_observations_produce_runtime_valid_profile(self):
    evidence = observations()
    profile = tool.build_profile(evidence)
    self.assertTrue(tool._POLICY.validate_mount(profile))
    self.assertEqual(profile["schema"], 1)
    self.assertIs(profile["gravity_verified"], True)
    self.assertEqual(profile["rotation_axes_verified"], {"x": True, "y": True, "z": True})
    for field in tool._EVIDENCE_FIELDS:
      self.assertEqual(profile[field], evidence[field])

  def test_evidence_digest_is_canonical_and_binds_observations(self):
    evidence = observations()
    profile = tool.build_profile(evidence)
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    self.assertEqual(profile["evidence_sha256"], hashlib.sha256(canonical).hexdigest())
    reordered = dict(reversed(list(evidence.items())))
    self.assertEqual(tool.build_profile(reordered)["evidence_sha256"], profile["evidence_sha256"])
    evidence["rotation_observations"][0]["android"][1] = -0.201
    self.assertNotEqual(tool.build_profile(evidence)["evidence_sha256"], profile["evidence_sha256"])

  def test_caller_mutations_cannot_change_the_returned_evidence(self):
    evidence = observations()
    original = copy.deepcopy(evidence)
    profile = tool.build_profile(evidence)
    evidence["gravity_observations"][0]["android"][0] = 10
    self.assertEqual(profile["gravity_observations"], original["gravity_observations"])

  def test_missing_metadata_and_evidence_cannot_use_verified_flags(self):
    for field in tool._EVIDENCE_FIELDS:
      evidence = observations()
      del evidence[field]
      evidence.update(gravity_verified=True, rotation_axes_verified={"x": True, "y": True, "z": True})
      with self.subTest(field=field), self.assertRaises(ValueError):
        tool.build_profile(evidence)

  def test_wrong_model_empty_calibration_and_malformed_root_fail(self):
    for evidence in (None, [], "observations", True):
      with self.subTest(evidence=evidence), self.assertRaises(ValueError):
        tool.build_profile(evidence)
    for field, bad in (("device_model", "SM-F926U"), ("calibration_id", " "), ("calibration_id", True)):
      evidence = observations()
      evidence[field] = bad
      with self.subTest(field=field), self.assertRaises(ValueError):
        tool.build_profile(evidence)

  def test_nonfinite_and_boolean_vector_entries_are_rejected(self):
    for field in ("gravity_observations", "rotation_observations"):
      for side in ("android", "expected_sensor"):
        for bad in (True, "0", None, math.nan, math.inf, -math.inf, 10 ** 1000):
          evidence = observations()
          evidence[field][0][side][0] = bad
          with self.subTest(field=field, side=side, bad=bad), self.assertRaises(ValueError):
            tool.build_profile(evidence)

  def test_nonfinite_values_in_extra_metadata_are_rejected(self):
    evidence = observations()
    evidence["note"] = math.nan
    with self.assertRaises(ValueError):
      tool.build_profile(evidence)

  def test_invalid_shapes_and_observation_types_are_rejected(self):
    for field in ("gravity_observations", "rotation_observations"):
      for bad in (None, {}, [], [None, None, None], [True, True, True]):
        evidence = observations()
        evidence[field] = bad
        with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
          tool.build_profile(evidence)
      for bad in ([1, 2], [1, 2, 3, 4], "123", None):
        evidence = observations()
        evidence[field][0]["android"] = bad
        with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
          tool.build_profile(evidence)

  def test_reflection_scaling_and_nonfinite_rotation_fail(self):
    for rotation in ([[-1, 0, 0], [0, 1, 0], [0, 0, 1]],
                     [[2, 0, 0], [0, 1, 0], [0, 0, 1]], [[math.nan, 0, 0], [0, 1, 0], [0, 0, 1]], []):
      evidence = observations()
      evidence["rotation_android_to_sensor"] = rotation
      with self.subTest(rotation=rotation), self.assertRaises(ValueError):
        tool.build_profile(evidence)

  def test_gravity_magnitude_is_checked_on_both_sides(self):
    for side in ("android", "expected_sensor"):
      evidence = observations()
      evidence["gravity_observations"][0][side] = [0, 0, 8.5]
      with self.subTest(side=side), self.assertRaisesRegex(ValueError, "gravity magnitude"):
        tool.build_profile(evidence)

  def test_gravity_direction_and_transform_error_are_checked(self):
    evidence = observations()
    evidence["gravity_observations"][0]["expected_sensor"] = [-9.80665, 0, 0]
    with self.assertRaisesRegex(ValueError, "gravity error"):
      tool.build_profile(evidence)

  def test_repeated_and_coplanar_gravity_directions_cannot_verify(self):
    for angles in ((0, 0, 0), (0, math.pi / 2, math.pi / 4)):
      evidence = observations()
      evidence["gravity_observations"] = []
      for angle in angles:
        x, y = 9.80665 * math.cos(angle), 9.80665 * math.sin(angle)
        evidence["gravity_observations"].append({"android": [y, -x, 0], "expected_sensor": [x, y, 0]})
      with self.subTest(angles=angles), self.assertRaisesRegex(ValueError, "span three"):
        tool.build_profile(evidence)

  def test_independent_direction_can_follow_duplicate_observations(self):
    evidence = observations()
    evidence["gravity_observations"].insert(0, copy.deepcopy(evidence["gravity_observations"][0]))
    self.assertTrue(tool.build_profile(evidence)["gravity_verified"])

  def test_every_angular_axis_must_be_covered(self):
    evidence = observations()
    evidence["rotation_observations"][2] = copy.deepcopy(evidence["rotation_observations"][0])
    with self.assertRaisesRegex(ValueError, "cover all three"):
      tool.build_profile(evidence)

  def test_unknown_axis_and_wrong_axis_direction_are_rejected(self):
    evidence = observations()
    evidence["rotation_observations"][0]["axis"] = "X"
    with self.assertRaisesRegex(ValueError, "axis must"):
      tool.build_profile(evidence)
    evidence = observations()
    evidence["rotation_observations"][0]["axis"] = "z"
    with self.assertRaisesRegex(ValueError, "primarily"):
      tool.build_profile(evidence)

  def test_angular_magnitude_must_be_at_least_point_fifteen(self):
    evidence = observations()
    evidence["rotation_observations"][0].update(android=[0, -0.15, 0], expected_sensor=[0.15, 0, 0])
    self.assertTrue(tool.build_profile(evidence)["rotation_axes_verified"]["x"])
    evidence["rotation_observations"][0].update(android=[0, -0.149, 0], expected_sensor=[0.149, 0, 0])
    with self.assertRaisesRegex(ValueError, "at least 0.15"):
      tool.build_profile(evidence)

  def test_angular_sign_is_checked(self):
    evidence = observations()
    evidence["rotation_observations"][1]["android"] = [0.3, 0, 0]
    with self.assertRaisesRegex(ValueError, "sign does not match"):
      tool.build_profile(evidence)

  def test_absolute_and_relative_angular_error_limits(self):
    for expected, accepted, rejected in ((0.2, 0.229, 0.231), (1.0, 1.049, 1.051)):
      evidence = observations()
      evidence["rotation_observations"][0].update(android=[0, -accepted, 0], expected_sensor=[expected, 0, 0])
      with self.subTest(expected=expected):
        self.assertTrue(tool.build_profile(evidence)["rotation_axes_verified"]["x"])
      evidence["rotation_observations"][0]["android"] = [0, -rejected, 0]
      with self.assertRaisesRegex(ValueError, "angular error"):
        tool.build_profile(evidence)

  def test_a_failed_extra_observation_cannot_be_ignored(self):
    evidence = observations()
    evidence["rotation_observations"].append({"axis": "x", "android": [0, 0, 0], "expected_sensor": [1, 0, 0]})
    with self.assertRaises(ValueError):
      tool.build_profile(evidence)


class MountProfileCliTest(unittest.TestCase):
  def run_cli(self, arguments):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
      return tool.main(arguments)

  def test_cli_writes_a_complete_profile_to_explicit_destination(self):
    with tempfile.TemporaryDirectory() as directory:
      source, output = Path(directory) / "observations.json", Path(directory) / "mount.json"
      source.write_text(json.dumps(observations()), encoding="utf-8")
      self.assertEqual(self.run_cli([str(source), "--output", str(output)]), 0)
      self.assertEqual(json.loads(output.read_text(encoding="utf-8")), tool.build_profile(observations()))
      self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), ["mount.json", "observations.json"])

  def test_no_default_output_is_created(self):
    with self.assertRaises(SystemExit) as failure:
      self.run_cli(["observations.json"])
    self.assertEqual(failure.exception.code, 2)

  def test_validation_failure_preserves_existing_destination(self):
    with tempfile.TemporaryDirectory() as directory:
      source, output = Path(directory) / "observations.json", Path(directory) / "mount.json"
      source.write_text('{"gravity_verified":true}', encoding="utf-8")
      output.write_text("existing", encoding="utf-8")
      with self.assertRaises(SystemExit):
        self.run_cli([str(source), "--output", str(output)])
      self.assertEqual(output.read_text(encoding="utf-8"), "existing")

  def test_failed_atomic_replace_preserves_destination_and_cleans_temporary(self):
    with tempfile.TemporaryDirectory() as directory:
      source, output = Path(directory) / "observations.json", Path(directory) / "mount.json"
      source.write_text(json.dumps(observations()), encoding="utf-8")
      output.write_text("existing", encoding="utf-8")
      with patch.object(tool.os, "replace", side_effect=OSError("simulated disk failure")), self.assertRaises(SystemExit):
        self.run_cli([str(source), "--output", str(output)])
      self.assertEqual(output.read_text(encoding="utf-8"), "existing")
      self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), ["mount.json", "observations.json"])

  def test_input_observations_cannot_be_overwritten(self):
    with tempfile.TemporaryDirectory() as directory:
      source = Path(directory) / "observations.json"
      original = json.dumps(observations())
      source.write_text(original, encoding="utf-8")
      with self.assertRaises(SystemExit):
        self.run_cli([str(source), "--output", str(source)])
      self.assertEqual(source.read_text(encoding="utf-8"), original)

  def test_duplicate_json_fields_and_nonfinite_literals_fail(self):
    for encoded in ('{"device_model":"SM-F926B","device_model":"SM-F926U"}', '{"reading":NaN}', '{"reading":Infinity}'):
      with tempfile.TemporaryDirectory() as directory:
        source, output = Path(directory) / "observations.json", Path(directory) / "mount.json"
        source.write_text(encoded, encoding="utf-8")
        with self.subTest(encoded=encoded), self.assertRaises(SystemExit):
          self.run_cli([str(source), "--output", str(output)])
        self.assertFalse(output.exists())


if __name__ == "__main__":
  unittest.main()
