"""Android-only OpenCL inference for the stationary live camera coordinator.

No model compiler, GPU backend or native library is opened on a desktop host.
The numerical probe is mandatory before RoadRunner accepts live camera frames.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import pickle
import sys
import time

_DEVICE = None


def configure():
  global _DEVICE
  if _DEVICE is not None:
    return _DEVICE
  if sys.platform != "linux" or not Path("/system/bin/app_process").exists():
    raise RuntimeError("OpenCL inference is restricted to the Android device")
  os.environ.update(DEV="CL", PARALLEL="0", CCACHE="0")
  from tinygrad.helpers import DEV, PARALLEL
  DEV.value, PARALLEL.value = "CL", 0
  from tinygrad.runtime.support.c import DLL
  # Android's public-library namespace resolves the soname declared in the APK
  # manifest. tinygrad's desktop directory scanner does not search that namespace.
  original_findlib = DLL.findlib
  DLL.findlib = staticmethod(lambda name, paths, extra_paths=():
                            "libOpenCL.so" if name == "opencl" else original_findlib(name, paths, extra_paths))
  from tinygrad import Device
  if any(name.split(":")[0] == "CPU" for name in Device._opened_devices):
    raise RuntimeError("GPU inference requires a separate worker with no CPU model backend")
  from tinygrad.renderer.cstyle import OpenCLRenderer
  from tinygrad.uop.ops import Ops

  class AndroidOpenCLRenderer(OpenCLRenderer):
    # Retained CPU lowering deliberately kept exact floating division. The
    # generic CL lowering normally decomposes FDIV before rendering; retained
    # sinks have already crossed that boundary and must keep the '/' operation.
    code_for_op = {**OpenCLRenderer.code_for_op, Ops.FDIV: lambda a, b, dtype: f"({a}/{b})"}

    def render(self, uops):
      return "#pragma OPENCL FP_CONTRACT OFF\n" + super().render(uops)

  device = Device["CL"]
  device.renderers = [AndroidOpenCLRenderer]
  device.cached_renderer.clear()
  if "cl_khr_fp16" not in device.device_exts:
    raise RuntimeError("The retained driving model requires cl_khr_fp16")
  _configure_cache(device)
  _DEVICE = device
  return device


def _configure_cache(device):
  """Private OpenCL cache qualified by verified assets, code and actual driver."""
  import importlib.util
  import marshal
  import tinygrad.helpers as helpers
  root = Path(os.environ["OPENPILOT_ANDROID_MODELS_ROOT"]).resolve(strict=True)
  manifest_path = root / "manifest.json"
  manifest_bytes = manifest_path.read_bytes()
  manifest = json.loads(manifest_bytes)
  hashes = manifest["sha256"]
  if not isinstance(hashes, dict) or not hashes:
    raise ValueError("GPU cache requires a nonempty installed asset manifest")
  for name, expected in sorted(hashes.items()):
    if not isinstance(name, str) or Path(name).name != name or not isinstance(expected, str) or len(expected) != 64:
      raise ValueError("Invalid GPU cache asset manifest entry")
    path = (root / name).resolve(strict=True)
    if path.parent != root:
      raise ValueError("GPU cache asset resolves outside the model directory")
    with path.open("rb") as stream:
      actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
      raise ValueError(f"GPU cache asset verification failed: {name}")
  if "live-build.json" not in hashes or "provenance.json" not in hashes:
    raise ValueError("GPU cache requires verified live and retained model identities")
  live = json.loads((root / "live-build.json").read_text())
  provenance = json.loads((root / "provenance.json").read_text())
  modules = ("android_runtime.gpu", "android_runtime.gpu_artifact", "android_runtime.gpu_warp", "android_runtime.gpu_diagnostic", "android_runtime.onnx_half", "tinygrad",
             "tinygrad.helpers", "tinygrad.device", "tinygrad.dtype", "tinygrad.tensor", "tinygrad.engine.jit",
             "tinygrad.engine.realize", "tinygrad.codegen", "tinygrad.renderer.cstyle", "tinygrad.uop.ops",
             "tinygrad.uop.weak", "tinygrad.runtime.ops_cl", "tinygrad.runtime.autogen.opencl", "tinygrad.runtime.support.c")
  runtime = {}
  for name in modules:
    spec = importlib.util.find_spec(name)
    if spec is None or spec.loader is None or not hasattr(spec.loader, "get_code"):
      raise RuntimeError(f"Cannot qualify GPU cache runtime module: {name}")
    code = spec.loader.get_code(name)
    if code is None:
      raise RuntimeError(f"No Python code identity for GPU cache module: {name}")
    # Loader-provided code works for both extracted packages and Chaquopy's
    # virtual bytecode assets; __file__ is not necessarily a physical .py file.
    runtime[name] = hashlib.sha256(marshal.dumps(code)).hexdigest()
  identity_inputs = {"schema": 1, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                     "assets": hashes, "runtime": runtime, "live_source_sha256": live["source_sha256"],
                     "tinygrad_commit": provenance["tinygrad_commit"], "python": sys.version,
                     "gpu": device.device_name, "driver": device.driver_version,
                     "math": "fp_contract_off_exact_division_retained_cpu_half_rne_subnormals_ushort_storage"}
  identity = hashlib.sha256(json.dumps(identity_inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
  cache_root = root.parent / "gpu-cache"
  cache_root.mkdir(mode=0o700, exist_ok=True)
  directory = cache_root / identity
  directory.mkdir(mode=0o700, exist_ok=True)
  for path in (cache_root, directory):
    if path.stat().st_uid != os.getuid():
      raise RuntimeError("GPU cache directory is not owned by this application")
    path.chmod(0o700)
  database = str(directory / "cache.sqlite3")
  if helpers.CACHEDB != database:
    if (connection := getattr(helpers._db_connection, "conn", None)) is not None:
      connection.close()
      del helpers._db_connection.conn
    helpers._db_tables.clear()
  helpers.CACHEDB, helpers.CACHELEVEL.value = database, 2
  # Keep every other compiler, including packaged CPU AOT, uncached. OpenCL's
  # compiler is the sole explicit exception and its SQL table has this identity.
  helpers.CCACHE.value = 0
  os.environ.update(CACHEDB=database, CACHELEVEL="2", CCACHE="0")
  device.cl_compiler.cachekey = "android_cl_" + identity
  report = {"enabled": True, "identity": identity, "directory": str(directory),
            "manifest_sha256": identity_inputs["manifest_sha256"], "runtime_sha256": runtime,
            "assets_sha256": hashes, "live_source_sha256": live['source_sha256'],
            "tinygrad_commit": provenance["tinygrad_commit"], "gpu": device.device_name, "driver": device.driver_version,
            "numerical_gate_required_every_startup": True, "relaxed_math": False, "requests": 0, "misses": 0, "hits": 0,
            "native_compile_seconds":0.0}
  # Actual loaded native/APK bytes supplement source/runtime and driver strings.
  # Missing read access is explicit and never becomes an accelerator claim.
  names={'libOpenCL.so','libCB.so','libgsl.so','libllvm-qcom.so','libonnxruntime.so',
         'libopenpilot_ipc.so','libopenpilot_kernels.so'}
  native_paths=set()
  for line in Path('/proc/self/maps').read_text().splitlines():
    parts=line.split(maxsplit=5)
    if len(parts)==6 and (Path(parts[5]).name in names or parts[5].endswith('/base.apk')):native_paths.add(parts[5])
  native=Path(os.environ.get('OPENPILOT_ANDROID_NATIVE_DIR','/nonexistent'))
  native_paths.update(str(native/name) for name in names if (native/name).is_file())
  report['loaded_files']={}
  for name in sorted(native_paths):
    try:
      with Path(name).open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
      report['loaded_files'][name]={'sha256':sha,'bytes':Path(name).stat().st_size}
    except OSError as failure:report['loaded_files'][name]={'unavailable':type(failure).__name__}
  compile_original, cached_original = device.cl_compiler.compile, device.cl_compiler.compile_cached

  def compile_counted(source):
    report["misses"] += 1
    started=time.monotonic()
    try:return compile_original(source)
    finally:report['native_compile_seconds']+=time.monotonic()-started

  def cached_counted(source):
    report["requests"] += 1
    result = cached_original(source)
    report["hits"] = report["requests"] - report["misses"]
    return result

  device.cl_compiler.compile, device.cl_compiler.compile_cached = compile_counted, cached_counted
  device._android_cache_report = report


def capabilities():
  """Probe the actual application OpenCL namespace, GPU and a computed result."""
  try:
    device = configure()
    import ctypes
    import numpy as np
    from tinygrad import Tensor
    from tinygrad.runtime.autogen import opencl as cl
    from tinygrad.runtime.ops_cl import check

    def scalar(key, dtype):
      result = dtype()
      check(cl.clGetDeviceInfo(device.cl_dev, key, ctypes.sizeof(result), ctypes.byref(result), None))
      return result.value

    source = np.arange(32, dtype=np.float32).reshape(4, 8) / 32
    weights = np.arange(24, dtype=np.float32).reshape(8, 3) / 24
    actual = (Tensor(source, device="CL").matmul(Tensor(weights, device="CL")).relu() + .25).numpy()
    expected = np.maximum(source @ weights, 0) + .25
    np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-6)
    return {"available": True, "backend": "CL", "device": device.device_name, "driver": device.driver_version,
            "fp32_correctly_rounded_divide_sqrt":bool(scalar(cl.CL_DEVICE_SINGLE_FP_CONFIG,ctypes.c_uint64)&getattr(cl,'CL_FP_CORRECTLY_ROUNDED_DIVIDE_SQRT',128)),
            "fp16": True, "fp16_denorm": bool(scalar(getattr(cl, "CL_DEVICE_HALF_FP_CONFIG", 0x1033), ctypes.c_uint64) & cl.CL_FP_DENORM),
            "fp32_denorm": bool(scalar(cl.CL_DEVICE_SINGLE_FP_CONFIG, ctypes.c_uint64) & cl.CL_FP_DENORM),
            "global_memory_bytes": scalar(cl.CL_DEVICE_GLOBAL_MEM_SIZE, ctypes.c_uint64),
            "compute_units": scalar(cl.CL_DEVICE_MAX_COMPUTE_UNITS, ctypes.c_uint32),
            "maximum_workgroup_size": scalar(cl.CL_DEVICE_MAX_WORK_GROUP_SIZE, ctypes.c_size_t), "cache": device._android_cache_report,
            "tensor_probe_maximum_absolute_difference": float(np.max(np.abs(actual - expected)))}
  except Exception as failure:
    return {"available": False, "backend": "CL", "error": f"{type(failure).__name__}: {failure}"}


def _retained_scalar_half(ctx, x):
  """Module-global callback: tinygrad pattern matchers reject closures."""
  from tinygrad.dtype import dtypes
  from tinygrad.helpers import strip_parens
  from tinygrad.uop.ops import Ops
  if x.dtype != dtypes.half or x.max_numel() != 1:
    return None
  operands = []
  for index, source in enumerate(x.src):
    rendered = ctx[source]
    if x.op is Ops.WHERE and index == 0:
      operands.append(rendered)
    elif source.op is x.op and x.op in (Ops.ADD, Ops.MUL) and not rendered.isidentifier():
      # Reproduce CStyleLanguage's printed association of inline chains. The
      # child expression has already been promoted; a new cast here would
      # add parentheses and change the retained C evaluation order.
      operands.append(strip_parens(rendered))
    else:
      operands.append(f"((float)({rendered}))")
  expression = (f"op_cpu_f32_div({operands[0]},{operands[1]})" if x.op is Ops.FDIV else
                f"op_cpu_f32_sqrt({operands[0]})" if x.op is Ops.SQRT else ctx.code_for_op[x.op](*operands, dtypes.float32))
  if x.op is Ops.WHERE or ctx._retained_child_count.get(x, 0) != 1:
    # This expression becomes a named __fp16 variable in retained C. Commit
    # exactly there, with the CPU's round-to-nearest-even conversion.
    return f"op_cpu_half_round({expression})"
  return expression


def _retained_vector_half(ctx, x):
  from tinygrad.dtype import dtypes
  from tinygrad.uop.ops import Ops
  if x.dtype != dtypes.half or x.max_numel() == 1:
    return None
  count = x.max_numel()
  expression = (_retained_float_div_expression(ctx,x) if x.op is Ops.FDIV else
                _retained_float_sqrt_expression(ctx,x) if x.op is Ops.SQRT else ctx.code_for_op[x.op](*(ctx[source] for source in x.src), dtypes.float32))
  return f"op_cpu_half_round{count}({expression})"


def _retained_float_div_expression(ctx,x):
  count=x.max_numel()
  def operand(node,lane):
    value=ctx[node]
    return f"({value}).s{'0123456789abcdef'[lane]}" if node.max_numel()>1 else value
  values=[f"op_cpu_f32_div({operand(x.src[0],lane)},{operand(x.src[1],lane)})" for lane in range(count)]
  return values[0] if count==1 else f"(float{count})({','.join(values)})"


def _retained_float_div(ctx,x):
  from tinygrad.dtype import dtypes
  if x.dtype!=dtypes.float32:return None
  return _retained_float_div_expression(ctx,x)


def _retained_float_sqrt_expression(ctx,x):
  count=x.max_numel();source=x.src[0];value=ctx[source]
  args=[f"({value}).s{'0123456789abcdef'[lane]}" if source.max_numel()>1 else value for lane in range(count)]
  values=[f'op_cpu_f32_sqrt({arg})' for arg in args]
  return values[0] if count==1 else f"(float{count})({','.join(values)})"


def _retained_float_sqrt(ctx,x):
  from tinygrad.dtype import dtypes
  return _retained_float_sqrt_expression(ctx,x) if x.dtype==dtypes.float32 else None


def _retained_half_stack(ctx, x):
  from tinygrad.dtype import dtypes
  if x.dtype != dtypes.half or not x.src:
    return None
  operands = []
  for source in x.src:
    suffix = str(source.max_numel()) if source.max_numel() > 1 else ""
    operands.append(f"op_cpu_half_round{suffix}({ctx[source]})")
  return f"({ctx.render_type(x)})({','.join(operands)})"


def _retained_half_store(ctx, x):
  from tinygrad.dtype import dtypes
  if x.src[0].dtype != dtypes.half or len(x.src) != 2:
    return None
  count = x.src[0].max_numel()
  suffix = str(count) if count > 1 else ""
  return f"{ctx.render_access(x.src[0])} = op_cpu_half_encode{suffix}({ctx[x.src[1]]});"


def _retained_half_load(ctx, x):
  from tinygrad.dtype import dtypes
  if x.dtype != dtypes.half:
    return None
  count = x.max_numel()
  suffix = str(count) if count > 1 else ""
  expression = f"op_cpu_half_decode{suffix}({ctx.render_access(x.src[0])})"
  if len(x.src) == 3:
    return f"({ctx[x.src[2]]}?{expression}:{ctx[x.src[1]]})"
  return expression


def _retained_half_bitcast(ctx, x):
  from tinygrad.dtype import dtypes, AddrSpace
  if x.addrspace not in (AddrSpace.ALU, None):
    return None
  source = x.src[0]
  count = x.max_numel()
  suffix = str(count) if count > 1 else ""
  if x.dtype == dtypes.half:
    if source.dtype == dtypes.half:
      return ctx[source]
    if source.dtype.itemsize != 2:
      raise RuntimeError("Unsupported size-changing retained half value bitcast")
    # C integer promotions widen scalar short arithmetic to int. Restore the
    # declared source width before OpenCL selects an as_ushort overload.
    return f"op_cpu_half_decode{suffix}(as_ushort{suffix}(({ctx.render_type(source)})({ctx[source]})))"
  if source.dtype == dtypes.half:
    if x.dtype.itemsize != 2:
      raise RuntimeError("Unsupported size-changing retained half value bitcast")
    return f"as_{ctx.render_type(x)}(op_cpu_half_encode{suffix}({ctx[source]}))"
  return None


def _retained_half_helpers():
  """Exact binary16 storage conversions without native half denorm behavior."""
  source = """
#pragma OPENCL FP_CONTRACT OFF
// C/ARM division is correctly rounded. OpenCL '/' may use an approximate
// reciprocal; one FP32 ULP can cross a later binary16 rounding boundary.
// Integer significand division keeps this contract even without the optional
// CL_FP_CORRECTLY_ROUNDED_DIVIDE_SQRT capability.
inline float op_cpu_f32_div(float av, float bv) {
  uint a=as_uint(av), b=as_uint(bv), sign=(a^b)&0x80000000u;
  uint ae=(a>>23)&255u, be=(b>>23)&255u, am=a&0x7fffffu, bm=b&0x7fffffu;
  if ((ae==255u&&am)||(be==255u&&bm)||(ae==255u&&be==255u)) return as_float(0x7fc00000u);
  if (ae==255u) return as_float(sign|0x7f800000u);
  if (be==255u) return as_float(sign);
  if (!(b&0x7fffffffu)) return as_float((a&0x7fffffffu)?sign|0x7f800000u:0x7fc00000u);
  if (!(a&0x7fffffffu)) return as_float(sign);
  if ((b&0x7fffffffu)==0x3f800000u) return as_float(a^(b&0x80000000u));
  int an=ae?(int)ae-127:-126, bn=be?(int)be-127:-126;
  am|=ae?0x800000u:0u; bm|=be?0x800000u:0u;
  while(am<0x800000u){am<<=1;an--;}
  while(bm<0x800000u){bm<<=1;bn--;}
  int exponent=an-bn;
  if(am<bm){am<<=1;exponent--;}
  if(exponent>127)return as_float(sign|0x7f800000u);
  if(exponent< -150)return as_float(sign);
  int shift=exponent< -126?exponent+149:23;
  // Restoring division uses only32-bit operations. Some mobileCL drivers
  // lower ulong division to unsupported device-library calls.
  uint quotient=1u, remainder=am-bm, denominator=bm;
  if(shift<0){quotient=0u;remainder=am;denominator=bm<<1;}
  else for(int bit=0;bit<shift;bit++){
    remainder<<=1;quotient<<=1;
    if(remainder>=denominator){remainder-=denominator;quotient|=1u;}
  }
  quotient+=(remainder*2u>denominator)||((remainder*2u==denominator)&&(quotient&1u));
  if(exponent< -126)return as_float(sign|quotient);
  if(quotient>=0x1000000u){quotient>>=1;exponent++;}
  if(exponent>127)return as_float(sign|0x7f800000u);
  return as_float(sign|((uint)(exponent+127)<<23)|(quotient&0x7fffffu));
}
inline float op_cpu_f32_sqrt(float value) {
  uint bits=as_uint(value), field=(bits>>23)&255u, mantissa=bits&0x7fffffu;
  if(!(bits&0x7fffffffu))return value;
  if(field==255u)return mantissa?as_float(bits|0x400000u):((bits>>31)?as_float(0x7fc00000u):value);
  if(bits>>31)return as_float(0x7fc00000u);
  int power=field?(int)field-127:-126;
  mantissa|=field?0x800000u:0u;
  while(mantissa<0x800000u){mantissa<<=1;power--;}
  if(power&1){mantissa<<=1;power--;}
  uint high=mantissa>>9,low=mantissa<<23,root=0u,remainder=0u;
  for(int index=23;index>=0;index--){
    int shift=index*2;
    uint pair=(shift>=32?high>>(shift-32):low>>shift)&3u;
    remainder=(remainder<<2)|pair;
    uint trial=(root<<2)|1u;root<<=1;
    if(remainder>=trial){remainder-=trial;root|=1u;}
  }
  // A half-integer square cannot be an integer: an exact midpoint is
  // impossible here. remainder>root is the exact nearest-rounding test.
  root+=(remainder>root);power/=2;
  if(root==0x1000000u){root>>=1;power++;}
  return as_float(((uint)(power+127)<<23)|(root&0x7fffffu));
}
// ORT 1.23.2 MLAS tanh.cpp, Microsoft (MIT): the generic NEON polynomial.
// The original CPU provider uses this approximation, rather than CL tanh.
inline float op_ort_tanh_f32(float value) {
  if(isnan(value))return value;
  float x=clamp(value,-9.0f,9.0f),s=x*x;
  // The pinned ARM CPU contracts MLAS multiply/add. An identical-input
  // 172800-value probe distinguishes this from separate FP32 operations.
  float p=fma(s,-2.76076847742355e-16f,2.00018790482477e-13f);
  p=fma(p,s,-8.60467152213735e-11f);
  p=fma(p,s,5.12229709037114e-08f);
  p=fma(p,s,1.48572235717979e-05f);
  p=fma(p,s,6.37261928875436e-04f);
  p=fma(p,s,4.89352455891786e-03f);
  p=p*x;
  float q=fma(s,1.19825839466702e-06f,1.18534705686654e-04f);
  q=fma(q,s,2.26843463243900e-03f);
  q=fma(q,s,4.89352518554385e-03f);
  return op_cpu_f32_div(p,q);
}
inline ushort op_cpu_half_encode(float value) {
  uint bits = as_uint(value), sign = (bits >> 16) & 0x8000u;
  uint exponent = (bits >> 23) & 255u, mantissa = bits & 0x7fffffu;
  if (exponent == 255u) return (ushort)(sign | (mantissa ? 0x7e00u : 0x7c00u));
  int half_exponent = (int)exponent - 112;
  if (half_exponent >= 31) return (ushort)(sign | 0x7c00u);
  if (half_exponent <= 0) {
    if (half_exponent < -10) return (ushort)sign;
    mantissa |= 0x800000u;
    uint shift = (uint)(14 - half_exponent), rounded = mantissa >> shift;
    uint remainder = mantissa & ((1u << shift) - 1u), halfway = 1u << (shift - 1u);
    rounded += (remainder > halfway) || ((remainder == halfway) && (rounded & 1u));
    return (ushort)(sign | rounded);
  }
  uint rounded = ((uint)half_exponent << 10) | (mantissa >> 13);
  uint remainder = mantissa & 0x1fffu;
  rounded += (remainder > 0x1000u) || ((remainder == 0x1000u) && (rounded & 1u));
  return (ushort)(sign | rounded);
}
inline float op_cpu_half_decode(ushort value) {
  uint bits = (uint)value, sign = (bits & 0x8000u) << 16;
  uint exponent = (bits >> 10) & 31u, mantissa = bits & 1023u;
  if (exponent == 0u) {
    if (mantissa == 0u) return as_float(sign);
    uint normalized_exponent = 113u;
    while ((mantissa & 0x400u) == 0u) { mantissa <<= 1; normalized_exponent -= 1u; }
    return as_float(sign | (normalized_exponent << 23) | ((mantissa & 1023u) << 13));
  }
  return as_float(sign | ((exponent == 31u ? 255u : exponent + 112u) << 23) | (mantissa << 13));
}
inline float op_cpu_half_round(float value) { return op_cpu_half_decode(op_cpu_half_encode(value)); }
inline float op_cpu_half_fma(float a,float b,float c) {
  // A product of two binary16 values is exact in FP32. Only an FP32 sum
  // landing exactly on a binary16 midpoint can suffer double rounding.
  float product=a*b, summed=product+c;
  if(!isfinite(summed))return op_cpu_half_round(summed);
  uint bits=as_uint(summed), mantissa=bits&0x7fffffu;
  int exponent=(int)((bits>>23)&255u)-112, shift=13;
  if(exponent>30||exponent< -10)return op_cpu_half_round(summed);
  if(exponent<=0){mantissa|=0x800000u;shift=14-exponent;}
  if((mantissa&((1u<<shift)-1u))!=(1u<<(shift-1)))return op_cpu_half_round(summed);
  float z=summed-product;
  float error=(product-(summed-z))+(c-z);
  if(error==0.0f)return op_cpu_half_round(summed);
  uint half_code=op_cpu_half_encode(fabs(summed));
  if(op_cpu_half_decode((ushort)half_code)>fabs(summed))half_code--;
  if((bits&0x80000000u)?error<0.0f:error>0.0f)half_code++;
  return op_cpu_half_decode((ushort)(((bits>>16)&0x8000u)|half_code));
}
"""
  lanes = "0123456789abcdef"
  for count in (2, 4, 8, 16):
    decoded = ",".join(f"op_cpu_half_decode(value.s{lane})" for lane in lanes[:count])
    encoded = ",".join(f"op_cpu_half_encode(value.s{lane})" for lane in lanes[:count])
    source += f"inline float{count} op_cpu_half_decode{count}(ushort{count} value) {{ return (float{count})({decoded}); }}\n"
    source += f"inline ushort{count} op_cpu_half_encode{count}(float{count} value) {{ return (ushort{count})({encoded}); }}\n"
    source += f"inline float{count} op_cpu_half_round{count}(float{count} value) {{ return op_cpu_half_decode{count}(op_cpu_half_encode{count}(value)); }}\n"
  return source


def retained_renderer():
  """Match scalar __fp16 promotion at the retained C renderer's boundaries."""
  device = configure()
  if hasattr(device, "_android_retained_renderer"):
    return device._android_retained_renderer
  from tinygrad.dtype import dtypes, AddrSpace
  from tinygrad.uop.ops import GroupOp, Ops, PatternMatcher, UPat
  base = type(device.renderer)

  class RetainedOpenCLRenderer(base):
    # Storage remains exactly16 bits. Numeric temporaries use FP32 so optional
    # native half flush-to-zero behavior cannot destroy binary16 subnormals.
    type_map = {**base.type_map, dtypes.half: "ushort"}
    string_rewrite = PatternMatcher([(UPat(GroupOp.ALU, name="x"), _retained_scalar_half),
                                     (UPat(GroupOp.ALU, name="x"), _retained_vector_half),
                                     (UPat(Ops.STACK, name="x"), _retained_half_stack),
                                     (UPat(Ops.STORE, name="x"), _retained_half_store),
                                     (UPat(Ops.LOAD, name="x"), _retained_half_load),
                                     (UPat(Ops.FDIV, name="x"), _retained_float_div),
                                     (UPat(Ops.SQRT, name="x"), _retained_float_sqrt),
                                     (UPat(Ops.BITCAST, name="x"), _retained_half_bitcast)]) + base.string_rewrite

    def render(self, uops):
      return _retained_half_helpers() + super().render(uops)

    def _render(self, uops):
      from collections import Counter
      self._retained_child_count = Counter(source for node in uops for source in node.src)
      return super()._render(uops)

    def render_cast(self, node, value):
      from tinygrad.dtype import dtypes, AddrSpace
      if node.dtype == dtypes.half and node.addrspace in (AddrSpace.ALU, None):
        count = node.max_numel()
        suffix = str(count) if count > 1 else ""
        return f"op_cpu_half_round{suffix}({value})"
      return super().render_cast(node, value)

    def render_type(self, node):
      if node.dtype == dtypes.half and node.addrspace in (AddrSpace.ALU, None):
        count = node.max_numel()
        return "float" + (str(count) if count > 1 else "")
      return super().render_type(node)

  device._android_retained_renderer = RetainedOpenCLRenderer(device.renderer.target)
  return device._android_retained_renderer


def _verified_asset(root, name):
  path = Path(root) / name
  manifest = json.loads((Path(root) / "manifest.json").read_text())
  expected = manifest["sha256"][name]
  with path.open("rb") as stream:
    actual = hashlib.file_digest(stream, "sha256").hexdigest()
  if actual != expected:
    raise ValueError(f"GPU asset hash differs: {name}")
  return path, actual


def _allocate(specs):
  import numpy as np
  from tinygrad import Tensor
  return {name: Tensor(np.zeros(shape, dtype=dtype), device="CL").realize() for name, (shape, dtype, _) in specs.items()}


def upload(tensor, frame, *, size=None, offset=0):
  """Blocking upload from a native snapshot; no intermediate full-frame array.

  The frame and its data view remain alive until OpenCL completes the transfer.
  Native snapshots optionally expose .pointer; regular writable buffer objects
  are supported by the numerical probe. This code executes only on Android.
  """
  device = configure()
  import ctypes
  from tinygrad.runtime.autogen import opencl as cl
  from tinygrad.runtime.ops_cl import check
  sequence = getattr(frame, "frame_id", None)
  view = memoryview(frame.data if hasattr(frame, "data") else frame).cast("B")
  size = view.nbytes if size is None else size
  buffer = tensor._buffer().ensure_allocated()
  if size < 0 or offset < 0 or size > view.nbytes or offset + size > buffer.nbytes:
    raise ValueError("Camera upload exceeds a source or GPU buffer")
  owner = None
  pointer = getattr(frame, "pointer", None)
  if pointer is None:
    if view.readonly:
      raise ValueError("A read-only camera buffer requires a native snapshot pointer")
    owner = ctypes.c_ubyte.from_buffer(view)
    pointer = ctypes.addressof(owner)
  check(cl.clEnqueueWriteBuffer(device.queue, buffer._buf, cl.CL_TRUE, offset, size, ctypes.c_void_p(int(pointer)), 0, None, None))
  if sequence is not None and getattr(frame, "frame_id", None) != sequence:
    raise RuntimeError("Camera frame was overwritten during GPU upload")
  return sequence


def _state_alias(tensor):
  """Distinct JIT argument identity, shared CL allocation with retained ownership.

  Buffer(opaque=...) disables allocator reuse. A retained CL reference belongs
  to the alias, and a strong owner keeps the original out of its allocator's
  free list until the alias has released that reference.
  """
  from tinygrad import Tensor
  from tinygrad.device import Buffer
  from tinygrad.uop.ops import UOp
  from tinygrad.runtime.autogen import opencl as cl
  from tinygrad.runtime.ops_cl import check
  original=tensor._buffer().ensure_allocated()
  check(cl.clRetainMemObject(original._buf))
  try:alias=Buffer('CL',original.nbytes,opaque=original._buf)
  except Exception:
    check(cl.clReleaseMemObject(original._buf))
    raise
  alias._android_state_owner=original
  return Tensor(UOp.from_buffer(alias,tensor.dtype)).reshape(tensor.shape)


class RoadRunner:
  """Real driving model with GPU-resident recurrent state and NV12 camera warp."""
  def __init__(self, model_root, width, height, native_directory=None, progress=None):
    self.device = configure()
    import numpy as np
    from tinygrad import Tensor
    from android_runtime.gpu_artifact import load
    from android_runtime import gpu_warp
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    self.root, self.width, self.height = Path(model_root), int(width), int(height)
    self.stride, self.y_height, self.uv_height, _ = get_nv12_info(self.width, self.height)
    self.frame_copy_size = self.stride * (self.y_height + self.uv_height)
    started = time.monotonic()
    if progress:
      progress({"stage": "driving_gpu_compile"})
    path, model_hash = _verified_asset(self.root, "driving_tinygrad.pkl")
    artifact = load(path, out_of_band=True, inplace_states=True)
    self.model_run = artifact["run"]
    self.inputs, self.outputs = _allocate(artifact["input_specs"]), _allocate(artifact["output_specs"])
    self.state_pairs = {name: f"next_{name}" for name in self.inputs if f"next_{name}" in self.outputs}
    self.state_zeros={name:np.zeros(self.inputs[name].shape,dtype=artifact['input_specs'][name][1]) for name in self.state_pairs}
    for name,next_name in self.state_pairs.items():self.outputs[next_name]=_state_alias(self.inputs[name])
    self.output_slices = pickle.loads(base64.b64decode(artifact["metadata"]["metadata"]["output_slices"]))
    provenance_path, _ = _verified_asset(self.root, "provenance.json")
    provenance = json.loads(provenance_path.read_text())
    self.report = {"backend": "CL", "artifact_sha256": model_hash, "model_sha256": provenance["model_sha256"],
                   "provenance": provenance, "retarget": artifact["gpu_retarget"], "cache": self.device._android_cache_report,
                   "recurrent_states_on_gpu": sorted(self.state_pairs), "frame_dimensions": [self.width, self.height]}
    if progress:progress({'stage':'driving_gpu_zero_check','retarget':self.report['retarget']})
    # Same retained reference and same tolerances as the packaged CPU gate.
    reference_path, reference_hash = _verified_asset(self.root, "reference.npz")
    self.model_run(output_buffers=self.outputs, **self.inputs)
    differences = {}
    try:
      with np.load(reference_path, allow_pickle=False) as reference:
        if set(reference.files) != set(self.outputs):
          raise AssertionError("GPU driving output names differ from the retained reference")
        for name, output in self.outputs.items():
          actual = output.numpy()
          np.testing.assert_allclose(actual, reference[name], rtol=1e-4, atol=1e-5, err_msg=f"GPU {name}")
          differences[name] = float(np.max(np.abs(actual.astype(np.float64) - reference[name])))
    except AssertionError as failure:
      # Reuse these exact compiled kernels and buffers in the diagnostic. A
      # second model allocation/upload obscures failures and doubles resources.
      failure.gpu_diagnostic_bundle = (artifact, self.inputs, self.outputs)
      raise
    self.report["reference"] = {"passed": True, "sha256": reference_hash, "rtol": 1e-4, "atol": 1e-5,
                                "maximum_absolute_difference": differences}
    self.frame_tensor = Tensor.zeros(2, self.frame_copy_size, dtype="uint8", device="CL").realize()
    self.transforms_np = np.stack((np.eye(3, dtype=np.float32), np.eye(3, dtype=np.float32)))
    self.transforms = Tensor(self.transforms_np, device="CL").realize()
    warp_name = f"driving_warp_{self.width}x{self.height}_tinygrad.pkl"
    if (self.root / warp_name).is_file():
      warp_path, warp_hash = _verified_asset(self.root, warp_name)
      warp = load(warp_path)
      self.warp_run = warp["run"]
      self.report["warp"] = {"source": "retained_cpu_artifact", "sha256": warp_hash, **warp["gpu_retarget"]}
    else:
      self.warp_run = gpu_warp.road(self.width, self.height)
      self.report["warp"] = {"source": "on_device_tinygrad", "algorithm": "retained_nv12_nearest_clamp"}
    if progress:
      progress({"stage": "camera_warp_gpu_check", "driving_reference": self.report["reference"]})
    # Both retained and newly captured warp graphs pass the same independent
    # pixel oracle before live frames can be accepted.
    rng = np.random.default_rng(42)
    frames = rng.integers(0, 256, (2, self.frame_copy_size), dtype=np.uint8)
    matrices = np.array([[[1.125, .03125, 4.0], [.015625, 1.25, 7.0], [0, 0, 1]],
                         [[4.0, -.015625, -32.0], [.03125, 8.0, -16.0], [0, 0, 1]]], dtype=np.float32)
    upload(self.frame_tensor, frames)
    upload(self.transforms, matrices)
    expected = gpu_warp.road_reference(frames, matrices, self.width, self.height)
    for _ in range(3):
      actual = self.warp_run(input_frame=self.frame_tensor, M_inv=self.transforms).numpy()
      np.testing.assert_array_equal(actual, expected, err_msg="GPU camera warp")
    self.report["warp"]["numerical_check"] = {"passed": True, "pixels": int(actual.size), "maximum_absolute_difference": 0}
    self.small_inputs = {name: np.zeros(value.shape, dtype=artifact["input_specs"][name][1]) for name, value in self.inputs.items()
                         if name not in self.state_pairs and name != "new_img"}
    self.prev_desire = np.zeros(self.small_inputs["desire"].shape, dtype=np.float32)
    for name in self.state_pairs:
      upload(self.inputs[name],self.state_zeros[name])
    self.device.synchronize()
    self.frames = 0
    self.report["initialize_seconds"] = time.monotonic() - started

  def reset(self):
    """Discard recurrent history after a camera discontinuity or cadence gap."""
    for name in self.state_pairs:
      upload(self.inputs[name],self.state_zeros[name])
    self.prev_desire[:] = 0
    self.device.synchronize()

  def run_pair(self, frames, transforms, inputs=None):
    """frames/transforms use keys img,big_img; return raw output and timings.

    inputs uses modeld's desire_pulse, traffic_convention and action_t fields.
    Unspecified inputs are stationary zeros. Callers must retain capture times
    and keep this bench output disconnected from CAN/Panda actuation.
    """
    import numpy as np
    inputs = {} if inputs is None else inputs
    started = time.monotonic()
    frame_ids = {}
    for index, name in enumerate(("img", "big_img")):
      frame = frames[name]
      if hasattr(frame, "width") and (frame.width, frame.height) != (self.width, self.height):
        raise ValueError(f"GPU camera dimensions changed for {name}")
      if hasattr(frame, "stride") and frame.stride != self.stride:
        raise ValueError(f"GPU camera stride differs for {name}")
      if hasattr(frame, "uv_offset") and frame.uv_offset != self.stride * self.y_height:
        raise ValueError(f"GPU camera UV offset differs for {name}")
      if hasattr(frame, "valid") and not frame.valid:
        raise ValueError(f"Invalid GPU camera frame for {name}")
      matrix = np.asarray(transforms[name], dtype=np.float32)
      if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix)) < 1e-9:
        raise ValueError(f"Invalid GPU camera transform for {name}")
      self.transforms_np[index] = matrix
      frame_ids[name] = upload(self.frame_tensor, frame, size=self.frame_copy_size, offset=index * self.frame_copy_size)
    upload(self.transforms, self.transforms_np)
    pulse = np.array(inputs.get("desire_pulse", np.zeros_like(self.prev_desire)), dtype=np.float32, copy=True)
    pulse[..., 0] = 0
    self.small_inputs["desire"][:] = np.where(pulse - self.prev_desire > .99, pulse, 0)
    self.prev_desire[:] = pulse
    for name in self.small_inputs:
      if name != "desire":
        self.small_inputs[name][:] = inputs.get(name, 0)
      if not np.all(np.isfinite(self.small_inputs[name])):
        raise ValueError(f"Non-finite GPU model input {name}")
      upload(self.inputs[name], self.small_inputs[name])
    uploaded = time.monotonic()
    self.inputs["new_img"] = self.warp_run(input_frame=self.frame_tensor, M_inv=self.transforms)
    self.device.synchronize()
    warped = time.monotonic()
    self.model_run(output_buffers=self.outputs, **self.inputs)
    raw = self.outputs["outputs"].numpy().reshape(-1).copy()
    if not np.all(np.isfinite(raw)):
      raise RuntimeError("Non-finite GPU driving output")
    # The retained model updates input/output state views in place. Swapping
    # separate allocations loses partial writes once the image history fills.
    finished = time.monotonic()
    self.frames += 1
    return {"raw": raw, "sliced": {name: raw[np.newaxis, region] for name, region in self.output_slices.items()},
            "frame_ids": frame_ids, "frames": self.frames,
            "timing": {"upload_ms": (uploaded - started) * 1000, "warp_ms": (warped - uploaded) * 1000,
                       "model_and_download_ms": (finished - warped) * 1000, "total_ms": (finished - started) * 1000}}


class CabinRunner:
  """Original driver ONNX and luma preprocessing compiled only on the phone."""
  def __init__(self, model_root, width, height, progress=None, reference_provider=None, cpu_semantics_model=None, ordered=False):
    self.device = configure()
    import numpy as np
    from tinygrad import Tensor, TinyJit
    from tinygrad.nn.onnx import OnnxPBParser, OnnxRunner
    from android_runtime import gpu_warp
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    self.width, self.height = int(width), int(height)
    stride, y_height, uv_height, _ = get_nv12_info(self.width, self.height)
    self.frame_copy_size = stride * (y_height + uv_height)
    path, model_hash = _verified_asset(model_root, "dmonitoring_model.onnx")
    if progress:
      progress({"stage": "driver_gpu_compile"})
    started = time.monotonic()
    runner = OnnxRunner(path if cpu_semantics_model is None else cpu_semantics_model)
    if cpu_semantics_model is not None:
      from android_runtime.onnx_half import install
      install(runner)
    if ordered:
      from android_runtime.onnx_half import materialize_operators
      materialize_operators(runner)
    if tuple(runner.graph_inputs["input_img"].shape) != (1, 1440 * 960):
      raise ValueError("Unexpected driver ONNX luma dimensions")
    self.frame_tensor = Tensor.zeros(self.frame_copy_size, dtype="uint8", device="CL").realize()
    self.matrix = Tensor(np.eye(3, dtype=np.float32), device="CL").realize()
    self.calib_np = np.zeros((1, 3), dtype=np.float32)
    self.calib = Tensor(self.calib_np, device="CL").realize()
    self.warp_run = gpu_warp.cabin(self.width, self.height)

    @TinyJit(prune=True)
    def model_run(input_img, calib):
      return runner({"input_img": input_img, "calib": calib})["outputs"].realize()

    self.model_run = model_run
    for _ in range(3):
      image = self.warp_run(input_frame=self.frame_tensor, M_inv=self.matrix)
      output = self.model_run(input_img=image, calib=self.calib).numpy()
      if not np.all(np.isfinite(output)):
        raise RuntimeError("Non-finite driver ONNX warmup output")
    self.report = {"backend": "CL", "model_sha256": model_hash, "source": "original_driver_onnx",
                   "output_dtype": str(output.dtype), "output_shape": list(output.shape), "cache": self.device._android_cache_report,
                   "initialize_seconds": time.monotonic() - started}
    if cpu_semantics_model is not None:
      self.report['cpu_semantics_lowering_sha256']=hashlib.sha256(Path(cpu_semantics_model).read_bytes()).hexdigest()
    self.report['operator_materialization']=bool(ordered)
    if progress:
      progress({"stage": "driver_cpu_reference"})
    try:
      if reference_provider is None:
        from java import jclass
        reference_provider = jclass("ai.comma.openpilot.sim.DriverReference").zeroInput
      reference = np.asarray(reference_provider(str(path)), dtype=np.float32).reshape(output.shape)
    except Exception as failure:
      raise RuntimeError(f"Driver CPU numerical reference unavailable: {failure}") from failure
    try:
      np.testing.assert_allclose(output.astype(np.float32), reference, rtol=1e-4, atol=1e-5, err_msg="GPU driver model")
    except AssertionError as failure:
      failure.driver_comparison={"actual":output.astype(np.float32).reshape(-1).tolist(),"reference":reference.reshape(-1).tolist(),
                                 "model_sha256":model_hash,"outputs":int(output.size)}
      raise
    self.report["reference"] = {"passed": True, "provider": "onnxruntime_android_cpu", "input": "uint8_luma_zero_calib_zero",
                                "rtol": 1e-4, "atol": 1e-5,
                                "maximum_absolute_difference": float(np.max(np.abs(output.astype(np.float32) - reference)))}
    rng = np.random.default_rng(43)
    pixels = rng.integers(0, 256, self.frame_copy_size, dtype=np.uint8)
    matrix = np.array([[2, .015625, -8], [.03125, 2, -4], [0, 0, 1]], dtype=np.float32)
    upload(self.frame_tensor, pixels)
    upload(self.matrix, matrix)
    actual = self.warp_run(input_frame=self.frame_tensor, M_inv=self.matrix).numpy()
    expected = gpu_warp.cabin_reference(pixels, matrix, self.width, self.height)
    np.testing.assert_array_equal(actual, expected, err_msg="GPU driver luma warp")
    self.report["warp"] = {"passed": True, "pixels": int(actual.size), "maximum_absolute_difference": 0}
    self.report["initialize_seconds"] = time.monotonic() - started
    # ONNX metadata contains the same output slicing contract as modeld artifacts.
    parser = OnnxPBParser(path, load_external_data=False)
    properties = {}
    for field, wire_type in parser._parse_message(parser.reader.len):
      if field == 14:
        entry = parser._parse_StringStringEntryProto()
        properties[entry["key"]] = entry["value"]
      else:
        parser.reader.skip_field(wire_type)
    self.output_slices = pickle.loads(base64.b64decode(properties["output_slices"]))

  def run(self, frame, transform, calib=None):
    import numpy as np
    started = time.monotonic()
    matrix = np.asarray(transform, dtype=np.float32)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix)) < 1e-9:
      raise ValueError("Invalid driver GPU camera transform")
    frame_id = upload(self.frame_tensor, frame, size=self.frame_copy_size)
    upload(self.matrix, matrix)
    self.calib_np[:] = 0 if calib is None else calib
    if not np.all(np.isfinite(self.calib_np)):
      raise ValueError("Non-finite driver calibration")
    upload(self.calib, self.calib_np)
    image = self.warp_run(input_frame=self.frame_tensor, M_inv=self.matrix)
    self.last_image=image
    raw = self.model_run(input_img=image, calib=self.calib).numpy().astype(np.float32).reshape(-1)
    if not np.all(np.isfinite(raw)):
      raise RuntimeError("Non-finite GPU driver output")
    return {"raw": raw, "sliced": {name: raw[np.newaxis, region] for name, region in self.output_slices.items()},
            "frame_id": frame_id, "timing": {"total_ms": (time.monotonic() - started) * 1000}}


class CabinCPURunner:
  """Explicit cabin diagnostic: GPU luma warp, original ONNX on ORT CPU.

  This class is selected only by the coordinator's explicit cabin mode. It is
  not a fallback for the live GPU candidate and makes no independent numerical
  acceptance claim for comparing the ORT runtime with itself.
  """
  def __init__(self, model_root, width, height, progress=None):
    self.device = configure()
    import numpy as np
    from java import jclass, jarray, jfloat
    from tinygrad import Tensor
    from tinygrad.nn.onnx import OnnxPBParser
    from android_runtime import gpu_warp
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    started = time.monotonic()
    self.width, self.height = int(width), int(height)
    self.stride, self.y_height, uv_height, _ = get_nv12_info(self.width, self.height)
    self.frame_copy_size = self.stride * (self.y_height + uv_height)
    self.path, model_hash = _verified_asset(model_root, "dmonitoring_model.onnx")
    self.bridge = jclass("ai.comma.openpilot.sim.NativeBridge")
    self.reference = jclass("ai.comma.openpilot.sim.DriverReference")
    self.calibration = jarray(jfloat)([0.0, 0.0, 0.0])
    if progress:
      progress({"stage": "driver_cpu_reference_initialization"})
    warmup = np.asarray(self.reference.zeroInput(str(self.path)), dtype=np.float32).reshape(-1)
    if warmup.size != 553 or not np.all(np.isfinite(warmup)):
      raise RuntimeError("Original driver ONNX CPU warmup produced an invalid output")
    self.frame_tensor = Tensor.zeros(self.frame_copy_size, dtype="uint8", device="CL").realize()
    self.matrix = Tensor(np.eye(3, dtype=np.float32), device="CL").realize()
    self.warp_run = gpu_warp.cabin(self.width, self.height)
    # Pixel readback is used only for this independent warmup oracle. The live
    # pixel path below stays in native/direct buffers and creates no NumPy image.
    rng = np.random.default_rng(43)
    pixels = rng.integers(0, 256, self.frame_copy_size, dtype=np.uint8)
    matrix = np.array([[2, .015625, -8], [.03125, 2, -4], [0, 0, 1]], dtype=np.float32)
    upload(self.frame_tensor, pixels)
    upload(self.matrix, matrix)
    expected = gpu_warp.cabin_reference(pixels, matrix, self.width, self.height)
    for _ in range(3):
      actual = self.warp_run(input_frame=self.frame_tensor, M_inv=self.matrix).numpy()
      np.testing.assert_array_equal(actual, expected, err_msg="CPU diagnostic GPU luma warp")
    parser = OnnxPBParser(self.path, load_external_data=False)
    properties = {}
    for field, wire_type in parser._parse_message(parser.reader.len):
      if field == 14:
        entry = parser._parse_StringStringEntryProto()
        properties[entry["key"]] = entry["value"]
      else:
        parser.reader.skip_field(wire_type)
    self.output_slices = pickle.loads(base64.b64decode(properties["output_slices"]))
    self.report = {"backend": "ORT_CPU_REFERENCE", "preprocessing_backend": "CL", "mode": "cabin_diagnostic",
                   "cache": self.device._android_cache_report,
                   "model_sha256": model_hash, "source": "original_driver_onnx", "output_shape": [1, 553],
                   "onnx_output_dtype": "float16", "returned_dtype": "float32",
                   "gpu_candidate": {"accepted": False, "reason": "independent_cpu_numerical_gate_failed"},
                   "warmup": {"finite": True, "input": "uint8_luma_zero_calib_zero", "independent_numerical_gate": False},
                   "warp": {"passed": True, "pixels": int(actual.size), "maximum_absolute_difference": 0},
                   "pixel_transfer": "native_cl_readback_to_java_direct_bytebuffer",
                   "initialize_seconds": time.monotonic() - started}

  def run(self, frame, transform, calib=None):
    import ctypes
    import numpy as np
    started = time.monotonic()
    if hasattr(frame, "width") and (frame.width, frame.height) != (self.width, self.height):
      raise ValueError("CPU diagnostic camera dimensions changed")
    if hasattr(frame, "stride") and frame.stride != self.stride:
      raise ValueError("CPU diagnostic camera stride differs")
    if hasattr(frame, "uv_offset") and frame.uv_offset != self.stride * self.y_height:
      raise ValueError("CPU diagnostic camera UV offset differs")
    if hasattr(frame, "valid") and not frame.valid:
      raise ValueError("Invalid CPU diagnostic camera frame")
    matrix = np.asarray(transform, dtype=np.float32)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix)) < 1e-9:
      raise ValueError("Invalid CPU diagnostic camera transform")
    calibration = np.zeros(3, dtype=np.float32) if calib is None else np.asarray(calib, dtype=np.float32).reshape(3)
    if not np.all(np.isfinite(calibration)):
      raise ValueError("Non-finite CPU diagnostic driver calibration")
    for index, value in enumerate(calibration):
      self.calibration[index] = float(value)
    frame_id = upload(self.frame_tensor, frame, size=self.frame_copy_size)
    upload(self.matrix, matrix)
    image = self.warp_run(input_frame=self.frame_tensor, M_inv=self.matrix)
    prepared = time.monotonic()
    # Android pointers may carry a top-byte tag. Java long is signed, while the
    # native helper reinterprets its bits as the original OpenCL handle.
    queue = ctypes.c_int64(ctypes.cast(self.device.queue, ctypes.c_void_p).value).value
    memory = ctypes.c_int64(ctypes.cast(image._buffer().ensure_allocated()._buf, ctypes.c_void_p).value).value
    direct_pixels = self.bridge.copyGpuLuma(queue, memory, 1440 * 960)
    if direct_pixels is None:
      raise RuntimeError("Native driver luma readback failed")
    copied = time.monotonic()
    # The direct buffer remains alive until synchronous ORT inference returns.
    raw = np.asarray(self.reference.runBuffer(str(self.path), direct_pixels, self.calibration), dtype=np.float32).reshape(-1)
    if raw.size != 553 or not np.all(np.isfinite(raw)):
      raise RuntimeError("Original driver ONNX CPU inference produced an invalid output")
    finished = time.monotonic()
    return {"raw": raw, "sliced": {name: raw[np.newaxis, region] for name, region in self.output_slices.items()},
            "frame_id": frame_id, "timing": {"preprocessing_enqueue_ms": (prepared - started) * 1000,
                                               "warp_and_native_readback_ms": (copied - prepared) * 1000,
                                               "model_cpu_ms": (finished - copied) * 1000,
                                               "total_ms": (finished - started) * 1000}}


def _cabin_intermediates(model_root,original_reference,progress=None):
  """Diagnostic copy of Android's actual CPU lowering, never a live backend."""
  import numpy as np
  from java import jclass,jarray
  from tinygrad import Tensor
  from tinygrad.nn.onnx import OnnxRunner
  root=Path(model_root).parent
  path=root/'cabin-cpu-nodes.onnx';metadata=json.loads(path.with_suffix('.json').read_text())
  if hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['sha256']:
    raise ValueError('Cabin diagnostic graph integrity failure')
  if hashlib.sha256((root/'driver-cpu-lowering.onnx').read_bytes()).hexdigest()!=metadata['source_sha256']:
    raise ValueError('Cabin diagnostic differs from actual ORT CPU lowering')
  names=list(dict.fromkeys(['outputs']+metadata.get('reference_names',[row['name'] for row in metadata['activations']])))
  reference=jclass('ai.comma.openpilot.sim.DriverReference').zeroIntermediates(str(path),jarray(jclass('java.lang.String'))(names))
  np.testing.assert_allclose(np.asarray(reference.get('outputs'),dtype=np.float32),original_reference,rtol=1e-4,atol=1e-5,
                             err_msg='Diagnostic graph changed original CPU results')
  runner=OnnxRunner(path).to('CL')
  from android_runtime.onnx_half import install,materialize_operators
  install(runner)
  materialize_operators(runner)
  tensors=runner({'input_img':Tensor.zeros(1,1440*960,dtype='uint8',device='CL'),
                  'calib':Tensor.zeros(1,3,dtype='float32',device='CL')})
  rows=[];first_bits=None
  for row in metadata['activations']:
    if progress:progress({'stage':'driver_intermediates','driver_diagnostic_node':row['name']})
    actual=tensors[row['name']].numpy().astype(np.float32)
    expected=np.asarray(reference.get(row['name']),dtype=np.float32).reshape(actual.shape)
    different=actual.view(np.uint32)!=expected.view(np.uint32)
    close=np.isclose(actual,expected,rtol=1e-4,atol=1e-5,equal_nan=False)
    item={**row,'bit_equal':not bool(np.any(different)),'passed':bool(np.all(close)),
          'maximum_absolute_difference':float(np.max(np.abs(actual-expected)))}
    rows.append(item)
    if first_bits is None and np.any(different):first_bits=item
    if not np.all(close):
      saved={'actual':actual,'expected':expected};inputs={};forced=[]
      node=next(node for node in runner.graph_nodes if row['name'] in node.outputs)
      for name in node.inputs:
        value=runner.graph_values[name]
        # ONNX Constant nodes can remain device-less; numpy() would then
        # open the CPU compiler. Force CL storage for diagnostic readback.
        before=value.to('CL',force=True).numpy()
        cpu=np.asarray(reference.get(name),dtype=before.dtype).reshape(before.shape)
        inputs[name]={'shape':list(before.shape),'dtype':str(before.dtype),'identical':before.tobytes()==cpu.tobytes(),
                      'gpu_sha256':hashlib.sha256(before.tobytes()).hexdigest(),'cpu_sha256':hashlib.sha256(cpu.tobytes()).hexdigest()}
        saved['cpu__'+name]=cpu;saved['gpu__'+name]=before
        forced.append(Tensor(cpu,device='CL'))
      teacher={}
      if row['op']=='Conv':
        from tinygrad.dtype import dtypes
        operation=runner._select_op(node.op,node.opset_id)
        for label,args in (('original',forced),('fp32_products',[value.cast(dtypes.float32) for value in forced])):
          output=operation(*args,**node.opts).cast(tensors[row['name']].dtype).numpy().astype(np.float32)
          teacher[label]={'passed':bool(np.all(np.isclose(output,expected,rtol=1e-4,atol=1e-5))),
                          'bit_equal':output.tobytes()==expected.tobytes(),'maximum_absolute_difference':float(np.max(np.abs(output-expected)))}
        # Independent scalar oracle at the first differing output; original
        # zero-model tensors only. Native half FMA and FP32-dot paths differ.
        from android_runtime.gpu_diagnostic import native_half_dot,rounded
        n,c,y,x=map(int,np.argwhere(~close)[0]);source,weights=map(lambda t:t.numpy(),forced[:2])
        bias=forced[2].numpy().reshape(-1)[c] if len(forced)>2 else 0.
        group=int(node.opts.get('group',1));strides=node.opts.get('strides',(1,1));dilations=node.opts.get('dilations',(1,1))
        pads=node.opts.get('pads',(0,0,0,0));start=(c//(weights.shape[0]//group))*weights.shape[1]
        aa=[];ww=[]
        for ky in range(weights.shape[2]):
          for kx in range(weights.shape[3]):
            for channel in range(weights.shape[1]):
              sy=y*strides[0]-pads[0]+ky*dilations[0];sx=x*strides[1]-pads[1]+kx*dilations[1]
              aa.append(float(source[n,start+channel,sy,sx]) if 0<=sy<source.shape[2] and 0<=sx<source.shape[3] else 0.)
              ww.append(float(weights[c,channel,ky,kx]))
        accumulator=0.
        for a,w in zip(aa,ww):accumulator=rounded(accumulator+rounded(a*w,'f'),'f')
        teacher['oracle']={'index':[n,c,y,x],'expected':float(expected[n,c,y,x]),'actual':float(actual[n,c,y,x]),
                           'half_fma_bias_first':native_half_dot(aa,ww,float(bias)),
                           'half_fma_bias_last':rounded(native_half_dot(aa,ww)+float(bias),'e'),
                           'fp32_bias_before_half':rounded(rounded(accumulator+float(bias),'f'),'e'),
                           'activations':aa,'weights':ww,'bias':float(bias)}
      np.savez(root/'cabin-first-divergence.npz',**saved)
      return {'passed':False,'first_bit_difference':first_bits,'first_tolerance_failure':item,'checked':rows,
              'original_cpu_unchanged':True,'diagnostic_sha256':metadata['sha256'],'complete_inputs':inputs,'teacher_forced':teacher}
  return {'passed':True,'first_bit_difference':first_bits,'checked':rows,'original_cpu_unchanged':True}


def validate_cabin(model_root,native_directory,progress=None):
  """Original553-output cabin model; fixture pixels only, no live capture."""
  import numpy as np
  import ctypes
  from java import jclass
  from android_runtime import gpu_warp
  try:
    device=configure()
    device.renderers=[type(retained_renderer())];device.cached_renderer.clear()
    fixture=Path(model_root).parent/'fixture'
    metadata=json.loads((fixture/'fixture.json').read_text())['cameras']['narrowRoadCameraState']
    width,height=int(metadata['width']),int(metadata['height'])
    reference=jclass('ai.comma.openpilot.sim.DriverReference')
    if progress:progress({'stage':'driver_cpu_mandatory_lowering'})
    lowered=Path(model_root).parent/'driver-cpu-lowering.onnx'
    reference.loweredModel(str(Path(model_root)/'dmonitoring_model.onnx'),str(lowered))
    runner=CabinRunner(model_root,width,height,progress=progress,cpu_semantics_model=lowered,ordered=True)
    bridge=jclass('ai.comma.openpilot.sim.NativeBridge')
    from java import jarray,jfloat
    calib=jarray(jfloat)([0.,0.,0.])
    matrix=np.eye(3,dtype=np.float32)
    maximum=0.;timings=[]
    for index in range(1,61):
      if progress:progress({'stage':'driver_gpu_sequence','driver_validation_frame':index})
      frame=np.frombuffer((fixture/'narrowRoadCameraState'/f'{index:04d}.nv12').read_bytes(),dtype=np.uint8)
      result=runner.run(frame,matrix)
      actual_image=runner.last_image.numpy()
      expected_image=gpu_warp.cabin_reference(frame,matrix,width,height)
      np.testing.assert_array_equal(actual_image,expected_image,err_msg=f'Cabin frame{index} preprocessing')
      queue=ctypes.c_int64(ctypes.cast(device.queue,ctypes.c_void_p).value).value
      memory=ctypes.c_int64(ctypes.cast(runner.last_image._buffer().ensure_allocated()._buf,ctypes.c_void_p).value).value
      pixels=bridge.copyGpuLuma(queue,memory,1440*960)
      expected=np.asarray(reference.runBuffer(str(Path(model_root)/'dmonitoring_model.onnx'),pixels,calib),dtype=np.float32)
      np.testing.assert_allclose(result['raw'],expected,rtol=1e-4,atol=1e-5,err_msg=f'Cabin frame{index} all553outputs')
      maximum=max(maximum,float(np.max(np.abs(result['raw']-expected))))
      timings.append(result['timing']['total_ms'])
    return {'passed':True,'model_role':'cabin','backend':'CL','renderer':'software_half_exact_division',
            'frames':60,'all_outputs':553,'preprocessing_exact':True,'maximum_absolute_difference':maximum,'initialization':runner.report,
            'rtol':1e-4,'atol':1e-5,'samples_ms':timings,'live_pixels_recorded':False,'qualification_scope':'recorded_fixture_only'}
  except Exception as failure:
    import traceback
    result={'passed':False,'model_role':'cabin','backend':'CL','renderer':'software_half_exact_division',
            'error':str(failure),'comparison':getattr(failure,'driver_comparison',None),'traceback':traceback.format_exc()}
    if result['comparison'] and (Path(model_root).parent/'cabin-cpu-nodes.onnx').is_file():
      try:result['intermediate_diagnostic']=_cabin_intermediates(model_root,np.asarray(result['comparison']['reference'],dtype=np.float32),progress)
      except Exception as diagnostic_failure:result['intermediate_diagnostic']={'error':str(diagnostic_failure),'traceback':traceback.format_exc()}
    return result


def validate(model_root, native_directory=None, width=1344, height=760, progress=None):
  """Run the actual on-phone GPU tensor, retained-model and camera pixel gates."""
  probe = capabilities()
  if not probe["available"]:
    return {"passed": False, "capabilities": probe}
  try:
    runner = RoadRunner(model_root, width, height, native_directory, progress)
    return {"passed": True, "capabilities": probe, "driving": runner.report}
  except Exception as failure:
    import traceback
    result = {"passed": False, "capabilities": probe, "error": f"{type(failure).__name__}: {failure}", "traceback": traceback.format_exc()}
    if isinstance(failure, AssertionError) and native_directory is not None:
      try:
        if progress:
          # Persist the original numerical failure before any further CL call:
          # a vendor-driver abort cannot be caught by this Python handler.
          progress({"stage": "retained_reference_failed", "gpu_validation": result})
        from android_runtime.gpu_artifact import compare_intermediates
        result["intermediate_diagnostic"] = compare_intermediates(
          model_root, native_directory, progress, gpu_bundle=getattr(failure, "gpu_diagnostic_bundle", None))
      except Exception as diagnostic_failure:
        result["intermediate_diagnostic"] = {"matched": False, "error": f"{type(diagnostic_failure).__name__}: {diagnostic_failure}",
                                             "traceback": traceback.format_exc()}
    return result
