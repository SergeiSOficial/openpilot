"""Fail APK assembly if fixture/reference/model checksums or ABI kernel exports are incomplete."""
import hashlib
import json
from pathlib import Path
import struct
import zipfile
import argparse

ROOT = Path(__file__).resolve().parents[2]

def digest(path):
  result = hashlib.sha256()
  with path.open("rb") as stream:
    for block in iter(lambda: stream.read(1024*1024), b""):
      result.update(block)
  return result.hexdigest()

def elf_exports(path, machine):
  data = path.read_bytes()
  if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != machine:
    raise RuntimeError(f"Wrong ELF architecture: {path}")
  offset = struct.unpack_from("<Q", data, 40)[0]
  size, count = struct.unpack_from("<HH", data, 58)
  sections = [struct.unpack_from("<IIQQQQIIQQ", data, offset+i*size) for i in range(count)]
  names = set()
  for section in sections:
    if section[1] != 11:
      continue
    strings = sections[section[6]]
    table = data[strings[4]:strings[4]+strings[5]]
    for start in range(section[4], section[4]+section[5], section[9]):
      name, _, _, index, _, _ = struct.unpack_from("<IBBHQQ", data, start)
      if index and name:
        names.add(table[name:table.index(b"\0", name)].decode())
  return names

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--check-source", action="store_true")
  args = parser.parse_args()
  assets = ROOT / "android/app/src/main/assets/generated"
  manifest = json.loads((assets / "model/manifest.json").read_text())["sha256"]
  for name, expected in manifest.items():
    if digest(assets / "model" / name) != expected:
      raise RuntimeError(f"Corrupted model/schema asset: {name}")
  fixture = json.loads((assets / "fixture/manifest.json").read_text())
  archive = assets / "fixture/fixture.zip"
  if digest(archive) != fixture["sha256"]:
    raise RuntimeError("Corrupted fixture archive")
  with zipfile.ZipFile(archive) as bundle:
    reference = json.loads(bundle.read("reference.json"))
    if hashlib.sha256(bundle.read("reference.rlog")).hexdigest() != reference["output_sha256"]:
      raise RuntimeError("Corrupted desktop reference")
  metadata = json.loads((assets / "model/build.json").read_text())
  if args.check_source:
    from provenance import source_sha256
    if source_sha256() != metadata["source_sha256"]:
      raise RuntimeError("Source changed after staging; regenerate the model gate and desktop reference")
    protocol = json.loads((ROOT / "android/app/src/main/assets/panda/protocol.json").read_text())
    expected_sources = {"panda/board/health.h", "opendbc_repo/opendbc/safety/can.h", "panda/python/__init__.py"}
    if set(protocol["source_sha256"]) != expected_sources:
      raise RuntimeError("Unexpected Panda protocol source manifest")
    for name, expected in protocol["source_sha256"].items():
      if digest(ROOT / name) != expected:
        raise RuntimeError(f"Panda protocol metadata is stale: {name}; regenerate using generate_panda_protocol.py")
  gate = json.loads((ROOT / "tools/android/.cache/model-aot/verification.json").read_text())
  if not gate["passed"] or gate["source_sha256"] != metadata["source_sha256"]:
    raise RuntimeError("Model numerical build gate is missing or stale; run certify_model.py")
  for name, expected in gate["sha256"].items():
    if digest(assets / "model" / name) != expected:
      raise RuntimeError(f"Model numerical build gate does not cover {name}")
  if reference["source_sha256"] != metadata["source_sha256"] or reference["counts"].get("longitudinalPlan") != 60:
    raise RuntimeError("Desktop reference is stale or incomplete")
  kernels = json.loads((assets / "model/kernels.json").read_text())["kernels"]
  required = {"op_" + key for key in kernels}
  libraries = ("params_c", "pose", "car", "acados", "hpipm", "blasfeo", "acados_ocp_solver_long", "acados_ocp_solver_pyx", "openpilot_ipc")
  for abi, machine in (("x86_64", 62), ("arm64-v8a", 183)):
    directory = ROOT / "android/app/src/main/jniLibs" / abi
    symbols = elf_exports(directory / "libopenpilot_kernels.so", machine)
    if missing := required-symbols:
      raise RuntimeError(f"Missing packaged {abi} model kernels: {sorted(missing)}")
    for library in libraries:
      elf_exports(directory / f"lib{library}.so", machine)
  print(f"Verified model/fixture/reference checksums and {len(kernels)} kernel exports for both ABIs")

if __name__ == "__main__":
  main()
