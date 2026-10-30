"""Causal process replay using Android Binder workers and bounded event waits."""
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import select
import time

import numpy as np

from android_runtime.worker import DAEMONS


def write_json(path, report):
  temporary = path.with_suffix(".tmp")
  temporary.write_text(json.dumps(report, allow_nan=False))
  temporary.replace(path)


class FixtureFrames:
  pix_fmt = "nv12"

  def __init__(self, root, camera, info):
    self.root, self.camera, self.info = root, camera, info
    self.w, self.h = info["width"], info["height"]

  def get(self, index):
    expected = self.info["sha256"].get(str(index))
    if expected is None:
      raise ValueError(f"Frame {index} is not in the synchronized fixture")
    raw = (self.root / self.camera / f"{index:04}.nv12").read_bytes()
    if len(raw) != self.info["buffer_size"] or hashlib.sha256(raw).hexdigest() != expected:
      raise ValueError(f"Corrupted fixture buffer {self.camera}/{index}")
    stride, y_height = self.info["stride"], self.info["y_height"]
    data = np.frombuffer(raw, dtype=np.uint8)
    y = data[:stride*y_height].reshape(y_height, stride)[:self.h, :self.w]
    uv = data[stride*y_height:stride*(y_height+self.info["uv_height"])].reshape(-1, stride)[:self.h//2, :self.w]
    return np.concatenate((y.reshape(-1), uv.reshape(-1)))


class AndroidProcess:
  def __init__(self, backend, name):
    self.backend, self.name, self.proc, self.pid = backend, name, None, None
    self.stopped = False

  def start(self):
    keys = ("OPENPILOT_PREFIX", "CEREAL_FAKE", "CEREAL_FAKE_PREFIX", "PROC_NAME", "REPLAY", "PARAMS_ROOT",
            "FINGERPRINT", "SKIP_FW_QUERY", "SIMULATION", "NOBOARD")
    environment = {key: os.environ[key] for key in keys if key in os.environ}
    # msgq sets these with native setenv(), which does not refresh Python's os.environ mapping.
    environment.update(CEREAL_FAKE="1", CEREAL_FAKE_PREFIX=self.name)
    self.pid = self.backend.supervisor.startWorker(self.name, json.dumps(environment))
    self.proc = self

  def is_alive(self):
    if self.stopped:
      return False
    status = json.loads(str(self.backend.supervisor.workerStatus(self.name)))
    if status["state"] not in ("starting", "running"):
      raise RuntimeError(f"Required worker {self.name} failed: {status}")
    return True

  def signal(self, _signal):
    self.stop()

  def stop(self):
    if not self.stopped:
      self.stopped = True
      self.backend.supervisor.stopWorker(self.name)


class AndroidBackend:
  def __init__(self, root, supervisor):
    self.root, self.supervisor = root, supervisor
    self.started = time.monotonic()
    self.deadline = self.started + 1800
    self.step_deadline, self.current = self.deadline, "startup"
    self.last_health = 0.0
    self.counts = Counter()
    self.report = {"schema": 1, "state": "starting", "frame_pairs_required": 60, "frames": 0, "counts": {}, "workers": {}}
    self.publish()

  def publish(self):
    self.report.update(elapsed_seconds=time.monotonic()-self.started, counts=dict(self.counts))
    write_json(self.root / "progress.json", self.report)

  def create_process(self, name):
    if name not in DAEMONS:
      raise ValueError(f"Unsupported Android simulation daemon {name}")
    self.report.update(state="starting", starting_worker=name)
    self.publish()
    return AndroidProcess(self, name)

  @contextmanager
  def step_context(self, name, timeout):
    previous = self.step_deadline, self.current
    self.step_deadline, self.current = min(self.deadline, time.monotonic()+timeout), name
    try:
      yield
    finally:
      self.step_deadline, self.current = previous

  def wait_for_events(self, events):
    poller = select.poll()
    indexes = {event.fd: index for index, event in enumerate(events)}
    if not indexes or any(fd < 0 for fd in indexes):
      raise RuntimeError(f"Invalid replay events for {self.current}")
    for fd in indexes:
      poller.register(fd, select.POLLIN)
    while True:
      now = time.monotonic()
      if now >= min(self.deadline, self.step_deadline):
        raise TimeoutError(f"Monotonic replay timeout waiting for {self.current}: {self.report['workers']}")
      if now-self.last_health >= 0.5:
        health = json.loads(str(self.supervisor.health()))
        self.report["workers"] = health
        self.last_health = now
        for name, status in health.items():
          if status["state"] not in ("starting", "running"):
            raise RuntimeError(f"Required worker {name} failed: {status}")
        self.publish()
      ready = poller.poll(min(100, max(1, int((self.step_deadline-now)*1000))))
      for fd, flags in ready:
        if flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
          raise RuntimeError(f"Replay event closed for {self.current}")
        if flags & select.POLLIN:
          return indexes[fd]

  def on_output(self, messages):
    for message in messages:
      kind = message.which()
      self.counts[kind] += 1
      if kind == "modelV2":
        model = message.modelV2
        self.report.update(frames=self.counts[kind], frame_id=model.frameId,
                           path={axis: list(getattr(model.position, axis)) for axis in ("x", "y", "z")})
      elif kind == "carControl":
        self.report["actuators"] = message.carControl.actuators.to_dict()
    self.report["state"] = "running"
    self.publish()


def load_fixture(root):
  from openpilot.cereal import log
  manifest = json.loads((root / "fixture.json").read_text())
  selection = manifest["selection"]
  data = (root / "fixture.rlog").read_bytes()
  if hashlib.sha256(data).hexdigest() != selection["log_sha256"]:
    raise ValueError("Corrupted recorded fixture log")
  messages = list(log.Event.read_multiple_bytes(data))
  frames = {name: FixtureFrames(root, name, info) for name, info in manifest["cameras"].items()}
  return messages, frames


def run_session(root, supervisor):
  from openpilot.selfdrive.test.process_replay.process_replay import replay_process
  from android_runtime.simulation import initial_params, process_configs
  root = Path(root)
  backend = AndroidBackend(root, supervisor)
  try:
    messages, frames = load_fixture(root.parents[1] / "fixture")
    configs = process_configs()
    outputs = replay_process(configs, messages, frames, custom_params=initial_params(messages),
                             disable_progress=True, backend=backend, drain_outputs=True)
    with (root / "outputs.rlog").open("wb") as output:
      for message in outputs:
        output.write(message.as_builder().to_bytes())
    required = ("modelV2", "longitudinalPlan", "carControl", "sendcan")
    if backend.counts["modelV2"] != 60 or backend.counts["longitudinalPlan"] != 60 or any(backend.counts[key] == 0 for key in required):
      raise RuntimeError(f"Incomplete model-to-control replay: {dict(backend.counts)}")
    from android_runtime.verification import verify
    comparison = verify(root, outputs, configs)
    write_json(root / "comparison.json", comparison)
    backend.report.update(replay_passed=True, comparison=comparison, verification_passed=comparison["passed"])
    if not comparison["passed"]:
      raise AssertionError("Android outputs differ from the same-source desktop reference; see comparison.json")
    backend.report["state"] = "completed"
  except BaseException as failure:
    if getattr(supervisor, "isStopping", lambda: False)():
      backend.report.update(state="stopped", error="", replay_passed=False, verification_passed=False)
    else:
      backend.report.update(state="failed", error=str(failure), replay_passed=False)
      raise
  finally:
    backend.report["workers"] = json.loads(str(supervisor.health()))
    backend.publish()
    write_json(root / "verification.json", backend.report)
