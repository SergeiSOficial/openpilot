"""Stdlib-only tests: never load tinygrad, OpenCL or a native helper."""
import importlib.util
from pathlib import Path
import struct
import json
import random
import math
import ast
import unittest
import sys
from types import SimpleNamespace,ModuleType
from unittest.mock import patch

path=Path(__file__).resolve().parents[3]/'android/app/src/main/python/android_runtime/gpu_diagnostic.py'
spec=importlib.util.spec_from_file_location('gpu_diagnostic_policy',path)
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)


class DiagnosticTest(unittest.TestCase):
  def test_uop_constructor_keywords_match_the_pinned_metaclass_api(self):
    source=Path(__file__).resolve().parents[3]/'tools/android/.cache/python/tinygrad/uop/ops.py'
    if not source.is_file():self.skipTest('Pinned runtime has not been staged')
    cls=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='UOpMetaClass')
    call=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__call__')
    allowed={a.arg for a in call.args.args+call.args.kwonlyargs}-{'cls','op'}
    files=[path.with_name(name) for name in ('gpu.py','gpu_artifact.py','onnx_half.py')]
    files.append(Path(__file__).resolve().parents[3]/'android/app/src/androidTest/assets/gpu_address_diagnostic.py')
    for file in files:
      for node in ast.walk(ast.parse(file.read_text())):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='UOp':
          self.assertFalse({k.arg for k in node.keywords}-allowed,(file.name,node.lineno))

  def test_flat_workgroup_is_a_bijection_with_contiguous_coordinates_first(self):
    import itertools
    for extents in ((128,8,8),(3,5,6),(16,64,32),(7,9,2),(16,)):
      axes=[(i,extent,4*math.prod(extents[i+1:])) for i,extent in enumerate(extents)]
      shape=policy.linear_workgroup(axes)
      self.assertEqual(shape['groups']*shape['lanes'],math.prod(extents))
      if math.prod(extents)>8192:continue
      coordinates=[]
      for flat in range(math.prod(extents)):
        coord=[None]*len(extents)
        for row in shape['axes']:coord[row['dimension']]=(flat//row['divisor'])%row['extent']
        coordinates.append(tuple(coord))
      self.assertEqual(coordinates,list(itertools.product(*(range(e) for e in extents))))
    shape=policy.linear_workgroup([(0,128,256),(1,8,32),(2,8,4)])
    self.assertEqual((shape['groups'],shape['lanes']),(128,64))
    self.assertEqual([row['dimension'] for row in shape['axes']],[2,1,0])

  def test_flat_workgroup_rejects_overflow_and_invalid_axes(self):
    for axes in ([],[(0,8,4),(0,8,4)],[(3,8,4)],[(0,True,4)],[(0,8,0)],[(0,65536,4),(1,65536,4)]):
      with self.subTest(axes=axes),self.assertRaises(ValueError):policy.linear_workgroup(axes)

  def test_captured_serial_7x7_padding_masks_exclude_the_output_arena(self):
    bounds={'channel':(0,127),'row':(0,15),'column':(0,7),'tap':(0,6)}
    coord=(0,{'row':1,'tap':1});vertical=('and',('lt',(2,{}),coord),('lt',coord,(19,{})))
    for constant,width,horizontal in ((1850,2,('lt',(0,{}),(0,{'column':1}))),
                                      (1852,4,('lt',(0,{}),(0,{'column':1}))),
                                      (1856,8,True),(1864,4,('lt',(0,{'column':1}),(7,{}))),
                                      (1868,2,('lt',(0,{'column':1}),(7,{})))):
      form=(constant,{'channel':1024,'row':64,'column':8,'tap':64})
      result=policy.gated_affine_interval(form,bounds,('and',vertical,horizontal))
      # Independent direct integer address enumeration from captured CL source.
      actual=[constant+c*1024+y*64+x*8+k*64 for c in range(128) for y in range(16) for x in range(8) for k in range(7)
              if 2<y+k<19 and (x>0 if constant in (1850,1852) else x<7 if constant in (1864,1868) else True)]
      self.assertEqual(result,(min(actual),max(actual)))
      self.assertLessEqual(result[1]+width,133120)
      self.assertGreater(policy.affine_interval(form,bounds)[1]+width,133120)

  def test_masked_interval_matches_exhaustive_coordinates_and_preserves_other_axes(self):
    rng=random.Random(681)
    for _ in range(250):
      bounds={a:(0,rng.randrange(2,5)) for a in ('x','y','z')}
      form=(rng.randrange(-20,20),{a:rng.randrange(-8,9) for a in bounds})
      gate=(rng.randrange(-5,5),{'x':rng.randrange(-3,4),'y':rng.randrange(-3,4)})
      threshold=rng.randrange(-5,10)
      predicate=('lt',gate,(threshold,{}))
      values=[form[0]+form[1]['x']*x+form[1]['y']*y+form[1]['z']*z
              for x in range(bounds['x'][1]+1) for y in range(bounds['y'][1]+1) for z in range(bounds['z'][1]+1)
              if gate[0]+gate[1]['x']*x+gate[1]['y']*y<threshold]
      self.assertEqual(policy.gated_affine_interval(form,bounds,predicate),(min(values),max(values)) if values else ())

  def test_masked_read_budget_and_empty_domain_are_explicit(self):
    form=(0,{'x':4});bounds={'x':(0,8191)}
    self.assertIsNone(policy.gated_affine_interval(form,bounds,('lt',(0,{'x':1}),(7,{}))))
    self.assertEqual(policy.gated_affine_interval(form,bounds,False),())
    self.assertEqual(policy.gated_affine_interval(form,bounds,True),(0,32764))
    with self.assertRaises(ValueError):policy.gated_affine_interval(form,bounds,('unknown',True,False))

  def test_residue_proof_for_interleaved_planes_and_rejected_overlap(self):
    bounds={'pixel':(0,8191),'plane':(0,5)}
    writes=[((0,{'pixel':8,'plane':65536}),4),((4,{'pixel':8,'plane':65536}),4)]
    self.assertTrue(policy.residue_disjoint(writes,bounds,'pixel'))
    self.assertFalse(policy.residue_disjoint(writes+[((7,{'pixel':8,'plane':65536}),2)],bounds,'pixel'))
    self.assertFalse(policy.residue_disjoint([((0,{'pixel':8,'plane':65535}),4)],bounds,'pixel'))
    self.assertFalse(policy.residue_disjoint([((0,{'pixel':8}),4),((0,{'pixel':4}),4)],bounds,'pixel'))
    self.assertTrue(policy.residue_disjoint([((0,{'pixel':8,'plane':65536}),4),
                                            ((65536,{'pixel':8,'plane':65536}),4)],bounds,'pixel'))
    self.assertFalse(policy.residue_disjoint([((0,{'pixel':8}),4),((8,{'pixel':8}),4)],bounds,'pixel'))
    self.assertFalse(policy.residue_disjoint([((0,{'pixel':8,'plane':65536}),4),
                                             ((65536,{'pixel':8,'plane':131072}),4)],bounds,'pixel',('plane',)))

  def test_residue_proof_uses_axis_keys_without_symbolic_inequality(self):
    class Axis:
      def __ne__(self,other):raise AssertionError('Symbolic inequality cannot be evaluated as a Python condition')
    pixel,plane,selected=Axis(),Axis(),Axis()
    writes=[((0,{pixel:8,plane:65536,selected:3}),8)]
    self.assertTrue(policy.residue_disjoint(writes,{pixel:(0,8191),plane:(0,5),selected:(0,3)},pixel,(selected,)))

  def test_residue_proof_never_accepts_cross_worker_byte_overlap(self):
    rng=random.Random(1982)
    for _ in range(1500):
      extent=rng.randrange(2,8);step=rng.randrange(1,9);period=extent*step
      writes=[((rng.randrange(-period,period),{'x':step,'y':rng.choice([period,2*period,period+1])}),rng.randrange(1,5))
              for _ in range(rng.randrange(1,4))]
      if policy.residue_disjoint(writes,{'x':(0,extent-1),'y':(0,2)},'x'):
        workers=[{c+terms['x']*x+terms['y']*y+byte for (c,terms),width in writes for y in range(3) for byte in range(width)}
                 for x in range(extent)]
        for i in range(extent):
          for j in range(i):self.assertTrue(workers[i].isdisjoint(workers[j]),writes)

  def test_workgroup_mapping_preserves_every_original_index(self):
    for extent in list(range(1,1025))+[8192,196608,2147483647]:
      groups,lanes=policy.workgroup_shape(extent)
      self.assertEqual(groups*lanes,extent)
      self.assertLessEqual(lanes,64)
      self.assertEqual(lanes & (lanes-1),0)
      if extent<=1024:
        self.assertEqual([group*lanes+lane for group in range(groups) for lane in range(lanes)],list(range(extent)))
    self.assertEqual(policy.workgroup_shape(16),(1,16))
    self.assertEqual(policy.workgroup_shape(192),(3,64))
    self.assertEqual(policy.workgroup_shape(128,31),(8,16))

  def test_workgroup_rejects_invalid_or_dynamic_bounds(self):
    for extent in (True,0,-1,2.0,None,2147483648):
      with self.assertRaises(ValueError):policy.workgroup_shape(extent)
    for limit in (False,0,65,1.0,None):
      with self.assertRaises(ValueError):policy.workgroup_shape(128,limit)

  def test_ordered_candidate_materializes_nested_outputs_on_cl(self):
    spec=importlib.util.spec_from_file_location('onnx_order_policy',path.with_name('onnx_half.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    events=[]
    class Tensor:
      def to(self,device,force=False):events.append(('to',device,force));return self
      def realize(self):events.append(('realize',));return self
    tensor=Tensor();runtime=ModuleType('tinygrad');runtime.Tensor=Tensor
    def select(op,opset):
      self.assertEqual((op,opset),('Conv',22))
      def operation(value):events.append(('operation',value));return tensor,[tensor,None],7
      return operation
    runner=SimpleNamespace(_select_op=select)
    with patch.dict(sys.modules,{'tinygrad':runtime}):
      module.materialize_operators(runner)
      result=runner._select_op('Conv',22)('input')
    self.assertEqual(result,(tensor,[tensor,None],7))
    self.assertEqual(events,[('operation','input'),('to','CL',True),('realize',),('to','CL',True),('realize',)])

  def test_referenced_opcodes_exist_in_pinned_runtime_source(self):
    enum_path=Path(__file__).resolve().parents[3]/'tools/android/.cache/python/tinygrad/uop/__init__.py'
    if not enum_path.is_file():self.skipTest('Pinned Android runtime source has not been staged')
    enum=next(node for node in ast.parse(enum_path.read_text()).body if isinstance(node,ast.ClassDef) and node.name=='Ops')
    names={target.id for node in enum.body if isinstance(node,ast.Assign) for target in node.targets if isinstance(target,ast.Name)}
    for filename in ('gpu.py','gpu_artifact.py','onnx_half.py'):
      tree=ast.parse(path.with_name(filename).read_text())
      referenced={node.attr for node in ast.walk(tree) if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id=='Ops'}
      self.assertFalse(referenced-names,(filename,sorted(referenced-names)))
    axis=next(node for node in ast.parse(enum_path.with_name('ops.py').read_text()).body if isinstance(node,ast.ClassDef) and node.name=='AxisType')
    axes={target.id for node in axis.body if isinstance(node,ast.Assign) for target in node.targets if isinstance(target,ast.Name)}
    # Check the actual staged runtime API without importing its compiler/backend.
    diagnostic=Path(__file__).resolve().parents[3]/'android/app/src/androidTest/assets/gpu_address_diagnostic.py'
    for file in (path.with_name('gpu_artifact.py'),path.with_name('onnx_half.py'),diagnostic):
      referenced={node.attr for node in ast.walk(ast.parse(file.read_text())) if isinstance(node,ast.Attribute)
                  and isinstance(node.value,ast.Name) and node.value.id=='AxisType'}
      self.assertFalse(referenced-axes,(file.name,sorted(referenced-axes)))

  def test_affine_interval_matches_enumerated_addresses(self):
    import itertools
    rng=random.Random(88)
    for _ in range(200):
      constant=rng.randrange(-100,100);terms={a:rng.randrange(-8,9) for a in range(3)}
      bounds={a:(0,rng.randrange(1,5)) for a in terms}
      values=[constant+sum(terms[a]*v for a,v in enumerate(point)) for point in
              itertools.product(*(range(bounds[a][0],bounds[a][1]+1) for a in terms))]
      self.assertEqual(policy.affine_interval((constant,terms),bounds),(min(values),max(values)))
    self.assertEqual(policy.affine_interval((7,{'x':-4,'y':8}),{'x':(0,3),'y':(0,2)},('y',)),(-5,7))

  def test_nested_alias_offsets_use_scalar_shrink_bounds_in_bytes(self):
    # Import only the stdlib retargeting module; replace device/UOp dependencies
    # with inert address expressions. No tinygrad or native backend is loaded.
    spec=importlib.util.spec_from_file_location('artifact_addresses',path.with_name('gpu_artifact.py'))
    artifact=importlib.util.module_from_spec(spec);spec.loader.exec_module(artifact)
    class Expr:
      def __init__(self,value):self.value=value
      def __mul__(self,value):return Expr(self.value*value)
      def __add__(self,value):return Expr(self.value+(value.value if isinstance(value,Expr) else value))
      def __radd__(self,value):return self+value
      def simplify(self):return self
      @staticmethod
      def const(value):return Expr(value)
    ops=SimpleNamespace(**{name:name for name in ('CAST','INDEX','SHRINK','BITCAST','PARAM')})
    module=ModuleType('tinygrad.uop.ops');module.Ops=ops;module.UOp=Expr
    dtype=ModuleType('tinygrad.dtype');dtype.AddrSpace=SimpleNamespace(GLOBAL='global')
    wide,narrow=SimpleNamespace(itemsize=4),SimpleNamespace(itemsize=2)
    base=SimpleNamespace(op=ops.PARAM,arg=SimpleNamespace(slot=3),addrspace='global',dtype=wide)
    # Shape-vector sentinels deliberately cannot participate in arithmetic.
    inner=SimpleNamespace(op=ops.SHRINK,src=(base,object()),marg=((7,20),),dtype=wide)
    cast=SimpleNamespace(op=ops.BITCAST,src=(inner,),dtype=narrow)
    view=SimpleNamespace(op=ops.SHRINK,src=(cast,object()),marg=((3,8),),dtype=narrow,max_numel=lambda:5)
    index=SimpleNamespace(op=ops.INDEX,src=(cast,Expr(4)),dtype=narrow,max_numel=lambda:1)
    with patch.dict(sys.modules,{'tinygrad.uop.ops':module,'tinygrad.dtype':dtype}):
      slot,start,width=artifact._pointer_access(view)
      self.assertEqual((slot,start.value,width),(3,34,10))
      slot,start,width=artifact._pointer_access(index)
      self.assertEqual((slot,start.value,width),(3,36,2))

  def test_capture_integrity_requires_all_bytes_and_correct_hash(self):
    data=b'complete tensor bytes'
    self.assertEqual(policy.verify_capture(data,len(data),policy.digest(data)),data)
    for value,size,sha in ((data[:-1],len(data),policy.digest(data)),(b'X'+data[1:],len(data),policy.digest(data)),
                            (data,len(data),''),(data,True,policy.digest(data)),(b'',policy.MAX_CAPTURE_BYTES+1,'0'*64)):
      with self.assertRaises(ValueError):policy.verify_capture(value,size,sha)

  def test_rebased_view_bounds(self):
    self.assertEqual(policy.checked_view(100,60,40),(60,40))
    for values in ((100,61,40),(100,-1,1),(100,False,1),(100,0,101)):
      with self.assertRaises(ValueError):policy.checked_view(*values)

  def test_equal_alias_overlaps_can_be_restored(self):
    views=[(1,12,0,b'abcdefgh'),(1,12,4,b'efghijkl'),(2,8,0,b'XXXXXXXX')]
    self.assertEqual(policy.checked_uploads(views),views)

  def test_conflicting_aliases_are_rejected(self):
    with self.assertRaises(ValueError):policy.checked_uploads([(1,8,0,b'abcdefgh'),(1,8,4,b'xxxx')])

  def test_fp32_rounding_is_per_add_not_a_double_sum(self):
    self.assertEqual(policy.half_dot([1.,1.,1.],[16777216.,1.,-16777216.],0.)['accumulator'],0.)

  def test_half_tie_is_nearest_even(self):
    self.assertEqual(policy.rounded(1.+2**-11,'e'),1.)
    self.assertEqual(policy.rounded(1.+3*2**-11,'e'),1.+2**-9)

  def test_half_subnormal_is_preserved(self):
    self.assertEqual(policy.rounded(2**-24,'e'),2**-24)

  def test_half_cast_happens_before_bias(self):
    row=policy.half_dot([1.],[1.+2**-11],-1.)
    self.assertEqual(row['output'],0.)

  def test_native_half_fma_keeps_product_residual_before_rounding(self):
    a=1.+2**-10;bias=-(1.+2**-9)
    self.assertEqual(policy.native_half_dot([a],[a],bias),2**-20)
    self.assertEqual(policy.rounded(policy.rounded(a*a,'e')+bias,'e'),0.)

  def test_captured_cabin_conv_matches_cpu_bias_first_oracle(self):
    row=json.loads((Path(__file__).parent/'fixtures/cabin_half_bias_first.json').read_text())
    actual=policy.native_half_dot(row['activations'],row['weights'],row['bias'])
    self.assertEqual(actual,row['expected'])
    self.assertNotEqual(actual,row['fp32_bias_before_half'])

  def test_half_fma_matches_independent_double_oracle_including_midpoints(self):
    rng=random.Random(415)
    midpoint_cases=0
    for _ in range(50000):
      a,b,c=(struct.unpack('<e',struct.pack('<H',rng.randrange(65536)))[0] for _ in range(3))
      if not all(math.isfinite(x) for x in (a,b,c)):continue
      expected=policy.rounded(a*b+c,'e')
      actual=policy.exact_half_fma(a,b,c)
      self.assertEqual(struct.pack('<e',actual),struct.pack('<e',expected),(a,b,c))
      naive=policy.rounded(policy.rounded(policy.rounded(a*b,'f')+c,'f'),'e')
      midpoint_cases+=naive!=expected
    for c in (2**-24,-2**-24):
      for i in range(1,1024,2):
        a,b=1.+i/1024,1.5
        expected=policy.rounded(a*b+c,'e')
        self.assertEqual(policy.exact_half_fma(a,b,c),expected)
        naive=policy.rounded(policy.rounded(policy.rounded(a*b,'f')+c,'f'),'e')
        midpoint_cases+=naive!=expected
    self.assertGreater(midpoint_cases,0)

  def test_bad_oracle_input_rejected(self):
    for a,w,b in (([],[],0.),([1.],[],0.),([float('nan')],[1.],0.)):
      with self.assertRaises(ValueError):policy.half_dot(a,w,b)

  def test_recorded_gelu_rounding_matches_packaged_cpu(self):
    row=json.loads((Path(__file__).parent/'fixtures/gpu_gelu_rounding.json').read_text())
    self.assertEqual(policy.retained_gelu_mean(row['values'],row['denominator'])['output'],row['packaged_cpu_output'])
    self.assertNotEqual(row['packaged_cpu_output'],row['original_gpu_output'])

  def test_integer_division_matches_independent_double_then_float_rounding(self):
    rng=random.Random(619)
    for _ in range(10000):
      a,b=(struct.unpack('<f',struct.pack('<I',rng.randrange(0xff000000)))[0] for _ in range(2))
      if not b or not math.isfinite(a) or not math.isfinite(b):continue
      expected=policy.rounded(a/b,'f');actual=policy.exact_f32_div(a,b)
      self.assertEqual(struct.pack('<f',actual),struct.pack('<f',expected),(a,b))

  def test_integer_sqrt_matches_independent_double_oracle(self):
    rng=random.Random(133)
    words=[0,1,2,0x007fffff,0x00800000,0x3f800000,0x40000000,0x7f7fffff]
    words.extend(rng.randrange(0x7f800000) for _ in range(20000))
    for bits in words:
      value=struct.unpack('<f',struct.pack('<I',bits))[0]
      expected=policy.rounded(math.sqrt(value),'f')
      self.assertEqual(struct.pack('<f',policy.exact_f32_sqrt(value)),struct.pack('<f',expected),hex(bits))
    self.assertEqual(struct.pack('<f',policy.exact_f32_sqrt(-0.)),struct.pack('<f',-0.))
    self.assertEqual(policy.exact_f32_sqrt(math.inf),math.inf)
    for value in (-1.,-math.inf,math.nan):self.assertTrue(math.isnan(policy.exact_f32_sqrt(value)))

  def test_captured_frame36_variance_sqrt_matches_packaged_cpu(self):
    row=json.loads((Path(__file__).parent/'fixtures/gpu_sqrt_rounding.json').read_text())
    for sample in row['samples']:
      self.assertEqual(policy.exact_f32_sqrt(sample['input']),sample['expected'])
    failed=row['original_gpu_failure']
    self.assertNotEqual(row['samples'][failed['index']]['expected'],failed['value'])

  def test_mlas_tanh_candidate_bounds_oddness_and_independent_function(self):
    previous=-math.inf
    for index in range(-900,901):
      x=index/100;actual=policy.mlas_tanh_f32(x)
      self.assertLessEqual(abs(actual-math.tanh(x)),2e-6)
      self.assertGreaterEqual(actual,previous-2e-6);previous=actual
      self.assertEqual(actual,-policy.mlas_tanh_f32(-x))
    self.assertEqual(policy.mlas_tanh_f32(math.inf),policy.mlas_tanh_f32(9.))
    self.assertEqual(policy.mlas_tanh_f32(-math.inf),policy.mlas_tanh_f32(-9.))
    self.assertTrue(math.isnan(policy.mlas_tanh_f32(math.nan)))

  def test_fp32_fma_matches_independent_fraction_neighbor_oracle(self):
    from fractions import Fraction
    rng=random.Random(172800)
    decode=lambda word:struct.unpack('<f',struct.pack('<I',word))[0]
    bits=lambda value:struct.unpack('<I',struct.pack('<f',value))[0]
    for _ in range(2000):
      a,b,c=(decode(rng.randrange(0x30000000,0x50000000)|(rng.randrange(2)<<31)) for _ in range(3))
      exact=Fraction(a)*Fraction(b)+Fraction(c)
      approximate=policy.rounded(float(exact),'f');word=bits(approximate)
      candidates=[decode(word+offset) for offset in (-1,0,1)]
      expected=min(candidates,key=lambda value:(abs(Fraction(value)-exact),bits(value)&1))
      self.assertEqual(bits(policy.exact_f32_fma(a,b,c)),bits(expected),(a,b,c))
    a=1.+2**-23;c=-(1.+2**-22)
    self.assertEqual(policy.exact_f32_fma(a,a,c),2**-46)
    self.assertEqual(policy.rounded(policy.rounded(a*a,'f')+c,'f'),0.)
    self.assertEqual(bits(policy.exact_f32_fma(-0.,1.,-0.)),0x80000000)
    with self.assertRaises(ValueError):policy.exact_f32_fma(math.inf,1.,0.)

  def test_captured_cabin_tanh_matches_observed_cpu_contraction(self):
    self.assertEqual(policy.mlas_tanh_f32(0.7457796931266785),0.6326244473457336)

  def test_division_signed_zero_and_nonfinite(self):
    self.assertEqual(struct.pack('<f',policy.exact_f32_div(-0.,1.)),struct.pack('<f',-0.))
    self.assertEqual(policy.exact_f32_div(1.,0.),float('inf'))
    self.assertEqual(policy.exact_f32_div(-1.,0.),-float('inf'))

  def test_exact_division_by_signed_one_for_subnormals_and_extremes(self):
    for bits in (0,1,0x007fffff,0x00800000,0x3f800000,0x7f7fffff,0x80000000,0x80000001,0xff7fffff):
      a=struct.unpack('<f',struct.pack('<I',bits))[0]
      for b in (1.,-1.):
        self.assertEqual(struct.pack('<f',policy.exact_f32_div(a,b)),struct.pack('<f',a/b))


if __name__=='__main__':unittest.main()
