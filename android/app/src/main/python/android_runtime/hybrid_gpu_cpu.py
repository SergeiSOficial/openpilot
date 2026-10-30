"""Explicit GPU-warp / CPU-model candidate, preserving retained model math.

No CPU warp code generation is needed for a new Android camera resolution.
This does not qualify camera geometry, real-time cadence or vehicle operation.
"""
import base64
from pathlib import Path
import pickle
import time


class HybridRoadRunner:
  def __init__(self,model_root,width,height,native_directory,progress=None):
    import numpy as np
    from android_runtime import gpu,gpu_warp,aot
    self.device=gpu.configure()
    from tinygrad import Tensor,Context
    from tinygrad.engine.realize import lower_and_compile
    from openpilot_android_vendor.helpers import load_pickle,allocate_inputs
    from openpilot.selfdrive.modeld.modeld import input_view
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    started=time.monotonic()
    self.root,self.width,self.height=Path(model_root),int(width),int(height)
    if progress:progress({"stage":"hybrid_cpu_model_and_gpu_warp"})
    aot.install(str(Path(native_directory)/"libopenpilot_kernels.so"))
    path,artifact_sha=gpu._verified_asset(self.root,"driving_tinygrad.pkl")
    # Out-of-band weights follow Device.DEFAULT; pin their allocation to CPU
    # even though the warp compiler's default device is CL.
    with Context(DEV="CPU:CLANG"):
      artifact=load_pickle(path,out_of_band=True)
    self.model_run=artifact["run"]
    self.model_run.captured._linear=lower_and_compile(self.model_run.captured._linear)
    self.inputs,self.outputs=allocate_inputs(artifact["input_specs"]),allocate_inputs(artifact["output_specs"])
    self.states={name:"next_"+name for name in self.inputs if "next_"+name in self.outputs}
    self.model_run(output_buffers=self.outputs,**self.inputs)
    reference,_=gpu._verified_asset(self.root,"reference.npz")
    with np.load(reference,allow_pickle=False) as expected:
      if set(expected.files)!=set(self.outputs):raise ValueError("Hybrid model output names differ")
      for name,value in self.outputs.items():
        np.testing.assert_allclose(value.numpy(),expected[name],rtol=1e-4,atol=1e-5,err_msg="Hybrid CPU "+name)
    # Same input/output aliasing as the qualified ModelState implementation.
    # Reset from real zero buffers, not from the result of the numerical probe.
    self.inputs,self.outputs=allocate_inputs(artifact["input_specs"]),allocate_inputs(artifact["output_specs"])
    for name,next_name in self.states.items():
      value=self.inputs[name]
      self.outputs[next_name]=input_view(value._buffer(),value.shape,value.dtype,0)
    self.output_slices=pickle.loads(base64.b64decode(artifact["metadata"]["metadata"]["output_slices"]))
    self.stride,self.y_height,uv_height,_=get_nv12_info(self.width,self.height)
    self.frame_copy_size=self.stride*(self.y_height+uv_height)
    self.frames_gpu=Tensor.zeros(2,self.frame_copy_size,dtype="uint8",device="CL").realize()
    self.matrices_np=np.stack((np.eye(3,dtype=np.float32),np.eye(3,dtype=np.float32)))
    self.matrices_gpu=Tensor(self.matrices_np,device="CL").realize()
    self.warp=gpu_warp.road(self.width,self.height)
    rng=np.random.default_rng(42)
    pixels=rng.integers(0,256,(2,self.frame_copy_size),dtype=np.uint8)
    matrices=np.array([[[1.125,.03125,4],[.015625,1.25,7],[0,0,1]],
                       [[4,-.015625,-32],[.03125,8,-16],[0,0,1]]],dtype=np.float32)
    gpu.upload(self.frames_gpu,pixels);gpu.upload(self.matrices_gpu,matrices)
    expected=gpu_warp.road_reference(pixels,matrices,self.width,self.height)
    for _ in range(3):
      np.testing.assert_array_equal(self.warp(input_frame=self.frames_gpu,M_inv=self.matrices_gpu).numpy(),expected)
    self.small={name:np.zeros(shape,dtype=dtype) for name,(shape,dtype,_) in artifact["input_specs"].items()
                if name not in self.states and name!="new_img"}
    self.previous_desire=np.zeros(8,dtype=np.float32)
    self.frames=0
    self.report={"backend":"CL_warp_CPU_model","artifact_sha256":artifact_sha,
                 "model_reference":{"passed":True,"rtol":1e-4,"atol":1e-5},
                 "warp":{"passed":True,"pixels":int(expected.size),"maximum_absolute_difference":0},
                 "initialize_seconds":time.monotonic()-started,"recurrent_states_on_cpu":True}

  def reset(self):
    import numpy as np
    from tinygrad import Tensor
    for name in self.states:
      value=self.inputs[name]
      value._buffer().copy_from(Tensor(np.zeros(value.shape,dtype=value.numpy().dtype),device="NPY")._buffer())
    self.previous_desire[:]=0

  def run_pair(self,frames,transforms,inputs=None):
    import numpy as np
    from tinygrad import Tensor
    from android_runtime.gpu import upload
    inputs={} if inputs is None else inputs
    start=time.monotonic();frame_ids={}
    for index,name in enumerate(("img","big_img")):
      frame=frames[name]
      if hasattr(frame,"width") and (frame.width,frame.height)!=(self.width,self.height):raise ValueError("Camera dimensions changed")
      if hasattr(frame,"stride") and frame.stride!=self.stride:raise ValueError("Camera stride differs")
      if hasattr(frame,"uv_offset") and frame.uv_offset!=self.stride*self.y_height:raise ValueError("Camera UV offset differs")
      if hasattr(frame,"valid") and not frame.valid:raise ValueError("Invalid camera frame")
      matrix=np.asarray(transforms[name],dtype=np.float32)
      if matrix.shape!=(3,3) or not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix))<1e-9:raise ValueError("Invalid camera transform")
      self.matrices_np[index]=matrix
      frame_ids[name]=upload(self.frames_gpu,frame,size=self.frame_copy_size,offset=index*self.frame_copy_size)
    upload(self.matrices_gpu,self.matrices_np)
    uploaded=time.monotonic()
    image=self.warp(input_frame=self.frames_gpu,M_inv=self.matrices_gpu).numpy()
    self.inputs["new_img"]._buffer().copy_from(Tensor(image,device="NPY")._buffer())
    desire=np.array(inputs.get("desire_pulse",np.zeros(8)),dtype=np.float32,copy=True)
    if desire.shape!=(8,) or not np.all(np.isfinite(desire)):raise ValueError("Invalid desire input")
    desire[0]=0
    self.small["desire"][:]=np.where(desire-self.previous_desire>.99,desire,0);self.previous_desire[:]=desire
    for name,array in self.small.items():
      if name!="desire":array[:]=inputs.get(name,0)
      if not np.all(np.isfinite(array)):raise ValueError("Nonfinite model input: "+name)
      self.inputs[name]._buffer().copy_from(Tensor(array,device="NPY")._buffer())
    prepared=time.monotonic()
    self.model_run(output_buffers=self.outputs,**self.inputs)
    raw=self.outputs["outputs"].numpy().reshape(-1).copy()
    if not np.all(np.isfinite(raw)):raise RuntimeError("Nonfinite hybrid model output")
    end=time.monotonic();self.frames+=1
    return {"raw":raw,"sliced":{name:raw[np.newaxis,region] for name,region in self.output_slices.items()},
            "frame_ids":frame_ids,"frames":self.frames,"timing":{"upload_ms":(uploaded-start)*1000,
            "warp_and_model_input_ms":(prepared-uploaded)*1000,"model_and_download_ms":(end-prepared)*1000,"total_ms":(end-start)*1000}}
