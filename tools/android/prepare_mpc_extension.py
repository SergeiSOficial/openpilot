"""Generate the existing acados Cython adapter and stage ABI-specific Python/NumPy headers."""
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import os

ROOT = Path(__file__).resolve().parents[2]

def extract(zip_path, destination, prefixes):
  destination.mkdir(parents=True, exist_ok=True)
  with zipfile.ZipFile(zip_path) as archive:
    for item in archive.infolist():
      if item.is_dir() or not item.filename.startswith(prefixes):
        continue
      target = (destination / item.filename).resolve()
      if not target.is_relative_to(destination.resolve()):
        raise RuntimeError("Header archive escaped staging directory")
      target.parent.mkdir(parents=True, exist_ok=True)
      with archive.open(item) as source, target.open("wb") as output:
        shutil.copyfileobj(source, output)

def main():
  import acados
  out = ROOT / "tools/android/.cache/generated/longitudinal_mpc"
  pyx = Path(acados.TEMPLATE_DIR) / "acados_ocp_solver_pyx.pyx"
  shutil.copy2(pyx, out / pyx.name)
  shutil.copy2(Path(acados.TEMPLATE_DIR) / "acados_solver_common.pxd", out)
  subprocess.run([sys.executable, "-m", "cython", "-3", "-o", str(out / "acados_ocp_solver_pyx.c"),
                  "-I", str(out), "-I", str(acados.TEMPLATE_DIR), str(out / pyx.name)], check=True)
  for abi, tag in (("x86_64", "x86_64"), ("arm64-v8a", "arm64_v8a")):
    cache = Path(os.environ.get("OPENPILOT_ANDROID_CACHE", Path.home() / ".cache/openpilot-android"))
    relative = Path("chaquopy/maven/com/chaquo/python/target/3.12.15-0") / f"target-3.12.15-0-{abi}.zip"
    target = cache / relative
    if not target.is_file():
      target = ROOT / "tools/android/.cache" / relative
    deps = ROOT / f"tools/android/.cache/native-deps/python/{abi}"
    extract(target, deps, ("include/", "jniLibs/"))
    wheel = next((ROOT / "tools/android/.cache/wheels").glob(f"numpy-2.5.3-*-android_24_{tag}.whl"))
    extract(wheel, deps, ("numpy/_core/include/",))
  print("Generated MPC Python adapter and staged both ABI header sets")

if __name__ == "__main__":
  main()
