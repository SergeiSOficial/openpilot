"""Use each process replay configuration's existing exclusions and numerical tolerance."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HOST = Path(os.environ.get("OPENPILOT_ANDROID_CACHE", Path.home() / ".cache/openpilot-android"))
sys.path[:0] = [str(HOST / "host-rednose"), str(HOST / "host-msgq"), str(ROOT / "tools/android/.cache/python"), str(ROOT),
               str(ROOT / "opendbc_repo"), str(ROOT / "android/app/src/main/python")]

def compare(reference, actual, configs):
  from android_runtime.verification import compare as compare_outputs
  return compare_outputs(reference, actual, configs)

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("actual", type=Path)
  parser.add_argument("--reference", type=Path, default=ROOT / "tools/android/.cache/reference/outputs.rlog")
  args = parser.parse_args()
  args.actual = args.actual.resolve()
  args.reference = args.reference.resolve()
  from android_runtime.worker import configure, DAEMONS
  session = HOST / "s/comparison"
  session.mkdir(parents=True, exist_ok=True)
  configure(str(session), str(HOST / "host-params"))
  os.environ["OPENPILOT_ANDROID_SCHEMAS"] = str(ROOT / "android/app/src/main/assets/generated/model")
  from openpilot.cereal import log
  from openpilot.selfdrive.test.process_replay.process_replay import get_process_config
  reference = list(log.Event.read_multiple_bytes(args.reference.read_bytes()))
  actual = list(log.Event.read_multiple_bytes(args.actual.read_bytes()))
  report = compare(reference, actual, [get_process_config(name) for name in DAEMONS])
  args.actual.with_name("comparison.json").write_text(json.dumps(report, indent=2) + "\n")
  print(json.dumps({"passed": report["passed"], "processes": {name: {key: value for key, value in result.items()
                      if key in ("passed", "differences", "error")} for name, result in report["processes"].items()}}))
  if not report["passed"]:
    raise SystemExit(1)

if __name__ == "__main__":
  main()
