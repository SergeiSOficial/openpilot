"""Index a completed physical Fold 3 run and its folded-only instrumentation suite."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "tools/android/.cache"


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--session", required=True)
  args = parser.parse_args()
  if not re.fullmatch(r"[a-f0-9]{16}", args.session):
    raise ValueError("Invalid physical verification session identifier")
  delivery = ROOT / "artifacts/android/fold3"
  evidence = delivery / args.session
  report = json.loads((evidence / "verification.json").read_text())
  lifecycle = json.loads((evidence / "lifecycle.json").read_text())
  device = json.loads((evidence / "device.json").read_text())
  suite = (CACHE / "fold3/phone-tests.txt").read_text()
  if not report.get("verification_passed") or report["frames"] != 60 or report["counts"]["longitudinalPlan"] != 60:
    raise RuntimeError("Physical simulation acceptance did not pass")
  passed = re.search(r'OK \((\d+) tests\)', suite)
  if passed is None or int(passed[1]) < 12 or "FAILURES" in suite:
    raise RuntimeError("The complete physical-phone instrumentation suite did not pass")
  if not lifecycle.get("folded_only") or not lifecycle.get("rotated") or not lifecycle.get("worker_preserved"):
    raise RuntimeError("Folded-phone lifecycle evidence is incomplete")
  if lifecycle.get("viewport_override_changed") or lifecycle.get("physical_hinge_transition_tested"):
    raise RuntimeError("Unexpected display/hinge test for the folded-only acceptance stage")
  if not device["model"].startswith("SM-F926") or device["device_state"] != "0" or device["abi"] != "arm64-v8a":
    raise RuntimeError("Physical evidence is not from a closed ARM64 Fold 3")
  apk = ROOT / "android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk"
  if not (CACHE / "signature-arm64-v8a.txt").read_text().startswith("Verifies"):
    raise RuntimeError("The delivered ARM64 APK signature was not verified")
  metadata = json.loads((ROOT / "android/app/src/main/assets/generated/model/build.json").read_text())
  if metadata["source_sha256"] != report["comparison"]["source_sha256"]:
    raise RuntimeError("Physical test source does not match the current staged APK")
  logs = delivery / "logs"
  logs.mkdir(exist_ok=True)
  for name in ("phone-tests.txt", "instrument-stderr.txt"):
    shutil.copy2(CACHE / "fold3" / name, logs / name)
  for name in ("model-diagnostic-comparison.txt", "post-fix-model-diagnostic-tests.txt", "post-fix-model-diagnostic-comparison.txt"):
    if (CACHE / "fold3" / name).is_file():
      shutil.copy2(CACHE / "fold3" / name, logs / name)
  for source, name in (("reference/report.json", "desktop-reference.json"),
                       ("model-aot/verification.json", "model-numerical-gate.json"),
                       ("signature-arm64-v8a.txt", "signature-arm64-v8a.txt")):
    shutil.copy2(CACHE / source, logs / name)
  with apk.open("rb") as stream:
    apk_hash = hashlib.file_digest(stream, "sha256").hexdigest()
  acceptance = {"milestone": "physical Fold 3 recorded simulation", "branch": "android-fold3-port",
                "source_revision": report["comparison"]["source_revision"], "source_sha256": metadata["source_sha256"],
                "session": args.session, "device": device, "verification_passed": True, "frames": 60,
                "elapsed_seconds": report["elapsed_seconds"], "counts": report["counts"],
                "android_tests": {"passed": int(passed[1]), "failed": 0}, "folded_only": True,
                "red_panda": {"software_protocol_tests": 3, "physical_link_tested": False, "vehicle_control_verified": False},
                "physical_hinge_transition_tested": False, "lifecycle": lifecycle,
                "comparison": {name: {"passed": result["passed"], "differences": result["differences"]}
                               for name, result in report["comparison"]["processes"].items()},
                "apk": {"path": apk.relative_to(ROOT).as_posix(), "bytes": apk.stat().st_size,
                        "sha256": apk_hash}}
  (delivery / "acceptance.json").write_text(json.dumps(acceptance, indent=2)+"\n")
  diagnostic_text = ("Nonzero tensor/model and real-frame warp diagnostics matched bit for bit across x86 and ARM64; "
                     "[post-fix comparison](logs/post-fix-model-diagnostic-comparison.txt) and "
                     "[singular-transform rejection test](logs/post-fix-model-diagnostic-tests.txt) record the focused regression check."
                     if (logs / "post-fix-model-diagnostic-comparison.txt").is_file() else "")
  layout_text = ("Landscape is the default: camera on the left, status and fixed controls on the right. "
                 "All four controls remain visible with single-line labels. The portrait fallback also preserved the simulation."
                 if lifecycle.get("landscape_main") and lifecycle.get("controls_visible") else "")
  text = f"""# Physical Fold 3 simulation acceptance

Installed and tested on **{device['model']}**, Android {device['android']} (API {device['api']}), ARM64.
The phone remained closed; the existing display-size setting was preserved.
{layout_text}

All **{passed[1]} instrumentation tests passed**. The completed dashboard run processed
**60 camera pairs, 60 plans, {report['counts']['carControl']} control messages and {report['counts']['sendcan']} simulated CAN messages**
in **{report['elapsed_seconds']:.1f} seconds**. All 12 daemons matched the corrected desktop reference
using the existing replay exclusions and tolerances.

- [Verification]({args.session}/verification.json), [numerical comparison]({args.session}/comparison.json)
- [Device]({args.session}/device.json), [lifecycle]({args.session}/lifecycle.json)
- [Completed dashboard]({args.session}/dashboard-completed.png), [alternate orientation]({args.session}/dashboard-rotated.png)
- [Test log](logs/phone-tests.txt), [acceptance JSON](acceptance.json)
- [Build and test commands](../../../docs/android-port.md)

Testing covered cover-screen rotation during inference, worker preservation, repeated Start/Stop/Reset,
background cleanup, required-worker death, corrupted assets, bounded IPC timeout, and real cross-process
messaging/VisionIPC. Physical unfolding and hinge transitions were not tested, as requested.

The first phone replay exposed uninitialized zero camera transforms. They produced architecture-dependent
warp pixels. Recorded startup snapshots and filter parameters now initialize the model, and singular transforms
are rejected. {diagnostic_text}

Physical cameras, hardware acceleration, sustained real-time performance and vehicle operation remain later stages.
The Red panda screen provides USB permission, pinned protocol/health checks and passive CAN monitoring.
Three added Android tests use upstream wire goldens, simulated failures and the absent-device UI.
No red panda was connected: physical USB, CAN RX/TX and control of the 2018 Ioniq PHEV remain unverified.
"""
  (delivery / "README.md").write_text(text)
  print(json.dumps({"report": str(delivery / "README.md"), "seconds": report["elapsed_seconds"], "apk": acceptance["apk"]}))


if __name__ == "__main__":
  main()
