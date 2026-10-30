"""Stage immutable live inputs and source identity; no host model execution/codegen.

The retained CPU certificate remains historical. GPU certification is mandatory
on the Android device before RoadRunner accepts any live camera frame.
"""
from pathlib import Path
import hashlib
import json
import shutil
from provenance import source_manifest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "android/app/src/main/assets/generated/live"


def live_sources():
    sources = source_manifest()
    for folder in ("android/app/src/main/java", "android/app/src/main/cpp", "android/app/src/main/aidl"):
        for path in (ROOT/folder).rglob("*"):
            if path.is_file() and path.suffix in (".java", ".cc", ".h", ".aidl", ".txt"):
                sources[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("android/app/build.gradle", "android/app/src/main/AndroidManifest.xml"):
        sources[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    return sources


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT/"openpilot/selfdrive/modeld/models/dmonitoring_model.onnx"
    if source.stat().st_size < 1000000:
        raise RuntimeError("Driver model is missing or a Git LFS pointer")
    shutil.copy2(source, OUT/source.name)
    sources = live_sources()
    build = {"schema": 1, "mode": "live-shadow-bootstrap", "source_sha256": sources,
             "current_source_certified": False, "requires_on_target_numerical_gate": True,
             "retained_reference_source": json.loads((ROOT/"android/app/src/main/assets/generated/model/build.json").read_text())["source_sha256"]}
    (OUT/"live-build.json").write_text(json.dumps(build, indent=2)+"\n", encoding="utf-8")
    hashes = {name: hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in (source.name, "live-build.json")}
    (OUT/"manifest.json").write_text(json.dumps({"schema": 1, "sha256": hashes}, indent=2)+"\n", encoding="utf-8")
    print("Staged original driver model and current live source identity; target numerical gate remains required")


if __name__ == "__main__":
    main()
