"""Bind successful Android sequence evidence to the actual selected ELF bytes."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--phone",type=Path,required=True)
    parser.add_argument("--emulator",type=Path,required=True)
    args=parser.parse_args()
    libraries,evidence={},{}
    for abi,path in (("arm64-v8a",args.phone),("x86_64",args.emulator)):
        report=json.loads(path.read_text())
        if not report.get("passed") or report.get("error") or report.get("frames")!=60:
            raise RuntimeError("Candidate did not pass all60frames: "+str(path))
        if not report.get("zero_gate",{}).get("passed") or not report.get("sequence_gate",{}).get("passed"):
            raise RuntimeError("Missing model/state numerical gate")
        library=ROOT/f"tools/android/.cache/parallel/jniLibs/{abi}/libopenpilot_kernels_parallel.so"
        actual=hashlib.sha256(library.read_bytes()).hexdigest()
        if actual!=report["kernel_sha256"]:raise RuntimeError("Evidence is for another compiled library")
        libraries[abi]=actual
        evidence[abi]={"report":path.resolve().relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                       "timing":report["timing"],"zero_gate":report["zero_gate"],"sequence_gate":report["sequence_gate"]}
    model=ROOT/"android/app/src/main/assets/generated/model"
    assets=json.loads((model/"manifest.json").read_text())["sha256"]
    result={"schema":1,"passed":True,"frames":60,"library":"libopenpilot_kernels_parallel.so",
            "libraries_sha256":libraries,"evidence":evidence,
            "model_sha256":json.loads((model/"provenance.json").read_text())["model_sha256"],
            "model_assets_sha256":{name:assets[name] for name in ("driving_tinygrad.pkl","reference.npz","kernels.json","provenance.json")},
            "scope":"on-target model/warp/recurrent equivalence; full daemon regression remains separately required"}
    destination=ROOT/"tools/android/.cache/cpu-qualification.json"
    destination.write_text(json.dumps(result,indent=2)+"\n")
    print("Qualified exact ELF bytes for both Android ABIs; full replay must still pass")


if __name__=="__main__":main()
