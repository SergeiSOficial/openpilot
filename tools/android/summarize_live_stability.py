"""Summarize collected text-only Android evidence; never qualifies a backend."""
import argparse
import json
from pathlib import Path


def summarize(directory):
  directory = Path(directory)
  def read(name):
    path = directory/name
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
  report = read("verification.json") or read("progress.json")
  samples = []
  path = directory/"samples.jsonl"
  if path.is_file():
    for line in path.read_text(encoding="utf-8-sig").splitlines():
      if line.strip():samples.append(json.loads(line))
  camera = read("camera.json")
  cleanup = read("sensor-cleanup.json").get("cleanup", {})
  sensors = report.get("sensors", {})
  thermal = [sample["camera"]["thermal_status"] for sample in samples if "thermal_status" in sample.get("camera", {})]
  if isinstance(camera.get("thermal_status"),int):thermal.append(camera["thermal_status"])
  def memory_range(key, nested=False):
    values = [(sample.get("camera", {}) if nested else sample).get(key) for sample in samples]
    values = [value for value in values if isinstance(value, (int, float))]
    return {"min": min(values), "max": max(values), "last": values[-1]} if values else None
  return {"session": directory.name, "mode": report.get("mode"), "state": report.get("state"),
    "error": report.get("error"), "elapsed_seconds": report.get("elapsed_seconds"),
    "pipeline_state": report.get("pipeline_state"), "road_inference_available": report.get("road_inference_available", False),
    "road_blocker": report.get("road_model_unavailable_reason"),
    "road_frames": report.get("frames"), "driver_frames": report.get("driver_frames"),
    "driver_model_fps": report.get("driver_model_fps"), "driver_timing": report.get("driver_timing"),
    "imu_published": sensors.get("published"), "imu_healthy_at_last_report": sensors.get("sensor_inputs_healthy"),
    "clock_discontinuities": sensors.get("clock_discontinuities"),
    "mount_calibrated": sensors.get("mount_calibrated", False),
    "gnss_fix_state": sensors.get("hardware", {}).get("gnss", {}).get("fix_state"),
    "thermal_status_max": max(thermal) if thermal else None,
    "degraded_report_samples": sum(sample.get("pipeline_state") == "degraded" for sample in samples),
    "inference_pss_kib": memory_range("inference_process_pss_kib"),
    "capture_pss_kib": memory_range("capture_process_pss_kib", True),
    "streams": camera.get("native", {}).get("streams", []), "sensor_cleanup": cleanup,
    "sensor_cleanup_passed": cleanup.get("closed") is True and all(cleanup.get(key) is False for key in
      ("thread_alive", "sensor_listener_registered", "location_listener_registered", "status_callback_registered", "raw_callback_registered")),
    "verification_passed": report.get("verification_passed", False)}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("session", type=Path)
  parser.add_argument("--output", type=Path)
  args = parser.parse_args()
  text = json.dumps(summarize(args.session), indent=2, allow_nan=False)+"\n"
  if args.output:args.output.write_text(text, encoding="utf-8")
  else:print(text, end="")


if __name__ == "__main__":main()
