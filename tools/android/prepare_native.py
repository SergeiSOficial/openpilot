"""Generate current schemas and stage headers needed by the Android parameter library."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def main():
  import capnproto
  deps = ROOT / "tools/android/.cache/native-deps"
  shutil.copytree(capnproto.INCLUDE_DIR, deps / "include", dirs_exist_ok=True)
  output = deps / "openpilot/cereal/gen/cpp"
  output.mkdir(parents=True, exist_ok=True)
  cereal = ROOT / "openpilot/cereal"
  cars = ROOT / "opendbc_repo/opendbc/car"
  compiler = str(Path(capnproto.BIN_DIR) / "capnp")
  env = {**os.environ, "PATH": str(capnproto.BIN_DIR) + os.pathsep + os.environ["PATH"]}
  subprocess.run([compiler, "compile", "--src-prefix=" + str(cereal), "--src-prefix=" + str(cars),
                  "--import-path=" + str(cars), "-oc++:" + str(output),
                  *[str(cereal / name) for name in ("log.capnp", "custom.capnp", "deprecated.capnp")], str(cars / "car.capnp")],
                 check=True, env=env)
  print("Generated current cereal schemas and staged Cap'n Proto headers")

if __name__ == "__main__":
  main()
