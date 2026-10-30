"""Shared simulation configuration for the Linux reference and Android workers."""
from android_runtime.worker import DAEMONS


def initialize_model(rc, pm, messages, fingerprint):
  from openpilot.selfdrive.test.process_replay.process_replay import get_car_params_callback
  get_car_params_callback(rc, pm, messages, fingerprint)
  # Wait until modeld has constructed SubMaster and is blocked on its first VIPC
  # receive. These recorded snapshots seed startup only; computed calibration
  # and subsequent external observations take over on the causal timeline.
  rc.wait_for_recv_called()
  for service in ("deviceState", "narrowRoadCameraState", "extrinsicsCalibration"):
    snapshot = next((message for message in messages if message.which() == service), None)
    if snapshot is None:
      raise ValueError(f"Missing required model initialization snapshot: {service}")
    pm.send(service, snapshot.as_builder())


def initial_params(messages):
  from openpilot.selfdrive.test.process_replay.process_replay import get_custom_params_from_lr
  return get_custom_params_from_lr(messages, initial_state="first")


def process_configs():
  from openpilot.selfdrive.test.process_replay.process_replay import get_car_params_callback, get_process_config
  configs = [get_process_config(name) for name in DAEMONS]
  for config in configs:
    config.timeout = 120
    if config.proc_name == "modeld":
      config.init_callback = initialize_model
    if config.proc_name == "card":
      # Live fingerprint bootstrap can consume a timing-dependent number of CAN packets.
      # Reconstruct current-source CarParams from recorded FW/CAN before timeline replay.
      config.init_callback = get_car_params_callback
  return configs
