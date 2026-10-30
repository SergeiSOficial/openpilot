"""Android sensor publisher. Host import is stdlib-only; Java opens on target."""
import json
import math
from pathlib import Path
import time

from android_runtime.live_policy import ClockNormalizer, transform, validate_mount


def load_mount(path):
  try:
    profile = json.loads(Path(path).read_text())
    return profile if validate_mount(profile) else None
  except (OSError, ValueError, TypeError):
    return None


def write_report(root, report):
  target = Path(root)/"sensors.json"
  temporary = target.with_suffix(".tmp")
  temporary.write_text(json.dumps(report, allow_nan=False))
  temporary.replace(target)


def main():
  import os
  from java import jclass
  from openpilot.cereal import messaging
  root = Path(os.environ["OPENPILOT_ANDROID_ROOT"])
  bridge = jclass("ai.comma.openpilot.sim.LiveSensorBridge")
  clock = jclass("android.os.SystemClock")
  system = jclass("java.lang.System")
  profile = load_mount(root.parents[1]/"mount-calibration.json")
  normalizer = ClockNormalizer()
  pm = messaging.PubMaster(["accelerometer", "gyroscope", "gpsLocation"])
  published = {key: 0 for key in ("accelerometer", "gyroscope", "gpsLocation")}
  rejected = 0
  last_report = last_gps = 0.
  last_sample = {}
  latest_bias = None
  try:
    while True:
      camera_path = root/"camera.json"
      try:
        camera = json.loads(camera_path.read_text())
      except (OSError, ValueError):
        camera = {}
      if camera.get("state") in ("failed", "stopped") or camera.get("thermal_status", 0) >= 4:
        break
      batch = json.loads(str(bridge.drain()))
      before = int(system.nanoTime())
      now_boot = int(clock.elapsedRealtimeNanos())
      after = int(system.nanoTime())
      now_mono = (before+after)//2
      if after-before>1_000_000:
        # Preemption between Java calls is not proof of a suspend discontinuity.
        rejected += sum(len(samples) for samples in batch.values())
        time.sleep(.01)
        continue
      for channel in ("accelerometer", "gyroscope"):
        for sample in batch[channel]:
          timestamp = normalizer.normalize(sample["timestamp_ns"], now_boot, now_mono, 100_000_000)
          if timestamp is None:
            rejected += 1
            continue
          if time.monotonic_ns()-timestamp>100_000_000:
            rejected += 1
            continue
          packet = messaging.new_message(channel)
          packet.valid = profile is not None
          sensor = getattr(packet, channel)
          sensor.timestamp = timestamp
          sensor.source = "android"
          values = sample["value"]
          if profile:
            values = transform(values, profile["rotation_android_to_sensor"])
          sensor.init("acceleration" if channel == "accelerometer" else "gyroUncalibrated").v = values
          pm.send(channel, packet)
          published[channel] += 1
          last_sample[channel] = timestamp
          if channel == "gyroscope":
            latest_bias = sample.get("bias")
      for fix in batch["gps"]:
        timestamp = normalizer.normalize(fix["timestamp_ns"], now_boot, now_mono, 2_000_000_000)
        if timestamp is None or fix["mock"]:
          rejected += 1
          continue
        packet = messaging.new_message("gpsLocation")
        packet.logMonoTime = timestamp
        gps = packet.gpsLocation
        gps.source = "android"
        gps.latitude, gps.longitude = fix["latitude_deg"], fix["longitude_deg"]
        gps.unixTimestampMillis = fix["utc_time_ms"]
        gps.hasFix = fix.get("horizontal_accuracy_m") is not None
        gps.flags = 1 if gps.hasFix else 0
        fields = {"horizontalAccuracy": "horizontal_accuracy_m", "altitude": "altitude_wgs84_m",
                  "verticalAccuracy": "vertical_accuracy_m", "speed": "speed_m_s", "speedAccuracy": "speed_accuracy_m_s",
                  "bearingDeg": "bearing_deg", "bearingAccuracyDeg": "bearing_accuracy_deg"}
        complete = True
        for field, key in fields.items():
          value = fix.get(key)
          if value is None or not math.isfinite(value):
            complete = False
          else:
            setattr(gps, field, value)
        packet.valid = bool(gps.hasFix and complete)
        # Android supplies no measured vertical velocity: do not fabricate vNED.
        pm.send("gpsLocation", packet)
        published["gpsLocation"] += 1
        last_gps = time.monotonic()
      now = time.monotonic()
      if now-last_gps >= 1:
        packet = messaging.new_message("gpsLocation")
        packet.valid = False
        packet.gpsLocation.source = "android"
        packet.gpsLocation.hasFix = False
        pm.send("gpsLocation", packet)
        last_gps = now
      if now-last_report >= 1:
        health = json.loads(str(bridge.status()))
        report_now = time.monotonic_ns()
        write_report(root, {"schema": 1, "state": "running", "published": published,
          "report_monotonic_ns": time.monotonic_ns(),
          "mount_calibrated": profile is not None, "calibration_id": profile["calibration_id"] if profile else None,
          "coordinate_frame": "openpilot_sensor" if profile else "raw_android_invalid_for_localization",
          "clock_generation": normalizer.generation, "clock_discontinuities": normalizer.discontinuities,
          "rejected_at_publication": rejected, "last_gyro_bias_android": latest_bias,
          "age_ms": {key: (report_now-ts)/1e6 for key, ts in last_sample.items()},
          "sensor_inputs_healthy": all(key in last_sample and 0 <= report_now-last_sample[key] <= 100_000_000 for key in ("accelerometer", "gyroscope")),
          "locationd_validated": False, "hardware": health})
        last_report = now
      time.sleep(.01)
  finally:
    bridge.stop()
    health = json.loads(str(bridge.status()))
    write_report(root, {"schema": 1, "state": "stopped", "published": published,
      "mount_calibrated": profile is not None, "clock_discontinuities": normalizer.discontinuities,
      "locationd_validated": False, "hardware": health})
