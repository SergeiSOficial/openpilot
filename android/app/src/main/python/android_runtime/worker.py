"""Embedded worker entry points. Missing real dependencies are fatal."""
import importlib
import json
import os
from pathlib import Path
import sys

DAEMONS = {
  "modeld": "openpilot.selfdrive.modeld.modeld",
  "card": "android_runtime.card_worker",
  "radard": "openpilot.selfdrive.controls.radard",
  "plannerd": "openpilot.selfdrive.controls.plannerd",
  "controlsd": "openpilot.selfdrive.controls.controlsd",
  "selfdrived": "openpilot.selfdrive.selfdrived.selfdrived",
  "calibrationd": "openpilot.selfdrive.locationd.calibrationd",
  "locationd": "openpilot.selfdrive.locationd.locationd",
  "paramsd": "openpilot.selfdrive.locationd.paramsd",
  "lagd": "openpilot.selfdrive.locationd.lagd",
  "torqued": "openpilot.selfdrive.locationd.torqued",
  "dmonitoringd": "openpilot.selfdrive.monitoring.dmonitoringd",
}

def configure(root: str, native_directory: str | None = None) -> None:
  base = Path(root).resolve(strict=True)
  os.chdir(base)
  for name in ("params", "log", "tmp", "shm"):
    (base / name).mkdir(exist_ok=True)
  os.environ.update(OPENPILOT_ANDROID_ROOT=str(base), MSGQ_ROOT=str(base / "shm"),
                    TMPDIR=str(base / "tmp"), PARAMS_ROOT=str(base / "params"),
                    LOG_ROOT=str(base / "log"), SIMULATION="1", NOBOARD="1", DEV="CPU:CLANG",
                    CCACHE="0", CACHELEVEL="0", PARALLEL="0", OPENPILOT_ANDROID_MODELS_ROOT=str(base.parents[1] / "model"))
  if native_directory is not None:
    os.environ["OPENPILOT_ANDROID_NATIVE_DIR"] = native_directory
  os.environ["OPENPILOT_ANDROID_METADATA"] = str(base.parents[1] / "model/build.json")
  os.environ["OPENPILOT_ANDROID_SCHEMAS"] = str(base.parents[1] / "model")

def check(root: str, native_directory: str | None = None) -> str:
  configure(root, native_directory)
  dependencies = {}
  for name in ("numpy", "capnp", "msgq", "msgq.visionipc", "opendbc.can.parser",
               "openpilot.common.params", "tinygrad", *DAEMONS.values(),
               "openpilot.selfdrive.test.process_replay.process_replay", "openpilot.selfdrive.test.process_replay.migration"):
    try:
      mod = importlib.import_module(name)
      dependencies[name] = {"ok": True, "version": getattr(mod, "__version__", None)}
    except Exception as failure:
      dependencies[name] = {"ok": False, "error": str(failure)}
  return json.dumps({"python": sys.version, "pid": os.getpid(), "dependencies": dependencies,
                     "ready": all(item["ok"] for item in dependencies.values())})

def schema_probe(root: str, native_directory: str) -> str:
  configure(root, native_directory)
  import capnp
  path = Path(root) / "probe.capnp"
  path.write_text('@0xf6c33b170aa14891;\nstruct Probe { sequence @0 :UInt64; payload @1 :Data; }\n')
  parser = capnp.SchemaParser()
  schema = parser.load(str(path))
  message = schema.Probe.new_message(sequence=17, payload=b"Android schema roundtrip")
  with schema.Probe.from_bytes(message.to_bytes()) as decoded:
    assert decoded.sequence == 17 and decoded.payload == b"Android schema roundtrip"
  from opendbc.car.structs import car
  from openpilot.cereal import messaging, log
  event = messaging.new_message("carParams")
  event.carParams = car.CarParams.new_message(carFingerprint="ANDROID_SCHEMA_IDENTITY")
  with log.Event.from_bytes(event.to_bytes()) as decoded:
    assert decoded.carParams.carFingerprint == "ANDROID_SCHEMA_IDENTITY"
  return json.dumps({"passed": True, "pycapnp": capnp.__version__})

def run(root: str, daemon: str, native_directory: str, environment: str = "{}", supervisor=None) -> None:
  if daemon not in DAEMONS and daemon not in ("replay", "live", "sensord"):
    raise ValueError(f"Daemon is not in the Android simulation allowlist: {daemon}")
  configure(root, native_directory)
  allowed = {"OPENPILOT_PREFIX", "CEREAL_FAKE", "CEREAL_FAKE_PREFIX", "PROC_NAME", "REPLAY", "PARAMS_ROOT",
             "FINGERPRINT", "SKIP_FW_QUERY", "SIMULATION", "NOBOARD", "OPENPILOT_ANDROID_MODE",
             "OPENPILOT_ANDROID_SEAT", "OPENPILOT_ANDROID_DURATION"}
  updates = json.loads(environment)
  if not isinstance(updates, dict) or set(updates) - allowed or any(not isinstance(v, str) for v in updates.values()):
    raise ValueError("Invalid simulation worker environment")
  os.environ.update(updates)
  if daemon == "sensord":
    from android_runtime.sensors import main
    main()
    return
  if daemon == "live":
    from android_runtime.live import run as run_live
    run_live(root, native_directory, supervisor)
    return
  if daemon == "replay":
    if supervisor is None:
      raise ValueError("Replay requires an Android service supervisor")
    from android_runtime.replay import run_session
    run_session(root, supervisor)
    return
  if daemon == "modeld":
    from android_runtime.aot import install
    install(str(Path(native_directory) / "libopenpilot_kernels.so"))
    # A single-use test request exists only in the isolated QNN package. Normal
    # simulation and live workers never create it or select this backend.
    request=Path(root).resolve().parents[1]/"qnn-replay-request.json"
    if request.exists():
      consumed=Path(root)/"qnn-replay-request.json"
      os.replace(request,consumed)
      payload=json.loads(consumed.read_text())
      if not isinstance(payload,dict) or payload.get("session",Path(root).name)!=Path(root).name:
        raise ValueError("QNN replay request belongs to a different session")
      payload["session"]=Path(root).name
      consumed.write_text(json.dumps(payload)+"\n")
      from android_runtime.qnn_replay import build
      module=importlib.import_module(DAEMONS[daemon])
      module.ModelState=build(module.ModelState,root,native_directory)
      module.main()
      return
  importlib.import_module(DAEMONS[daemon]).main()
