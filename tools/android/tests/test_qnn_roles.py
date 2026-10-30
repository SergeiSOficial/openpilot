"""Reviewed stdlib-only role/provenance tests; no inference, ADB, native imports or compilation."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[3]
TOOLS=ROOT/"tools/android"
sys.path.insert(0,str(TOOLS))


def load(name,path):
  spec=importlib.util.spec_from_file_location(name,path)
  module=importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


graph=load("qnn_role_graph",TOOLS/"qnn_graph.py")
experiment=load("qnn_role_experiment",TOOLS/"test_qnn_experiment.py")
runtime=load("qnn_role_runtime",ROOT/"android/app/src/main/python/android_runtime/qnn_diagnostic.py")
stage=load("qnn_role_stage",TOOLS/"stage_acceleration.py")


def ranges(role="road"):
  return {"model_role":role,"complete":True,"calibration_model_sha256":"a"*64,
          "source_model_sha256":graph.model_config(role)["sha256"],"capture_sha256":"b"*64,
          "calibration_frames":[1,40],"holdout_frames":[41,60],"calibration_frame_indices":list(range(40))}


def corpus(directory,role="road"):
  directory.mkdir(parents=True,exist_ok=True)
  hashes={}
  for index in range(1,61):
    path=directory/f"{index:04d}.npz"
    # Hash/transfer fixture only; deliberately not a model array or real measurement.
    path.write_bytes(b"synthetic provenance-only test "+str(index).encode())
    hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
  meta={"schema":1,"model_role":role,"frames":60,"model_sha256":graph.model_config(role)["sha256"],
        "calibration_frames":[1,40],"holdout_frames":[41,60],"sha256":hashes}
  (directory/"manifest.json").write_text(json.dumps(meta))
  return meta


class QnnRolesTest(unittest.TestCase):
  def test_cpu_oracle_loader_binds_the_reference_graph_apk_and_native_runtime(self):
    baseline="a"*64;reference="b"*64
    graph_manifest={"model_role":"road","source":{"sha256":graph.SOURCE_HASH},
      "quantized_boundary_baseline_sha256":baseline,"models":{"normalization_reference":{"file":"reference.onnx"}},
      "sha256":{"reference.onnx":reference}}
    raw_graph=json.dumps(graph_manifest).encode();raw_build=b'{"schema":1}'
    native_bytes=b"mocked native identity bytes; never an executable file"
    entries={"assets/acceleration/qnn-graph-manifest.json":raw_graph,"assets/acceleration/manifest.json":raw_build,
             "lib/arm64-v8a/libonnxruntime.so":native_bytes}
    class MockArchive:
      def __enter__(self):return self
      def __exit__(self,*args):return False
      def read(self,name):return entries[name]
    report={"backend":"qnn_preprocess","model_role":"road","ort_version":"1.29.0","fresh_report_received":True,
      "cpu_reference_codes":[i*257 for i in range(256)],"graph_manifest_sha256":hashlib.sha256(raw_graph).hexdigest(),
      "build_manifest_sha256":hashlib.sha256(raw_build).hexdigest(),
      "native_runtime_sha256":{"libonnxruntime.so":hashlib.sha256(native_bytes).hexdigest()}}
    with tempfile.TemporaryDirectory() as temporary,patch.object(graph.zipfile,"ZipFile",return_value=MockArchive()):
      root=Path(temporary);path=root/"report.json";apk=root/"metadata-fixture.dat"
      apk.write_bytes(b"mock archive; no native content on disk");(root/"build.json").write_bytes(raw_build)
      path.write_text(json.dumps(report));codes,provenance=graph.load_normalization_oracle(path,apk,baseline,reference)
      self.assertEqual(codes,report["cpu_reference_codes"]);self.assertEqual(provenance["baseline_model_sha256"],baseline)
      for key,value in (("fresh_report_received",False),("model_role","cabin"),("ort_version","1.23.2"),
                        ("cpu_reference_codes",[0]*255),("cpu_reference_codes",[True]+[0]*255),
                        ("graph_manifest_sha256","c"*64),("native_runtime_sha256",{"libonnxruntime.so":"d"*64})):
        changed=copy.deepcopy(report);changed[key]=value;path.write_text(json.dumps(changed))
        with self.subTest(key=key),self.assertRaises(ValueError):graph.load_normalization_oracle(path,apk,baseline,reference)

  def test_normalization_table_preserves_the_existing_quantized_formula_for_all_bytes(self):
    parameters={"cat_scale":0.0036926832981407642,"cat_zero":0,"sub_scale":0.0036926832981407642,
      "sub_zero":34528,"div_scale":5.792444426333532e-05,"div_zero":34528,"mean":127.5,"std":63.75}
    codes=graph.normalization_codes(parameters)
    self.assertEqual(len(codes),256);self.assertEqual([codes[i] for i in (0,121,242,255)],[0,32768,65535,65535])
    self.assertEqual(codes,sorted(codes))
    narrow=graph.normalization_codes({**parameters,"input_scale":0.0036469062324613333,"input_zero":0})
    wide=graph.normalization_codes({**parameters,"input_scale":0.0036926832981407642,"input_zero":0})
    self.assertEqual([narrow[i] for i in (2,3,255)],[541,813,64723])
    self.assertEqual([wide[i] for i in (2,3,255)],[542,812,65535])
    self.assertNotEqual(narrow,wide)
    for key,value in (("std",0),("cat_scale",float("nan")),("div_scale",float("inf")),("sub_zero",True),("cat_zero",-1)):
      bad=dict(parameters);bad[key]=value
      with self.subTest(key=key,value=value),self.assertRaises(ValueError):graph.normalization_codes(bad)

  def test_normalization_proof_cannot_skip_cpu_all_bytes_native_identity_or_provider(self):
    identities={k:"a"*64 for k in ("candidate_model_sha256","baseline_model_sha256","reference_probe_sha256",
      "lut_probe_sha256","table_sha256","build_manifest_sha256","graph_manifest_sha256")}
    identities["native_runtime_sha256"]={"libQnnHtp.so":"b"*64}
    proof={"schema":1,"model_role":"road","values_checked":256,"position_permutations":3,"channels_checked":24,"cpu_all256_exact":True,
      "htp_codes_exact":True,"htp_float_match":True,"profile":{"executed_providers":{"QNNExecutionProvider":1}},**identities}
    runtime.validate_normalization_proof(proof,identities)
    for key,value in (("schema",True),("values_checked",255),("values_checked",256.0),("position_permutations",2),
                      ("channels_checked",23),("cpu_all256_exact",False),
                      ("htp_codes_exact",1),("htp_float_match",False),("native_runtime_sha256",{}),
                      ("table_sha256","c"*64),("profile",{"executed_providers":{"CPUExecutionProvider":1}})):
      bad=copy.deepcopy(proof);bad[key]=value
      with self.subTest(key=key,value=value),self.assertRaises(ValueError):runtime.validate_normalization_proof(bad,identities)

  def test_float32_boundary_transport_recovers_every_uint16_code(self):
    import struct
    f32=lambda value:struct.unpack("<f",struct.pack("<f",value))[0]
    scale=f32(0.0001459585764678195);zero=54068
    for code in range(65536):
      decoded=f32(f32(code-zero)*scale)
      recovered=min(65535,max(0,round(f32(decoded/scale))+zero))
      self.assertEqual(recovered,code)

  def test_cpu_only_normalization_success_cannot_authorize_hardware_execution(self):
    identities={k:"a"*64 for k in ("candidate_model_sha256","baseline_model_sha256","reference_probe_sha256",
      "lut_probe_sha256","table_sha256","build_manifest_sha256","graph_manifest_sha256")}
    identities["native_runtime_sha256"]={"libonnxruntime.so":"b"*64}
    report={"schema":1,"model_role":"road","passed":True,"cpu_only":True,"hardware_execution":False,
      "values_checked":256,"position_permutations":3,"channels_checked":24,"cpu_all256_exact":True,**identities}
    with self.assertRaisesRegex(ValueError,"all256 normalization"):
      runtime.validate_normalization_proof(report,identities)

  def test_composed_reference_requires_exact_all_code_proof_and_same_native_build(self):
    manifest={"model_role":"cabin","quantized_boundary_baseline_sha256":"a"*64,
      "output_boundary_probe":{"codes":[0,65535],"scale_float32_le_hex":"750c1939","zero_point_uint16":54068}}
    identities={name:"b"*64 for name in ("probe_model_sha256","candidate_model_sha256","build_manifest_sha256","graph_manifest_sha256")}
    identities["native_runtime_sha256"]={"libQnnHtp.so":"c"*64,"libonnxruntime.so":"d"*64}
    proof={"schema":1,"model_role":"cabin","exact":True,"values_checked":65536,"intermediate_codes_exact":True,
      "baseline_model_sha256":"a"*64,"parameters":manifest["output_boundary_probe"],
      "profile":{"executed_providers":{"QNNExecutionProvider":1}},**identities}
    runtime.validate_composed_output_proof(proof,manifest,identities)
    for field,value in (("exact",1),("exact",False),("intermediate_codes_exact",False),("intermediate_codes_exact",1),
                        ("values_checked",65535),("values_checked",65536.0),
                        ("baseline_model_sha256","e"*64),("parameters",{}),("native_runtime_sha256",{}),
                        ("build_manifest_sha256","e"*64),
                        ("profile",{"executed_providers":{"QNNExecutionProvider":1,"CPUExecutionProvider":1}}),
                        ("profile",{"executed_providers":{"QNNExecutionProvider":True}})):
      changed=copy.deepcopy(proof);changed[field]=value
      with self.subTest(field=field,value=value),self.assertRaises(ValueError):runtime.validate_composed_output_proof(changed,manifest,identities)
    with self.assertRaises(ValueError):runtime.validate_composed_output_proof(proof,manifest,{})

  def test_sustain_requires_strict_quantized_reference_and_exact_build_identity(self):
    native={"libQnnHtp.so":"e"*64,"libonnxruntime.so":"f"*64}
    good={"model_role":"road","hardware_execution":True,"frames":60,"model_sha256":"a"*64,
          "capture_manifest_sha256":"b"*64,"build_manifest_sha256":"c"*64,"graph_manifest_sha256":"d"*64,
          "quantized_reference_match":True,"original_reference_match":False,"native_runtime_sha256":native}
    def check(value):runtime.require_sustained_gate(value,"road","a"*64,"b"*64,"c"*64,"d"*64,native)
    check(good)  # Original accuracy is separately failed; the isolated fixture test has no live promotion.
    for field,value in (("model_role","cabin"),("hardware_execution",1),("frames",60.0),
                        ("frames",59),("model_sha256","e"*64),("capture_manifest_sha256","e"*64),
                        ("build_manifest_sha256","e"*64),("graph_manifest_sha256","e"*64),
                        ("native_runtime_sha256",None),("native_runtime_sha256",{}),
                        ("native_runtime_sha256",{"libQnnHtp.so":"a"*64,"libonnxruntime.so":"f"*64}),
                        ("native_runtime_sha256",{"libQnnHtp.so":"e"*64}),
                        ("quantized_reference_match",False),("quantized_reference_match",1)):
      changed=dict(good);changed[field]=value
      with self.subTest(field=field,value=value),self.assertRaises(ValueError):check(changed)

  def test_sustain_cannot_accept_matching_but_malformed_native_identities(self):
    good={"model_role":"road","hardware_execution":True,"frames":60,"model_sha256":"a"*64,
          "capture_manifest_sha256":"b"*64,"build_manifest_sha256":"c"*64,"graph_manifest_sha256":"d"*64,
          "quantized_reference_match":True}
    for native in ({},None,{"libQnnHtp.so":True},{"libQnnHtp.so":"bad"},
                   {"libQnnHtp.so":"A"*64},{"../libQnnHtp.so":"e"*64}):
      certificate={**good,"native_runtime_sha256":native}
      with self.subTest(native=native),self.assertRaisesRegex(ValueError,"native runtime"):
        runtime.require_sustained_gate(certificate,"road","a"*64,"b"*64,"c"*64,"d"*64,native)

  def test_exhaustive_boundary_probe_requires_finite_exact_scale_and_uint16_codes(self):
    import struct
    good={"model_role":"cabin","output_boundary_probe":{"codes":[0,65535],
          "scale_float32_le_hex":struct.pack("<f",0.0001459585764678195).hex(),"zero_point_uint16":54068}}
    self.assertEqual(runtime.boundary_probe_parameters(good),(0.0001459585764678195,54068))
    for field,value in (("codes",[False,65535]),("codes",[1,65535]),("codes",None),
                        ("zero_point_uint16",True),("zero_point_uint16",65536),("zero_point_uint16",-1),
                        ("scale_float32_le_hex","0000c07f"),("scale_float32_le_hex","0000807f"),
                        ("scale_float32_le_hex","00000000"),("scale_float32_le_hex","000080bf"),
                        ("scale_float32_le_hex","no-scale")):
      changed=copy.deepcopy(good);changed["output_boundary_probe"][field]=value
      with self.subTest(field=field,value=value),self.assertRaises(ValueError):runtime.boundary_probe_parameters(changed)
    good["model_role"]="road"
    with self.assertRaises(ValueError):runtime.boundary_probe_parameters(good)

  def test_changed_boundary_requires_all_cpu_frames_and_exact_baseline_identity(self):
    manifest={"requires_quantized_boundary_equivalence":True,"models":{"quantized_baseline":{"file":"baseline.onnx"}},
              "quantized_boundary_baseline_sha256":"a"*64,"sha256":{"baseline.onnx":"a"*64}}
    good={"cpu_stateless":{"executed":True,"frames":60,"boundary_cpu_equivalence":True}}
    self.assertTrue(runtime.quantized_boundary_ready(manifest,good,("stateless",)))
    composed=copy.deepcopy(manifest);composed["requires_composed_output_reference"]=True
    self.assertFalse(runtime.quantized_boundary_ready(composed,good,("stateless",)))
    proved=copy.deepcopy(good);proved["cpu_stateless"]["composed_reference_verified"]=True
    self.assertTrue(runtime.quantized_boundary_ready(composed,proved,("stateless",)))
    road={"cpu_"+mode:dict(good["cpu_stateless"]) for mode in ("teacher","free")}
    self.assertTrue(runtime.quantized_boundary_ready(manifest,road,("teacher","free")))
    road["cpu_free"]["frames"]=59
    self.assertFalse(runtime.quantized_boundary_ready(manifest,road,("teacher","free")))
    for field,value in (("executed",False),("executed",1),("frames",59),("boundary_cpu_equivalence",False),("boundary_cpu_equivalence",1)):
      bad=copy.deepcopy(good);bad["cpu_stateless"][field]=value
      with self.subTest(field=field,value=value):self.assertFalse(runtime.quantized_boundary_ready(manifest,bad,("stateless",)))
    self.assertFalse(runtime.quantized_boundary_ready(manifest,{},("stateless",)))
    self.assertFalse(runtime.quantized_boundary_ready(manifest,good,("stateless","free")))
    for field,value in (("quantized_boundary_baseline_sha256","b"*64),("models",{}),("sha256",{})):
      bad=copy.deepcopy(manifest);bad[field]=value
      with self.subTest(field=field):self.assertFalse(runtime.quantized_boundary_ready(bad,good,("stateless",)))

  def test_invalid_graph_selection_preserves_previous_private_stage(self):
    with tempfile.TemporaryDirectory() as temporary:
      root=Path(temporary);previous=root/"private-stage";previous.mkdir()
      marker=previous/"qnn-graph-manifest.json";marker.write_text("previous private graph")
      with patch.object(stage,"ROOT",root),patch.object(stage,"OUT",previous),patch.object(sys,"argv",["stage","--qnn-quantized","--graph-root","missing-graph"]):
        with self.assertRaises(FileNotFoundError):stage.main()
      self.assertEqual(marker.read_text(),"previous private graph")

  def test_graph_preflight_rejects_role_and_hash_mismatches(self):
    with tempfile.TemporaryDirectory() as temporary:
      root=Path(temporary);(root/"graph.onnx").write_bytes(b"synthetic graph integrity fixture")
      metadata={"model_role":"cabin","source":{"sha256":graph.model_config("cabin")["sha256"]},
                "sha256":{"graph.onnx":hashlib.sha256((root/"graph.onnx").read_bytes()).hexdigest()}}
      (root/"manifest.json").write_text(json.dumps(metadata))
      self.assertEqual(stage.graph_bundle(root,"cabin"),metadata)
      with self.assertRaises(ValueError):stage.graph_bundle(root,"road")
      (root/"graph.onnx").write_bytes(b"changed")
      with self.assertRaisesRegex(ValueError,"Graph asset changed"):stage.graph_bundle(root,"cabin")

  def test_contiguous_gather_nd_indices_prove_the_exact_slice(self):
    self.assertEqual(graph.contiguous_gather_slice([[i] for i in range(-9,0)],25),(16,25))
    self.assertEqual(graph.contiguous_gather_slice([[0],[1],[2]],3),(0,3))
    for indices,length in (([],25),([[-26]],25),([[25]],25),([[0],[2]],25),([[2],[1]],25),
                           ([[1],[1]],25),([[True]],25),([[1,2]],25),([1],25),([[0]],0)):
      with self.subTest(indices=indices,length=length),self.assertRaises(ValueError):
        graph.contiguous_gather_slice(indices,length)

  def test_fixed_byte_qdq_is_exact_for_every_uint8_value(self):
    import struct
    def f32(value):return struct.unpack("<f",struct.pack("<f",value))[0]
    for byte in range(256):
      decoded=f32(f32(byte-0)*f32(1.0))
      self.assertEqual(decoded,float(byte))
      requantized=min(255,max(0,round(f32(decoded/f32(1.0)))+0))
      self.assertEqual(requantized,byte)

  def test_roles_bind_distinct_original_models(self):
    self.assertEqual(graph.model_config("road")["sha256"],graph.SOURCE_HASH)
    self.assertEqual(graph.model_config("cabin")["file"],"dmonitoring_model.onnx")
    self.assertNotEqual(graph.model_config("road")["sha256"],graph.model_config("cabin")["sha256"])
    for role in (None,"driver","ROAD",True):
      with self.subTest(role=role),self.assertRaises(ValueError):graph.model_config(role)

  def test_complete_ranges_bind_role_graph_source_and_frame_split(self):
    for role in ("road","cabin"):
      good=ranges(role)
      self.assertEqual(graph.validate_ranges_identity(good,"a"*64,graph.model_config(role)["sha256"],role),"a"*64)
      mutations={"model_role":"cabin" if role=="road" else "road","complete":False,
                 "calibration_model_sha256":"c"*64,"source_model_sha256":"d"*64,
                 "calibration_frames":[1,41],"holdout_frames":[40,60],"calibration_frame_indices":list(range(1,41)),
                 "capture_sha256":"not a hash"}
      for field,bad in mutations.items():
        changed=copy.deepcopy(good);changed[field]=bad
        with self.subTest(role=role,field=field),self.assertRaises(ValueError):
          graph.validate_ranges_identity(changed,"a"*64,graph.model_config(role)["sha256"],role)

  def test_legacy_ranges_are_road_only_and_source_identity_is_required(self):
    legacy=ranges();del legacy["model_role"]
    self.assertEqual(graph.validate_ranges_identity(legacy,"a"*64,graph.SOURCE_HASH),"a"*64)
    with self.assertRaises(ValueError):graph.validate_ranges_identity(legacy,"a"*64,graph.model_config("cabin")["sha256"],"cabin")
    del legacy["source_model_sha256"]
    with self.assertRaises(ValueError):graph.validate_ranges_identity(legacy,"a"*64,graph.SOURCE_HASH)

  def test_capture_and_gate_paths_are_separate(self):
    self.assertEqual(experiment.capture_name("road"),"capture")
    self.assertEqual(experiment.capture_name("cabin"),"capture-cabin")
    for name in ("qnn-ranges.json","fp32-calibration-gate.json","qnn-quantized-execution.json"):
      for role in ("road","cabin"):
        self.assertEqual(experiment.evidence_name(role,name),runtime.role_file({"model_role":role},name))
      self.assertNotEqual(experiment.evidence_name("road",name),experiment.evidence_name("cabin",name))

  def test_capture_hashes_and_model_role_are_checked(self):
    with tempfile.TemporaryDirectory() as temporary:
      directory=Path(temporary);corpus(directory,"cabin")
      self.assertEqual(experiment.validate_capture(directory,"cabin")["frames"],60)
      with self.assertRaises(ValueError):experiment.validate_capture(directory,"road")
      (directory/"0041.npz").write_bytes(b"tampered holdout")
      with self.assertRaisesRegex(ValueError,"hash mismatch"):experiment.validate_capture(directory,"cabin")

  def test_partial_capture_and_unsafe_member_names_are_rejected(self):
    for change in ("missing","path","split","source","boolean_frames"):
      with tempfile.TemporaryDirectory() as temporary:
        directory=Path(temporary);meta=corpus(directory)
        if change=="missing":del meta["sha256"]["0060.npz"]
        elif change=="path":meta["sha256"]["../outside.npz"]="a"*64
        elif change=="split":meta["holdout_frames"]=[40,60]
        elif change=="source":meta["model_sha256"]=graph.model_config("cabin")["sha256"]
        else:meta["frames"]=True
        (directory/"manifest.json").write_text(json.dumps(meta))
        with self.subTest(change=change),self.assertRaises(ValueError):experiment.validate_capture(directory,"road")

  def test_capture_archive_contains_only_the_selected_role(self):
    with tempfile.TemporaryDirectory() as temporary:
      directory=Path(temporary);corpus(directory,"cabin")
      (directory/"unrelated.txt").write_text("must not transfer")
      payload=experiment.capture_archive(directory,"cabin")
      with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        names=archive.getnames()
        self.assertEqual(len(names),61)
        self.assertIn("capture-cabin/manifest.json",names)
        self.assertTrue(all(name.startswith("capture-cabin/") and ".." not in name for name in names))

  def test_capture_import_uses_explicit_qnn_package_and_no_shell_interpolation(self):
    with tempfile.TemporaryDirectory() as temporary:
      directory=Path(temporary);corpus(directory,"cabin")
      with patch.object(experiment.subprocess,"run") as run:
        experiment.import_capture("adb-test","unit-test-serial",directory,"cabin")
      self.assertEqual(run.call_count,2)
      arguments=run.call_args.args[0]
      self.assertEqual(arguments[:5],["adb-test","-s","unit-test-serial","exec-in","run-as"])
      self.assertIn("ai.comma.openpilot.qnn",arguments)
      self.assertIsInstance(run.call_args.kwargs["input"],bytes)

  def test_target_capture_validation_enforces_role_and_holdout_hashes(self):
    with tempfile.TemporaryDirectory() as temporary:
      root=Path(temporary);directory=root/"acceleration/capture-cabin";corpus(directory,"cabin")
      self.assertEqual(runtime.capture(root,{"model_role":"cabin"})[0],directory)
      (directory/"0060.npz").write_bytes(b"tampered")
      with self.assertRaises(ValueError):runtime.capture(root,{"model_role":"cabin"})

  def test_role_mismatch_fails_before_any_native_source_hash(self):
    with tempfile.TemporaryDirectory() as temporary:
      root=Path(temporary);(root/"model").mkdir()
      (root/"model/qnn-graph-manifest.json").write_text(json.dumps({"model_role":"cabin"}))
      (root/"acceleration-build.json").write_text(json.dumps({"model_role":"cabin","sha256":{}}))
      with self.assertRaisesRegex(ValueError,"roles differ"):runtime.loaded(root,"road")


class CabinGraphArtifacts(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.directory=ROOT/"tools/android/.cache/qnn-quantized-cabin"
    if not (cls.directory/"manifest.json").exists():raise unittest.SkipTest("Prepare static cabin graphs first")
    cls.manifest=json.loads((cls.directory/"manifest.json").read_text())

  def test_all_full_graphs_preserve_original_cabin_interface(self):
    self.assertEqual(self.manifest["model_role"],"cabin")
    expected_inputs=[("input_img",2,[1,1382400]),("calib",1,[1,3])]
    for alias in ("fp32_original","fp32","calibration"):
      spec=self.manifest["models"][alias]
      self.assertEqual([(item["name"],item["dtype"],item["shape"]) for item in spec["inputs"]],expected_inputs)
      self.assertEqual([(item["name"],item["dtype"],item["shape"]) for item in spec["outputs"][:1]],[("outputs",10,[1,553])])
    self.assertFalse(self.manifest["calibration_limits"]["requires_actual_incoming_recurrent_state"])
    self.assertFalse(self.manifest["host_inference_executed"])
    self.assertFalse(self.manifest["target_execution_verified"])

  def test_cabin_graph_bytes_and_boundary_cast_are_recorded(self):
    for name,expected in self.manifest["sha256"].items():
      with (self.directory/name).open("rb") as stream:self.assertEqual(hashlib.file_digest(stream,"sha256").hexdigest(),expected)
    ledger=json.loads((self.directory/"conversion-ledger.json").read_text())
    self.assertTrue(any(entry["kind"]=="external_interface_cast" and entry["name"]=="outputs" for entry in ledger["entries"]))


class SupportedRoadArtifacts(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.directory=ROOT/"tools/android/.cache/qnn-quantized-road-supported"
    if not (cls.directory/"manifest.json").exists():raise unittest.SkipTest("Prepare supported road graph first")
    cls.manifest=json.loads((cls.directory/"manifest.json").read_text())
    cls.baseline=json.loads((ROOT/"tools/android/.cache/qnn-quantized/manifest.json").read_text())

  def test_new_graph_requires_equivalence_and_fresh_calibration(self):
    self.assertTrue(self.manifest["supported_road_forms"])
    self.assertTrue(self.manifest["requires_cpu_support_equivalence"])
    self.assertEqual(self.manifest["models"]["fp32"]["inputs"],self.baseline["models"]["fp32"]["inputs"])
    self.assertEqual(self.manifest["models"]["fp32"]["outputs"],self.baseline["models"]["fp32"]["outputs"])
    self.assertEqual(self.manifest["sha256"]["driving_fp32_before_support.onnx"],self.baseline["sha256"]["driving_fp32_calibration.onnx"])
    self.assertNotEqual(self.manifest["sha256"]["driving_fp32_instrumented.onnx"],self.baseline["sha256"]["driving_fp32_instrumented.onnx"])
    tensors={value["name"] for value in self.manifest["calibration_tensors"]}
    for prefix in ("model/linalg_vector_norm","model/linalg_vector_norm_1"):
      self.assertIn(prefix+"__qnn_square",tensors)
      self.assertIn(prefix+"__qnn_sum",tensors)

  def test_seven_supported_formulations_are_explicitly_recorded(self):
    ledger=json.loads((self.directory/"conversion-ledger.json").read_text())
    changes=[entry for entry in ledger["entries"] if entry["kind"].startswith("supported_")]
    self.assertEqual(len(changes),7)
    self.assertEqual(sum(entry["kind"]=="supported_reduce_l2" for entry in changes),2)
    self.assertTrue(all(entry.get("requires_fresh_calibration") or entry.get("value_preserving") for entry in changes))

  def test_original_ranges_cannot_be_relabelled_for_the_new_graph(self):
    old=ROOT/"artifacts/android/qnn-experiment/emulator-5556/20261029T092522Z/qnn-ranges.json"
    if not old.exists():self.skipTest("Original measured road ranges are unavailable")
    measured=json.loads(old.read_text())
    with self.assertRaisesRegex(ValueError,"exact instrumented graph"):
      graph.validate_ranges_identity(measured,self.manifest["sha256"]["driving_fp32_instrumented.onnx"],graph.SOURCE_HASH,"road")


if __name__=="__main__":unittest.main()
