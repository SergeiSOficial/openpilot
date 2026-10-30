"""On-phone camera warps using the retained openpilot NV12 sampling contract."""


def _sample(source, matrix, out_width, out_height, src_width, src_height, stride):
  from tinygrad import Tensor
  x = Tensor.arange(out_width).reshape(1, out_width).expand(out_height, out_width).reshape(-1)
  y = Tensor.arange(out_height).reshape(out_height, 1).expand(out_height, out_width).reshape(-1)
  sx = matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]
  sy = matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]
  sw = matrix[2, 0] * x + matrix[2, 1] * y + matrix[2, 2]
  ix = Tensor.round(sx / sw).clip(0, src_width - 1).cast("int")
  iy = Tensor.round(sy / sw).clip(0, src_height - 1).cast("int")
  return source[iy * stride + ix]


def road(width, height):
  """Two NV12 frames -> [2,6,128,256], matching compile_warp.py."""
  from tinygrad import Tensor, TinyJit, Context
  from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
  stride, y_height, uv_height, _ = get_nv12_info(width, height)
  model_width, model_height = 512, 256

  def prepare(frame, matrix):
    uv_matrix = matrix * Tensor([[1.0, 1.0, 0.5], [1.0, 1.0, 0.5], [2.0, 2.0, 1.0]], device="CL")
    uv = frame[stride * y_height:stride * (y_height + uv_height)].reshape(uv_height, stride)
    with Context(SPLIT_REDUCEOP=0):
      y = _sample(frame[:height * stride], matrix, model_width, model_height, width, height, stride).realize()
      u = _sample(uv[:height // 2, :width:2].flatten(), uv_matrix,
                  model_width // 2, model_height // 2, width // 2, height // 2, width // 2).realize()
      v = _sample(uv[:height // 2, 1:width:2].flatten(), uv_matrix,
                  model_width // 2, model_height // 2, width // 2, height // 2, width // 2).realize()
    image = y.cat(u).cat(v).reshape(model_height * 3 // 2, model_width)
    return Tensor.cat(image[0:model_height:2, 0::2], image[1:model_height:2, 0::2],
                      image[0:model_height:2, 1::2], image[1:model_height:2, 1::2],
                      image[model_height:model_height + model_height // 4].reshape(model_height // 2, model_width // 2),
                      image[model_height + model_height // 4:model_height + model_height // 2].reshape(model_height // 2, model_width // 2),
                      dim=0).reshape(6, model_height // 2, model_width // 2)

  @TinyJit(prune=True)
  def run(input_frame, M_inv):
    return Tensor.stack(*(prepare(input_frame[i], M_inv[i]) for i in range(2)))
  return run


def cabin(width, height):
  """Driver ONNX expects uint8 [1,1440*960] luma, with edge clamping."""
  from tinygrad import TinyJit
  from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
  stride = get_nv12_info(width, height)[0]

  @TinyJit(prune=True)
  def run(input_frame, M_inv):
    return _sample(input_frame[:height * stride], M_inv, 1440, 960, width, height, stride).reshape(1, 1440 * 960)
  return run


def road_reference(frames, matrices, width, height):
  """Independent NumPy oracle, used only by the on-phone numerical probe."""
  import numpy as np
  from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
  stride, y_height, uv_height, _ = get_nv12_info(width, height)

  def sample(source, matrix, ow, oh):
    y, x = np.indices((oh, ow), dtype=np.float32)
    divisor = matrix[2, 0] * x + matrix[2, 1] * y + matrix[2, 2]
    sx = (matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]) / divisor
    sy = (matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]) / divisor
    ix = np.clip(np.rint(sx), 0, source.shape[1] - 1).astype(np.int32)
    iy = np.clip(np.rint(sy), 0, source.shape[0] - 1).astype(np.int32)
    return source[iy, ix]

  results = []
  for frame, matrix in zip(frames, matrices):
    uv_matrix = matrix * np.array([[1, 1, .5], [1, 1, .5], [2, 2, 1]], dtype=np.float32)
    uv = frame[stride * y_height:stride * (y_height + uv_height)].reshape(uv_height, stride)[:height // 2, :width]
    y = sample(frame[:height * stride].reshape(height, stride)[:, :width], matrix, 512, 256)
    u, v = (sample(uv[:, offset::2], uv_matrix, 256, 128) for offset in (0, 1))
    results.append(np.stack((y[0::2, 0::2], y[1::2, 0::2], y[0::2, 1::2], y[1::2, 1::2], u, v)))
  return np.stack(results)


def cabin_reference(frame, matrix, width, height):
  """Independent complete luma pixel oracle for driver preprocessing."""
  import numpy as np
  from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
  stride = get_nv12_info(width, height)[0]
  y, x = np.indices((960, 1440), dtype=np.float32)
  divisor = matrix[2, 0] * x + matrix[2, 1] * y + matrix[2, 2]
  sx = (matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]) / divisor
  sy = (matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]) / divisor
  ix = np.clip(np.rint(sx), 0, width - 1).astype(np.int32)
  iy = np.clip(np.rint(sy), 0, height - 1).astype(np.int32)
  source = frame[:height * stride].reshape(height, stride)
  return source[iy, ix].reshape(1, 1440 * 960)
