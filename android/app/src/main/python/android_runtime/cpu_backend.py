"""Select only a byte-pinned CPU implementation qualified on Android.

The optional certificate is extracted from the installed APK. Absence keeps the
existing desktop/device path. Corruption fails closed rather than selecting an
unverified native implementation.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform


def select(original):
  original=Path(original)
  model_root=os.environ.get("OPENPILOT_ANDROID_MODELS_ROOT")
  if original.name!="libopenpilot_kernels.so" or not model_root or not Path("/system/bin/app_process").exists():
    return str(original)
  root=Path(model_root); certificate=root/"cpu-qualification.json"
  if not certificate.exists():return str(original)
  qualification=json.loads(certificate.read_text())
  if qualification.get("schema")!=1 or not qualification.get("passed") or qualification.get("frames")!=60:
    raise RuntimeError("Invalid CPU qualification certificate")
  machine=platform.machine()
  abi="arm64-v8a" if machine in ("aarch64","arm64") else "x86_64" if machine=="x86_64" else None
  if abi not in qualification["libraries_sha256"]:return str(original)
  from java import jclass
  device=str(jclass("android.os.Build").MODEL)
  if abi=="arm64-v8a" and not device.startswith("SM-F926"):return str(original)
  manifest=json.loads((root/"manifest.json").read_text())["sha256"]
  for name,expected in qualification["model_assets_sha256"].items():
    if manifest.get(name)!=expected:raise RuntimeError("CPU qualification is for different model assets: "+name)
  if json.loads((root/"provenance.json").read_text())["model_sha256"]!=qualification["model_sha256"]:
    raise RuntimeError("CPU qualification is for a different driving model")
  name=qualification["library"]
  if name!="libopenpilot_kernels_parallel.so":raise RuntimeError("Unapproved qualified CPU library")
  candidate=original.parent/name
  with candidate.open("rb") as stream:actual=hashlib.file_digest(stream,"sha256").hexdigest()
  if actual!=qualification["libraries_sha256"][abi]:raise RuntimeError("Qualified CPU library hash differs")
  library=ctypes.CDLL(str(candidate))
  library.op_parallel_set_core_policy.argtypes=[ctypes.c_int]
  library.op_parallel_set_core_policy(1 if abi=="arm64-v8a" else 0)
  if abi=="arm64-v8a":os.sched_setaffinity(0,{7})
  session=os.environ.get("OPENPILOT_ANDROID_ROOT")
  if session:
    (Path(session)/"cpu-backend.json").write_text(json.dumps({"backend":"CPU_parallel","abi":abi,"device":device,
      "library_sha256":actual,"certificate_sha256":hashlib.sha256(certificate.read_bytes()).hexdigest(),
      "reference_frames":60,"rtol":1e-4,"atol":1e-5,"caller_affinity":sorted(os.sched_getaffinity(0))},indent=2)+"\n")
  return str(candidate)
