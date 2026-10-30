"""Export only required host tools and their transitive dependencies from uv.lock."""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]
NAMES = {"numpy", "pycapnp", "comma-deps-capnproto", "comma-deps-acados", "comma-deps-ffmpeg", "comma-deps-eigen",
         "pyzmq", "cffi", "requests", "tqdm", "sympy", "zstandard", "pycryptodome", "setproctitle", "scons",
         "setuptools", "cython", "jeepney", "packaging"}

def main():
  packages = {package["name"]: package for package in tomllib.loads((ROOT / "uv.lock").read_text())["package"]}
  selected = set()
  pending = list(NAMES)
  while pending:
    name = pending.pop()
    if name in selected:
      continue
    package = packages[name]
    if "version" not in package or "registry" not in package.get("source", {}):
      raise RuntimeError(f"Host dependency needs an explicit recipe: {name}")
    selected.add(name)
    pending.extend(dependency["name"] for dependency in package.get("dependencies", []))
  lines = []
  for name in sorted(selected):
    package = packages[name]
    hashes = sorted({item["hash"] for item in [*package.get("wheels", []), *([package["sdist"]] if "sdist" in package else [])]})
    if not hashes:
      raise RuntimeError(f"No locked host download checksums for {name}")
    lines.append(f"{name}=={package['version']} " + " ".join(f"--hash={digest}" for digest in hashes) + "\n")
  output = ROOT / "tools/android/.cache/host-requirements.txt"
  output.parent.mkdir(parents=True, exist_ok=True)
  output.write_text("".join(lines))
  print(f"Exported {len(selected)} locked host dependencies")

if __name__ == "__main__":
  main()
