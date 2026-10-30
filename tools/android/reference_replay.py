"""Generate a Linux reference using current source, canonical fixture and packaged CPU artifacts."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import copy
from provenance import source_sha256

ROOT = Path(__file__).resolve().parents[2]
HOST = Path(os.environ.get("OPENPILOT_ANDROID_CACHE", Path.home() / ".cache/openpilot-android"))
sys.path[:0] = [str(HOST / "host-rednose"), str(HOST / "host-msgq"), str(ROOT / "tools/android/.cache/python"), str(ROOT),
               str(ROOT / "opendbc_repo"), str(ROOT / "tinygrad_repo"), str(ROOT / "android/app/src/main/python")]

def setup():
  from android_runtime.worker import configure
  session = HOST / "s/reference"
  session.mkdir(parents=True, exist_ok=True)
  configure(str(session), str(HOST / "host-params"))
  os.environ["OPENPILOT_ANDROID_MODELS_ROOT"] = str(ROOT / "tools/android/.cache/model-aot")
  os.environ["OPENPILOT_ANDROID_METADATA"] = str(ROOT / "android/app/src/main/assets/generated/model/build.json")
  os.environ["OPENPILOT_ANDROID_SCHEMAS"] = str(ROOT / "android/app/src/main/assets/generated/model")
  # The Linux msgq build uses /dev/shm. Keep its normal storage contract for the desktop reference.
  from openpilot.common.hardware.hw import Paths
  Paths.shm_path = staticmethod(lambda: "/dev/shm")
  return session

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--capture-kernels", action="store_true")
  args = parser.parse_args()
  session = setup()
  from android_runtime import aot
  models = ROOT / "tools/android/.cache/model-aot"
  if args.capture_kernels:
    aot.capture(str(models / "kernels"))
    from openpilot.selfdrive.modeld.modeld import ModelState
    # Exercise the daemon's buffer views and state allocations in addition to graph execution.
    for width, height in ((1344, 760), (1928, 1208)):
      model = ModelState(width, height, False)
      model.warmup()
    aot.manifest(str(models / "kernels"), str(models / "kernels.json"))
    subprocess.run(["clang", "-shared", "-fPIC", "-O2", "-ffreestanding", "-fno-math-errno", "-ffp-contract=off",
                    *map(str, sorted((models / "kernels").glob("*.c"))), "-lm", "-o", str(models / "libopenpilot_kernels.so")], check=True)
    print("Captured complete ModelState initialization and execution kernels")
    return
  aot.install(str(models / "libopenpilot_kernels.so"))
  from android_runtime.replay import load_fixture
  from android_runtime.replay import AndroidBackend
  from android_runtime.worker import DAEMONS
  from openpilot.selfdrive.test.process_replay.process_replay import replay_process
  from android_runtime.simulation import initial_params, process_configs
  messages, frames = load_fixture(ROOT / "tools/android/.cache/fixture")
  configs = process_configs()
  start = time.monotonic()
  from openpilot.system.manager.process_config import managed_processes

  class HostSupervisor:
    def __init__(self):
      self.processes = {}

    def health(self):
      return json.dumps({name: {"state": "running" if process.proc and process.proc.is_alive() else "dead",
                                "exitcode": process.proc.exitcode if process.proc else None}
                         for name, process in self.processes.items()})

  class HostBackend(AndroidBackend):
    def create_process(self, name):
      process = copy.deepcopy(managed_processes[name])
      process.module = DAEMONS[name]
      self.supervisor.processes[name] = process
      return process

  backend = HostBackend(session, HostSupervisor())
  outputs = replay_process(configs, messages, frames, custom_params=initial_params(messages),
                           disable_progress=True, drain_outputs=True, backend=backend)
  out = ROOT / "tools/android/.cache/reference"
  out.mkdir(exist_ok=True)
  with (out / "outputs.rlog").open("wb") as stream:
    for message in outputs:
      stream.write(message.as_builder().to_bytes())
  counts = dict(Counter(message.which() for message in outputs))
  report = {"schema": 1, "elapsed_seconds": time.monotonic()-start, "counts": counts,
            "source_sha256": source_sha256(),
            "output_sha256": hashlib.sha256((out / "outputs.rlog").read_bytes()).hexdigest(),
            "source_revision": subprocess.check_output(["git.exe", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "fixture_sha256": hashlib.sha256((ROOT / "tools/android/.cache/fixture/fixture.rlog").read_bytes()).hexdigest(),
            "model_sha256": json.loads((models / "provenance.json").read_text())["model_sha256"]}
  (out / "report.json").write_text(json.dumps(report, indent=2)+"\n")
  if counts.get("modelV2") != 60 or counts.get("longitudinalPlan") != 60 or any(not counts.get(key) for key in ("carControl", "sendcan")):
    raise RuntimeError(f"Incomplete desktop reference: {counts}")
  print(json.dumps(report))

if __name__ == "__main__":
  main()
