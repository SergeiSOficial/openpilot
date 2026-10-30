"""Run the current location and MPC generators on the host, writing only build-cache artifacts."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import argparse

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), *[str(ROOT / name) for name in ("opendbc_repo", "rednose_repo", "tinygrad_repo", "msgq_repo")]]
os.environ["OPENPILOT_ANDROID_NATIVE_DIR"] = str(Path(os.environ.get("OPENPILOT_ANDROID_CACHE", Path.home() / ".cache/openpilot-android")) / "host-params")

def generator(path):
  tree = ast.parse(path.read_text(), filename=str(path))
  last = tree.body[-1]
  if not isinstance(last, ast.If) or "__main__" not in ast.unparse(last.test):
    raise RuntimeError(f"Unexpected generator entry point: {path}")
  tree.body.pop()  # Load its real code-generation imports without invoking a source-tree output path.
  namespace = {"__name__": "__main__", "__file__": str(path)}
  exec(compile(tree, str(path), "exec"), namespace)
  return namespace

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--mpc-only", action="store_true")
  args = parser.parse_args()
  import acados
  import eigen
  os.environ.update(ACADOS_SOURCE_DIR=acados.DIR, ACADOS_PYTHON_INTERFACE_PATH=acados.TEMPLATE_DIR, TERA_PATH=acados.TERA_PATH)
  out = ROOT / "tools/android/.cache/generated"
  location = out / "locationd"
  location.mkdir(parents=True, exist_ok=True)
  sources = []
  for name, cls in (("pose", "PoseKalman"), ("car", "CarKalman")):
    source = ROOT / f"openpilot/selfdrive/locationd/models/{name}_kf.py"
    if not args.mpc_only:
      namespace = generator(source)
      namespace[cls].generate_code(str(location))
    sources.append(source)
  mpc = out / "longitudinal_mpc"
  mpc.mkdir(parents=True, exist_ok=True)
  source = ROOT / "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py"
  namespace = generator(source)
  namespace["EXPORT_DIR"] = str(mpc)
  namespace["JSON_FILE"] = str(mpc / "acados_ocp_long.json")
  ocp = namespace["gen_long_ocp"]()
  namespace["AcadosOcpSolver"].generate(ocp, json_file=namespace["JSON_FILE"])
  sources.append(source)
  shutil.copytree(eigen.INCLUDE_DIR, ROOT / "tools/android/.cache/native-deps/eigen", dirs_exist_ok=True)
  (out / "sources.json").write_text(json.dumps({str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                              for path in sources}, indent=2) + "\n")
  print("Generated current pose/car filters and longitudinal MPC")

if __name__ == "__main__":
  main()
