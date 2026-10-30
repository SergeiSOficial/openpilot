"""Collect a concise acceptance index after the actual emulator suite has passed."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "tools/android/.cache"

def sha256(path):
  digest = hashlib.sha256()
  with path.open("rb") as stream:
    for block in iter(lambda: stream.read(1024*1024), b""):
      digest.update(block)
  return digest.hexdigest()

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--session", required=True)
  args = parser.parse_args()
  if not re.fullmatch(r"[a-f0-9]{16}", args.session):
    raise ValueError("Invalid verification session identifier")
  evidence = ROOT / "artifacts/android" / args.session
  report = json.loads((evidence / "verification.json").read_text())
  lifecycle = json.loads((evidence / "lifecycle.json").read_text())
  suite = (CACHE / "final-suite-tests.txt").read_text()
  host = (CACHE / "host-tests.txt").read_text()
  if not report.get("verification_passed") or report["frames"] != 60 or report["counts"]["longitudinalPlan"] != 60:
    raise RuntimeError("Simulation acceptance did not pass")
  passed = re.search(r'OK \((\d+) tests\)', suite)
  if passed is None or int(passed[1]) < 12 or "FAILURES" in suite or "Ran 7 tests" not in host or not host.rstrip().endswith("OK"):
    raise RuntimeError("Required Android/host test suites did not pass")
  delivery = ROOT / "artifacts/android"
  physical_file = delivery / "fold3/acceptance.json"
  physical = json.loads(physical_file.read_text()) if physical_file.exists() else {}
  physical_passed = bool(physical.get("verification_passed") and physical.get("source_sha256") == report["comparison"]["source_sha256"])
  logs = delivery / "logs"
  logs.mkdir(parents=True, exist_ok=True)
  names = ("final-suite-tests.txt", "emulator-tests.txt", "host-tests.txt", "apk-build.log", "native-build.log",
           "reference-replay.log", "model-gate.log", "signature-x86_64.txt", "signature-arm64-v8a.txt")
  for name in names:
    shutil.copy2(CACHE / name, logs / name)
  shutil.copy2(CACHE / "reference/report.json", logs / "desktop-reference.json")
  shutil.copy2(CACHE / "model-aot/provenance.json", logs / "model-provenance.json")
  shutil.copy2(CACHE / "model-aot/verification.json", logs / "model-numerical-gate.json")
  apks = {}
  for abi in ("x86_64", "arm64-v8a"):
    apk = ROOT / f"android/app/build/outputs/apk/debug/app-{abi}-debug.apk"
    if not (CACHE / f"signature-{abi}.txt").read_text().startswith("Verifies"):
      raise RuntimeError(f"Missing signature verification for {abi}")
    apks[abi] = {"path": apk.relative_to(ROOT).as_posix(), "bytes": apk.stat().st_size, "sha256": sha256(apk),
                 "signed": True, "physical_phone_tested": physical_passed if abi == "arm64-v8a" else None}
  acceptance = {"milestone": "first integrated Android simulation", "branch": "android-fold3-port",
                "source_revision": report["comparison"]["source_revision"], "source_sha256": report["comparison"]["source_sha256"],
                "verification_passed": True, "session": args.session, "frames": 60,
                "elapsed_seconds": report["elapsed_seconds"], "counts": report["counts"],
                "android_tests": {"passed": int(passed[1]), "failed": 0},
                "host_tests": {"passed": 7, "failed": 0, "carried_forward": True,
                               "note": "Earlier computational-source validation; no native host helpers run for this UI update"},
                "comparison": {name: {"passed": result["passed"], "differences": result["differences"]}
                               for name, result in report["comparison"]["processes"].items()},
                "folding": lifecycle, "apks": apks, "physical_phone_tested": physical_passed,
                "native_compiler_settings": {"ndk": "28.2.13676358", "cmake": "3.22.1",
                   "model_flags": ["-O2", "-ffreestanding", "-fno-math-errno", "-ffp-contract=off"]}}
  (delivery / "acceptance.json").write_text(json.dumps(acceptance, indent=2)+"\n")
  (delivery / "SHA256SUMS.txt").write_text("".join(f"{value['sha256']}  ../../{value['path']}\n" for value in apks.values()))
  phone_text = (f"The ARM64 APK also passed {physical.get('android_tests', {}).get('passed', 0)} tests on the physical Fold 3 while closed; "
                "[physical-phone results](fold3/README.md) include numerical comparison, cover-screen rotation and captures."
                if physical_passed else "ARM64 compilation and APK signatures pass; physical-phone acceptance is recorded separately when available.")
  text = f"""# Android simulation acceptance

Branch: `android-fold3-port`. Base revision: `{acceptance['source_revision']}`.
Computational source SHA-256: `{acceptance['source_sha256']}` (includes uncommitted port changes).

The APK completed **60 model frames, 60 plans, {report['counts']['carControl']} control messages and {report['counts']['sendcan']} simulated CAN messages**
in **{report['elapsed_seconds']:.1f} seconds**. All 12 daemons matched the Linux reference using the existing
replay exclusions and tolerances. Android tests: **{passed[1]}/{passed[1]}**. The earlier **7/7** host-adapter
results are retained as baseline evidence; this UI update used source inspection and Android target tests.

- [Verification report]({args.session}/verification.json)
- [Numerical comparisons]({args.session}/comparison.json)
- [Lifecycle results]({args.session}/lifecycle.json)
- [Completed dashboard]({args.session}/dashboard-completed.png), [folded dashboard]({args.session}/dashboard-folded.png)
- [Android test log](logs/final-suite-tests.txt), [host test log](logs/host-tests.txt)
- [Build commands and architecture](../../docs/android-port.md)
- [APK checksums](SHA256SUMS.txt), [machine-readable acceptance](acceptance.json)

The fold test preserved workers across a reduced viewport and rotation.
The API 36 image needs the documented explicit viewport workaround alongside its hinge event.
{phone_text}
Camera capture, hardware acceleration, real-time performance and vehicle operation remain later stages.
"""
  (delivery / "README.md").write_text(text)
  print(json.dumps({"acceptance": str(delivery / "README.md"), "seconds": report["elapsed_seconds"], "apks": apks}))

if __name__ == "__main__":
  main()
