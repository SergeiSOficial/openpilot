"""Use one canonical C++ annotation schema after Android assets lose source-tree symlinks."""
from pathlib import Path
import difflib

ROOT = Path(__file__).resolve().parents[2]

def main():
  changes = []
  patched = set()
  for source, dest in ((ROOT / "openpilot/cereal", "openpilot/cereal"), (ROOT / "opendbc_repo/opendbc/car", "opendbc/car")):
    for path in source.glob("*.capnp"):
      original = path.read_text()
      updated = original
      for spelling in ('include/c++.capnp', './include/c++.capnp', '/include/c++.capnp'):
        updated = updated.replace(f'"{spelling}"', '"/capnp/c++.capnp"')
      if updated != original:
        relative = dest + "/" + path.name
        patched.add(relative)
        changes.extend(difflib.unified_diff(original.splitlines(True), updated.splitlines(True), fromfile="a/" + relative, tofile="b/" + relative))
  if not {"openpilot/cereal/log.capnp", "opendbc/car/car.capnp"}.issubset(patched):
    raise RuntimeError("Unexpected C++ annotation imports in current schemas")
  path = ROOT / "opendbc_repo/opendbc/car/structs.py"
  original = path.read_text()
  before = 'car = capnp.load(os.path.join(BASEDIR, "car.capnp"), imports=[BASEDIR])'
  after = '''imports = [BASEDIR]
schema_path = BASEDIR
if os.environ.get("OPENPILOT_ANDROID_ROOT"):
  schema_path = os.environ["OPENPILOT_ANDROID_SCHEMAS"]
  imports = [schema_path]
  imports.append(os.path.dirname(os.path.dirname(os.path.realpath(capnp.__file__))))
car = capnp.load(os.path.join(schema_path, "car.capnp"), imports=imports)'''
  if original.count(before) != 1:
    raise RuntimeError("Unexpected opendbc schema loader")
  changes.extend(difflib.unified_diff(original.splitlines(True), original.replace(before, after).splitlines(True),
                                    fromfile="a/opendbc/car/structs.py", tofile="b/opendbc/car/structs.py"))
  (ROOT / "tools/android/patches/schemas-android.patch").write_text("".join(changes), newline="\n")

if __name__ == "__main__":
  main()
