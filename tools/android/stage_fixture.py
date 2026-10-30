"""Package only selected canonical buffers and the trimmed raw log for offline replay."""
import hashlib
import json
from pathlib import Path
import zipfile
import shutil
from provenance import source_sha256

ROOT = Path(__file__).resolve().parents[2]

def main():
  source = ROOT / "tools/android/.cache/fixture"
  manifest = json.loads((source / "fixture.json").read_text())
  names = ["fixture.json", "fixture.rlog", "selection.json", "sources.json"]
  reference = ROOT / "tools/android/.cache/reference"
  report = json.loads((reference / "report.json").read_text())
  if report["source_sha256"] != source_sha256():
    raise RuntimeError("Desktop reference is stale; regenerate it from the current source")
  if report["counts"].get("modelV2") != 60 or report["counts"].get("longitudinalPlan") != 60 or not report["counts"].get("sendcan"):
    raise RuntimeError("Desktop reference did not complete the simulation acceptance path")
  shutil.copy2(reference / "outputs.rlog", source / "reference.rlog")
  shutil.copy2(reference / "report.json", source / "reference.json")
  names += ["reference.rlog", "reference.json"]
  for camera, info in manifest["cameras"].items():
    for index, expected in info["sha256"].items():
      name = f"{camera}/{int(index):04}.nv12"
      if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"Corrupted fixture buffer: {name}")
      names.append(name)
  output = ROOT / "android/app/src/main/assets/generated/fixture"
  output.mkdir(parents=True, exist_ok=True)
  archive = output / "fixture.zip"
  with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
    for name in names:
      entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
      entry.compress_type = zipfile.ZIP_DEFLATED
      bundle.writestr(entry, (source / name).read_bytes(), compresslevel=1)
  digest = hashlib.sha256(archive.read_bytes()).hexdigest()
  (output / "manifest.json").write_text(json.dumps({"schema": 1, "sha256": digest, "entries": len(names)}, indent=2) + "\n")
  print(f"Packaged {manifest['frame_pairs']} frame pairs, {archive.stat().st_size} bytes")

if __name__ == "__main__":
  main()
