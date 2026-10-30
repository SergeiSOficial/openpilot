"""Collect private replay evidence through adb run-as from the debug emulator APK."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--serial", default="emulator-5556")
  parser.add_argument("--session")
  parser.add_argument("--physical", action="store_true", help="Collect from the explicitly selected Fold 3 instead of an emulator")
  args = parser.parse_args()
  if not args.physical and not re.fullmatch(r"emulator-\d+", args.serial):
    raise ValueError("Evidence collection requires an emulator serial")
  if args.physical and not re.fullmatch(r"[A-Za-z0-9_-]+", args.serial):
    raise ValueError("Invalid physical-device serial")
  adb = Path(os.environ["ANDROID_HOME"]) / "platform-tools/adb.exe"
  command = [str(adb), "-s", args.serial]
  if args.physical:
    model = subprocess.check_output([*command, "shell", "getprop", "ro.product.model"], text=True).strip()
    if not model.startswith("SM-F926"):
      raise ValueError(f"Selected physical device is not a Fold 3: {model}")
  private = [*command, "exec-out", "run-as", "ai.comma.openpilot.sim", "cat"]
  session = args.session or subprocess.check_output([*private, "files/last-replay-session.txt"], text=True).strip()
  if not re.fullmatch(r"[a-f0-9]{16}", session):
    raise ValueError("Invalid recorded session identifier")
  out = ROOT / "artifacts/android" / ("fold3" if args.physical else "") / session
  out.mkdir(parents=True, exist_ok=True)
  if args.physical:
    def read_device(*arguments):
      return subprocess.check_output([*command, "shell", *arguments], text=True).strip()
    device = {"model": model, "android": read_device("getprop", "ro.build.version.release"),
              "api": int(read_device("getprop", "ro.build.version.sdk")), "abi": read_device("getprop", "ro.product.cpu.abi"),
              "build_type": read_device("getprop", "ro.build.type"), "verified_boot": read_device("getprop", "ro.boot.verifiedbootstate"),
              "shell_identity": read_device("id"), "device_state": read_device("cmd", "device_state", "print-state"),
              "display_size": read_device("wm", "size")}
    (out / "device.json").write_text(json.dumps(device, indent=2)+"\n")
  def read_private(name, required=False):
    path = f"files/s/{session}/{name}"
    # exec-out does not propagate the remote command's exit status reliably.
    # Query size through shell first so error text cannot masquerade as an asset.
    size = subprocess.run([*command, "shell", "run-as", "ai.comma.openpilot.sim", "stat", "-c", "%s", path], capture_output=True, text=True)
    if size.returncode != 0:
      (out / name).unlink(missing_ok=True)
      if required:
        raise FileNotFoundError(f"Missing private simulation evidence: {name}")
      return
    data = subprocess.check_output([*private, path])
    if len(data) != int(size.stdout.strip()):
      raise ValueError(f"Evidence length mismatch: {name}")
    if name.endswith(".json"):
      json.loads(data)
    if name.endswith(".png") and not data.startswith(b"\x89PNG\r\n\x1a\n"):
      raise ValueError(f"Invalid dashboard capture: {name}")
    (out / name).write_bytes(data)
  for name in ("verification.json", "progress.json"):
    read_private(name, required=True)
  for name in ("outputs.rlog", "comparison.json", "lifecycle.json", "dashboard-open.png", "dashboard-folded.png", "dashboard-rotated.png", "dashboard-completed.png"):
    read_private(name)
  with (out / "logcat.txt").open("wb") as stream:
    subprocess.run([*command, "logcat", "-d", "-s", "OpenpilotWorker", "python.stderr", "python.stdout"], stdout=stream, check=True)
  pointer = ROOT / "tools/android/.cache" / ("fold3" if args.physical else "") / "last-evidence.txt"
  pointer.parent.mkdir(parents=True, exist_ok=True)
  pointer.write_text(str(out))
  report = json.loads((out / "verification.json").read_text())
  print(json.dumps({"directory": str(out), "frames": report["frames"], "counts": report["counts"]}))

if __name__ == "__main__":
  main()
