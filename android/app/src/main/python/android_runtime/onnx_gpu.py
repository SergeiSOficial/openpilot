"""Build the original ONNX graph for Adreno instead of retargeting CPU loops.

Runs only inside Android. Uses the existing CL loader and pixel/input contract.
No quantization, model substitution, host model execution or KGSL access.
"""
import base64
import hashlib
import json
from pathlib import Path
import pickle
import time

from android_runtime.gpu import RoadRunner, configure, upload, _verified_asset


class OnnxRoadRunner(RoadRunner):
  def __init__(self, model_root, width, height, native_directory=None, progress=None):
    self.device = configure()
    import numpy as np
    from tinygrad import Tensor, TinyJit
    from tinygrad.nn.onnx import OnnxRunner, OnnxPBParser
    from android_runtime import gpu_warp
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    started = time.monotonic()
    self.root, self.width, self.height = Path(model_root), int(width), int(height)
    provenance_path, _ = _verified_asset(self.root,"provenance.json")
    provenance = json.loads(provenance_path.read_text())
    path = self.root/"driving_supercombo.onnx"
    with path.open("rb") as stream:
      model_hash = hashlib.file_digest(stream,"sha256").hexdigest()
    if model_hash != provenance["model_sha256"]:
      raise ValueError("Original GPU ONNX differs from the retained reference model")
    if progress: progress({"stage":"original_onnx_gpu_compile"})
    network = OnnxRunner(path)
    # Shape constants can have device=None; Tensor.data then clones them to
    # CPU regardless of DEV. Materialize these small constants on CL instead.
    # Keep this local to construction, outside concurrent daemon execution.
    import tinygrad.nn.onnx as onnx
    original_const = onnx._to_python_const
    def cl_const(tensor):
      # Tensor.to is a no-op on device-less constants in this revision. A
      # concrete CL copy gives Tensor.data a real device before it inspects it.
      from tinygrad.dtype import dtypes
      from tinygrad.tensor import Tensor
      concrete=Tensor.empty(*tensor.shape,device="CL",dtype=tensor.dtype if tensor.dtype not in dtypes.weaks else tensor.commit_dtype())
      concrete.assign(tensor).realize()
      return original_const(concrete)
    self.inputs = {name:Tensor.zeros(*value.shape,dtype=value.dtype,device="CL").realize()
                   for name,value in network.graph_inputs.items()}
    self.outputs = {"outputs":Tensor.zeros(1,2576,dtype="float32",device="CL").realize()}
    self.state_pairs = {name:"next_"+name for name in self.inputs if name.startswith("state_")}
    for name,next_name in self.state_pairs.items():
      self.outputs[next_name] = Tensor.zeros(*self.inputs[name].shape,dtype=self.inputs[name].dtype,device="CL").realize()

    @TinyJit(prune=True)
    def model_run(output_buffers, **inputs):
      outputs = network(inputs)
      if set(outputs) != set(output_buffers): raise ValueError("Original ONNX output names differ")
      Tensor.realize(*(output_buffers[name].assign(value) for name,value in outputs.items()))

    self.model_run = model_run
    # Compile, capture and execute the actual JIT before accepting a frame.
    onnx._to_python_const = cl_const
    try:
      for _ in range(3): self.model_run(output_buffers=self.outputs,**self.inputs)
    finally:
      onnx._to_python_const = original_const
    differences = {}
    reference_path, reference_hash = _verified_asset(self.root,"reference.npz")
    with np.load(reference_path,allow_pickle=False) as reference:
      if set(reference.files) != set(self.outputs): raise ValueError("GPU ONNX reference output names differ")
      for name,value in self.outputs.items():
        actual = value.numpy()
        np.testing.assert_allclose(actual,reference[name],rtol=1e-4,atol=1e-5,err_msg="Original ONNX GPU "+name)
        differences[name] = float(np.max(np.abs(actual.astype(np.float64)-reference[name])))
    parser = OnnxPBParser(path,load_external_data=False)
    properties = {}
    for field,wire_type in parser._parse_message(parser.reader.len):
      if field==14:
        entry=parser._parse_StringStringEntryProto();properties[entry["key"]]=entry["value"]
      else: parser.reader.skip_field(wire_type)
    self.output_slices=pickle.loads(base64.b64decode(properties["output_slices"]))
    self.stride,y_height,uv_height,_ = get_nv12_info(self.width,self.height)
    self.frame_copy_size = self.stride*(y_height+uv_height)
    self.frame_tensor = Tensor.zeros(2,self.frame_copy_size,dtype="uint8",device="CL").realize()
    self.transforms_np = np.stack((np.eye(3,dtype=np.float32),np.eye(3,dtype=np.float32)))
    self.transforms = Tensor(self.transforms_np,device="CL").realize()
    self.warp_run = gpu_warp.road(self.width,self.height)
    rng=np.random.default_rng(42)
    frames=rng.integers(0,256,(2,self.frame_copy_size),dtype=np.uint8)
    matrices=np.array([[[1.125,.03125,4],[.015625,1.25,7],[0,0,1]],
                       [[4,-.015625,-32],[.03125,8,-16],[0,0,1]]],dtype=np.float32)
    upload(self.frame_tensor,frames);upload(self.transforms,matrices)
    expected=gpu_warp.road_reference(frames,matrices,self.width,self.height)
    for _ in range(3):
      actual=self.warp_run(input_frame=self.frame_tensor,M_inv=self.transforms).numpy()
      np.testing.assert_array_equal(actual,expected,err_msg="Original ONNX GPU warp")
    self.small_inputs={name:np.zeros(value.shape,dtype=np.float32) for name,value in self.inputs.items()
                       if name not in self.state_pairs and name!="new_img"}
    self.prev_desire=np.zeros(8,dtype=np.float32)
    self.frames=0
    self.reset()
    self.report={"backend":"CL", "source":"original_onnx_gpu_schedule", "model_sha256":model_hash,
                 "provenance":provenance,"recurrent_states_on_gpu":sorted(self.state_pairs),
                 "reference":{"passed":True,"sha256":reference_hash,"rtol":1e-4,"atol":1e-5,
                              "maximum_absolute_difference":differences},
                 "warp":{"passed":True,"pixels":int(actual.size),"maximum_absolute_difference":0},
                 "initialize_seconds":time.monotonic()-started}
