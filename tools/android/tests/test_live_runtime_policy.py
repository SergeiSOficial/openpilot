"""Reviewed stdlib-only policy tests; no native runtime, subprocesses or devices."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[3] / "android/app/src/main/python/android_runtime/live_policy.py"
spec = importlib.util.spec_from_file_location("android_live_runtime_policy", SOURCE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

IDENTITY_ROTATION = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
QUARTER_TURN = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]


def mount():
  return {"schema": 1, "calibration_id": "measured-fold3-mount-01", "device_model": "SM-F926B",
          "rotation_android_to_sensor": copy.deepcopy(QUARTER_TURN), "gravity_verified": True,
          "rotation_axes_verified": {"x": True, "y": True, "z": True}}


def identity():
  return {"model_sha256": "a" * 64, "source_sha256": "b" * 64, "native_sha256": "c" * 64,
          "artifact_sha256":"d"*64,"apk_sha256":"e"*64,"runtime_sha256":"f"*64,"native_libraries_sha256":"0"*64,
          "runtime": "CL", "driver": "OpenCL driver build", "device_fingerprint": "Samsung/firmware/build"}


def certificate():
  return {"schema": 1, "identity": identity(), "physical_device": "SM-F926B", "accelerated": True,
          "numerical_passed": True, "exact_images": True, "sequence_frames": 60, "rtol": 1e-4,
          "atol": 1e-5, "sustained_seconds": 1200, "fresh_fps": 19.5, "cycle_p95_ms": 50,
          "max_pair_skew_ms": 10}


class ClockNormalizerTest(unittest.TestCase):
  def setUp(self):
    self.clock = policy.ClockNormalizer()

  def test_converts_boottime_offset_and_includes_maximum_age(self):
    self.assertEqual(self.clock.normalize(2_900_000_000, 3_000_000_000, 1_000_000_000, 100_000_000),
                     900_000_000)
    self.assertEqual((self.clock.generation, self.clock.discontinuities), (0, 0))

  def test_fresh_sample_maps_to_now(self):
    self.assertEqual(self.clock.normalize(3_000_000_000, 3_000_000_000, 1_000_000_000, 1), 1_000_000_000)

  def test_rejects_a_single_nanosecond_future_or_too_old(self):
    for timestamp in (3_000_000_001, 2_899_999_999):
      with self.subTest(timestamp=timestamp):
        self.assertIsNone(self.clock.normalize(timestamp, 3_000_000_000, 1_000_000_000, 100_000_000))

  def test_rejects_malformed_nonpositive_and_boolean_inputs(self):
    for position in range(4):
      for bad in (0, -1, True, False, None, "100", 1.0, math.nan, math.inf):
        arguments = [3_000_000_000, 3_000_000_000, 1_000_000_000, 100_000_000]
        arguments[position] = bad
        with self.subTest(position=position, bad=bad):
          self.assertIsNone(self.clock.normalize(*arguments))

  def test_rejects_normalized_nonpositive_timestamp(self):
    self.assertIsNone(self.clock.normalize(100, 300, 200, 200))
    self.assertIsNone(self.clock.normalize(99, 300, 200, 201))

  def test_streams_can_arrive_in_opposite_timestamp_order(self):
    self.assertEqual(self.clock.normalize(2_950_000_000, 3_000_000_000, 1_000_000_000, 100_000_000), 950_000_000)
    self.assertEqual(self.clock.normalize(2_925_000_000, 3_000_000_000, 1_000_000_000, 100_000_000), 925_000_000)

  def test_exact_five_millisecond_offset_change_is_allowed(self):
    self.clock.normalize(3_000_000_000, 3_000_000_000, 1_000_000_000, 100_000_000)
    self.assertEqual(self.clock.normalize(3_005_000_000, 3_005_000_000, 1_000_000_000, 100_000_000), 1_000_000_000)
    self.assertEqual(self.clock.generation, 0)

  def test_suspend_offset_change_invalidates_observing_sample_then_recovers(self):
    self.clock.normalize(3_000_000_000, 3_000_000_000, 1_000_000_000, 100_000_000)
    self.assertIsNone(self.clock.normalize(4_000_000_000, 4_000_000_000, 1_000_000_000, 100_000_000))
    self.assertEqual((self.clock.generation, self.clock.discontinuities), (1, 1))
    self.assertEqual(self.clock.normalize(4_010_000_000, 4_010_000_000, 1_010_000_000, 100_000_000), 1_010_000_000)
    self.assertEqual(self.clock.generation, 1)

  def test_clock_offset_jump_in_either_direction_is_rejected(self):
    self.clock.normalize(3_000_000_000, 3_000_000_000, 1_000_000_000, 100_000_000)
    self.assertIsNone(self.clock.normalize(3_005_000_001, 3_005_000_001, 1_000_000_000, 100_000_000))
    self.assertIsNone(self.clock.normalize(3_000_000_000, 3_000_000_000, 1_000_000_000, 100_000_000))
    self.assertEqual((self.clock.generation, self.clock.discontinuities), (2, 2))

  def test_invalid_input_does_not_change_clock_offset(self):
    self.clock.normalize(3_000_000_000, 3_000_000_000, 1_000_000_000, 100_000_000)
    self.assertIsNone(self.clock.normalize(True, 4_000_000_000, 1_000_000_000, 100_000_000))
    self.assertEqual(self.clock.normalize(3_000_000_000, 3_000_000_000, 1_000_000_000, 100_000_000), 1_000_000_000)
    self.assertEqual(self.clock.generation, 0)


class MountPolicyTest(unittest.TestCase):
  def test_measured_rotation_and_identity_rotation_are_valid(self):
    self.assertTrue(policy.validate_mount(mount()))
    profile = mount()
    profile["rotation_android_to_sensor"] = IDENTITY_ROTATION
    self.assertTrue(policy.validate_mount(profile))

  def test_valid_flag_alone_never_qualifies_a_mount(self):
    self.assertFalse(policy.validate_mount({"valid": True}))

  def test_every_mount_evidence_field_is_required(self):
    for key in mount():
      profile = mount()
      del profile[key]
      with self.subTest(key=key):
        self.assertFalse(policy.validate_mount(profile))

  def test_schema_device_and_calibration_are_checked(self):
    for field, value in (("schema", True), ("schema", 2), ("schema", 1.0), ("device_model", "SM-F926U"),
                         ("calibration_id", " "), ("calibration_id", 1), ("gravity_verified", 1)):
      profile = mount()
      profile[field] = value
      with self.subTest(field=field, value=value):
        self.assertFalse(policy.validate_mount(profile))

  def test_axis_verification_requires_all_three_explicit_booleans(self):
    for axis in ("x", "y", "z"):
      for value in (False, 1, "true", None):
        profile = mount()
        profile["rotation_axes_verified"][axis] = value
        with self.subTest(axis=axis, value=value):
          self.assertFalse(policy.validate_mount(profile))
      profile = mount()
      del profile["rotation_axes_verified"][axis]
      self.assertFalse(policy.validate_mount(profile))

  def test_rejects_scaling_shear_reflection_and_invalid_matrix_shape(self):
    matrices = (None, [], [1, 2, 3], [[1, 0], [0, 1], [0, 0]],
                [[2, 0, 0], [0, 1, 0], [0, 0, 1]], [[1, 1, 0], [0, 1, 0], [0, 0, 1]],
                [[-1, 0, 0], [0, 1, 0], [0, 0, 1]])
    for matrix in matrices:
      profile = mount()
      profile["rotation_android_to_sensor"] = matrix
      with self.subTest(matrix=matrix):
        self.assertFalse(policy.validate_mount(profile))

  def test_rejects_nonfinite_boolean_and_non_numeric_rotation_entries(self):
    for bad in (math.nan, math.inf, -math.inf, True, "1", None, 10 ** 1000):
      profile = mount()
      profile["rotation_android_to_sensor"][0][0] = bad
      with self.subTest(bad=bad):
        self.assertFalse(policy.validate_mount(profile))

  def test_transform_respects_axis_order_and_sign(self):
    self.assertEqual(policy.transform([1, 2, 3], QUARTER_TURN), [-2, 1, 3])
    self.assertEqual(policy.transform([0, 0, 9.81], QUARTER_TURN), [0, 0, 9.81])

  def test_arbitrary_proper_rotation_preserves_vector_length(self):
    angle = math.pi / 7
    rotation = [[math.cos(angle), 0, math.sin(angle)], [0, 1, 0], [-math.sin(angle), 0, math.cos(angle)]]
    vector = [2, -3, 5]
    result = policy.transform(vector, rotation)
    self.assertAlmostEqual(sum(value * value for value in result), 38)

  def test_transform_rejects_bad_vectors_and_improper_rotation(self):
    for vector in (None, [], [1, 2], [1, 2, 3, 4], [True, 0, 0], [math.nan, 0, 0], [0, math.inf, 0], "123"):
      with self.subTest(vector=vector), self.assertRaises(ValueError):
        policy.transform(vector, IDENTITY_ROTATION)
    with self.assertRaises(ValueError):
      policy.transform([1, 2, 3], [[-1, 0, 0], [0, 1, 0], [0, 0, 1]])


class ExecutionBindingsTest(unittest.TestCase):
  def claims(self):
    return {'enabled':True,'runtime_sha256':{'android_runtime.gpu':'a'*64,'android_runtime.gpu_artifact':'b'*64,
                                           'tinygrad.runtime.ops_cl':'c'*64},
            'loaded_files':{'/data/app/current/base.apk':{'sha256':'d'*64},
                            '/vendor/lib64/libOpenCL.so':{'sha256':'e'*64},
                            '/data/app/current/lib/arm64/libopenpilot_ipc.so':{'sha256':'f'*64},
                            '/data/app/current/lib/arm64/libopenpilot_kernels.so':{'sha256':'0'*64}}}

  def test_actual_bytes_are_bound_independently_of_map_order_and_install_directory(self):
    original=self.claims();expected=policy.execution_bindings(original)
    reordered=copy.deepcopy(original);reordered['runtime_sha256']=dict(reversed(list(reordered['runtime_sha256'].items())))
    reordered['loaded_files']={key.replace('/current/','/reinstalled/'):value for key,value in reversed(list(reordered['loaded_files'].items()))}
    self.assertEqual(policy.execution_bindings(reordered),expected)
    for mapping,key in (('runtime_sha256','android_runtime.gpu'),('loaded_files','/vendor/lib64/libOpenCL.so'),
                        ('loaded_files','/data/app/current/base.apk')):
      changed=self.claims()
      if mapping=='runtime_sha256':changed[mapping][key]='9'*64
      else:changed[mapping][key]['sha256']='9'*64
      self.assertNotEqual(policy.execution_bindings(changed),expected)

  def test_missing_unreadable_or_ambiguous_native_and_apk_claims_are_rejected(self):
    for key in self.claims()['loaded_files']:
      for claim in (None,{'unavailable':'PermissionError'},{'sha256':'g'*64}):
        bad=self.claims()
        if claim is None:del bad['loaded_files'][key]
        else:bad['loaded_files'][key]=claim
        with self.subTest(key=key,claim=claim):
          with self.assertRaises(ValueError):policy.execution_bindings(bad)
    bad=self.claims();bad['loaded_files']['/other/libOpenCL.so']={'sha256':'1'*64}
    with self.assertRaises(ValueError):policy.execution_bindings(bad)
    bad=self.claims();bad['loaded_files']['/other/base.apk']={'sha256':'d'*64}
    with self.assertRaises(ValueError):policy.execution_bindings(bad)
    self.assertEqual(policy.execution_bindings(bad,'/data/app/current/base.apk'),policy.execution_bindings(self.claims()))
    with self.assertRaises(ValueError):policy.execution_bindings(bad,'/wrong/base.apk')

  def test_unverified_or_incomplete_runtime_is_rejected(self):
    for changed in (None,{}, {'enabled':False}, {'enabled':1}, {'runtime_sha256':{}},
                    {'runtime_sha256':{'android_runtime.gpu':'a'*64}}):
      bad=changed if not changed else {**self.claims(),**changed}
      with self.subTest(changed=changed):
        with self.assertRaises(ValueError):policy.execution_bindings(bad)


class QualificationPolicyTest(unittest.TestCase):
  def test_exact_boundary_metrics_pass(self):
    self.assertEqual(policy.qualification_passed(certificate(), identity()), (True, "qualified"))

  def test_more_than_sixty_frames_is_allowed(self):
    proof = certificate()
    proof["sequence_frames"] = 61
    self.assertTrue(policy.qualification_passed(proof, identity())[0])

  def test_each_required_certificate_field_is_required(self):
    for field in certificate():
      proof = certificate()
      del proof[field]
      with self.subTest(field=field):
        self.assertFalse(policy.qualification_passed(proof, identity())[0])

  def test_non_mapping_certificate_and_schema_types_fail(self):
    for proof in (None, [], "passed", True):
      with self.subTest(proof=proof):
        self.assertEqual(policy.qualification_passed(proof, identity()), (False, "invalid_certificate"))
    for schema in (True, False, 1.0, "1", 2):
      proof = certificate()
      proof["schema"] = schema
      self.assertEqual(policy.qualification_passed(proof, identity()), (False, "schema"))

  def test_every_identity_binding_must_match(self):
    for key in identity():
      current = identity()
      current[key] = "9" * 64 if key.endswith("_sha256") else "changed"
      with self.subTest(key=key):
        self.assertEqual(policy.qualification_passed(certificate(), current), (False, "identity"))

  def test_unknown_missing_empty_and_malformed_identities_fail(self):
    for current in (None, {}, {"runtime": "CL"}, [], True):
      proof = certificate()
      proof["identity"] = current
      with self.subTest(identity=current):
        self.assertEqual(policy.qualification_passed(proof, current), (False, "identity"))
    for key in identity():
      for bad in (None, " ", True, 1):
        current = identity()
        current[key] = bad
        proof = certificate()
        proof["identity"] = copy.deepcopy(current)
        with self.subTest(key=key, bad=bad):
          self.assertEqual(policy.qualification_passed(proof, current), (False, "identity"))

  def test_required_identity_keys_cannot_be_omitted_from_both_sides(self):
    for key in identity():
      current = identity()
      del current[key]
      proof = certificate()
      proof["identity"] = current.copy()
      with self.subTest(key=key):
        self.assertEqual(policy.qualification_passed(proof, current), (False, "identity"))

  def test_hashes_require_lowercase_sha256(self):
    for field in policy._HASH_KEYS:
      for value in ("a" * 63, "a" * 65, "g" * 64, "A" * 64, "a" * 64 + "\n"):
        current = identity()
        current[field] = value
        proof = certificate()
        proof["identity"] = current.copy()
        with self.subTest(field=field, value=value):
          self.assertEqual(policy.qualification_passed(proof, current), (False, "identity"))

  def test_additional_identity_fields_are_also_exactly_bound(self):
    proof = certificate()
    proof["identity"]["compiler"] = "one"
    self.assertEqual(policy.qualification_passed(proof, identity()), (False, "identity"))
    current = identity()
    current["compiler"] = "one"
    self.assertTrue(policy.qualification_passed(proof, current)[0])
    current["compiler"] = "two"
    self.assertEqual(policy.qualification_passed(proof, current), (False, "identity"))

  def test_physical_device_is_exact(self):
    proof = certificate()
    proof["physical_device"] = "SM-F926U"
    self.assertEqual(policy.qualification_passed(proof, identity()), (False, "physical_device"))

  def test_acceleration_numerical_and_image_evidence_require_true(self):
    for field in ("accelerated", "numerical_passed", "exact_images"):
      for value in (False, 1, "true", None):
        proof = certificate()
        proof[field] = value
        with self.subTest(field=field, value=value):
          self.assertEqual(policy.qualification_passed(proof, identity()), (False, field))

  def test_tolerance_cannot_be_relaxed_or_relabelled(self):
    for field, values in (("rtol", (1e-3, 1e-5)), ("atol", (1e-4, 1e-6))):
      for value in values:
        proof = certificate()
        proof[field] = value
        with self.subTest(field=field, value=value):
          self.assertEqual(policy.qualification_passed(proof, identity()), (False, field))

  def test_performance_and_sequence_failure_boundaries(self):
    for field, value in (("sequence_frames", 59), ("sequence_frames", 60.0), ("sustained_seconds", 1199.999),
                         ("fresh_fps", 19.499), ("cycle_p95_ms", 50.001), ("max_pair_skew_ms", 10.001),
                         ("cycle_p95_ms", -0.001), ("max_pair_skew_ms", -0.001)):
      proof = certificate()
      proof[field] = value
      with self.subTest(field=field, value=value):
        self.assertEqual(policy.qualification_passed(proof, identity()), (False, field))

  def test_every_numeric_metric_rejects_nonfinite_boolean_and_text_values(self):
    for field in ("sequence_frames", "rtol", "atol", "sustained_seconds", "fresh_fps", "cycle_p95_ms", "max_pair_skew_ms"):
      for bad in (math.nan, math.inf, -math.inf, True, False, "60", None, 10 ** 1000):
        proof = certificate()
        proof[field] = bad
        with self.subTest(field=field, bad=bad):
          self.assertEqual(policy.qualification_passed(proof, identity()), (False, field))


class ThermalPolicyTest(unittest.TestCase):
  def test_statuses_cover_running_pause_and_stop(self):
    for status, expected in ((0, "running"), (1, "running"), (2, "running"), (3, "paused"),
                             (4, "stop"), (5, "stop"), (6, "stop"), (100, "stop")):
      with self.subTest(status=status):
        self.assertEqual(policy.thermal_action(status), expected)

  def test_malformed_thermal_status_fails_closed(self):
    for status in (-1, None, True, False, 2.0, "2", math.nan, math.inf):
      with self.subTest(status=status):
        self.assertEqual(policy.thermal_action(status), "stop")


class InputHealthTest(unittest.TestCase):
  def test_short_input_gap_pauses_and_recovers(self):
    health=policy.InputHealth()
    self.assertEqual(health.update(False,10),"degraded")
    self.assertEqual(health.update(False,11.9),"degraded")
    self.assertEqual(health.update(True,12),"healthy")
    self.assertIsNone(health.unhealthy_since)

  def test_persistent_input_gap_fails_at_bound(self):
    health=policy.InputHealth()
    self.assertEqual(health.update(None,10),"degraded")
    self.assertEqual(health.update(False,12),"failed")

  def test_bad_clock_cannot_certify_health(self):
    self.assertEqual(policy.InputHealth().update(True,float("nan")),"failed")


if __name__ == "__main__":
  unittest.main()
