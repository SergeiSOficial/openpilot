"""Run the actual driving ONNX graph using only packaged Android native kernels."""
from pathlib import Path
import json
import time

def run(model_directory: str, native_directory: str) -> str:
  from android_runtime.aot import install
  install(str(Path(native_directory) / "libopenpilot_kernels.so"))
  import numpy as np
  from tinygrad import Tensor
  x = np.arange(32, dtype=np.float32).reshape(4, 8) / 32
  weights = np.arange(24, dtype=np.float32).reshape(8, 3) / 24
  operations = (Tensor(x).matmul(Tensor(weights)).relu() + 0.25).numpy()
  np.testing.assert_allclose(operations, np.maximum(x @ weights, 0) + 0.25, rtol=1e-5, atol=1e-6)
  from openpilot_android_vendor.helpers import allocate_inputs, load_pickle
  from tinygrad.engine.realize import lower_and_compile
  root = Path(model_directory)
  start = time.monotonic()
  artifact = load_pickle(root / "driving_tinygrad.pkl", out_of_band=True)
  artifact["run"].captured._linear = lower_and_compile(artifact["run"].captured._linear)
  inputs = allocate_inputs(artifact["input_specs"])
  outputs = allocate_inputs(artifact["output_specs"])
  artifact["run"](output_buffers=outputs, **inputs)
  results = {name: tensor.numpy().copy() for name, tensor in outputs.items()}
  differences = {}
  with np.load(root / "reference.npz") as expected:
    if set(results) != set(expected.files):
      raise AssertionError("Driving model output names differ from host reference")
    for name, values in results.items():
      np.testing.assert_allclose(values, expected[name], rtol=1e-4, atol=1e-5, err_msg=name)
      differences[name] = float(np.max(np.abs(values - expected[name])))
  return json.dumps({"passed": True, "tensor_operations": ["matmul", "relu", "add"], "numpy": np.__version__, "elapsed_seconds": time.monotonic() - start,
                     "maximum_absolute_difference": differences})
