"""Optional device/host isolation of graph execution and camera input staging."""
from pathlib import Path
import hashlib
import json
import os


def run(files, native):
  import numpy as np
  from android_runtime.worker import configure
  base = Path(files)
  session = base / 's/diagnostic000000'
  session.mkdir(parents=True, exist_ok=True)
  configure(str(session), os.environ.get('DIAGNOSTIC_HOST_NATIVE', str(native)))
  models = base / 'model'
  if os.environ.get('DIAGNOSTIC_HOST_MODEL'):
    models = Path(os.environ['DIAGNOSTIC_HOST_MODEL'])
    os.environ['OPENPILOT_ANDROID_MODELS_ROOT'] = str(models)
    os.environ['OPENPILOT_ANDROID_SCHEMAS'] = str(models)
  from android_runtime.aot import install
  install(str(Path(native) / 'libopenpilot_kernels.so'))
  from openpilot_android_vendor.helpers import load_pickle, allocate_inputs
  from tinygrad.engine.realize import lower_and_compile
  from tinygrad import Tensor
  artifact = load_pickle(models/'driving_tinygrad.pkl', out_of_band=True)
  artifact['run'].captured._linear = lower_and_compile(artifact['run'].captured._linear)
  results = {}
  specs = {}
  for case in ['zero', 'pattern']:
    arrays = {}
    for name, (shape, dtype, device) in artifact['input_specs'].items():
      specs[name] = (shape, dtype, device)
      if case == 'zero':
        values = np.zeros(shape, dtype=dtype)
      elif np.dtype(dtype) == np.uint8:
        values = (np.arange(np.prod(shape), dtype=np.int64) % 251).astype(dtype).reshape(shape)
      else:
        values = ((np.arange(np.prod(shape), dtype=np.float32) % 17 - 8) / 32).astype(dtype).reshape(shape)
      arrays[name] = Tensor(values, device=device).realize()
      results[f'{case}_input_{name}'] = values
    outputs = allocate_inputs(artifact['output_specs'])
    artifact['run'](output_buffers=outputs, **arrays)
    for name, tensor in outputs.items():
      results[f'{case}_output_{name}'] = tensor.numpy().copy()
  from openpilot.selfdrive.modeld.modeld import ModelState, ModelConstants
  from openpilot.common.transformations.model import get_warp_matrix
  from openpilot.common.transformations.camera import DEVICE_CAMERAS
  fixture = base/'fixture'
  # Canonical route camera sizes are equal for both streams.
  metadata = json.loads((fixture/'fixture.json').read_text())
  camera = metadata['cameras']['narrowRoadCameraState']
  model = ModelState(camera['width'], camera['height'], False)
  dc = DEVICE_CAMERAS[('tici', 'ar0231')]
  transforms = {'img': get_warp_matrix(np.zeros(3), dc.narrow_road.intrinsics, False).astype(np.float32),
                'big_img': get_warp_matrix(np.zeros(3), dc.wide_road.intrinsics, True).astype(np.float32)}
  frames = {name: np.frombuffer((fixture/camera/'0001.nv12').read_bytes(), dtype=np.uint8)
            for name, camera in [('img', 'narrowRoadCameraState'), ('big_img', 'wideRoadCameraState')]}
  for index in range(2):
    inputs = {'desire_pulse': np.zeros(ModelConstants.DESIRE_LEN, dtype=np.float32),
              'traffic_convention': np.array([1, 0], dtype=np.float32), 'action_t': np.array([0.3, 0.6], dtype=np.float32)}
    model.run(frames, transforms, inputs)
    results[f'frame{index}_warp'] = model.input_queues['new_img'].numpy().copy()
    results[f'frame{index}_packed'] = model.packed_input.copy()
    for name, tensor in model.outputs.items():
      results[f'frame{index}_output_{name}'] = tensor.numpy().copy()
  try:
    model.run(frames, {name: np.zeros((3,3), dtype=np.float32) for name in transforms}, inputs)
  except ValueError as failure:
    assert 'Invalid Android model camera transform' in str(failure)
  else:
    raise AssertionError('Singular camera transform was accepted')
  np.savez(base/'diagnostic.npz', **results)
  (base/'diagnostic.json').write_text(json.dumps({'invalid_transform_rejected':True, 'specs':specs, 'arrays':{name:{'shape':list(v.shape),'dtype':str(v.dtype),
      'min':float(v.min()),'max':float(v.max()),'sha256':hashlib.sha256(v.tobytes()).hexdigest()} for name,v in results.items()}}, indent=2))
