"""Isolated on-target profiling. Never execute model code on a build host."""
from pathlib import Path
import hashlib
import json
import statistics
import sys
import time
import traceback


def summary(values):
  values = sorted(values)
  if not values:
    return {"samples": 0}
  def percentile(p):
    position = (len(values)-1)*p
    lo = int(position)
    return values[lo] + (values[min(lo+1,len(values)-1)]-values[lo])*(position-lo)
  return {"samples": len(values), "mean_ms": statistics.mean(values), "p50_ms": percentile(.5),
          "p95_ms": percentile(.95), "maximum_ms": max(values), "over_50_ms": sum(x>50 for x in values)}


def nnapi_devices():
  import ctypes as c
  try:
    lib = c.CDLL("libneuralnetworks.so")
    lib.ANeuralNetworks_getDeviceCount.argtypes = [c.POINTER(c.c_uint32)]
    lib.ANeuralNetworks_getDevice.argtypes = [c.c_uint32,c.POINTER(c.c_void_p)]
    for name in ("Name", "Version"):
      getattr(lib,"ANeuralNetworksDevice_get"+name).argtypes = [c.c_void_p,c.POINTER(c.c_char_p)]
    lib.ANeuralNetworksDevice_getType.argtypes = [c.c_void_p,c.POINTER(c.c_int32)]
    lib.ANeuralNetworksDevice_getFeatureLevel.argtypes = [c.c_void_p,c.POINTER(c.c_int64)]
    def check(result):
      if result: raise RuntimeError(f"NNAPI status {result}")
    count = c.c_uint32(); check(lib.ANeuralNetworks_getDeviceCount(c.byref(count)))
    devices = []
    for i in range(count.value):
      device = c.c_void_p(); check(lib.ANeuralNetworks_getDevice(i,c.byref(device)))
      name, version, kind, level = c.c_char_p(), c.c_char_p(), c.c_int32(), c.c_int64()
      check(lib.ANeuralNetworksDevice_getName(device,c.byref(name)))
      check(lib.ANeuralNetworksDevice_getVersion(device,c.byref(version)))
      check(lib.ANeuralNetworksDevice_getType(device,c.byref(kind)))
      check(lib.ANeuralNetworksDevice_getFeatureLevel(device,c.byref(level)))
      devices.append({"name": name.value.decode(), "version": version.value.decode(), "type": kind.value,
                      "feature_level": level.value, "type_name": {0:"unknown",1:"other",2:"cpu",3:"gpu",4:"accelerator"}.get(kind.value,"unknown"),
                      "hardware_accelerator": kind.value in (3,4)})
    return {"available": True, "devices": devices}
  except Exception as failure:
    return {"available": False, "error": str(failure)}


def fixture(root):
  import numpy as np
  from openpilot.common.transformations.model import get_warp_matrix
  from openpilot.common.transformations.camera import DEVICE_CAMERAS
  metadata = json.loads((root/"fixture/fixture.json").read_text())
  camera = metadata["cameras"]["narrowRoadCameraState"]
  dc = DEVICE_CAMERAS[("tici","ar0231")]
  transforms = {"img": get_warp_matrix(np.zeros(3),dc.narrow_road.intrinsics,False).astype(np.float32),
                "big_img": get_warp_matrix(np.zeros(3),dc.wide_road.intrinsics,True).astype(np.float32)}
  def frames(index):
    return {name: np.frombuffer((root/"fixture"/stream/f"{index:04d}.nv12").read_bytes(),dtype=np.uint8).copy()
            for name,stream in (("img","narrowRoadCameraState"),("big_img","wideRoadCameraState"))}
  return camera, transforms, frames


def model_inputs():
  import numpy as np
  return {"desire_pulse": np.zeros(8,dtype=np.float32), "traffic_convention": np.array([1,0],dtype=np.float32),
          "action_t": np.array([.3,.6],dtype=np.float32)}


def cpu_reference(root, native, report, count, tuned=False, parallel=False, fp16_compute=False):
  import numpy as np
  from android_runtime.worker import configure
  session = root/"s/acceleration00001"; session.mkdir(parents=True,exist_ok=True)
  configure(str(session),native)
  from android_runtime.aot import install
  library = Path(native)/("libopenpilot_kernels_parallel_v82.so" if fp16_compute else "libopenpilot_kernels_parallel.so" if parallel else "libopenpilot_kernels_v82.so" if tuned else "libopenpilot_kernels.so")
  import platform
  abi="arm64-v8a" if platform.machine() in ("aarch64","arm64") else "x86_64"
  actual_library_hash=hashlib.sha256(library.read_bytes()).hexdigest()
  expected_library_hash=json.loads((root/"acceleration-build.json").read_text()).get("native_candidates_sha256",{}).get(abi+"/"+library.name)
  if actual_library_hash != expected_library_hash:
    raise ValueError(f"Native candidate differs from staged build identity: {abi}/{library.name}: expected {expected_library_hash}, actual {actual_library_hash}")
  report["kernel_sha256"]=actual_library_hash
  if parallel:
    import os
    import platform
    import ctypes
    library_handle=ctypes.CDLL(str(library))
    library_handle.op_parallel_set_core_policy.argtypes=[ctypes.c_int]
    library_handle.op_parallel_set_core_policy(0)
    if platform.machine() in ("aarch64","arm64") and os.cpu_count()>=8:
      os.environ["OPENPILOT_ANDROID_FOLD3_CORES"]="1"
      library_handle.op_parallel_set_core_policy(1)
      os.sched_setaffinity(0,{7})
    report["caller_cpu_affinity"]=sorted(os.sched_getaffinity(0))
  install(str(library),allow_qualified=False)
  if tuned or parallel:
    from openpilot_android_vendor.helpers import allocate_inputs,load_pickle
    from tinygrad.engine.realize import lower_and_compile
    artifact=load_pickle(root/"model/driving_tinygrad.pkl",out_of_band=True)
    artifact["run"].captured._linear=lower_and_compile(artifact["run"].captured._linear)
    outputs=allocate_inputs(artifact["output_specs"])
    artifact["run"](output_buffers=outputs,**allocate_inputs(artifact["input_specs"]))
    with np.load(root/"model/reference.npz",allow_pickle=False) as reference:
      for name,value in outputs.items():compare(value.numpy(),reference[name],"Tuned CPU zero "+name)
    report["zero_gate"]={"passed":True,"rtol":1e-4,"atol":1e-5}
  from openpilot.selfdrive.modeld.modeld import ModelState
  camera, transforms, frames = fixture(root)
  model = ModelState(camera["width"],camera["height"],False)
  for _ in range(3): model.run(frames(1),transforms,model_inputs())
  for name in model.state_pairs: model.input_queues[name].assign(0).realize()
  model.prev_desire[:] = 0
  arrays, times = {}, []
  capture=root/"acceleration/capture";capture.mkdir(exist_ok=True)
  capture_hashes={}
  for index in range(1,count+1):
    pair, inputs = frames(index), model_inputs()
    incoming={name:model.input_queues[name].numpy().copy() for name in model.state_pairs} if not (tuned or parallel) else {}
    started = time.perf_counter()
    model.run(pair,transforms,inputs)
    times.append((time.perf_counter()-started)*1000)
    arrays[f"image_{index}"] = model.input_queues["new_img"].numpy().copy()
    arrays[f"output_{index}"] = model.outputs["outputs"].numpy().reshape(-1).copy()
    if not (tuned or parallel):
      incoming.update(new_img=arrays[f"image_{index}"])
      incoming.update({name:values.copy() for name,values in model.npy.items() if name in model.input_shapes})
      incoming.update({"output__"+name:value.numpy().copy() for name,value in model.outputs.items()})
      path=capture/f"{index:04d}.npz";np.savez_compressed(path,**incoming)
      capture_hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
  if capture_hashes:
    (capture/"manifest.json").write_text(json.dumps({"schema":1,"model_role":"road","frames":count,"calibration_frames":[1,40],"holdout_frames":[41,60],
      "model_sha256":json.loads((root/"model/provenance.json").read_text())["model_sha256"],"sha256":capture_hashes,
      "fixture_manifest_sha256":hashlib.sha256((root/"fixture/fixture.json").read_bytes()).hexdigest(),
      "kernel_sha256":actual_library_hash,"transforms":{name:values.tolist() for name,values in transforms.items()},
      "reference_input":"canonical fixture, fixed zero calibration, stationary small inputs",
      "inputs":"actual warped images, small inputs and incoming CPU recurrent states","vehicle_control_enabled":False},indent=2)+"\n")
  for name,tensor in model.outputs.items(): arrays["final_"+name] = tensor.numpy().copy()
  if tuned or parallel:
    report["timing"]=summary(times)
    report["samples_ms"]=times
    np.savez(root/("acceleration/parallel-frames.npz" if parallel else "acceleration/tuned-frames.npz"),**arrays)
    with np.load(root/"acceleration/reference-frames.npz",allow_pickle=False) as reference:
      for name,values in arrays.items():compare(values,reference[name],"Tuned CPU "+name)
    report["sequence_gate"]={"passed":True,"rtol":1e-4,"atol":1e-5}
  else:
    np.savez(root/"acceleration/reference-frames.npz",**arrays)
  report.update(frames=count,passed=True,scope="full_cpu_modelstate_including_warp_and_parser",timing=summary(times),
                samples_ms=times,
                model_sha256=json.loads((root/"model/provenance.json").read_text())["model_sha256"],
                kernel_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                reference_input="canonical_fixture_fixed_zero_calibration_stationary_small_inputs")
  # Sample kernel costs separately so instrumentation does not distort the
  # preceding benchmark. All native calls remain the packaged Android backend.
  from tinygrad.runtime.ops_cpu import CPUProgram
  original=CPUProgram.__call__
  samples={}
  def measured(program,*args,**kwargs):
    start=time.perf_counter()
    result=original(program,*args,**kwargs)
    elapsed=(time.perf_counter()-start)*1000
    key=program.fxn.__name__
    samples.setdefault(key,[]).append(elapsed)
    return result
  CPUProgram.__call__=measured
  try:
    for _ in range(3):model.run(frames(1),transforms,model_inputs())
  finally:CPUProgram.__call__=original
  report["kernel_profile"]=[{"name":name,"calls":len(values),"total_ms":sum(values),"mean_ms":statistics.mean(values)}
                            for name,values in sorted(samples.items(),key=lambda item:-sum(item[1]))[:20]]
  if parallel:
    import ctypes
    stats=(ctypes.c_uint64*2)()
    library_handle=ctypes.CDLL(str(library))
    library_handle.op_parallel_stats.argtypes=[ctypes.POINTER(ctypes.c_uint64)]
    library_handle.op_parallel_stats(stats)
    report["parallel_dispatches"],report["serial_alias_fallbacks"]=map(int,stats)
    masks=(ctypes.c_uint64*3)()
    library_handle.op_parallel_affinities.argtypes=[ctypes.POINTER(ctypes.c_uint64)]
    library_handle.op_parallel_affinities(masks)
    report["worker_affinity_masks"]=list(map(int,masks))


def compare(actual, expected, name):
  import numpy as np
  actual, expected = np.asarray(actual), np.asarray(expected)
  if actual.shape != expected.shape: raise AssertionError(f"{name} shape {actual.shape} != {expected.shape}")
  if actual.dtype == np.uint8 or expected.dtype == np.uint8:
    np.testing.assert_array_equal(actual,expected,err_msg=name)
  else:
    np.testing.assert_allclose(actual,expected,rtol=1e-4,atol=1e-5,err_msg=name)
  return float(np.max(np.abs(actual.astype(np.float64)-expected)))


def ort(root, native, backend, threads, report, count):
  import numpy as np
  from java import jclass
  Bridge = jclass("ai.comma.openpilot.sim.OrtDrivingBridge")
  report["ort_version"]=str(jclass("ai.onnxruntime.OrtEnvironment").getEnvironment().getVersion())
  report["qnn_htp_requested"]=backend=="qnn"
  report["cpu_fallback_disabled"]=backend=="qnn"
  path = str(root/"model/driving_supercombo.onnx")
  runner = Bridge(path,backend,threads,"",native)
  try:
    zero = bytes(2*6*128*256)
    runner.run(zero,[0.]*8,[0.,0.],[0.,0.])
    differences = {}
    with np.load(root/"model/reference.npz",allow_pickle=False) as reference:
      for name in reference.files:
        expected = reference[name]
        actual = (np.array(runner.outputBytes(name),dtype=np.int8).view(np.uint8) if expected.dtype==np.uint8
                  else np.array(runner.outputFloats(name),dtype=np.float32)).reshape(expected.shape)
        differences[name] = compare(actual,expected,name)
    report["zero_gate"] = {"passed": True,"maximum_absolute_difference":differences,"rtol":1e-4,"atol":1e-5}
    for _ in range(3): runner.run(zero,[0.]*8,[1.,0.],[.3,.6])
    runner.reset()
    times, errors = [], []
    with np.load(root/"acceleration/reference-frames.npz",allow_pickle=False) as reference:
      for index in range(1,count+1):
        image = reference[f"image_{index}"].tobytes()
        started = time.perf_counter()
        actual = np.array(runner.run(image,[0.]*8,[1.,0.],[.3,.6]),dtype=np.float32)
        times.append((time.perf_counter()-started)*1000)
        errors.append(compare(actual,reference[f"output_{index}"],f"frame {index}"))
      for name in ("outputs","next_state_img_q","next_state_desire_q","next_state_feat_q"):
        expected = reference["final_"+name]
        actual = (np.array(runner.outputBytes(name),dtype=np.int8).view(np.uint8) if expected.dtype==np.uint8
                  else np.array(runner.outputFloats(name),dtype=np.float32)).reshape(expected.shape)
        compare(actual,expected,"final "+name)
    report.update(passed=True,frames=count,threads=threads,timing=summary(times),
                  samples_ms=times,
                  scope="model_only_plus_java_transfer_and_output_read_no_warp_or_parser",
                  maximum_absolute_difference=max(errors),state_on_runtime=True)
  finally:
    runner.close()
  # Trace an independent short run: CPU fallback must never be labelled NPU work.
  trace = Bridge(path,backend,threads,str(root/f"acceleration/profile-{backend}-{threads}"),native)
  try:
    for _ in range(3): trace.run(zero,[0.]*8,[1.,0.],[.3,.6])
    profile = json.loads(Path(trace.endProfiling()).read_text())
    providers = {}
    for row in profile:
      if provider := row.get("args",{}).get("provider"):
        item = providers.setdefault(provider,{"events":0,"duration_us":0})
        item["events"] += 1; item["duration_us"] += row.get("dur",0)
    report["executed_providers"] = providers
    report["hardware_acceleration_observed"] = any("Nnapi" in key or "QNN" in key for key in providers)
  finally:
    trace.close()


def gpu(root, native, report, count, original_onnx=False, hybrid=False):
  import numpy as np
  from android_runtime.worker import configure
  session=root/"s/acceleration00001";session.mkdir(parents=True,exist_ok=True)
  configure(str(session),native)
  from android_runtime.gpu import RoadRunner, capabilities
  def progress(values):
    (root/'acceleration/gpu-progress.json').write_text(json.dumps({'attempt_id':report['attempt_id'],**values})+'\n')
  progress({'stage':'gpu_capabilities'})
  report["capabilities"] = capabilities()
  progress({'stage':'gpu_constructor','capabilities':report['capabilities']})
  camera, transforms, frames = fixture(root)
  if original_onnx:
    from android_runtime.onnx_gpu import OnnxRoadRunner
    RoadRunner = OnnxRoadRunner
  if hybrid:
    from android_runtime.hybrid_gpu_cpu import HybridRoadRunner
    RoadRunner = HybridRoadRunner
  runner = RoadRunner(root/"model",camera["width"],camera["height"],native,**({} if hybrid or original_onnx else {'progress':progress}))
  report["initialization"] = runner.report
  for warmup in range(3):
    progress({'stage':'gpu_fixture_warmup','index':warmup})
    runner.run_pair(frames(1),transforms,model_inputs())
  runner.reset()
  progress({'stage':'gpu_timed_sequence'})
  timings, differences = [], []
  from openpilot.selfdrive.modeld.parse_model_outputs import Parser
  parser=Parser()
  image_hashes=[];state_checks=0;history_checks=0;parser_times=[]
  with np.load(root/"acceleration/reference-frames.npz",allow_pickle=False) as reference:
    for index in range(1,count+1):
      result = runner.run_pair(frames(index),transforms,model_inputs())
      timings.append(result["timing"])
      # Diagnostic progress and comparisons are outside run_pair's timer.
      # Preserve measured samples even when the next numerical gate rejects.
      report['sequence_timing_samples_ms']=[item['total_ms'] for item in timings]
      report['last_measured_frame']=index
      progress({'stage':'gpu_sequence_comparison','frame':index,'total_ms':timings[-1]['total_ms']})
      differences.append(compare(result["raw"],reference[f"output_{index}"],f"GPU frame {index}"))
      image=runner.inputs["new_img"].numpy()
      np.testing.assert_array_equal(image,reference[f"image_{index}"],err_msg=f"GPU exact warp {index}")
      image_hashes.append(hashlib.sha256(image.tobytes()).hexdigest())
      if not (original_onnx or hybrid):
        with np.load(root/"acceleration/capture"/f"{index:04d}.npz",allow_pickle=False) as capture:
          for name,next_name in runner.state_pairs.items():
            actual=runner.inputs[name].numpy() # Independently evolved GPU state after the model call.
            expected=capture["output__"+next_name]
            compare(actual,expected,f"GPU independently evolved {name} frame {index}")
            state_checks+=1
            if actual.dtype==np.uint8:
              np.testing.assert_array_equal(actual,expected,err_msg=f"GPU exact history {name} frame {index}")
              history_checks+=1
      parsed_at=time.perf_counter();parser.parse_outputs(result["sliced"])
      parser_times.append((time.perf_counter()-parsed_at)*1000)
      report["completed_frames"]=index
    if hybrid:
      for name,value in runner.outputs.items():compare(value.numpy(),reference["final_"+name],"Hybrid final "+name)
  report.update(passed=True,frames=count,timing=summary([x["total_ms"] for x in timings]),
                samples_ms=[x["total_ms"] for x in timings],
                stages={name:summary([x[name] for x in timings]) for name in timings[0]},
                maximum_absolute_difference=max(differences),scope="gpu_warp_cpu_model_no_parser" if hybrid else "full_gpu_warp_model_upload_and_output_no_parser",
                image_and_final_state_gate=hybrid or not original_onnx,
                preprocessing_exact=True,image_sha256=image_hashes,independent_state_checks=state_checks,
                exact_history_checks=history_checks,parser_ms=summary(parser_times),
                end_to_end_timing=summary([t["total_ms"]+p for t,p in zip(timings,parser_times)]))


def cabin_reference(root,native,report,count):
  """Original cabin ORT CPU outputs over recorded fixture luma; no live pixels."""
  if count!=60:raise ValueError("The cabin reference corpus requires all60 fixture frames")
  import numpy as np
  from android_runtime.qnn_diagnostic import loaded,runner,inputs,tensor_output,SOURCE_MODELS
  from android_runtime.gpu_warp import cabin_reference as cabin_pixels
  from openpilot.common.transformations.camera import DEVICE_CAMERAS
  from openpilot.common.transformations.model import dmonitoringmodel_intrinsics
  manifest=loaded(root,"cabin")
  camera,_,frames=fixture(root)
  matrix=(DEVICE_CAMERAS[("tici","ar0231")].narrow_road.intrinsics @ np.linalg.inv(dmonitoringmodel_intrinsics)).astype(np.float32)
  spec={"file":SOURCE_MODELS["cabin"][0],"model_role":"cabin",**manifest["source"]["interfaces"]}
  directory=root/"acceleration/capture-cabin";directory.mkdir(exist_ok=True)
  r=runner(root,native,spec,"cpu","cabin-original-cpu")
  hashes={};times=[]
  try:
    for index in range(1,61):
      pixels=cabin_pixels(frames(index)["img"],matrix,camera["width"],camera["height"])
      if pixels.shape!=(1,1382400) or pixels.dtype!=np.uint8:raise ValueError("Cabin preprocessing interface differs")
      values={"input_img":pixels,"calib":np.zeros((1,3),dtype=np.float32)}
      started=time.monotonic();inputs(r,spec,values);r.execute([])
      outputs={item["name"]:tensor_output(r,item) for item in spec["outputs"]}
      times.append((time.monotonic()-started)*1000)
      r.execute([])
      for item in spec["outputs"]:np.testing.assert_array_equal(outputs[item["name"]],tensor_output(r,item))
      values.update({"output__"+name:value for name,value in outputs.items()})
      path=directory/f"{index:04d}.npz";np.savez_compressed(path,**values)
      hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
  finally:r.close()
  meta={"schema":1,"model_role":"cabin","frames":60,"model_sha256":SOURCE_MODELS["cabin"][1],"sha256":hashes,
        "calibration_frames":[1,40],"holdout_frames":[41,60],"calibration_frame_indices":list(range(40)),
        "fixture_manifest_sha256":hashlib.sha256((root/"fixture/fixture.json").read_bytes()).hexdigest(),
        "preprocessing_provider":"android_runtime.gpu_warp.cabin_reference","transform":matrix.tolist(),
        "reference_provider":"original_onnx_ORT_CPU","reference_repeatable":True,"live_pixels_saved":False,
        "scope":"Recorded narrow-road fixture luma resized by the cabin pixel oracle; no cabin/face accuracy coverage",
        "inputs":"uint8 input_img[1,1382400], FP32 calib[1,3]=0; native original FP16 outputs",
        "vehicle_control_enabled":False}
  from java import jclass
  build=jclass("android.os.Build")
  meta["capture_location"]={"device_model":str(build.MODEL),"device_fingerprint":str(build.FINGERPRINT),
                            "ort_version":str(jclass("ai.onnxruntime.OrtEnvironment").getEnvironment().getVersion())}
  temporary=directory/"manifest.tmp";temporary.write_text(json.dumps(meta,indent=2,allow_nan=False)+"\n");temporary.replace(directory/"manifest.json")
  report.update(passed=True,frames=60,model_role="cabin",model_sha256=meta["model_sha256"],
                capture_manifest_sha256=hashlib.sha256((directory/"manifest.json").read_bytes()).hexdigest(),
                original_reference_provider="ORT_CPU",reference_repeatable=True,scope=meta["scope"],timing=summary(times))


def run(files, native, backend, threads, count, attempt_id, dashboard_visible, model_role="road"):
  if not Path("/system/bin/app_process").exists(): raise RuntimeError("Android target only")
  if backend not in ("capabilities","reference","cpu_tuned","cpu_parallel","cpu_parallel_v82","cpu","xnnpack","nnapi","qnn","qnn_convolution","qnn_fp32","qnn_calibrate","qnn_quantized","qnn_sustain","qnn_boundary","qnn_intermediate","qnn_preprocess","qnn_preprocess_cpu","gpu","gpu_onnx","gpu_hybrid") or not 1<=count<=60:
    raise ValueError("Invalid benchmark configuration")
  if model_role not in ("road","cabin") or (model_role=="cabin" and backend!="reference" and not backend.startswith("qnn_")):
    raise ValueError("Cabin role is available only in explicit QNN/reference experiments")
  root = Path(files); (root/"acceleration").mkdir(exist_ok=True)
  report = {"schema":1,"model_role":model_role,"backend":backend,"attempt_id":attempt_id,"passed":False,"vehicle_control_enabled":False,
            "build_manifest_sha256":hashlib.sha256((root/"acceleration-build.json").read_bytes()).hexdigest()}
  import os
  import threading
  report["pid"]=os.getpid()
  report["scheduling"]={"tid":threading.get_native_id(),"initial_affinity":sorted(os.sched_getaffinity(0)),
                        "nice":os.getpriority(os.PRIO_PROCESS,0),"cgroup":Path("/proc/self/cgroup").read_text(),
                        "dashboard_visible":bool(dashboard_visible)}
  started = time.monotonic()
  try:
    if backend=="capabilities":
      from android_runtime.gpu import capabilities
      report.update(passed=True,opencl=capabilities(),nnapi=nnapi_devices())
    elif backend=="reference" and model_role=="cabin":cabin_reference(root,native,report,count)
    elif backend in ("reference","cpu_tuned","cpu_parallel","cpu_parallel_v82"):
      cpu_reference(root,native,report,count,tuned=backend=="cpu_tuned",parallel=backend.startswith("cpu_parallel"),fp16_compute=backend=="cpu_parallel_v82")
    elif backend.startswith("qnn_"):
      from android_runtime.qnn_diagnostic import run as qnn_run
      qnn_run(root,native,backend,report)
    elif backend in ("gpu","gpu_onnx","gpu_hybrid"): gpu(root,native,report,count,original_onnx=backend=="gpu_onnx",hybrid=backend=="gpu_hybrid")
    else: ort(root,native,backend,threads,report,count)
  except Exception as failure:
    report.update(passed=False,error=f"{type(failure).__name__}: {failure}",traceback=traceback.format_exc())
  finally:
    report["elapsed_seconds"] = time.monotonic()-started
    prefix="" if model_role=="road" else "cabin-"
    (root/f"acceleration/{prefix}{backend}-{threads}.json").write_text(json.dumps(report,indent=2)+"\n")
  return json.dumps(report)
