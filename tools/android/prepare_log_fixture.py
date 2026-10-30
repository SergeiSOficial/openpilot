"""Select 60 matching encoded camera frames and retain their real initialization/log inputs."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "tools/android/.cache/fixture"
CAMERAS = {"narrowRoadCameraState": "narrowRoadEncodeIdx", "wideRoadCameraState": "wideRoadEncodeIdx"}

def main():
  import capnp
  import zstandard
  parser = capnp.SchemaParser()
  schema = parser.load(str(ROOT / "openpilot/cereal/log.capnp"), imports=[str(ROOT / "opendbc_repo/opendbc/car")])
  with (CACHE / "rlog.zst").open("rb") as compressed, zstandard.ZstdDecompressor().stream_reader(compressed) as reader:
    raw = reader.read()
  messages = list(schema.Event.read_multiple_bytes(raw, traversal_limit_in_words=2**64-1))
  maps = {camera: {} for camera in CAMERAS}
  states = {camera: {} for camera in CAMERAS}
  for msg in messages:
    kind = msg.which()
    for camera, encode in CAMERAS.items():
      if kind == encode:
        index = getattr(msg, kind)
        if index.segmentNum == 1:
          maps[camera][index.frameId] = index.segmentId
  for msg in messages:
    kind = msg.which()
    if kind in CAMERAS:
      frame = getattr(msg, kind)
      if frame.frameId in maps[kind]:
        states[kind][maps[kind][frame.frameId]] = msg
  frame_ids = sorted(set(states["narrowRoadCameraState"]) & set(states["wideRoadCameraState"]))[:60]
  if len(frame_ids) != 60:
    raise RuntimeError("The public segment does not contain 60 synchronized frame pairs")
  end = max(states[camera][index].logMonoTime for camera in CAMERAS for index in frame_ids)
  selected = []
  init_types = {"carParams", "extrinsicsCalibration", "vehicleParameters", "driverMonitoringState", "pandaStates",
                "deviceState", "peripheralState", "managerState"}
  included = set()
  for index, msg in enumerate(messages):
    kind = msg.which()
    keep = msg.logMonoTime <= end
    if kind in CAMERAS:
      keep = maps[kind].get(getattr(msg, kind).frameId) in frame_ids
    if kind in CAMERAS.values():
      keep = getattr(msg, kind).segmentNum == 1 and getattr(msg, kind).segmentId in frame_ids
    if kind in init_types and kind not in included:
      keep = True
    if keep:
      included.add(kind)
      selected.append(msg)
  path = CACHE / "fixture.rlog"
  with path.open("wb") as output:
    for msg in sorted(selected, key=lambda m: m.logMonoTime):
      output.write(msg.as_builder().to_bytes())
  manifest = {"schema": 1, "frame_ids": frame_ids, "messages": len(selected),
              "log_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "maximum_camera_timestamp_difference_ns": max(abs(states["narrowRoadCameraState"][index].narrowRoadCameraState.timestampSof
                    - states["wideRoadCameraState"][index].wideRoadCameraState.timestampSof) for index in frame_ids)}
  (CACHE / "selection.json").write_text(json.dumps(manifest, indent=2) + "\n")
  print(json.dumps(manifest))

if __name__ == "__main__":
  main()
