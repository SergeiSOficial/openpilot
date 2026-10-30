"""Single-request experimental QNN replay. The normal model selection is unchanged."""
import hashlib
import json
from pathlib import Path
import time


def _digest(path):
  with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


def _write(path,value):
  temporary=path.with_suffix(".tmp")
  temporary.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n")
  temporary.replace(path)


def build(base_class,root_session,native_dir):
  """Return an explicitly selected subclass; never install a global/default backend."""
  from java import jclass
  from android_runtime.qnn_diagnostic import DTYPES,loaded,inputs,tensor_output,profile
  import numpy as np
  from tinygrad import Tensor

  if not Path("/system/bin/app_process").is_file() or str(jclass("ai.comma.openpilot.sim.BuildConfig").APPLICATION_ID)!="ai.comma.openpilot.qnn":
    raise RuntimeError("QNN replay is restricted to the isolated Android QNN application")
  root=Path(root_session).resolve(strict=True)
  if root.parent.name!="s" or len(root.name)!=16 or any(c not in "0123456789abcdef" for c in root.name):
    raise ValueError("Invalid QNN replay session")
  app=root.parents[1]
  request_path=root/"qnn-replay-request.json"
  request=json.loads(request_path.read_text())
  created=request.get("created_elapsed_ms")
  now=int(jclass("android.os.SystemClock").elapsedRealtime())
  if type(created) is not int or not 0<=now-created<=600_000:
    raise ValueError("QNN replay request expired or has an invalid elapsed-realtime timestamp")
  if request.get("session")!=root.name or request.get("backend")!="qnn_quantized" or request.get("measured_calibrated") is not True:
    raise ValueError("An explicit matching measured-calibration replay request is required")
  manifest=loaded(app)
  if manifest.get("quantized_model_calibrated") is not True or "quantized" not in manifest.get("models",{}):
    raise ValueError("A measured-calibrated quantized graph has not been staged")
  spec=manifest["models"]["quantized"]
  name=spec["file"]
  if Path(name).name!=name:raise ValueError("Invalid quantized graph filename")
  executed_hash=manifest["sha256"][name]
  if request.get("executed_model_sha256")!=executed_hash:raise ValueError("Requested quantized graph differs from the staged graph")
  quantization=manifest.get("quantization",{})
  if (quantization.get("calibration_frames")!=[1,40] or quantization.get("holdout_frames")!=[41,60]
      or not quantization.get("ranges_file_sha256") or not quantization.get("capture_sha256")):
    raise ValueError("Quantized graph lacks measured calibration and holdout provenance")
  gate_path=app/"acceleration/qnn-quantized-execution.json"
  gate=json.loads(gate_path.read_text())
  if gate.get("hardware_execution") is not True or gate.get("model_sha256")!=executed_hash:
    raise ValueError("The matching 60-frame QNN teacher/free hardware gate is required")
  source_hash=manifest["source"]["sha256"]
  if json.loads((app/"model/provenance.json").read_text())["model_sha256"]!=source_hash:
    raise ValueError("Quantized graph source differs from the retained model source")
  metadata={"backend":"qnn_quantized","experimental":True,"automatically_selected":False,
            "executed_model_file":name,"executed_model_sha256":executed_hash,"source_model_sha256":source_hash,
            "graph_manifest_sha256":_digest(app/"model/qnn-graph-manifest.json"),
            "request_sha256":_digest(request_path),"preceding_hardware_gate_sha256":_digest(gate_path),
            "measured_calibrated":True,"calibration_frames":[1,40],"holdout_frames":[41,60],
            "ranges_file_sha256":quantization["ranges_file_sha256"],"capture_sha256":quantization["capture_sha256"],
            "cpu_fallback_disabled":True,"model_provider":"QNNExecutionProvider","warp_provider":"retained_cpu_aot",
            "parser":"unchanged_base_model_state","chestnut":False,"physical_vehicle_control_enabled":False,
            "scope":"Recorded simulation: QNN execution evidence and original-reference accuracy are separate"}

  class QnnReplayModelState(base_class):
    def __init__(self,cam_w,cam_h,chestnut):
      self._qnn=None;self._qnn_calls=0;self._qnn_samples=[];self._qnn_closed=False
      self._qnn_report={**metadata,"state":"initializing","frames":0,"hardware_execution":False,"finite_outputs":False}
      self._qnn_started=time.monotonic()
      try:
        if chestnut:raise ValueError("Experimental QNN replay supports only the standard driving model")
        super().__init__(cam_w,cam_h,False)
        if not str(self.model_device).startswith("CPU"):raise ValueError("The retained CPU warp/state path is required")
        declared={item["name"]:(tuple(item["shape"]),np.dtype(DTYPES[item["dtype"]])) for item in spec["inputs"]}
        if declared!=self.input_shapes or set(self.outputs)!={item["name"] for item in spec["outputs"]}:
          raise ValueError("Quantized graph does not match the original model state interface")
        for item in spec["outputs"]:
          value=self.outputs[item["name"]]
          if tuple(value.shape)!=tuple(item["shape"]) or value.numpy().dtype!=np.dtype(DTYPES[item["dtype"]]):
            raise ValueError("Quantized graph output schema differs: "+item["name"])
        self._qnn_aliases=self._state_aliases()
        if _digest(app/"model"/name)!=executed_hash:raise ValueError("Quantized graph changed before session creation")
        self._qnn=jclass("ai.comma.openpilot.sim.QnnGraphBridge")(
          str(app/"model"/name),"htp",str(native_dir),str(root/"qnn-replay-profile"))
        self.run_model=self._run_qnn_model
        self._qnn_report.update(state="ready",state_aliases_preserved=True,recurrent_state_pairs=self.state_pairs)
        _write(root/"qnn-backend.json",self._qnn_report)
      except BaseException as error:
        self._failed(error);raise

    def _state_aliases(self):
      aliases={}
      for state,next_state in self.state_pairs.items():
        left,right=self.input_queues[state]._buffer(),self.outputs[next_state]._buffer()
        if left.base is not right.base or left.offset!=right.offset or left.nbytes!=right.nbytes:
          raise ValueError("Retained recurrent buffer alias changed: "+state)
        aliases[state]=(left.base,left.offset,left.nbytes,self.outputs[next_state])
      return aliases

    def _run_qnn_model(self,output_buffers,**supplied):
      try:
        if self._qnn is None or self._qnn_closed or self._qnn_calls>=60:raise RuntimeError("QNN replay is bounded to 60 calls")
        if output_buffers is not self.outputs or set(supplied)!=set(self.input_shapes):raise ValueError("Base model buffers changed")
        if self._state_aliases()!=self._qnn_aliases:raise ValueError("Recurrent state aliases were replaced")
        started=time.monotonic()
        # Snapshot every incoming recurrent state before writing any output alias.
        arrays={key:np.array(value.numpy(),copy=True,order="C") for key,value in supplied.items()}
        inputs(self._qnn,spec,arrays)
        prepared=time.monotonic();self._qnn.execute([]);executed=time.monotonic()
        returned={item["name"]:tensor_output(self._qnn,item) for item in spec["outputs"]}
        # Copy into the existing buffers. Tensor.assign/replacement would risk
        # breaking BaseModelState's next_state -> incoming_state buffer aliases.
        for key,value in returned.items():
          output_buffers[key]._buffer().copy_from(Tensor(value,device="NPY")._buffer())
        if self._state_aliases()!=self._qnn_aliases:raise ValueError("Recurrent state aliases changed after copy")
        self._qnn_calls+=1
        self._qnn_samples.append({"inputs_ms":(prepared-started)*1000,"execute_ms":(executed-prepared)*1000,
                                  "total_adapter_ms":(time.monotonic()-started)*1000})
        self._qnn_report.update(state="running",frames=self._qnn_calls,finite_outputs=True)
        if self._qnn_calls==60:
          attribution=profile(self._qnn)
          if attribution["executed_providers"].get("QNNExecutionProvider",0)<60:
            raise ValueError("QNN trace does not attribute all 60 calls")
          self._qnn_report.update(profile=attribution,hardware_execution=True,state="completed",samples=self._qnn_samples,
                                  elapsed_seconds=time.monotonic()-self._qnn_started)
          self.close()
        _write(root/"qnn-backend.json",self._qnn_report)
      except BaseException as error:
        self._failed(error);raise

    def run(self,*args,**kwargs):
      try:return super().run(*args,**kwargs)
      except BaseException as error:
        self._failed(error);raise

    def close(self):
      if not self._qnn_closed:
        self._qnn_closed=True
        if self._qnn is not None:self._qnn.close()
      self._qnn_report["native_resources_closed"]=True

    def _failed(self,error):
      self._qnn_report.update(state="failed",error=str(error),frames=self._qnn_calls)
      try:self.close()
      except Exception as cleanup:self._qnn_report["cleanup_error"]=str(cleanup)
      try:_write(root/"qnn-backend.json",self._qnn_report)
      except OSError as reporting:error.add_note("QNN diagnostic report write failed: "+str(reporting))

  return QnnReplayModelState
