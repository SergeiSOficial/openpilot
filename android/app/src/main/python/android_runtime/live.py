"""Stationary, disengaged Android camera/GPU coordinator. No vehicle workers.

Host import is stdlib-only. Native libraries and model backends are opened only
inside the Android worker entry point. Frames remain in owned native snapshots.
"""
import json
import math
import os
from pathlib import Path
import statistics
import time
from collections import deque


def timing_summary(values):
  if not values:
    return {"samples": 0}
  ordered = sorted(values)
  return {"samples": len(values), "mean_ms": statistics.fmean(values), "p50_ms": statistics.median(values),
          "p95_ms": ordered[max(0, math.ceil(len(ordered) * .95)-1)], "max_ms": ordered[-1],
          "over_50_ms": sum(value > 50 for value in values)}


def pair_eligible(main, wide, now_ns, previous):
  """Bench pairing only; the separate 10-ms timing acceptance flag is stricter."""
  if main is None or wide is None:
    return False, "missing_frame"
  if not main.valid or not wide.valid:
    return False, "untrusted_sensor_clock"
  if main.frame_id <= previous[0] or wide.frame_id <= previous[1]:
    return False, "repeated_frame"
  ages = [now_ns-main.timestamp_sof, now_ns-wide.timestamp_sof]
  if any(age < -5_000_000 or age > 250_000_000 for age in ages):
    return False, "stale_or_untrusted_clock"
  if abs(main.timestamp_sof-wide.timestamp_sof) > 75_000_000:
    return False, "pair_skew"
  return True, "fresh_bench_pair"


def _write(path, report):
  temp = path.with_suffix(".tmp")
  temp.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
  temp.replace(path)


class NativeFrames:
  def __init__(self, root, native_dir):
    self.read_count = self.read_ns = self.read_max_ns = 0
    import ctypes
    self.ctypes = ctypes
    self.lib = ctypes.CDLL(str(Path(native_dir)/"libopenpilot_ipc.so"))
    self.lib.op_live_connect.argtypes = [ctypes.c_char_p]
    self.lib.op_live_connect.restype = ctypes.c_int
    self.lib.op_live_read.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint64), ctypes.c_int]
    self.lib.op_live_read.restype = ctypes.c_void_p
    self.lib.op_live_error.restype = ctypes.c_char_p
    if self.lib.op_live_connect(str(root).encode()) != 0:
      raise RuntimeError(self.lib.op_live_error().decode())

  def read(self, stream, timeout=0):
    started = time.monotonic_ns()
    meta = (self.ctypes.c_uint64*9)()
    pointer = self.lib.op_live_read(stream, meta, timeout)
    if not pointer:
      return None
    elapsed = time.monotonic_ns()-started
    self.read_count += 1;self.read_ns += elapsed;self.read_max_ns = max(self.read_max_ns, elapsed)
    return Frame(pointer, meta, self.ctypes)


class Frame:
  def __init__(self, pointer, meta, ctypes_module):
    self.pointer = pointer
    (self.frame_id, self.timestamp_sof, self.timestamp_eof, self.length, self.width,
     self.height, self.stride, self.uv_offset, self.valid) = map(int, meta)
    self._view = (ctypes_module.c_ubyte*self.length).from_address(pointer)
    self.data = memoryview(self._view).cast("B")


def _camera_state(root, previous=None):
  try:
    current = json.loads((root/"camera.json").read_text())
    return current if isinstance(current, dict) and current.get("state") else (previous or {})
  except (FileNotFoundError, json.JSONDecodeError):
    return previous or {}


def road_qualification(root, model_root, native_directory, capabilities):
  import hashlib
  from android_runtime.live_policy import qualification_passed,execution_bindings
  from java import jclass
  try:
    certificate = json.loads((root.parents[1]/"road-qualification.json").read_text())
    provenance = json.loads((model_root/"provenance.json").read_text())
    identity = {"model_sha256": provenance["model_sha256"],
      "artifact_sha256": hashlib.sha256((model_root/"driving_tinygrad.pkl").read_bytes()).hexdigest(),
      "source_sha256": hashlib.sha256((model_root/"live-build.json").read_bytes()).hexdigest(),
      "native_sha256": hashlib.sha256((Path(native_directory)/"libopenpilot_ipc.so").read_bytes()).hexdigest(),
      "runtime": "tinygrad.CL.retained.v1", "driver": capabilities.get("driver", ""),
      "device_fingerprint": str(jclass("android.os.Build").FINGERPRINT),
      **execution_bindings(capabilities.get('cache'),str(Path(native_directory).parents[1]/'base.apk'))}
    return qualification_passed(certificate, identity)
  except (OSError, ValueError, KeyError, TypeError):
    return False, "missing_or_invalid_sustained_qualification"


def _transform(profile, wide=False, cabin=False):
  import numpy as np
  from openpilot.common.transformations.model import get_warp_matrix, dmonitoringmodel_intrinsics
  k = np.array([[profile["fx"],0,profile["cx"]],[0,profile["fy"],profile["cy"]],[0,0,1]], dtype=np.float32)
  transform = k @ np.linalg.inv(dmonitoringmodel_intrinsics) if cabin else get_warp_matrix(np.zeros(3), k, wide)
  rotation = profile.get("rotation_degrees", 0)
  w, h = profile["width"], profile["height"]
  if rotation == 180:
    transform = np.array([[-1,0,w-1],[0,-1,h-1],[0,0,1]], dtype=np.float32) @ transform
  elif rotation != 0:
    raise RuntimeError("This bench camera profile requires landscape alignment (0 or 180 degrees)")
  if profile.get("mirror_input", False):
    transform = np.array([[-1,0,w-1],[0,1,0],[0,0,1]], dtype=np.float32) @ transform
  return transform.astype(np.float32)


def run(root, native_directory, supervisor=None):
  import sys
  from android_runtime.live_policy import thermal_action, InputHealth
  if sys.platform != "linux" or not Path("/system/bin/app_process").exists():
    raise RuntimeError("Live capture and GPU execution are Android-only")
  root = Path(root)
  mode = os.environ.get("OPENPILOT_ANDROID_MODE", "live")
  gpu_check=mode in ('gpucheck','drivergpucheck')
  duration = max(5, min(1200, int(os.environ.get("OPENPILOT_ANDROID_DURATION", "1200"))))
  seat = os.environ.get("OPENPILOT_ANDROID_SEAT", "unset")
  model_root = Path(os.environ["OPENPILOT_ANDROID_MODELS_ROOT"])
  report = {"schema": 1, "mode": mode, "state": "initializing", "backend": "CL", "frames": 0,
            "driver_frames": 0, "stationary_inputs": True, "vehicle_connected": False,
            "controls_enabled": False, "calibration_validated": False, "raw_images_saved": False,
            "driver_seat": seat, "real_time_accepted": False, "verification_passed": False,
            "driver_monitoring_available": False, "driver_monitoring_reason": "initializing",
            "camera_timing_accepted": False, "current_source_certified": False}
  start = time.monotonic()
  road_times, driver_times, skews, frame_ages = [deque(maxlen=4096) for _ in range(4)]
  def progress(update=None):
    if update:
      report.update(update)
    report["elapsed_seconds"] = time.monotonic()-start
    _write(root/"progress.json", report)
  progress()
  try:
    if supervisor is None:
      raise RuntimeError("Live session requires the Android worker supervisor")
    if not gpu_check:supervisor.startWorker("sensord", "{}")
    sensor_start = time.monotonic()
    from android_runtime import gpu
    candidate_present = (root.parents[1]/"road-qualification.json").is_file()
    caps = gpu.capabilities() if gpu_check or mode=='cabin' or candidate_present else {"available": False, "probe_skipped": "no_qualified_road_backend"}
    progress({"gpu": caps})
    if not caps.get("available") and (gpu_check or mode=='cabin'):
      raise RuntimeError("OpenCL unavailable: "+str(caps))
    if gpu_check:
      result = gpu.validate_cabin(model_root,native_directory,progress=progress) if mode=='drivergpucheck' else gpu.validate(model_root, native_directory, progress=progress)
      progress({"state": "completed" if result.get("passed") else "failed", "gpu_validation": result,
                "verification_passed": bool(result.get("passed"))})
      _write(root/"verification.json", report)
      return
    frames = NativeFrames(root, native_directory)
    deadline = time.monotonic()+20
    camera = {}
    while time.monotonic() < deadline:
      latest_camera = _camera_state(root)
      if latest_camera:camera = latest_camera
      if camera.get("state") == "failed":
        raise RuntimeError(camera.get("error", "Camera startup failed"))
      if camera.get("cabin_available" if mode == "cabin" else "rear_available"):
        break
      time.sleep(.1)
    else:
      raise RuntimeError("Camera startup timed out")
    profiles = {int(p["stream"]): p for p in camera.get("profiles", [])}
    import numpy as np
    from openpilot.cereal import log, messaging
    from openpilot.selfdrive.modeld.parse_model_outputs import Parser
    from openpilot.selfdrive.modeld.fill_model_msg import PublishState, fill_model_msg, fill_pose_msg, fill_driving_model_data
    from openpilot.selfdrive.modeld.modeld import get_action_from_model
    from openpilot.selfdrive.modeld.dmonitoringmodeld import parse_model_output, get_driverstate_packet
    os.environ.pop("CEREAL_FAKE", None)
    os.environ.pop("CEREAL_FAKE_PREFIX", None)
    channels = ["modelV2","drivingModelData","cameraOdometry","driverStateV2","carState","selfdriveState",
                "extrinsicsCalibration","deviceState","narrowRoadCameraState","wideRoadCameraState","cabinCameraState"]
    pm = messaging.PubMaster(channels)
    monitoring_state=messaging.SubMaster(["driverMonitoringState"])
    road = None
    road_accepted, road_reason = road_qualification(root, model_root, native_directory, caps) if candidate_present else (False, "missing_sustained_20hz_qualification")
    progress({"road_inference_available": False, "road_qualification_passed": road_accepted,
              "road_model_unavailable_reason": road_reason, "pipeline_state": "capture_only" if mode == "capture" else "inference_blocked"})
    if mode not in ("cabin","capture") and road_accepted and caps.get("available"):
      progress({"stage": "road_gpu_initialization"})
      try:
        road = gpu.RoadRunner(model_root,1920,1080,native_directory=native_directory,progress=progress)
        progress({"road_initialization": road.report,"road_inference_available":True})
      except Exception as e:
        # Retain the verified rear pair and previews when numerical validation
        # rejects a GPU candidate. No rejected model output is published.
        progress({"road_inference_available":False,"road_model_unavailable_reason":str(e),
                  "road_numerical_gate_passed":False})
    driver = None
    if camera.get("cabin_available"):
      try:
        runner = gpu.CabinCPURunner if mode == "cabin" else gpu.CabinRunner
        driver = runner(model_root,1280,720,progress=progress)
        progress({"driver_initialization": driver.report})
      except Exception as e:
        progress({"driver_monitoring_reason": "driver_model_validation_failed: "+str(e)})
    else:
      progress({"driver_monitoring_reason": camera.get("cabin_unavailable_reason","capture_unavailable")})
    if supervisor is not None and driver is not None:
      # Only the unchanged monitoring-policy daemon is allowed in this live coordinator.
      from openpilot.common.params import Params
      Params().put_bool("IsRhdDetected",seat=="right")
      Params().put_bool("AlwaysOnDM",False)
      Params().put_bool("IsDriverViewEnabled",False)
      supervisor.startWorker("dmonitoringd", json.dumps({"SIMULATION":"1","NOBOARD":"1"}))
    parser, publish_state = Parser(), PublishState()
    previous_action = log.ModelDataV2.Action.new_message()
    previous_pair, last_driver = (0,0), 0
    driver_deliveries=deque()
    last_driver_timestamp=0
    last_road_capture = None
    sensor_clock_generation = None
    location_started = False
    location_retired = False
    previous_thermal = "running"
    input_health = InputHealth()
    pair_rejections = {}
    from java import jclass
    performance = jclass("ai.comma.openpilot.sim.LivePerformance")
    debug = jclass("android.os.Debug")
    active_start = time.monotonic()
    next_tick = active_start
    last_report = last_stationary = 0.0
    progress({"stage":"live_inference","state":"running","temporal_status":"experimental_camera_rate_below_20hz"})
    while time.monotonic()-active_start < duration:
      now = time.monotonic()
      if supervisor is not None and supervisor.isStopping():
        break
      camera = _camera_state(root, camera)
      if camera.get("state") in ("failed","stopped"):
        raise RuntimeError(camera.get("error", "Camera capture stopped"))
      if time.monotonic_ns()-camera.get("report_monotonic_ns",0)>3_000_000_000:
        raise RuntimeError("Camera reporting stalled; last heartbeat="+str(camera.get("report_monotonic_ns")))
      thermal = thermal_action(camera.get("thermal_status", 0))
      report["thermal_action"] = thermal
      if thermal == "stop":
        raise RuntimeError("Critical thermal state; restart explicitly after cooling")
      report["pipeline_state"] = "degraded" if thermal == "paused" else "running" if road is not None or driver is not None else "capture_only" if mode == "capture" else "inference_blocked"
      if thermal == "paused" and previous_thermal != "paused":
        if road is not None:road.reset()
        previous_pair = (0, 0)
        last_road_capture = None
        previous_action = log.ModelDataV2.Action.new_message()
        publish_state = PublishState()
      previous_thermal = thermal
      if now-last_stationary >= .05:
        for channel in ("carState","selfdriveState","extrinsicsCalibration","deviceState"):
          msg = messaging.new_message(channel)
          msg.valid = channel != "extrinsicsCalibration"
          if channel == "carState":
            msg.carState.vEgo=0;msg.carState.standstill=True;msg.carState.steeringAngleDeg=0
          elif channel == "selfdriveState":
            msg.selfdriveState.enabled=False;msg.selfdriveState.active=False
          elif channel == "extrinsicsCalibration":
            msg.extrinsicsCalibration.rpyCalib=[0.,0.,0.]
          pm.send(channel,msg)
        last_stationary=now
      road_ran = False
      if road is None and mode!="cabin":
        wide=frames.read(2);main=frames.read(0) if wide is not None else None
        eligible,reason=pair_eligible(main,wide,time.monotonic_ns(),previous_pair)
        report["pair_status"]=reason
        if not eligible:pair_rejections[reason] = pair_rejections.get(reason, 0)+1
        if eligible:
          previous_pair=(main.frame_id,wide.frame_id)
          report["fresh_capture_pairs"]=report.get("fresh_capture_pairs",0)+1
          skews.append(abs(main.timestamp_sof-wide.timestamp_sof)/1e6)
          frame_ages.append((time.monotonic_ns()-min(main.timestamp_sof,wide.timestamp_sof))/1e6)
          report.update(pair_skew_ms=skews[-1],frame_age_ms=frame_ages[-1],last_frame_id=main.frame_id)
      if road is not None and input_health.unhealthy_since is None and thermal == "running" and now >= next_tick:
        next_tick=now+.05
        wide=frames.read(2)
        main=frames.read(0) if wide is not None else None
        eligible, reason=pair_eligible(main,wide,time.monotonic_ns(),previous_pair)
        report["pair_status"]=reason
        if eligible and abs(main.timestamp_sof-wide.timestamp_sof)>10_000_000:
          eligible, reason = False, "qualified_pair_skew_exceeded"
        if not eligible:pair_rejections[reason] = pair_rejections.get(reason, 0)+1
        if eligible:
          if last_road_capture is not None and main.timestamp_sof-last_road_capture > 250_000_000:
            if hasattr(road,"reset"):road.reset()
            report["temporal_resets"]=report.get("temporal_resets",0)+1
          last_road_capture=main.timestamp_sof
          transforms={"img":_transform(profiles[0]),"big_img":_transform(profiles[2],wide=True)}
          result=road.run_pair({"img":main,"big_img":wide},transforms,
              {"desire_pulse":np.zeros(8,dtype=np.float32),"traffic_convention":np.array([seat!="right",seat=="right"],dtype=np.float32),"action_t":np.array([.075,.075],dtype=np.float32)})
          previous_pair=(main.frame_id,wide.frame_id)
          parsed=parser.parse_outputs(result["sliced"])
          action=get_action_from_model(parsed,previous_action,.075,.075,0.0);previous_action=action
          model=messaging.new_message("modelV2")
          fill_model_msg(model,parsed,action,publish_state,main.frame_id,wide.frame_id,main.frame_id,0.,main.timestamp_eof,result["timing"]["total_ms"]/1000,False)
          model.valid=False
          pm.send("modelV2",model)
          driving=messaging.new_message("drivingModelData");fill_driving_model_data(driving,model);driving.valid=False;pm.send("drivingModelData",driving)
          pose=messaging.new_message("cameraOdometry");fill_pose_msg(pose,parsed,main.frame_id,0,main.timestamp_eof,False);pm.send("cameraOdometry",pose)
          for channel,frame in (("narrowRoadCameraState",main),("wideRoadCameraState",wide)):
            msg=messaging.new_message(channel);state=getattr(msg,channel);state.frameId=frame.frame_id;state.timestampSof=frame.timestamp_sof;state.timestampEof=frame.timestamp_eof;msg.valid=bool(frame.valid);pm.send(channel,msg)
          report["frames"]+=1;road_times.append(result["timing"]["total_ms"])
          skew=abs(main.timestamp_sof-wide.timestamp_sof)/1e6;skews.append(skew)
          age=(time.monotonic_ns()-min(main.timestamp_sof,wide.timestamp_sof))/1e6;frame_ages.append(age)
          report.update(last_frame_id=main.frame_id,pair_skew_ms=skew,frame_age_ms=age,last_road_timing=result["timing"])
          road_ran=True
          performance.report(int(result["timing"]["total_ms"]*1e6))
          if result["timing"]["total_ms"]>50:
            progress({"pipeline_state":"degraded", "road_model_unavailable_reason":"runtime_deadline_exceeded"})
            road=None
            report["road_inference_available"]=False
      # One GPU thread owns both models. Road work takes priority; cabin never queues behind an unbounded backlog.
      remaining=next_tick-time.monotonic() if road is not None else .05
      estimated_driver=(statistics.median(list(driver_times)[-20:])/1000 if driver_times else .015)
      if driver is not None and input_health.unhealthy_since is None and thermal == "running" and (mode=="cabin" or remaining>estimated_driver+.003):
        frame=frames.read(1)
        if frame is not None and frame.valid and frame.frame_id>last_driver and 0<=time.monotonic_ns()-frame.timestamp_sof<=250_000_000:
          result=driver.run(frame,_transform(profiles[1],cabin=True))
          report["driver_frames_discarded"]=report.get("driver_frames_discarded",0)+max(0,frame.frame_id-last_driver-1) if last_driver else 0
          last_driver=frame.frame_id;driver_times.append(result["timing"]["total_ms"]);report["driver_frames"]+=1
          last_driver_timestamp=frame.timestamp_sof
          driver_deliveries.append(time.monotonic())
          output=parse_model_output(result["sliced"]);output["raw_pred"]=b""
          packet=get_driverstate_packet(output,frame.frame_id,frame.timestamp_sof,result["timing"]["total_ms"]/1000,result["timing"]["total_ms"]/1000)
          # Geometry/cadence are not accepted yet; probabilities remain diagnostics, never "attentive" certification.
          packet.valid=False;pm.send("driverStateV2",packet)
          suffix="rhd" if seat=="right" else "lhd"
          raw={name:float(output[f"{key}_{suffix}"][0,0]) for name,key in (("face_probability","face_prob"),("left_eye_probability","left_eye_prob"),("right_eye_probability","right_eye_prob"),("left_blink_probability","left_blink_prob"),("right_blink_probability","right_blink_prob"))}
          raw["head_orientation"]=output[f"face_descs_{suffix}"][0,:3].tolist()
          visible=raw["face_probability"]>=.7
          report.update(driver=raw,driver_monitoring_available=False,
                        driver_visibility="face_visible" if visible else "poor_or_absent_face",
                        driver_frame_id=frame.frame_id,driver_capture_timestamp_ns=frame.timestamp_sof,
                        driver_frame_age_ms=(time.monotonic_ns()-frame.timestamp_sof)/1e6,
                        last_driver_timing=result["timing"],
                        driver_monitoring_reason="provisional_geometry" if visible else "poor_or_absent_face")
      now=time.monotonic()
      if now-last_report>=1:
        sensor_status = json.loads(str(supervisor.workerStatus("sensord")))
        if sensor_status.get("state") in ("failed", "dead", "stopped", "finished"):
          raise RuntimeError("Sensor worker failed: "+str(sensor_status))
        try:
          sensors = json.loads((root/"sensors.json").read_text())
        except (OSError, ValueError):
          sensors = {}
        report["sensors"] = sensors
        if sensors:
          if time.monotonic_ns()-sensors.get("report_monotonic_ns", 0)>2_000_000_000:
            raise RuntimeError("Sensor publication stalled")
        elif time.monotonic()-sensor_start>15:
          raise RuntimeError("Sensor publication startup timed out")
        if time.monotonic()-sensor_start>15:
          health = input_health.update(sensors.get("sensor_inputs_healthy"),time.monotonic())
          report["input_health"] = health
          if health == "degraded":report["pipeline_state"]="degraded"
          if health == "failed":raise RuntimeError("Persistent IMU input loss: "+str(sensors.get("age_ms")))
        generation = sensors.get("clock_generation")
        if sensor_clock_generation is not None and generation != sensor_clock_generation:
          # A suspend invalidates recurrent history and any prior timing qualification.
          road = None
          report.update(road_inference_available=False, road_model_unavailable_reason="sensor_clock_discontinuity")
          previous_pair = (0, 0)
          report["temporal_resets"] = report.get("temporal_resets", 0)+1
        sensor_clock_generation = generation
        if (not location_started and not location_retired and road is not None and sensors.get("sensor_inputs_healthy") is True and sensors.get("mount_calibrated") is True
            and camera.get("calibration_validated") is True):
          supervisor.startWorker("locationd", json.dumps({"SIMULATION":"0", "NOBOARD":"1"}))
          location_started = True
        if location_started:
          if road is None:
            supervisor.stopWorker("locationd")
            location_started = False
            location_retired = True
          else:
            location_status = json.loads(str(supervisor.workerStatus("locationd")))
            if location_status.get("state") != "running":raise RuntimeError("Localization worker failed: "+str(location_status))
        report.update(sensors=sensors, sensor_worker=sensor_status, pair_rejections=pair_rejections,
                      inference_process_pss_kib=int(debug.getPss()), timing_history_limit=4096,
                      timing_statistics="last_4096_samples",
                      native_snapshot_ms={"samples":frames.read_count,"mean_ms":frames.read_ns/max(1,frames.read_count)/1e6,"max_ms":frames.read_max_ns/1e6},
                      locationd_state="running" if location_started else "blocked_until_mount_and_camera_odometry_qualified")
        elapsed=now-active_start
        while driver_deliveries and driver_deliveries[0]<now-1:driver_deliveries.popleft()
        report["driver_fresh_outputs_last_second"]=len(driver_deliveries)
        report["driver_20hz_accepted"]=False
        if last_driver_timestamp:
          report["driver_frame_age_ms"]=(time.monotonic_ns()-last_driver_timestamp)/1e6
          if report["driver_frame_age_ms"]>250:
            report.update(driver_monitoring_reason="stale_cabin_input",driver_visibility="stale")
          elif len(driver_deliveries)<20:
            report["driver_monitoring_reason"]="insufficient_fresh_driver_rate"
          elif seat=="unset":report["driver_monitoring_reason"]="driver_seat_not_configured"
        monitoring_state.update(0)
        if monitoring_state.updated["driverMonitoringState"]:
          state=monitoring_state["driverMonitoringState"]
          report["monitoring_policy"]={"valid":monitoring_state.valid["driverMonitoringState"],
              "alert_level":str(state.alertLevel),"active_policy":str(state.activePolicy),
              "face_detected":state.visionPolicyState.faceDetected,"is_distracted":state.visionPolicyState.isDistracted,
              "available":False,"stationary_disengaged":True}
        if supervisor is not None and driver is not None:
          monitoring=json.loads(str(supervisor.workerStatus("dmonitoringd")))
          if monitoring.get("state") in ("failed","dead","stopped","finished"):
            raise RuntimeError("Monitoring worker failed: "+str(monitoring))
          report["monitoring_worker"]=monitoring
        report.update(road_model_fps=report["frames"]/elapsed,driver_model_fps=report["driver_frames"]/elapsed,
                      fresh_capture_pair_fps=report.get("fresh_capture_pairs",0)/elapsed,
                      road_timing=timing_summary(road_times),driver_timing=timing_summary(driver_times),camera=camera,
                      gpu_schedule="single_owner_road_priority",warmup_excluded=True)
        progress();last_report=now
      if not road_ran:time.sleep(.002)
    progress({"state":"completed","road_timing":timing_summary(road_times),"driver_timing":timing_summary(driver_times),
              "pair_skew":timing_summary(skews),"frame_age":timing_summary(frame_ages),
              "compute_budget_met":bool(road_times) and timing_summary(road_times)["p95_ms"]<=50,
              "camera_timing_accepted":bool(skews) and max(skews)<=10 and report.get("road_model_fps",0)>=19.5,
              "verification_passed":False})
    _write(root/"verification.json",report)
  except Exception as e:
    import traceback
    progress({"state":"failed","error":str(e),"traceback":traceback.format_exc(),"verification_passed":False})
    _write(root/"verification.json",report)
    raise
  finally:
    if supervisor is not None:
      supervisor.stopWorker("sensord")
    performance_class = locals().get("performance")
    if performance_class is not None:performance_class.close()
