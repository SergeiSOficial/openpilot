"""Validate live bootstrap bytes and identity without relabeling old certificates.

All imports are standard library or reviewed stdlib-only local hashing helpers.
No GPU/CPU model runtime or generated native helper executes on the host.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
from validate_bundle import digest, elf_exports
from stage_live import live_sources

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-source", action="store_true")
    args = parser.parse_args()
    # Preserve the retained model/reference checksum, historical certificate and ABI checks.
    subprocess.run([sys.executable, str(ROOT/"tools/android/validate_bundle.py")], check=True)
    directory = ROOT/"android/app/src/main/assets/generated/live"
    manifest = json.loads((directory/"manifest.json").read_text())["sha256"]
    for name, expected in manifest.items():
        if name not in ("dmonitoring_model.onnx", "live-build.json") or digest(directory/name) != expected:
            raise RuntimeError("Live model/input integrity failure: "+name)
    build = json.loads((directory/"live-build.json").read_text())
    if build["current_source_certified"] or not build["requires_on_target_numerical_gate"]:
        raise RuntimeError("Bootstrap must not claim target certification")
    if args.check_source and build["source_sha256"] != live_sources():
        raise RuntimeError("Live sources changed after staging; run stage_live.py (does not run model code)")
    symbols = elf_exports(ROOT/"android/app/src/main/jniLibs/arm64-v8a/libopenpilot_ipc.so",183)
    if not {"op_live_connect", "op_live_read", "op_live_cl_upload"} <= symbols:
        raise RuntimeError("ARM64 capture bridge exports missing")
    print("Live bootstrap integrity passed; execution is gated by mandatory Android numerical validation")


if __name__ == "__main__":
    main()
