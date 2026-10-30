"""Select pure runtime dependencies from this checkout's existing lockfile."""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]
NAMES = {"requests", "sympy", "mpmath", "tqdm", "jeepney", "pycparser", "certifi", "charset-normalizer", "idna", "urllib3", "packaging"}

def main():
  packages = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
  versions = {p["name"]: p["version"] for p in packages if p["name"] in NAMES}
  if versions.keys() != NAMES:
    raise RuntimeError(f"Missing locked runtime versions: {NAMES - versions.keys()}")
  destination = ROOT / "tools/android/.cache/runtime-requirements.txt"
  destination.parent.mkdir(parents=True, exist_ok=True)
  destination.write_text("".join(f"{name}=={versions[name]}\n" for name in sorted(NAMES)))
  print(destination)

if __name__ == "__main__":
  main()
