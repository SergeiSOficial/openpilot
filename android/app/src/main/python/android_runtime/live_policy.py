"""Pure-Python acceptance rules for the Android live pipeline.

These checks validate supplied evidence. They do not establish camera alignment,
device identity, numerical accuracy, or sustained performance by themselves.
"""
import math
import re
import hashlib
import json


DEVICE_MODEL = "SM-F926B"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HASH_KEYS = ("model_sha256", "source_sha256", "native_sha256", "artifact_sha256", "apk_sha256",
              "runtime_sha256", "native_libraries_sha256")
_IDENTITY_KEYS = frozenset((*_HASH_KEYS,
                            "runtime", "driver", "device_fingerprint"))


def _finite_number(value):
  if type(value) not in (int, float):
    return False
  try:
    return math.isfinite(value)
  except OverflowError:
    return False


def _positive_integer(value):
  return type(value) is int and value > 0


class ClockNormalizer:
  """Translate BOOTTIME samples using a contemporaneous MONOTONIC clock pair.

  A clock-offset jump larger than 5 ms invalidates the observing sample and
  starts a new generation. The next call can use the new offset. Callers must
  discard pending frames when generation changes and enforce ordering separately
  for each camera or sensor stream.
  """
  def __init__(self):
    self.generation = 0
    self.discontinuities = 0
    self._offset_ns = None

  def normalize(self, timestamp_boottime_ns, now_boottime_ns, now_monotonic_ns, max_age_ns):
    if not all(_positive_integer(value) for value in
               (timestamp_boottime_ns, now_boottime_ns, now_monotonic_ns, max_age_ns)):
      return None
    offset_ns = now_boottime_ns - now_monotonic_ns
    previous_offset = self._offset_ns
    self._offset_ns = offset_ns
    if previous_offset is not None and abs(offset_ns - previous_offset) > 5_000_000:
      self.generation += 1
      self.discontinuities += 1
      return None
    age_ns = now_boottime_ns - timestamp_boottime_ns
    if age_ns < 0 or age_ns > max_age_ns:
      return None
    normalized = now_monotonic_ns - age_ns
    return normalized if normalized > 0 else None


def _proper_rotation(rotation):
  if not isinstance(rotation, (list, tuple)) or len(rotation) != 3:
    return False
  if any(not isinstance(row, (list, tuple)) or len(row) != 3 for row in rotation):
    return False
  if any(not _finite_number(value) for row in rotation for value in row):
    return False
  if any(abs(value) > 1.000001 for row in rotation for value in row):
    return False
  for i in range(3):
    for j in range(3):
      dot = sum(rotation[i][k] * rotation[j][k] for k in range(3))
      if not math.isclose(dot, float(i == j), rel_tol=0, abs_tol=1e-6):
        return False
  a, b, c = rotation
  determinant = (a[0] * (b[1] * c[2] - b[2] * c[1])
                 - a[1] * (b[0] * c[2] - b[2] * c[0])
                 + a[2] * (b[0] * c[1] - b[1] * c[0]))
  return math.isclose(determinant, 1, rel_tol=0, abs_tol=1e-6)


def validate_mount(profile):
  """Require device-specific calibration and verified axes, with a proper rotation."""
  if not isinstance(profile, dict) or type(profile.get("schema")) is not int or profile["schema"] != 1:
    return False
  calibration_id = profile.get("calibration_id")
  axes = profile.get("rotation_axes_verified")
  return (isinstance(calibration_id, str) and bool(calibration_id.strip())
          and profile.get("device_model") == DEVICE_MODEL
          and profile.get("gravity_verified") is True
          and isinstance(axes, dict) and all(axes.get(axis) is True for axis in ("x", "y", "z"))
          and _proper_rotation(profile.get("rotation_android_to_sensor")))


def transform(vector, rotation):
  """Apply the Android-to-sensor rotation; malformed inputs raise ValueError."""
  if not _proper_rotation(rotation):
    raise ValueError("Expected a finite proper 3x3 rotation")
  if (not isinstance(vector, (list, tuple)) or len(vector) != 3
      or not all(_finite_number(value) for value in vector)):
    raise ValueError("Expected a finite three-axis vector")
  result = [sum(row[index] * vector[index] for index in range(3)) for row in rotation]
  if not all(_finite_number(value) for value in result):
    raise ValueError("Transformed vector is not finite")
  return result


def _valid_identity(identity):
  if not isinstance(identity, dict) or not _IDENTITY_KEYS.issubset(identity):
    return False
  if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip()
         for key, value in identity.items()):
    return False
  return all(_SHA256.fullmatch(identity[key]) is not None for key in _HASH_KEYS)


def execution_bindings(cache,apk_path=None):
  """Bind qualification to actual loaded bytes, rejecting incomplete claims."""
  if not isinstance(cache,dict) or cache.get('enabled') is not True:raise ValueError('Unverified GPU runtime cache')
  runtime=cache.get('runtime_sha256');loaded=cache.get('loaded_files')
  if (not isinstance(runtime,dict) or not {'android_runtime.gpu','android_runtime.gpu_artifact','tinygrad.runtime.ops_cl'}.issubset(runtime)
      or any(not isinstance(k,str) or not k or not isinstance(v,str) or _SHA256.fullmatch(v) is None for k,v in runtime.items())):
    raise ValueError('Incomplete loaded runtime identity')
  if not isinstance(loaded,dict):raise ValueError('Missing loaded native/APK identities')
  native={};apks={}
  for path,claim in loaded.items():
    if not isinstance(path,str):raise ValueError('Invalid loaded file path')
    name=path.rsplit('/',1)[-1]
    if name!='base.apk' and not name.endswith('.so'):continue
    if not isinstance(claim,dict) or not isinstance(claim.get('sha256'),str) or _SHA256.fullmatch(claim['sha256']) is None:
      raise ValueError('Unreadable loaded file: '+name)
    if name=='base.apk':apks[path]=claim['sha256']
    else:
      if name in native and native[name]!=claim['sha256']:raise ValueError('Ambiguous native library: '+name)
      native[name]=claim['sha256']
  if ((apk_path is None and len(apks)!=1) or (apk_path is not None and apk_path not in apks)
      or not {'libOpenCL.so','libopenpilot_ipc.so','libopenpilot_kernels.so'}.issubset(native)):
    raise ValueError('Incomplete loaded accelerator/APK identities')
  def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  return {'apk_sha256':apks[apk_path] if apk_path is not None else next(iter(apks.values())),
          'runtime_sha256':digest(runtime),'native_libraries_sha256':digest(native)}


def qualification_passed(certificate, identity):
  """Check a certificate against the complete current artifact/device identity.

  Reasons name the failed field so callers can report why promotion is withheld.
  Certificates need independently collected numerical and sustained device data.
  """
  if not isinstance(certificate, dict):
    return False, "invalid_certificate"
  if type(certificate.get("schema")) is not int or certificate["schema"] != 1:
    return False, "schema"
  if (not _valid_identity(identity) or not _valid_identity(certificate.get("identity"))
      or certificate["identity"] != identity):
    return False, "identity"
  if certificate.get("physical_device") != DEVICE_MODEL:
    return False, "physical_device"
  for field in ("accelerated", "numerical_passed", "exact_images"):
    if certificate.get(field) is not True:
      return False, field
  if (type(certificate.get("sequence_frames")) is not int or not _finite_number(certificate["sequence_frames"])
      or certificate["sequence_frames"] < 60):
    return False, "sequence_frames"
  for field, expected in (("rtol", 1e-4), ("atol", 1e-5)):
    if not _finite_number(certificate.get(field)) or certificate[field] != expected:
      return False, field
  for field, minimum, maximum in (("sustained_seconds", 1200, math.inf),
                                  ("fresh_fps", 19.5, math.inf),
                                  ("cycle_p95_ms", 0, 50),
                                  ("max_pair_skew_ms", 0, 10)):
    value = certificate.get(field)
    if not _finite_number(value) or not minimum <= value <= maximum:
      return False, field
  return True, "qualified"


def thermal_action(status):
  """Map Android thermal status to a fail-closed pipeline action."""
  if type(status) is not int or status < 0:
    return "stop"
  if status <= 2:
    return "running"
  return "paused" if status == 3 else "stop"


class InputHealth:
  """Pause immediately on stale inputs; terminate only a persistent outage."""
  def __init__(self):
    self.unhealthy_since = None

  def update(self, healthy, now):
    if not _finite_number(now):return "failed"
    if healthy is True:
      self.unhealthy_since = None
      return "healthy"
    if self.unhealthy_since is None:self.unhealthy_since = now
    return "failed" if now-self.unhealthy_since >= 2 else "degraded"
