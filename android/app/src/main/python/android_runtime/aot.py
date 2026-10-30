"""Build-time capture and Android dispatch for tinygrad's C CPU kernels.

The runtime compiler is a strict lookup: an uncaptured kernel is an error.
"""
import ctypes
import hashlib
import json
from pathlib import Path
import re

def kernel_id(source: str) -> str:
  return hashlib.sha256(source.encode()).hexdigest()

def capture(directory: str) -> None:
  from tinygrad.runtime.support.compiler_cpu import ClangCompiler
  out = Path(directory)
  out.mkdir(parents=True, exist_ok=True)
  original = ClangCompiler.compile

  def compile_and_export(self, source):
    key = kernel_id(source)
    # Each generated translation unit has one exported kernel and may contain helpers.
    matches = re.findall(r"(?m)^void (\w+)\(", source)
    if len(matches) != 1:
      raise RuntimeError(f"Cannot identify a unique exported C kernel: {matches}")
    renamed = re.sub(r"\b" + re.escape(matches[0]) + r"\b", "op_" + key, source)
    (out / (key + ".c")).write_text(renamed, encoding="utf-8")
    # Match the packaged library's arithmetic; host-native fused operations can
    # otherwise round differently from generic Android x86 and ARM targets.
    previous = self.args
    self.args = [*previous, "-ffp-contract=off"]
    try:
      return original(self, source)
    finally:
      self.args = previous

  ClangCompiler.compile = compile_and_export

def install(library_path: str, *, allow_qualified: bool = True) -> None:
  if allow_qualified:
    from android_runtime.cpu_backend import select
    library_path = select(library_path)
  from tinygrad.runtime.support.compiler_cpu import ClangCompiler
  from tinygrad.runtime.ops_cpu import CPUProgram
  library = ctypes.CDLL(library_path)

  def lookup(self, source):
    key = kernel_id(source)
    if not hasattr(library, "op_" + key):
      raise RuntimeError(f"Missing packaged Android CPU kernel {key}; rebuild the AOT bundle")
    return ("ANDROID_AOT:" + key).encode()

  def initialize(self, dev, obj):
    marker = b"ANDROID_AOT:"
    if not obj.lib.startswith(marker):
      raise RuntimeError("Android requires a retargeted AOT model artifact")
    self.dev, self.name, self.signature, self.profile_key = dev, obj.name, obj.signature, obj.profile_key
    self.lvp = False
    self.fxn = getattr(library, "op_" + obj.lib[len(marker):].decode())
    self.fxn.restype = None

  ClangCompiler.compile = lookup
  CPUProgram.__init__ = initialize

def manifest(directory: str, output: str) -> None:
  files = sorted(Path(directory).glob("*.c"))
  Path(output).write_text(json.dumps({"schema": 1, "kernels": [file.stem for file in files]}, indent=2) + "\n")
