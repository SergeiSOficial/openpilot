"""Explicit Android-only QNN experiment. No default backend or CAN selection."""
import hashlib
import json
from pathlib import Path
import time

DTYPES={1:"float32",2:"uint8",3:"int8",6:"int32",7:"int64",9:"bool",10:"float16",11:"float64",12:"uint32",13:"uint64",4:"uint16",5:"int16"}
SOURCE_MODELS={"road":("driving_supercombo.onnx","65a08adc31d5c456219687d99b7bf5e44d61dae2d49ea67850e76105c7248cce"),
               "cabin":("dmonitoring_model.onnx","dee5a294e8afaacc9295ac5d100e00733ecac278e79264b96331e40a3ede1b04")}


def role_of(manifest):
  role=manifest.get("model_role","road")
  if role not in SOURCE_MODELS:raise ValueError("Unknown model role")
  return role


def role_file(manifest,name):
  role=role_of(manifest)
  path=Path(name)
  return name if role=="road" else path.stem+"-cabin"+path.suffix


def digest(path):
  with Path(path).open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


def loaded(root,model_role="road"):
  manifest=json.loads((root/"model/qnn-graph-manifest.json").read_text())
  role=role_of(manifest)
  build=json.loads((root/"acceleration-build.json").read_text())
  if role!=model_role or build.get("model_role","road")!=role:raise ValueError("Requested/staged QNN model roles differ")
  source_name,source_hash=SOURCE_MODELS[role]
  if manifest.get("source",{}).get("sha256")!=source_hash or digest(root/"model"/source_name)!=source_hash:
    raise ValueError("Original model source identity differs")
  staged=build["sha256"]
  for name,expected in manifest["sha256"].items():
    if Path(name).name!=name or staged.get(name)!=expected or digest(root/"model"/name)!=expected:
      raise ValueError("QNN graph identity differs: "+name)
  return manifest


def tensor_output(runner,spec):
  import numpy as np
  raw=np.array(runner.output(spec["name"]),dtype=np.int8).view(np.uint8)
  result=raw.view(DTYPES[spec["dtype"]]).reshape(spec["shape"]).copy()
  if not np.all(np.isfinite(result)):raise ValueError("Nonfinite tensor "+spec["name"])
  return result


def error(actual,expected):
  import numpy as np
  if actual.shape!=expected.shape:raise ValueError("Output shape changed")
  diff=np.abs(actual.astype(np.float64)-expected.astype(np.float64))
  return {"maximum_absolute":float(diff.max(initial=0)),"mean_absolute":float(diff.mean()) if diff.size else 0,
          "matches_original_tolerance":bool(np.allclose(actual,expected,rtol=1e-4,atol=1e-5)),
          "exact":bool(np.array_equal(actual,expected))}


def runner(root,native,spec,backend,tag):
  from java import jclass
  profile=str(root/"acceleration"/tag) if backend=="htp" else ""
  role=spec.get("model_role","road")
  return jclass("ai.comma.openpilot.sim.QnnGraphBridge")(str(root/"model"/spec["file"]),backend,native,profile,role)


def inputs(r,spec,data,skip_states=False):
  import numpy as np
  for item in spec["inputs"]:
    name=item["name"]
    if skip_states and name.startswith("state_"):continue
    value=np.asarray(data[name])
    if value.shape!=tuple(item["shape"]) or value.dtype!=np.dtype(DTYPES[item["dtype"]]):raise ValueError("Input schema differs: "+name)
    if not np.all(np.isfinite(value)):raise ValueError("Nonfinite input "+name)
    r.setInput(name,value.tobytes())


def profile(r):
  path=Path(str(r.endProfiling()));events=json.loads(path.read_text());providers={}
  for event in events:
    if name:=event.get("args",{}).get("provider"):providers[name]=providers.get(name,0)+1
  if not providers or set(providers)!={"QNNExecutionProvider"}:raise ValueError("HTP provider attribution failed: "+str(providers))
  return {"path":str(path),"sha256":digest(path),"executed_providers":providers}


def capture(root,manifest):
  role=role_of(manifest)
  directory=root/"acceleration"/("capture" if role=="road" else "capture-cabin")
  meta=json.loads((directory/"manifest.json").read_text())
  if (type(meta.get("frames")) is not int or meta["frames"]!=60 or meta.get("model_role","road")!=role
      or meta.get("model_sha256")!=SOURCE_MODELS[role][1]):
    raise ValueError("A fresh full60 original-model capture is required")
  if set(meta.get("sha256",{}))!={f"{index:04d}.npz" for index in range(1,61)}:
    raise ValueError("Capture must bind exactly frames1..60")
  if meta.get("calibration_frames")!=[1,40] or meta.get("holdout_frames")!=[41,60]:
    raise ValueError("Capture calibration/holdout split differs")
  for name,expected in meta["sha256"].items():
    if Path(name).name!=name or digest(directory/name)!=expected:raise ValueError("Captured input hash differs: "+name)
  return directory,meta


def convolution(root,native,manifest,report):
  import numpy as np
  results={}
  for alias in ("conv_fp16","conv_fp32","conv_qdq"):
    spec=manifest["models"][alias];baseline={}
    for backend in ("cpu","htp"):
      key=alias+"_"+backend;r=None;item={"executed":False}
      try:
        r=runner(root,native,spec,backend,key)
        with np.load(root/"model"/spec["input_file"],allow_pickle=False) as data:inputs(r,spec,data)
        r.execute([])
        actual={s["name"]:tensor_output(r,s) for s in spec["outputs"]}
        if backend=="cpu":baseline=actual
        elif baseline:item["quantized_reference_errors"]={name:error(value,baseline[name]) for name,value in actual.items()}
        if backend=="htp":item["profile"]=profile(r)
        item["executed"]=True
      except Exception as failure:item["error"]=str(failure)
      finally:
        if r is not None:r.close()
      results[key]=item
  report.update(passed=results["conv_qdq_htp"]["executed"],convolution=results,
                scope="isolated convolution support; not full-model qualification")


def fp32(root,native,manifest,report):
  import numpy as np
  directory,meta=capture(root,manifest);spec=manifest["models"]["fp32"];r=runner(root,native,spec,"cpu","fp32")
  original_spec=manifest["models"].get("fp32_original")
  baseline_spec=manifest["models"].get("fp32_baseline")
  original=baseline=None
  differences=[];original_match=True
  try:
    if original_spec:original=runner(root,native,original_spec,"cpu","fp32_original")
    if baseline_spec:baseline=runner(root,native,baseline_spec,"cpu","fp32_baseline")
    if manifest.get("requires_cpu_support_equivalence") and baseline is None:
      raise ValueError("Supported road graph requires the unchanged experimental CPU baseline")
    for index in range(1,61):
      with np.load(directory/f"{index:04d}.npz",allow_pickle=False) as data:
        inputs(r,spec,data);r.execute([])
        first={s["name"]:tensor_output(r,s) for s in spec["outputs"]}
        if baseline is not None:
          inputs(baseline,baseline_spec,data);baseline.execute([])
          for s in baseline_spec["outputs"]:
            expected=tensor_output(baseline,s)
            if s["dtype"]==2:np.testing.assert_array_equal(first[s["name"]],expected,err_msg="Supported road byte copy "+s["name"])
            else:np.testing.assert_allclose(first[s["name"]],expected,rtol=1e-4,atol=1e-5,err_msg="Supported road CPU equivalence "+s["name"])
        if original is not None:
          inputs(original,original_spec,data);original.execute([])
          for s in original_spec["outputs"]:
            np.testing.assert_allclose(first[s["name"]],tensor_output(original,s),rtol=1e-4,atol=1e-5,err_msg="Finite masked softmax "+s["name"])
        # Teacher forced replay of identical inputs must be repeatable.
        r.execute([])
        for s in spec["outputs"]:np.testing.assert_array_equal(tensor_output(r,s),first[s["name"]])
        row={name:error(value,data["output__"+name]) for name,value in first.items()}
        original_match &= all(e["matches_original_tolerance"] for e in row.values());differences.append(row)
    certificate={"model_role":role_of(manifest),"passed":True,"repeatable":True,"frames":60,"model_sha256":digest(root/"model"/spec["file"]),
                 "capture_manifest_sha256":digest(directory/"manifest.json"),"original_reference_match":original_match,
                 "mask_rewrite_reference_match":original is not None,"support_cpu_equivalence":baseline is not None,
                 "support_baseline_sha256":digest(root/"model"/baseline_spec["file"]) if baseline_spec else None}
    (root/"acceleration"/role_file(manifest,"fp32-calibration-gate.json")).write_text(json.dumps(certificate,indent=2)+"\n")
    report.update(certificate,errors=differences,scope="FP32 calibration graph; experimental precision conversion")
  finally:
    try:r.close()
    finally:
      try:
        if original is not None:original.close()
      finally:
        if baseline is not None:baseline.close()


def calibrate(root,native,manifest,report):
  import numpy as np
  directory,meta=capture(root,manifest);spec=manifest["models"]["calibration"]
  gate=json.loads((root/"acceleration"/role_file(manifest,"fp32-calibration-gate.json")).read_text())
  if (gate.get("model_role","road")!=role_of(manifest) or not gate["passed"]
      or gate["capture_manifest_sha256"]!=digest(directory/"manifest.json") or gate["model_sha256"]!=digest(root/"model"/manifest["models"]["fp32"]["file"])):
    raise ValueError("Calibration requires the matching finite/repeatable FP32 gate")
  if manifest.get("requires_cpu_support_equivalence") and (gate.get("support_cpu_equivalence") is not True
      or gate.get("support_baseline_sha256")!=digest(root/"model"/manifest["models"]["fp32_baseline"]["file"])):
    raise ValueError("Fresh calibration requires the supported-graph CPU equivalence proof")
  from java import jclass
  build=jclass("android.os.Build")
  location={"device_model":str(build.MODEL),"device_fingerprint":str(build.FINGERPRINT),
            "ort_version":str(jclass("ai.onnxruntime.OrtEnvironment").getEnvironment().getVersion())}
  identity={"model_role":role_of(manifest),"graph_sha256":digest(root/"model"/spec["file"]),
            "capture_sha256":digest(directory/"manifest.json"),"calibration_location":location}
  target=root/"acceleration"/role_file(manifest,"qnn-ranges.json")
  state=json.loads(target.read_text()) if target.exists() else {**identity,"groups":[],"ranges":{}}
  state.setdefault("model_role","road")
  if any(state.get(k)!=v for k,v in identity.items()):state={**identity,"groups":[],"ranges":{}}
  groups=[];group=[];size=0
  for item in manifest["calibration_tensors"]:
    amount=int(np.prod(item["shape"]))*np.dtype(DTYPES[item["dtype"]]).itemsize
    if amount>128*1024*1024:raise ValueError("Calibration tensor exceeds memory bound: "+item["name"])
    if group and (len(group)==8 or size+amount>128*1024*1024):groups.append(group);group=[];size=0
    group.append(item);size+=amount
  if group:groups.append(group)
  index=next((i for i in range(len(groups)) if i not in state["groups"]),None)
  if index is not None:
    selected=groups[index];r=runner(root,native,spec,"cpu","calibration")
    ranges={}
    try:
      for frame in range(1,41):
        with np.load(directory/f"{frame:04d}.npz",allow_pickle=False) as data:inputs(r,spec,data)
        r.execute([s["name"] for s in selected])
        for s in selected:
          a=tensor_output(r,s);name=s["name"];previous=ranges.get(name,{"min":0.,"max":0.})
          ranges[name]={"min":min(previous["min"],float(a.min(initial=0))),
                        "max":max(previous["max"],float(a.max(initial=0))),"nonfinite_count":0}
    finally:r.close()
    state["ranges"].update(ranges);state["groups"].append(index)
    state.update(total_groups=len(groups),calibration_frames=[1,40],holdout_frames=[41,60],
                 calibration_frame_indices=list(range(40)),source_model_sha256=meta["model_sha256"],
                 calibration_model_sha256=identity["graph_sha256"],complete=len(state["groups"])==len(groups))
    temporary=target.with_suffix(".tmp");temporary.write_text(json.dumps(state,indent=2)+"\n");temporary.replace(target)
  report.update(passed=True,calibration_complete=state.get("complete",False),completed_groups=len(state["groups"]),total_groups=len(groups),range_sha256=digest(target))


def quantized_boundary_ready(manifest,results,modes):
  """A changed external formulation needs all target CPU baseline frames first."""
  if not manifest.get("requires_quantized_boundary_equivalence"):return True
  baseline=manifest.get("models",{}).get("quantized_baseline",{})
  expected=manifest.get("quantized_boundary_baseline_sha256")
  if (not isinstance(expected,str) or len(expected)!=64
      or manifest.get("sha256",{}).get(baseline.get("file"))!=expected):return False
  comparison="composed_reference_verified" if manifest.get("requires_composed_output_reference") else "boundary_cpu_equivalence"
  return all(results.get("cpu_"+mode,{}).get("executed") is True
             and results["cpu_"+mode].get("frames")==60
             and results["cpu_"+mode].get(comparison) is True for mode in modes)


def boundary_probe_parameters(manifest):
  import math
  import struct
  if role_of(manifest)!="cabin":raise ValueError("Output boundary probe belongs to cabin")
  info=manifest.get("output_boundary_probe",{})
  bits=info.get("scale_float32_le_hex");zero=info.get("zero_point_uint16")
  codes=info.get("codes")
  if (not isinstance(bits,str) or len(bits)!=8 or any(c not in "0123456789abcdef" for c in bits)
      or type(zero) is not int or not 0<=zero<=65535 or codes!=[0,65535]
      or any(type(code) is not int for code in codes)):
    raise ValueError("Invalid exhaustive boundary parameters")
  scale=struct.unpack("<f",bytes.fromhex(bits))[0]
  if not math.isfinite(scale) or scale<=0:raise ValueError("Invalid boundary scale")
  return scale,zero


def power2_half_bits(difference,exponent):
  """Integer-only exact binary16 RNE for difference * 2**exponent."""
  if type(difference) is not int or abs(difference)>65535 or type(exponent) is not int or not -149<=exponent<=127:
    raise ValueError("Bounded integer difference and binary exponent required")
  if difference==0:return 0
  sign=0x8000 if difference<0 else 0;value=abs(difference)
  def rounded_shift(number,shift):
    if shift<=0:return number<<(-shift)
    divisor=1<<shift;quotient,remainder=divmod(number,divisor)
    return quotient+(remainder*2>divisor or (remainder*2==divisor and bool(quotient&1)))
  size=value.bit_length();output_exponent=size-1+exponent
  if output_exponent<-14:return sign|rounded_shift(value,-exponent-24)
  mantissa=rounded_shift(value,size-11)
  if mantissa==2048:mantissa>>=1;output_exponent+=1
  if output_exponent>15:return sign|0x7c00
  return sign|((output_exponent+15)<<10)|(mantissa&1023)


def power2_oracle_bytes(exponent,zero):
  import struct
  if type(zero) is not int or not 0<=zero<=65535:raise ValueError("UInt16 zero point required")
  result=bytearray(65536*2)
  for code in range(65536):struct.pack_into("<H",result,code*2,power2_half_bits(code-zero,exponent))
  return bytes(result)


def power2_boundary_parameters(manifest):
  """Require the new scale, calibration split and alternate graph identities."""
  import math
  parameters=manifest.get("power2_output_boundary")
  scale,zero=boundary_probe_parameters(manifest)
  quantization=manifest.get("quantization",{});models=manifest.get("models",{});hashes=manifest.get("sha256",{})
  if any(not isinstance(value,dict) for value in (quantization,models,hashes)):raise ValueError("Complete power2 graph identity required")
  reference=models.get("output_boundary_cpu_reference",{});previous=models.get("pre_power2_quantized_reference",{})
  if not isinstance(parameters,dict):raise ValueError("Power2 derivation metadata required")
  exponent=parameters.get("power_exponent");maximum=max(zero,65535-zero)
  if (parameters.get("kind")!="calibration_output_power2_v1" or type(exponent) is not int or not -14<=exponent<=15
      or scale!=math.ldexp(1.,exponent) or parameters.get("scale_float32_le_hex")!=manifest["output_boundary_probe"]["scale_float32_le_hex"]
      or type(parameters.get("zero_point_uint16")) is not int or parameters["zero_point_uint16"]!=zero
      or parameters.get("codes")!=[0,65535] or maximum>65504 or maximum*scale>65504
      or type(parameters.get("maximum_integer_difference")) is not int or parameters["maximum_integer_difference"]!=maximum
      or parameters.get("all_nonzero_outputs_fp16_normal") is not True or parameters.get("all_code_outputs_finite") is not True
      or parameters.get("quantized_reference_changed") is not True or parameters.get("target_gate_passed") is not False
      or parameters.get("host_inference_executed") is not False
      or parameters.get("calibration_frames")!=[1,40] or parameters.get("holdout_frames")!=[41,60]
      or any(type(value) is not int for value in parameters.get("calibration_frames",[])+parameters.get("holdout_frames",[]))
      or parameters.get("calibration_frame_indices")!=list(range(40))
      or any(type(value) is not int for value in parameters.get("calibration_frame_indices",[]))
      or parameters.get("original_model_sha256")!=SOURCE_MODELS["cabin"][1]):raise ValueError("Invalid power2 all-code arithmetic contract")
  for key in ("ranges_file_sha256","capture_sha256","calibration_model_sha256"):
    value=parameters.get(key)
    if (not isinstance(value,str) or len(value)!=64 or any(c not in "0123456789abcdef" for c in value)
        or quantization.get(key)!=value):raise ValueError("Power2 calibration provenance differs: "+key)
  for name,key in ((reference,"cpu_reference_probe_sha256"),(previous,"pre_power2_quantized_reference_sha256")):
    expected=parameters.get(key)
    if (not isinstance(expected,str) or len(expected)!=64 or any(c not in "0123456789abcdef" for c in expected)
        or hashes.get(name.get("file"))!=expected):raise ValueError("Power2 alternate/previous graph identity differs")
  low,high=parameters.get("calibration_output_min"),parameters.get("calibration_output_max")
  if (any(type(value) not in (int,float) or not math.isfinite(value) for value in (low,high)) or not low<0<high
      or -zero*scale>low or (65535-zero)*scale<high
      or (-zero*(scale/2)<=low and (65535-zero)*(scale/2)>=high)
      or parameters.get("decoded_min")!=-zero*scale or parameters.get("decoded_max")!=(65535-zero)*scale):
    raise ValueError("Power2 scale is not the smallest covering measured calibration")
  return exponent,zero


def output_boundary(root,native,manifest,report):
  import numpy as np
  scale,zero=boundary_probe_parameters(manifest)
  spec=manifest["models"]["output_boundary_probe"]
  codes=np.arange(65536,dtype=np.uint16)
  lattice=(codes.astype(np.int32)-zero).astype(np.float32)*np.float32(scale)
  expected=lattice.astype(np.float16).reshape(spec["outputs"][0]["shape"])
  power2=manifest.get("power2_output_boundary") is not None
  cpu_actual=None;oracle_bytes=None;cpu_exact=False;cpu_codes_exact=False
  if power2:
    exponent,zero=power2_boundary_parameters(manifest)
    oracle_bytes=power2_oracle_bytes(exponent,zero)
    expected=np.frombuffer(oracle_bytes,dtype="<f2").reshape(spec["outputs"][0]["shape"])
    reference=manifest["models"]["output_boundary_cpu_reference"]
    cpu=runner(root,native,reference,"cpu","cabin-power2-cpu-alternate-reference")
    try:
      cpu.setInput("decoded_input",lattice.tobytes());cpu.execute([])
      cpu_actual=tensor_output(cpu,reference["outputs"][0]);cpu_codes=tensor_output(cpu,reference["outputs"][1])
      cpu_exact=cpu_actual.dtype==np.float16 and cpu_actual.shape==expected.shape and cpu_actual.tobytes()==oracle_bytes
      cpu_codes_exact=cpu_codes.dtype==np.uint16 and np.array_equal(cpu_codes,codes)
      report.update(cpu_alternate_reference_exact=cpu_exact,cpu_alternate_codes_exact=cpu_codes_exact,
                    cpu_alternate_comparison=error(cpu_actual,expected),oracle_sha256=hashlib.sha256(oracle_bytes).hexdigest(),
                    cpu_alternate_reference_sha256=digest(root/"model"/reference["file"]),
                    oracle_scope="Integer-only binary16 RNE for all UInt16 differences times exact power of two")
      if not cpu_exact or not cpu_codes_exact:raise ValueError("Power2 CPU alternate reference did not match every code/FP16 bit")
    finally:cpu.close()
  if not np.isfinite(expected).all():raise ValueError("Boundary reference must be finite")
  r=runner(root,native,spec,"htp","cabin-output-boundary-provider-probe")
  try:
    r.setInput("decoded_input",lattice.tobytes());r.execute([])
    actual=tensor_output(r,spec["outputs"][0]);comparison=error(actual,expected)
    exact_codes=bool(np.array_equal(tensor_output(r,spec["outputs"][1]),codes))
    bits_exact=actual.dtype==np.float16 and actual.shape==expected.shape and actual.tobytes()==expected.tobytes()
    provider=profile(r)
    report.update(passed=bool((bits_exact and cpu_exact and cpu_codes_exact if power2 else comparison["matches_original_tolerance"]) and exact_codes),
                  hardware_execution=True,values_checked=65536,fp16_bits_exact=bits_exact,
                  intermediate_codes_exact=exact_codes,
                  comparison=comparison,profile=provider,full_model_execution=False,accuracy_qualified=False,
                  scope="isolated output boundary capability; no full-model gate or accuracy qualification")
    if power2:
      path=root/"acceleration"/("qnn-boundary-power2-"+report["attempt_id"]+".npz")
      np.savez_compressed(path,codes=codes,lattice=lattice,oracle_bits=np.frombuffer(oracle_bytes,dtype="<u2"),
                          cpu_alternate=cpu_actual,htp_actual=actual)
      report.update(array_file=str(path),array_sha256=digest(path))
      different=np.flatnonzero(actual.view(np.uint16).reshape(-1)!=expected.view(np.uint16).reshape(-1))
      report["first_fp16_bit_differences"]=[{"code":int(code),"expected_bits":int(expected.view(np.uint16).reshape(-1)[code]),
          "actual_bits":int(actual.view(np.uint16).reshape(-1)[code])} for code in different[:16]]
    if bits_exact and exact_codes and (not power2 or cpu_exact and cpu_codes_exact):
      proof={"schema":1,"model_role":"cabin","exact":True,"values_checked":65536,
             "intermediate_codes_exact":True,
             "probe_model_sha256":digest(root/"model"/spec["file"]),
             "candidate_model_sha256":digest(root/"model"/manifest["models"]["quantized"]["file"]),
             "baseline_model_sha256":manifest["quantized_boundary_baseline_sha256"],
             "parameters":manifest["output_boundary_probe"],"profile":provider,
             **{key:report[key] for key in ("build_manifest_sha256","graph_manifest_sha256","native_runtime_sha256")}}
      if power2:proof.update(cpu_alternate_reference_exact=True,cpu_alternate_codes_exact=True,oracle_bit_exact=True,
                            cpu_alternate_reference_sha256=report["cpu_alternate_reference_sha256"],
                            oracle_sha256=report["oracle_sha256"],power2_parameters=manifest["power2_output_boundary"])
      (root/"acceleration/qnn-output-boundary-cabin.json").write_text(json.dumps(proof,indent=2)+"\n")
  finally:r.close()


def validate_composed_output_proof(proof,manifest,identities):
  boundary_probe_parameters(manifest)
  required={"probe_model_sha256","candidate_model_sha256","build_manifest_sha256","graph_manifest_sha256","native_runtime_sha256"}
  if set(identities)!=required:raise ValueError("Complete native/build/model proof identity is required")
  if (role_of(manifest)!="cabin" or type(proof.get("schema")) is not int or proof["schema"]!=1 or proof.get("model_role")!="cabin"
      or proof.get("exact") is not True or proof.get("intermediate_codes_exact") is not True
      or type(proof.get("values_checked")) is not int or proof["values_checked"]!=65536
      or proof.get("parameters")!=manifest.get("output_boundary_probe")
      or proof.get("baseline_model_sha256")!=manifest.get("quantized_boundary_baseline_sha256")):
    raise ValueError("Matching exhaustive exact cabin boundary proof is required")
  for key,expected in identities.items():
    if not expected or proof.get(key)!=expected:raise ValueError("Boundary proof identity changed: "+key)
  providers=proof.get("profile",{}).get("executed_providers",{})
  if set(providers)!={"QNNExecutionProvider"} or type(providers["QNNExecutionProvider"]) is not int or providers["QNNExecutionProvider"]<1:
    raise ValueError("Boundary proof lacks QNN-only execution")
  if manifest.get("power2_output_boundary") is not None:
    exponent,zero=power2_boundary_parameters(manifest)
    reference=manifest["models"]["output_boundary_cpu_reference"]["file"]
    if (proof.get("cpu_alternate_reference_exact") is not True or proof.get("cpu_alternate_codes_exact") is not True
        or proof.get("oracle_bit_exact") is not True or proof.get("power2_parameters")!=manifest["power2_output_boundary"]
        or proof.get("cpu_alternate_reference_sha256")!=manifest["sha256"][reference]
        or proof.get("oracle_sha256")!=hashlib.sha256(power2_oracle_bytes(exponent,zero)).hexdigest()):
      raise ValueError("Power2 reference requires exact CPU alternate, oracle and native-bound all-code proof")


def intermediate(root,native,manifest,report):
  import numpy as np
  spec=manifest["models"]["quantized_diagnostic"];details=manifest["intermediate_diagnostic"]
  if details["base_quantized_sha256"]!=digest(root/"model"/manifest["models"]["quantized"]["file"]):
    raise ValueError("Diagnostic base graph identity differs")
  directory,meta=capture(root,manifest)
  if manifest["quantization"]["capture_sha256"]!=digest(directory/"manifest.json"):
    raise ValueError("Diagnostic and exact captured input differ")
  files={};rows={};cpu_values=None;diagnostic_values={}
  for backend in ("cpu","htp"):
    r=runner(root,native,spec,backend,"intermediate-"+backend)
    try:
      with np.load(directory/"0001.npz",allow_pickle=False) as data:
        hashes={item["name"]:hashlib.sha256(np.asarray(data[item["name"]]).tobytes()).hexdigest() for item in spec["inputs"]}
        inputs(r,spec,data);r.execute([])
      values={item["name"]:tensor_output(r,item) for item in spec["outputs"]}
      diagnostic_values[backend]=values
      path=root/"acceleration"/("qnn-intermediate-"+backend+"-"+report["attempt_id"]+".npz")
      np.savez_compressed(path,**values);files[backend]={"file":str(path),"sha256":digest(path)}
      rows[backend]={"input_sha256":hashes,"executed":True}
      if backend=="cpu":cpu_values=values
      else:
        if rows["cpu"]["input_sha256"]!=hashes:raise ValueError("CPU/HTP inputs differ")
        rows[backend]["profile"]=profile(r)
        comparisons=[]
        for item in details["ordered_tensors"]:
          name=item["name"];comparison=error(values[name],cpu_values[name])
          comparison["matches_reference"]=comparison["exact"] if values[name].dtype.kind in "iub" else comparison["matches_original_tolerance"]
          comparisons.append({"name":name,"dtype":item["dtype"],"shape":item["shape"],**comparison})
        report.update(comparisons=comparisons,first_failing_probe=next((v["name"] for v in comparisons if not v["matches_reference"]),None))
    finally:r.close()
  base_spec=manifest["models"]["quantized"]
  for backend in ("cpu","htp"):
    r=runner(root,native,base_spec,backend,"intermediate-base-"+backend)
    try:
      with np.load(directory/"0001.npz",allow_pickle=False) as data:inputs(r,base_spec,data);r.execute([])
      base_values={item["name"]:tensor_output(r,item) for item in base_spec["outputs"]}
      comparisons={name:error(diagnostic_values[backend][name],value) for name,value in base_values.items()}
      rows[backend]["diagnostic_vs_base_outputs"]=comparisons
      rows[backend]["diagnostic_final_outputs_match_base"]=all(v["matches_original_tolerance"] for v in comparisons.values())
      path=root/"acceleration"/("qnn-intermediate-base-"+backend+"-"+report["attempt_id"]+".npz")
      np.savez_compressed(path,**base_values);files["base_"+backend]={"file":str(path),"sha256":digest(path)}
      if backend=="htp":rows[backend]["base_profile"]=profile(r)
    finally:r.close()
  report.update(passed=True,hardware_execution=True,frames=1,diagnostic_files=files,modes=rows,
                base_model_sha256=details["base_quantized_sha256"],diagnostic_model_sha256=digest(root/"model"/spec["file"]),
                scope="one identical recorded input, selected intermediates; diagnostic outputs alter partition visibility; no qualification")


def normalization_identities(root,manifest,report):
  names={"candidate_model_sha256":"quantized","baseline_model_sha256":"quantized_baseline",
         "reference_probe_sha256":"normalization_reference","lut_probe_sha256":"normalization_lut_probe"}
  return {**{key:digest(root/"model"/manifest["models"][alias]["file"]) for key,alias in names.items()},
    "table_sha256":manifest["normalization_lut"]["table_sha256"],
    **{key:report[key] for key in ("build_manifest_sha256","graph_manifest_sha256","native_runtime_sha256")}}


def validate_normalization_proof(proof,identities):
  required={"candidate_model_sha256","baseline_model_sha256","reference_probe_sha256","lut_probe_sha256","table_sha256",
            "build_manifest_sha256","graph_manifest_sha256","native_runtime_sha256"}
  if set(identities)!=required:raise ValueError("Complete normalization proof identity is required")
  if (type(proof.get("schema")) is not int or proof["schema"]!=1 or proof.get("model_role")!="road"
      or type(proof.get("values_checked")) is not int or proof["values_checked"]!=256
      or type(proof.get("position_permutations")) is not int or proof["position_permutations"]<3
      or type(proof.get("channels_checked")) is not int or proof["channels_checked"]!=24
      or any(proof.get(key) is not True for key in ("cpu_all256_exact","htp_codes_exact","htp_float_match"))):
    raise ValueError("Exact all256 normalization reference gate is required")
  for key,value in identities.items():
    if not value or proof.get(key)!=value:raise ValueError("Normalization proof identity changed: "+key)
  providers=proof.get("profile",{}).get("executed_providers",{})
  if set(providers)!={"QNNExecutionProvider"} or type(providers["QNNExecutionProvider"]) is not int or providers["QNNExecutionProvider"]<1:
    raise ValueError("Normalization proof lacks QNN-only execution")


def preprocess(root,native,manifest,report,cpu_only=False):
  import numpy as np
  if role_of(manifest)!="road":raise ValueError("Normalization LUT belongs to road")
  order=np.arange(256,dtype=np.int32)
  patterns=(order,order[::-1].copy(),(order*73+19)%256)
  results={};provider=None
  code_name="model/div_QuantizeLinear_Output";float_name="model/div_DequantizeLinear_Output"
  tables=np.asarray(manifest["normalization_lut"]["codes_by_camera"],dtype=np.uint16)
  if tables.shape!=(2,256):raise ValueError("Two distinct camera input-domain tables are required")
  for label,alias,backend in (("reference_cpu","normalization_reference","cpu"),
                              ("stage_cpu","normalization_stage_oracle","cpu"),
                              ("lut_cpu","normalization_lut_probe","cpu"),("lut_htp","normalization_lut_probe","htp")):
    if backend=="htp":
      cpu=results["reference_cpu"];lookup=results["lut_cpu"]
      table_match=all(np.array_equal(values[code_name],np.concatenate([np.tile(tables[camera][permutation],(12,1))
                                  for camera in range(2)],axis=0).reshape(1,24,16,16))
                      for values,permutation in zip(cpu,patterns))
      cpu_exact=table_match and all(np.array_equal(lookup[index][name],value)
                                    for index,values in enumerate(cpu) for name,value in values.items())
      report.update(cpu_all256_exact=cpu_exact,generated_table_matches_original_cpu=table_match,
                    cpu_reference_codes=cpu[0][code_name].reshape(24,256)[0].tolist(),
                    cpu_reference_codes_by_channel=cpu[0][code_name].reshape(24,256).tolist(),
                    position_permutations=3,channels_checked=24)
      stages=results["stage_cpu"]
      report["cpu_stage_oracle_final_matches_reference"]=all(np.array_equal(stages[index][name],value)
          for index,values in enumerate(cpu) for name,value in values.items())
      selected=[0,1,2,3,7,8,12,13,121,242,255]
      report["cpu_stage_samples"]={name:[value.item() for value in array.reshape(-1)[selected if array.size>=256 else [0]]]
                                   for name,array in stages[0].items()}
      if not cpu_exact:
        report.update(passed=False,error="All256 original CPU preprocessing equivalence failed; HTP was not attempted")
        return
      if cpu_only:
        report.update(passed=True,hardware_execution=False,cpu_only=True,values_checked=256,
                      scope="Android CPU-only all-byte preprocessing equivalence; no HTP execution or proof")
        return
    spec=manifest["models"][alias];r=runner(root,native,spec,backend,"normalization-"+label)
    try:
      results[label]=[]
      for permutation in patterns:
        pixels=np.tile(permutation.astype(np.float32),(12,1)).reshape(1,12,16,16)
        for item in spec["inputs"]:r.setInput(item["name"],pixels.tobytes())
        r.execute([]);results[label].append({item["name"]:tensor_output(r,item) for item in spec["outputs"]})
      if backend=="htp":provider=profile(r)
    finally:r.close()
  cpu=results["reference_cpu"];lookup=results["lut_cpu"];hardware=results["lut_htp"]
  htp_codes=all(np.array_equal(actual[code_name],expected[code_name]) for actual,expected in zip(hardware,cpu))
  floating=[error(actual[float_name],expected[float_name]) for actual,expected in zip(hardware,cpu)]
  float_match=all(value["matches_original_tolerance"] for value in floating)
  passed=cpu_exact and htp_codes and float_match
  report.update(passed=passed,hardware_execution=True,values_checked=256,cpu_all256_exact=cpu_exact,
                generated_table_matches_original_cpu=table_match,htp_codes_exact=htp_codes,htp_float=floating,
                profile=provider,scope="all-byte preprocessing operator gate only; full60 model comparisons remain required")
  if passed:
    proof={"schema":1,"model_role":"road","values_checked":256,"position_permutations":3,"channels_checked":24,"cpu_all256_exact":True,
           "htp_codes_exact":True,"htp_float_match":True,"profile":provider,**normalization_identities(root,manifest,report)}
    (root/"acceleration/qnn-normalization-gate.json").write_text(json.dumps(proof,indent=2)+"\n")


def quantized(root,native,manifest,report):
  import numpy as np
  if not manifest.get("quantized_model_calibrated") or "quantized" not in manifest["models"]:
    raise ValueError("Measured calibration ranges and a staged quantized graph are required")
  directory,meta=capture(root,manifest);spec=manifest["models"]["quantized"]
  if manifest["quantization"]["capture_sha256"]!=digest(directory/"manifest.json"):
    raise ValueError("Quantized model and evaluation capture differ")
  reference=root/"acceleration"/("quantized-reference-"+role_of(manifest)+"-"+report["attempt_id"]);reference.mkdir()
  results={}
  modes=("teacher","free") if role_of(manifest)=="road" else ("stateless",)
  baseline_spec=manifest["models"].get("quantized_baseline")
  needs_boundary=manifest.get("requires_quantized_boundary_equivalence",False)
  if needs_boundary and baseline_spec is None:raise ValueError("Quantized boundary baseline is required")
  if manifest.get("requires_exact_normalization_gate"):
    proof=json.loads((root/"acceleration/qnn-normalization-gate.json").read_text())
    validate_normalization_proof(proof,normalization_identities(root,manifest,report))
  composed=manifest.get("requires_composed_output_reference",False)
  if composed:
    proof=json.loads((root/"acceleration/qnn-output-boundary-cabin.json").read_text())
    validate_composed_output_proof(proof,manifest,{
      "probe_model_sha256":digest(root/"model"/manifest["models"]["output_boundary_probe"]["file"]),
      "candidate_model_sha256":digest(root/"model"/spec["file"]),
      **{key:report[key] for key in ("build_manifest_sha256","graph_manifest_sha256","native_runtime_sha256")}})
    report.update(candidate_cpu_execution_available=False,composed_reference="unchanged preceding quantized CPU graph plus exhaustive exact HTP boundary proof",
                  candidate_cpu_limitation="ORT 1.29.0 DQ-23 FLOAT16 output kernel requests FLOAT32 storage")
  for backend in ("cpu","htp"):
    if backend=="htp" and not quantized_boundary_ready(manifest,results,modes):
      report.update(passed=False,hardware_execution=False,boundary_cpu_equivalence=False,modes=results,
                    error="Quantized boundary did not pass all 60 target CPU baseline frames; HTP was not attempted")
      return
    for mode in modes:
      key=backend+"_"+mode;r=None;baseline=None;row={"executed":False,"frames":0};errors=[];timings=[]
      boundary_match=True
      original_match=True;quantized_match=backend=="cpu" or results.get("cpu_"+mode,{}).get("executed",False)
      try:
        execution_spec=baseline_spec if backend=="cpu" and composed else spec
        r=runner(root,native,execution_spec,backend,"quantized-"+key)
        if backend=="cpu" and needs_boundary and not composed:baseline=runner(root,native,baseline_spec,"cpu","quantized-boundary-baseline")
        for index in range(1,61):
          with np.load(directory/f"{index:04d}.npz",allow_pickle=False) as data:
            started=time.monotonic()
            inputs(r,execution_spec,data,skip_states=mode=="free" and index>1)
            prepared=time.monotonic();r.execute([]);executed=time.monotonic()
            values={s["name"]:tensor_output(r,s) for s in execution_spec["outputs"]}
            if mode=="free":r.advanceStates()
            timings.append({"inputs_ms":(prepared-started)*1000,"execute_ms":(executed-prepared)*1000,
                            "with_diagnostic_download_ms":(time.monotonic()-started)*1000})
            item={"frame":index,"holdout":index>=41,"original":{name:error(a,data["output__"+name]) for name,a in values.items()}}
            if baseline is not None:
              inputs(baseline,baseline_spec,data,skip_states=mode=="free" and index>1)
              baseline.execute([])
              expected={s["name"]:tensor_output(baseline,s) for s in baseline_spec["outputs"]}
              if mode=="free":baseline.advanceStates()
              item["boundary_baseline"]={name:error(a,expected[name]) for name,a in values.items()}
              boundary_match &= all(e["matches_original_tolerance"] for e in item["boundary_baseline"].values())
            original_match &= all(e["matches_original_tolerance"] for e in item["original"].values())
            path=reference/f"{mode}-{index:04d}.npz"
            if backend=="cpu":np.savez_compressed(path,**values)
            elif results.get("cpu_"+mode,{}).get("executed"):
              with np.load(path,allow_pickle=False) as expected:
                item["quantized_reference"]={name:error(a,expected[name]) for name,a in values.items()}
              quantized_match &= all(e["matches_original_tolerance"] for e in item["quantized_reference"].values())
            errors.append(item);row["frames"]=index
        if backend=="htp":row["profile"]=profile(r)
        row.update(executed=True,original_reference_match=bool(original_match),quantized_reference_match=bool(quantized_match),
                   boundary_cpu_equivalence=bool(boundary_match) if baseline is not None else None,
                   composed_reference_verified=True if backend=="cpu" and composed else None,
                   errors=errors,timing={"samples":60,"execute_mean_ms":float(np.mean([t["execute_ms"] for t in timings])),
                   "execute_p95_ms":float(np.percentile([t["execute_ms"] for t in timings],95)),
                   "diagnostic_downloads_included_in_end_to_end":True},samples=timings)
      except Exception as failure:row.update(error=str(failure),errors=errors)
      finally:
        try:
          if baseline is not None:baseline.close()
        finally:
          if r is not None:r.close()
      results[key]=row
  hardware=all(results["htp_"+mode]["executed"] and results["htp_"+mode]["frames"]==60 for mode in modes)
  report.update(passed=hardware,hardware_execution=hardware,
                boundary_cpu_equivalence=quantized_boundary_ready(manifest,results,modes) if needs_boundary else None,
                quantized_reference_match=all(results["htp_"+mode].get("quantized_reference_match",False) for mode in modes),
                original_reference_match=all(results["htp_"+mode].get("original_reference_match",False) for mode in modes),
                model_sha256=digest(root/"model"/spec["file"]),modes=results,
                scope="quantized model execution and drift; not accuracy or vehicle qualification")
  if hardware:
    (root/"acceleration"/role_file(manifest,"qnn-quantized-execution.json")).write_text(json.dumps({
      "schema":1,"model_role":role_of(manifest),"hardware_execution":True,"model_sha256":report["model_sha256"],"frames":60,
      "capture_manifest_sha256":digest(directory/"manifest.json"),"attempt_id":report["attempt_id"],
      "build_manifest_sha256":report["build_manifest_sha256"],"graph_manifest_sha256":report["graph_manifest_sha256"],
      "native_runtime_sha256":report["native_runtime_sha256"],
      "quantized_reference_match":report["quantized_reference_match"],"original_reference_match":report["original_reference_match"],
      "profiles":{mode:results["htp_"+mode]["profile"] for mode in modes},
      "experimental":True,"vehicle_control_enabled":False},indent=2)+"\n")


def require_sustained_gate(certificate,role,model_hash,capture_hash,build_hash,graph_hash,native_hashes):
  if (certificate.get("model_role","road")!=role or certificate.get("hardware_execution") is not True
      or type(certificate.get("frames")) is not int or certificate["frames"]!=60
      or certificate.get("capture_manifest_sha256")!=capture_hash or certificate.get("model_sha256")!=model_hash
      or certificate.get("build_manifest_sha256")!=build_hash or certificate.get("graph_manifest_sha256")!=graph_hash):
    raise ValueError("Sustained inference requires the matching full-model hardware gate")
  if certificate.get("quantized_reference_match") is not True:
    raise ValueError("20-minute run gated: strict quantized CPU reference agreement did not pass")
  if (type(native_hashes) is not dict or not native_hashes
      or any(type(name) is not str or not name.endswith(".so") or "/" in name or "\\" in name
             or type(value) is not str or len(value)!=64 or any(c not in "0123456789abcdef" for c in value)
             for name,value in native_hashes.items())
      or certificate.get("native_runtime_sha256")!=native_hashes):
    raise ValueError("Sustained inference requires matching complete native runtime identities")


def sustain(root,native,manifest,report):
  import numpy as np
  from java import jclass
  from android_runtime.live_policy import thermal_action
  bridge=jclass("ai.comma.openpilot.sim.QnnGraphBridge")
  directory,meta=capture(root,manifest);spec=manifest["models"]["quantized"]
  certificate=json.loads((root/"acceleration"/role_file(manifest,"qnn-quantized-execution.json")).read_text())
  require_sustained_gate(certificate,role_of(manifest),digest(root/"model"/spec["file"]),digest(directory/"manifest.json"),
                         digest(root/"acceleration-build.json"),digest(root/"model/qnn-graph-manifest.json"),report["native_runtime_sha256"])
  if not bridge.foregroundVisible():raise RuntimeError("An unlocked foreground activity is required")
  if thermal_action(int(bridge.thermalStatus()))!="running":raise RuntimeError("Thermal precondition prevents sustained warmup")
  r=runner(root,native,spec,"htp","sustain-provider-probe")
  samples=[];checks=[];started=None;paused_seconds=0.0;thermal="running"
  try:
    for index in range(1,6):
      with np.load(directory/f"{index:04d}.npz",allow_pickle=False) as data:inputs(r,spec,data,skip_states=index>1)
      r.execute([]);r.advanceStates()
      tensor_output(r,next(s for s in spec["outputs"] if s["name"]=="outputs"))
    provider=profile(r)  # Stop tracing before timing to avoid a huge profiling log.
    started=time.monotonic();last_check=started;frame=0
    while time.monotonic()-started<1200:
      now=time.monotonic()
      if now-last_check>=1:
        visible=bool(bridge.foregroundVisible());status=int(bridge.thermalStatus());thermal=thermal_action(status)
        checks.append({"seconds":now-started,"foreground":visible,"thermal_status":status,"thermal_action":thermal});last_check=now
        if not visible:raise RuntimeError("Foreground lost; sustained run stopped")
        if thermal=="stop":raise RuntimeError("Critical thermal status; sustained run stopped")
      if thermal=="paused":
        pause_start=time.monotonic();time.sleep(.2);paused_seconds+=time.monotonic()-pause_start;continue
      index=frame%60+1
      with np.load(directory/f"{index:04d}.npz",allow_pickle=False) as data:
        data={item["name"]:data[item["name"]] for item in spec["inputs"]}
        begin=time.monotonic();inputs(r,spec,data,skip_states=index>1)
        r.execute([]);r.advanceStates()
        tensor_output(r,next(s for s in spec["outputs"] if s["name"]=="outputs"))
        samples.append((time.monotonic()-begin)*1000)
      frame+=1
    report.update(passed=True,frames=frame,duration_seconds=time.monotonic()-started,hardware_execution=True,
      computed_fixture_throughput_fps=1000*frame/sum(samples),wall_fixture_rate_fps=frame/(time.monotonic()-started),paused_seconds=paused_seconds,
      prewarped_fixture=True,preprocessing_excluded=True,live_camera_fps_qualified=False,
      profile=provider,foreground_checks=checks,samples_ms=samples,
      timing={"mean_ms":float(np.mean(samples)),"p95_ms":float(np.percentile(samples,95)),"maximum_ms":max(samples),
              "over_50_ms":sum(x>50 for x in samples)},
      scope="20-minute prewarped fixture, reset each60; sample timing includes upload/model/output, excludes preprocessing/disk; wall rate includes disk/thermal pauses")
  finally:
    if started is not None:report.update(completed_frames=len(samples),samples_ms=samples,foreground_checks=checks,
                                       measured_duration_seconds=time.monotonic()-started)
    r.close()


def run(root,native,backend,report):
  if not Path("/system/bin/app_process").exists():raise RuntimeError("Android target only")
  manifest=loaded(root,report.get("model_role","road"))
  for spec in manifest["models"].values():spec["model_role"]=role_of(manifest)
  from java import jclass
  report.update(model_role=role_of(manifest),experimental=True,vehicle_control_enabled=False,automatically_selected=False,
                ort_version=str(jclass("ai.onnxruntime.OrtEnvironment").getEnvironment().getVersion()),
                graph_manifest_sha256=digest(root/"model/qnn-graph-manifest.json"))
  report["native_runtime_sha256"]={p.name:digest(p) for p in sorted(Path(native).glob("*.so"))
      if any(name in p.name.lower() for name in ("onnxruntime","qnn","cdsprpc"))}
  if not report["native_runtime_sha256"]:raise ValueError("Native runtime identities unavailable")
  if backend=="qnn_convolution":convolution(root,native,manifest,report)
  elif backend=="qnn_fp32":fp32(root,native,manifest,report)
  elif backend=="qnn_calibrate":calibrate(root,native,manifest,report)
  elif backend=="qnn_quantized":quantized(root,native,manifest,report)
  elif backend=="qnn_sustain":sustain(root,native,manifest,report)
  elif backend=="qnn_boundary":output_boundary(root,native,manifest,report)
  elif backend=="qnn_intermediate":intermediate(root,native,manifest,report)
  elif backend=="qnn_preprocess":preprocess(root,native,manifest,report)
  elif backend=="qnn_preprocess_cpu":preprocess(root,native,manifest,report,cpu_only=True)
  else:raise ValueError("Quantized graph has not been staged and qualified")
