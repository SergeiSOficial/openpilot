"""Stage original ONNX bytes for isolated on-Android acceleration experiments.

Standard library only. Historical reference certificates are not regenerated or
relabelled. Every candidate must pass numerical tests on the target device.
"""
import hashlib
import json
from pathlib import Path
import shutil
import argparse

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tools/android/.cache/acceleration-assets/acceleration"


def sources():
    from provenance import source_manifest
    result = source_manifest()
    for directory in ("android/app/src/main/java", "android/app/src/main/cpp", "android/app/src/androidTest", "android/app/src/accelerationTest", "android/app/src/qnnTest"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in (".java", ".py", ".cc", ".h", ".txt"):
                result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def graph_bundle(directory,role):
    """Preflight a graph selection before changing the previous private stage."""
    from qnn_graph import model_config
    metadata=json.loads((directory/"manifest.json").read_text())
    if metadata.get("model_role","road")!=role:raise ValueError("QNN graph model role differs")
    if metadata.get("source",{}).get("sha256")!=model_config(role)["sha256"]:
        raise ValueError("QNN graph original model identity differs")
    for name,expected in metadata["sha256"].items():
        if Path(name).name!=name:raise ValueError("Invalid graph asset name")
        with (directory/name).open("rb") as stream:actual=hashlib.file_digest(stream,"sha256").hexdigest()
        if actual!=expected:raise ValueError("Graph asset changed: "+name)
    return metadata


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--qualified-cpu",action="store_true")
    parser.add_argument("--qnn-quantized",action="store_true")
    parser.add_argument("--model",choices=("road","cabin"),default="road")
    parser.add_argument("--graph-root",type=Path,help="explicit separately prepared graph variant directory")
    args=parser.parse_args()
    if args.model == "cabin" and args.qualified_cpu:
        parser.error("The retained CPU qualification belongs to the road model")
    graph_root=metadata=None
    if args.qnn_quantized:
        graph_root=args.graph_root or ROOT/"tools/android/.cache"/("qnn-quantized" if args.model=="road" else "qnn-quantized-cabin")
        if not graph_root.is_absolute():graph_root=ROOT/graph_root
        metadata=graph_bundle(graph_root,args.model)
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "openpilot/selfdrive/modeld/models/driving_supercombo.onnx"
    expected = json.loads((ROOT / "tools/android/.cache/model-aot/provenance.json").read_text())["model_sha256"]
    actual = hashlib.file_digest(source.open("rb"), "sha256").hexdigest()
    if actual != expected:
        raise RuntimeError("Original ONNX differs from the retained CPU reference model")
    shutil.copy2(source, OUT / source.name)
    libraries = {}
    for directory in (ROOT / "android/app/src/main/jniLibs", ROOT / "tools/android/.cache/tuned/jniLibs",
                      ROOT / "tools/android/.cache/parallel/jniLibs"):
        for library in directory.glob("*/*.so"):
            if library.name.startswith("libopenpilot_kernels"):
                with library.open("rb") as stream:
                    libraries[library.parent.name+"/"+library.name] = hashlib.file_digest(stream,"sha256").hexdigest()
    assets={source.name:actual}
    if args.model == "cabin":
        from qnn_graph import model_config
        config=model_config("cabin")
        cabin=ROOT/"openpilot/selfdrive/modeld/models"/config["file"]
        with cabin.open("rb") as stream:cabin_hash=hashlib.file_digest(stream,"sha256").hexdigest()
        if cabin_hash!=config["sha256"]:raise ValueError("Original cabin ONNX identity differs")
        shutil.copy2(cabin,OUT/cabin.name);assets[cabin.name]=cabin_hash
    # Clear only files named by the preceding experiment's private manifest.
    prior=OUT/"qnn-graph-manifest.json"
    if prior.exists():
        for name in json.loads(prior.read_text()).get("sha256",{}):
            if Path(name).name==name and name!=source.name:(OUT/name).unlink(missing_ok=True)
        prior.unlink()
    if args.qnn_quantized:
        for name,expected in metadata["sha256"].items():
            if Path(name).name!=name:raise ValueError("Invalid graph asset name")
            path=graph_root/name
            with path.open("rb") as stream:actual_graph=hashlib.file_digest(stream,"sha256").hexdigest()
            if actual_graph!=expected:raise ValueError("Graph asset changed: "+name)
            shutil.copy2(path,OUT/name);assets[name]=expected
        shutil.copy2(graph_root/"manifest.json",prior)
        assets[prior.name]=hashlib.sha256(prior.read_bytes()).hexdigest()
    qualification=OUT/"cpu-qualification.json"
    if args.qualified_cpu:
        shutil.copy2(ROOT/"tools/android/.cache/cpu-qualification.json",qualification)
        certificate=json.loads(qualification.read_text())
        for abi,expected in certificate["libraries_sha256"].items():
            if libraries.get(abi+"/"+certificate["library"])!=expected:
                raise RuntimeError("Qualified CPU binary changed; repeat target verification")
        assets[qualification.name]=hashlib.sha256(qualification.read_bytes()).hexdigest()
    elif qualification.exists():qualification.unlink()
    (OUT / "manifest.json").write_text(json.dumps({
        "schema": 1, "model_role": args.model, "sha256": assets, "source_sha256": sources(),
        "current_source_certified": False, "requires_on_target_numerical_gate": True,
        "native_candidates_sha256": libraries,
        "retained_cpu_reference_sha256": hashlib.sha256((ROOT / "tools/android/.cache/model-aot/reference.npz").read_bytes()).hexdigest(),
    }, indent=2) + "\n", encoding="utf-8")
    print("Staged original ONNX and source identity; no host inference or code generation")


if __name__ == "__main__":
    main()
