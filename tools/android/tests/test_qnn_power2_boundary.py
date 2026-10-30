"""Reviewed stdlib-only calibration/rounding/proof checks; no native model code."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
def load(name,path):
  spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
graph=load('power2_static_graph',ROOT/'tools/android/qnn_graph.py')
runtime=load('power2_runtime_policy',ROOT/'android/app/src/main/python/android_runtime/qnn_diagnostic.py')


def measured():
  return {'model_role':'cabin','complete':True,'calibration_model_sha256':'a'*64,
    'source_model_sha256':graph.model_config('cabin')['sha256'],'capture_sha256':'b'*64,
    'calibration_frames':[1,40],'holdout_frames':[41,60],'calibration_frame_indices':list(range(40)),
    'ranges':{'outputs__qnn_internal_fp32':{'min':-7.891676902770996,'max':1.673717975616455,'nonfinite_count':0}}}


def manifest():
  p=graph.derive_cabin_power2_parameters(measured(),'a'*64,'750c1939',54068)
  p.update(ranges_file_sha256='c'*64,pre_power2_quantized_reference_sha256='d'*64,cpu_reference_probe_sha256='e'*64)
  return {'model_role':'cabin','power2_output_boundary':p,
    'output_boundary_probe':{'codes':[0,65535],'scale_float32_le_hex':'00008039','zero_point_uint16':54068},
    'quantization':{key:p[key] for key in ('ranges_file_sha256','capture_sha256','calibration_model_sha256')},
    'models':{'output_boundary_cpu_reference':{'file':'alternate.onnx'},'pre_power2_quantized_reference':{'file':'previous.onnx'},
              'quantized_baseline':{'file':'baseline.onnx'}},
    'sha256':{'alternate.onnx':'e'*64,'previous.onnx':'d'*64,'baseline.onnx':'f'*64},
    'quantized_boundary_baseline_sha256':'f'*64}


class CalibrationDerivedPower2Test(unittest.TestCase):
  def test_smallest_covering_power_preserves_zero_and_split(self):
    p=graph.derive_cabin_power2_parameters(measured(),'a'*64,'750c1939',54068)
    self.assertEqual(p['power_exponent'],-12);self.assertEqual(p['scale_float32_le_hex'],'00008039')
    self.assertEqual(p['zero_point_uint16'],54068)
    self.assertEqual((p['decoded_min'],p['decoded_max']),(-13.2001953125,2.799560546875))
    self.assertEqual(p['holdout_frames'],[41,60]);self.assertTrue(p['quantized_reference_changed'])
    self.assertFalse(p['target_gate_passed']);self.assertFalse(p['host_inference_executed'])

  def test_bad_role_incomplete_foreign_or_holdout_calibration_rejects(self):
    for key,value in (('model_role','road'),('complete',False),('calibration_model_sha256','z'*64),
                      ('calibration_frames',[1,60]),('calibration_frames',[True,40]),('holdout_frames',[40,60]),
                      ('calibration_frame_indices',list(range(1,41))),('calibration_frame_indices',[False,*range(1,40)])):
      d=measured();d[key]=value
      with self.subTest(key=key,value=value),self.assertRaises(ValueError):
        graph.derive_cabin_power2_parameters(d,'a'*64,'750c1939',54068)

  def test_nonfinite_or_boolean_range_and_invalid_quantizer_reject(self):
    for key,value in (('min',True),('max',float('nan')),('min',float('-inf')),('nonfinite_count',1),('nonfinite_count',False)):
      d=measured();d['ranges']['outputs__qnn_internal_fp32'][key]=value
      with self.subTest(key=key,value=value),self.assertRaises(ValueError):
        graph.derive_cabin_power2_parameters(d,'a'*64,'750c1939',54068)
    for bits,zero in (('0000807f',54068),('00000000',54068),('750C1939',54068),('750c1939',True),('750c1939',0),('750c1939',65535)):
      with self.subTest(bits=bits,zero=zero),self.assertRaises(ValueError):
        graph.derive_cabin_power2_parameters(measured(),'a'*64,bits,zero)

  def test_unsupported_subnormal_or_overflow_proof_conditions_reject(self):
    for low,high in ((-1e-8,1e-8),(-1e6,1e6)):
      d=measured();d['ranges']['outputs__qnn_internal_fp32'].update(min=low,max=high)
      with self.subTest(low=low,high=high),self.assertRaises(ValueError):
        graph.derive_cabin_power2_parameters(d,'a'*64,'750c1939',54068)

  def test_old_candidate_directory_and_incomplete_outputs_cannot_be_overwritten(self):
    with tempfile.TemporaryDirectory() as temporary:
      path=Path(temporary)/'new';graph.require_new_power2_directory(path);path.mkdir();graph.require_new_power2_directory(path)
      (path/'old.onnx').write_bytes(b'non-executable static test data')
      with self.assertRaises(ValueError):graph.require_new_power2_directory(path)
      (path/'manifest.json').write_text('{}')
      with self.assertRaises(ValueError):graph.require_new_power2_directory(path)
      (path/'manifest.json').write_text(json.dumps({'power2_output_boundary':{'kind':'calibration_output_power2_v1'}}))
      graph.require_new_power2_directory(path)


class ExactPower2HalfOracleTest(unittest.TestCase):
  def test_all_65536_codes_match_independent_stdlib_half_and_float32_routes(self):
    oracle=runtime.power2_oracle_bytes(-12,54068);expected=bytearray();half_first=bytearray();inexact=0
    for code in range(65536):
      n=code-54068;exact=n/4096
      rounded=struct.unpack('<f',struct.pack('<f',exact))[0];inexact+=exact!=rounded
      expected.extend(struct.pack('<e',rounded))
      n_half=struct.unpack('<e',struct.pack('<e',n))[0];half_first.extend(struct.pack('<e',n_half/4096))
    self.assertEqual(inexact,0);self.assertEqual(oracle,bytes(expected));self.assertEqual(oracle,bytes(half_first))
    bits=struct.unpack('<65536H',oracle)
    self.assertEqual(sum((b&0x7fff)==0 for b in bits),1)
    self.assertFalse(any(((b>>10)&31) in (0,31) for b in bits if b&0x7fff))

  def test_zero_subnormal_ties_normal_boundaries_and_overflow(self):
    for n,k,bits in ((0,-12,0),(1,-25,0),(-1,-25,0x8000),(3,-25,2),
                     (1023,-24,1023),(1024,-24,0x400),(2049,0,0x6800),(2051,0,0x6802),
                     (65519,0,0x7bff),(65520,0,0x7c00),(-65520,0,0xfc00)):
      with self.subTest(n=n,k=k):self.assertEqual(runtime.power2_half_bits(n,k),bits)
    for n,k in ((True,-12),(1,True),(65536,-12),(1,-150),(1,128)):
      with self.subTest(n=n,k=k),self.assertRaises(ValueError):runtime.power2_half_bits(n,k)

  def test_old_scale_reproduces_the_seven_double_rounding_counterexamples(self):
    scale=struct.unpack('<f',bytes.fromhex('750c1939'))[0];different=[]
    for code in range(65536):
      # A 16-bit integer times a binary32 scale is exact in binary64 (<=40 bits).
      exact=(code-54068)*scale;rounded=struct.unpack('<f',struct.pack('<f',exact))[0]
      if struct.pack('<e',exact)!=struct.pack('<e',rounded):different.append(code)
    self.assertEqual(different,[15436,17015,34752,44410,49239,58897,63726])


class Power2ProofBindingTest(unittest.TestCase):
  def test_runtime_accepts_only_the_bound_minimal_power_and_reference(self):
    good=manifest();self.assertEqual(runtime.power2_boundary_parameters(good),(-12,54068))
    for field,value in (('ranges_file_sha256','f'*64),('capture_sha256','a'*64),('cpu_reference_probe_sha256','d'*64),
                        ('calibration_frames',[1,60]),('maximum_integer_difference',True),('target_gate_passed',True),
                        ('decoded_max',0),('power_exponent',-11)):
      bad=copy.deepcopy(good);bad['power2_output_boundary'][field]=value
      with self.subTest(field=field),self.assertRaises(ValueError):runtime.power2_boundary_parameters(bad)

  def test_composed_proof_needs_cpu_oracle_exact_bits_and_all_native_identities(self):
    good=manifest();identities={key:str(index)*64 for index,key in enumerate(
      ('probe_model_sha256','candidate_model_sha256','build_manifest_sha256','graph_manifest_sha256'),1)}
    identities['native_runtime_sha256']={'libQnnHtp.so':'5'*64,'libonnxruntime.so':'6'*64}
    proof={'schema':1,'model_role':'cabin','exact':True,'values_checked':65536,'intermediate_codes_exact':True,
      'baseline_model_sha256':'f'*64,'parameters':good['output_boundary_probe'],'power2_parameters':good['power2_output_boundary'],
      'profile':{'executed_providers':{'QNNExecutionProvider':1}},'cpu_alternate_reference_exact':True,
      'cpu_alternate_codes_exact':True,'oracle_bit_exact':True,'cpu_alternate_reference_sha256':'e'*64,
      'oracle_sha256':hashlib.sha256(runtime.power2_oracle_bytes(-12,54068)).hexdigest(),**identities}
    runtime.validate_composed_output_proof(proof,good,identities)
    for key,value in (('cpu_alternate_reference_exact',False),('cpu_alternate_reference_exact',1),('cpu_alternate_codes_exact',False),
                      ('oracle_bit_exact',1),('cpu_alternate_reference_sha256','f'*64),('oracle_sha256','0'*64),
                      ('power2_parameters',{}),('schema',True),('native_runtime_sha256',{}),
                      ('profile',{'executed_providers':{'QNNExecutionProvider':1,'CPUExecutionProvider':1}})):
      bad=copy.deepcopy(proof);bad[key]=value
      with self.subTest(key=key,value=value),self.assertRaises(ValueError):runtime.validate_composed_output_proof(bad,good,identities)


class PreparedPower2ArtifactsTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.directory=ROOT/'tools/android/.cache/qnn-quantized-cabin-output-power2'
    path=cls.directory/'manifest.json'
    if not path.is_file():raise unittest.SkipTest('Prepare the isolated power2 static graphs first')
    cls.manifest=json.loads(path.read_text())

  def test_every_separate_static_artifact_is_hashed_and_unexecuted(self):
    self.assertFalse(self.manifest['host_inference_executed']);self.assertFalse(self.manifest['target_execution_verified'])
    self.assertEqual(runtime.power2_boundary_parameters(self.manifest),(-12,54068))
    for name,expected in self.manifest['sha256'].items():
      self.assertEqual(name,Path(name).name)
      with (self.directory/name).open('rb') as stream:self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),expected)

  def test_previous_graph_bytes_and_new_reference_identity_are_separate(self):
    m=self.manifest;models=m['models']
    previous=self.directory/models['pre_power2_quantized_reference']['file']
    old=ROOT/'tools/android/.cache/qnn-quantized-cabin-output-dq/cabin_qdq_u16a_u8w_before_output_dq.onnx'
    if old.exists():self.assertEqual(previous.read_bytes(),old.read_bytes())
    old_hash=m['sha256'][previous.name]
    self.assertEqual(old_hash,'7d317e6d8618dd86de2e01f593b0aa208a30627e57adcbd4e06d82d9377773a0')
    self.assertNotEqual(m['quantized_boundary_baseline_sha256'],old_hash)
    self.assertEqual(models['quantized']['inputs'],models['quantized_baseline']['inputs'])
    self.assertEqual(models['quantized']['outputs'],models['quantized_baseline']['outputs'])
    self.assertEqual(models['quantized']['outputs'],[{'name':'outputs','dtype':10,'dtype_name':'FLOAT16','shape':[1,553]}])

  def test_cpu_operator_probe_preserves_exhaustive_transport_and_half_interface(self):
    models=self.manifest['models'];cpu=models['output_boundary_cpu_reference'];htp=models['output_boundary_probe']
    self.assertEqual(cpu['inputs'],htp['inputs']);self.assertEqual(cpu['outputs'],htp['outputs'])
    self.assertEqual(cpu['inputs'],[{'name':'decoded_input','dtype':1,'dtype_name':'FLOAT','shape':[65536]}])
    self.assertEqual([(v['name'],v['dtype'],v['shape']) for v in cpu['outputs']],
                     [('decoded',10,[256,256]),('codes',4,[65536])])


if __name__=='__main__':unittest.main()
