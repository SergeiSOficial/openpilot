"""Build a mount profile from recorded physical observations, without a device connection.

Usage: py -3.12 -B tools/android/mount_profile.py observations.json --output mount-calibration.json

Gravity vectors use m/s^2; angular vectors use rad/s. Record at least three
independent gravity directions and rotations about each sensor-frame axis.
Expected angular vectors must put at least 90% of their magnitude on the named
axis. A normalized gravity direction needs a residual above 1e-3 to add rank.
The tool checks consistency of supplied observations; collect them physically.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[2]
_POLICY_PATH = ROOT / "android/app/src/main/python/android_runtime/live_policy.py"
_SPEC = importlib.util.spec_from_file_location("android_mount_live_policy", _POLICY_PATH)
_POLICY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_POLICY)

_EVIDENCE_FIELDS = ("device_model", "calibration_id", "rotation_android_to_sensor",
                    "gravity_observations", "rotation_observations")


def _vector(value, label):
  if not isinstance(value, list) or len(value) != 3 or any(type(item) not in (int, float) for item in value):
    raise ValueError(f"{label}: expected a finite three-axis numeric vector")
  try:
    result = [float(item) for item in value]
  except OverflowError as error:
    raise ValueError(f"{label}: vector is outside the finite numeric range") from error
  if not all(math.isfinite(item) for item in result):
    raise ValueError(f"{label}: expected finite vector values")
  return result


def _observations(evidence, field, minimum):
  entries = evidence.get(field)
  if not isinstance(entries, list) or len(entries) < minimum or any(not isinstance(entry, dict) for entry in entries):
    raise ValueError(f"{field}: expected at least {minimum} observation objects")
  return entries


def _distance(actual, expected):
  return math.hypot(*(left - right for left, right in zip(actual, expected)))


def _adds_direction(basis, vector):
  length = math.hypot(*vector)
  residual = [value / length for value in vector]
  for direction in basis:
    projection = sum(left * right for left, right in zip(residual, direction))
    residual = [value - projection * unit for value, unit in zip(residual, direction)]
  norm = math.hypot(*residual)
  if norm > 1e-3:
    basis.append([value / norm for value in residual])


def build_profile(observations):
  """Validate supplied physical evidence and return the persistable profile.

  evidence_sha256 binds canonical UTF-8 JSON (sorted keys, compact separators,
  ensure_ascii=True) of the five retained evidence fields. Caller-supplied
  verification flags cannot replace the observation checks.
  """
  if not isinstance(observations, dict):
    raise ValueError("Expected a JSON observation object")
  try:
    # A JSON snapshot prevents later caller mutations and rejects NaNs anywhere.
    snapshot = json.loads(json.dumps(observations, allow_nan=False, sort_keys=True))
  except (ValueError, TypeError, OverflowError) as error:
    raise ValueError("Observations must contain finite JSON values") from error
  if any(field not in snapshot for field in _EVIDENCE_FIELDS):
    raise ValueError("Missing device, calibration, rotation, or physical observations")
  evidence = {field: snapshot[field] for field in _EVIDENCE_FIELDS}
  if evidence["device_model"] != "SM-F926B":
    raise ValueError("Physical observations must be for device_model SM-F926B")
  calibration_id = evidence["calibration_id"]
  if not isinstance(calibration_id, str) or not calibration_id.strip():
    raise ValueError("calibration_id must be a nonempty measurement identifier")
  rotation = evidence["rotation_android_to_sensor"]
  # Validates finite dimensions, orthonormality and determinant +1 exactly as runtime does.
  _POLICY.transform([0, 0, 0], rotation)

  basis = []
  for index, observation in enumerate(_observations(evidence, "gravity_observations", 3)):
    label = f"gravity_observations[{index}]"
    android = _vector(observation.get("android"), label + ".android")
    expected = _vector(observation.get("expected_sensor"), label + ".expected_sensor")
    if any(abs(math.hypot(*vector) - 9.80665) > 0.5 for vector in (android, expected)):
      raise ValueError(label + ": gravity magnitude must be within 0.5 m/s^2 of 9.80665")
    if _distance(_POLICY.transform(android, rotation), expected) > 0.35:
      raise ValueError(label + ": transformed gravity error exceeds 0.35 m/s^2")
    if len(basis) < 3:
      _adds_direction(basis, expected)
  if len(basis) != 3:
    raise ValueError("Expected gravity directions must span three dimensions")

  verified_axes = {axis: False for axis in ("x", "y", "z")}
  for index, observation in enumerate(_observations(evidence, "rotation_observations", 3)):
    label = f"rotation_observations[{index}]"
    axis = observation.get("axis")
    if not isinstance(axis, str) or axis not in verified_axes:
      raise ValueError(label + ": axis must be x, y, or z")
    android = _vector(observation.get("android"), label + ".android")
    expected = _vector(observation.get("expected_sensor"), label + ".expected_sensor")
    length = math.hypot(*expected)
    if not math.isfinite(length) or length < 0.15:
      raise ValueError(label + ": expected angular magnitude must be at least 0.15 rad/s")
    axis_index = ("x", "y", "z").index(axis)
    if abs(expected[axis_index]) < 0.9 * length:
      raise ValueError(label + ": expected rotation must primarily follow its named axis")
    actual = _POLICY.transform(android, rotation)
    if actual[axis_index] == 0 or (actual[axis_index] > 0) != (expected[axis_index] > 0):
      raise ValueError(label + ": transformed angular axis sign does not match")
    if _distance(actual, expected) > max(0.03, 0.05 * length):
      raise ValueError(label + ": transformed angular error exceeds tolerance")
    verified_axes[axis] = True
  if not all(verified_axes.values()):
    raise ValueError("Rotation observations must cover all three axes")

  encoded = json.dumps(evidence, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
  profile = {"schema": 1, **evidence, "gravity_verified": True, "rotation_axes_verified": verified_axes,
             "evidence_sha256": hashlib.sha256(encoded).hexdigest()}
  if not _POLICY.validate_mount(profile):
    raise ValueError("Measured profile does not satisfy runtime mount policy")
  return profile


def _no_duplicate_keys(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      raise ValueError("Duplicate JSON field: " + key)
    result[key] = value
  return result


def _no_nonfinite_constant(value):
  raise ValueError("Nonfinite JSON constant: " + value)


def _write_atomic(path, profile):
  temporary = None
  try:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix="." + path.name + ".", suffix=".tmp", delete=False) as output:
      temporary = Path(output.name)
      json.dump(profile, output, allow_nan=False, indent=2)
      output.write("\n")
      output.flush()
      os.fsync(output.fileno())
    os.replace(temporary, path)
  finally:
    if temporary is not None:
      temporary.unlink(missing_ok=True)


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("input", type=Path, help="JSON file containing recorded physical observations")
  parser.add_argument("--output", type=Path, required=True, help="explicit destination profile path")
  arguments = parser.parse_args(argv)
  try:
    if arguments.input.resolve() == arguments.output.resolve():
      raise ValueError("Input observations and output profile must use different files")
    observations = json.loads(arguments.input.read_text(encoding="utf-8"),
                              object_pairs_hook=_no_duplicate_keys, parse_constant=_no_nonfinite_constant)
    profile = build_profile(observations)
    _write_atomic(arguments.output, profile)
  except (OSError, ValueError) as error:
    parser.error(str(error))
  print(f"Wrote measured mount profile: {arguments.output}")
  return 0


if __name__ == "__main__":
  main()
