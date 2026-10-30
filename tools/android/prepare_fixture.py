"""Download the pinned public replay segment and prepare canonical camera frames."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://commadataci.blob.core.windows.net/openpilotci/98395b7c5b27882e/0000002b--2686b5a2d0/1/"
NAMES = ("rlog.zst", "fcamera.hevc", "ecamera.hevc")
CACHE = ROOT / "tools/android/.cache/fixture"

def sha256(path):
  with path.open("rb") as stream:
    return hashlib.file_digest(stream, "sha256").hexdigest()

def download():
  CACHE.mkdir(parents=True, exist_ok=True)
  manifest = {"schema": 1, "route": "98395b7c5b27882e|0000002b--2686b5a2d0", "segment": 1, "files": {}}
  pinned_path = ROOT / "tools/android/fixture.sources.json"
  pinned = json.loads(pinned_path.read_text()) if pinned_path.exists() else None
  for name in NAMES:
    dest = CACHE / name
    if not dest.exists():
      partial = dest.with_suffix(dest.suffix + ".partial")
      with urllib.request.urlopen(BASE + name, timeout=120) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output)
      partial.replace(dest)
    digest = sha256(dest)
    if pinned and digest != pinned["files"][name]["sha256"]:
      raise RuntimeError(f"Fixture checksum mismatch: {name}")
    manifest["files"][name] = {"url": BASE + name, "bytes": dest.stat().st_size, "sha256": digest}
  (CACHE / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
  print("Public fixture downloads verified")

def prepare():
  import ffmpeg
  import numpy as np
  import sys
  sys.path.insert(0, str(ROOT))
  from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
  binaries = Path(ffmpeg.BIN_DIR)
  selection = json.loads((CACHE / "selection.json").read_text()) if (CACHE / "selection.json").exists() else {"frame_ids": list(range(60))}
  frame_ids = selection["frame_ids"]
  result = {"schema": 1, "frame_pairs": 60, "sources": json.loads((CACHE / "sources.json").read_text()), "cameras": {}}
  for name, camera in (("fcamera.hevc", "narrowRoadCameraState"), ("ecamera.hevc", "wideRoadCameraState")):
    video = CACHE / name
    info = json.loads(subprocess.check_output([str(binaries / "ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(video)]))["streams"][0]
    width, height = info["width"], info["height"]
    stride, y_height, uv_height, size = get_nv12_info(width, height)
    folder = CACHE / camera
    folder.mkdir(exist_ok=True)
    process = subprocess.Popen([str(binaries / "ffmpeg"), "-v", "error", "-i", str(video), "-frames:v", str(max(frame_ids) + 1),
                                "-f", "rawvideo", "-pix_fmt", "nv12", "pipe:1"], stdout=subprocess.PIPE)
    assert process.stdout is not None
    hashes = {}
    try:
      for index in range(max(frame_ids) + 1):
        frame = process.stdout.read(width * height * 3 // 2)
        if len(frame) != width * height * 3 // 2:
          raise RuntimeError(f"Missing canonical frame {index} in {name}")
        if index not in frame_ids:
          continue
        raw = np.frombuffer(frame, dtype=np.uint8)
        padded = np.zeros(size, dtype=np.uint8)
        padded[:stride*y_height].reshape(y_height, stride)[:height, :width] = raw[:width*height].reshape(height, width)
        padded[stride*y_height:stride*(y_height+uv_height)].reshape(uv_height, stride)[:height//2, :width] = raw[width*height:].reshape(height//2, width)
        dest = folder / f"{index:04}.nv12"
        dest.write_bytes(padded.tobytes())
        hashes[str(index)] = sha256(dest)
    finally:
      process.stdout.close()
      if process.wait() != 0:
        raise RuntimeError(f"FFmpeg failed for {name}")
    result["cameras"][camera] = {"width": width, "height": height, "stride": stride, "y_height": y_height,
                                  "uv_height": uv_height, "buffer_size": size, "sha256": hashes, "frame_ids": frame_ids}
  result["selection"] = selection
  (CACHE / "fixture.json").write_text(json.dumps(result, indent=2) + "\n")
  print("Prepared 60 canonical frame pairs")

if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--prepare", action="store_true")
  args = parser.parse_args()
  download()
  if args.prepare:
    prepare()
