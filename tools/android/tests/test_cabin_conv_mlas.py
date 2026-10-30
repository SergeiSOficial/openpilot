"""Reviewed stdlib-only dispatch/scalar regressions; no model/native runtime.

The two captured dot products are checked with exact rational FMA and explicit
binary32 nearest-even rounding. No host tensor library, FFI, JIT or compiler is
loaded. Fake tinygrad modules exercise dispatch without a device/backend.
"""
from fractions import Fraction
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/'android/app/src/main/python/android_runtime/onnx_half.py'
spec=importlib.util.spec_from_file_location('cabin_conv_policy',SOURCE)
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)


def fraction32(bits):
  if type(bits) is not int or not 0<=bits<2**32 or (bits>>23)&255==255:
    raise ValueError('Finite binary32 bits required')
  exponent=(bits>>23)&255;mantissa=bits&0x7fffff
  if exponent:mantissa|=1<<23
  power=exponent-150 if exponent else -149
  value=Fraction(mantissa<<power) if power>=0 else Fraction(mantissa,1<<-power)
  return -value if bits>>31 else value


def round32(value):
  if value==0:return 0
  sign=0x80000000 if value<0 else 0;n=abs(value.numerator);d=value.denominator
  exponent=n.bit_length()-d.bit_length()
  if (n<d<<exponent) if exponent>=0 else (n<<-exponent<d):exponent-=1
  step=max(exponent-23,-149)
  numerator=n if step>=0 else n<<-step
  denominator=d<<step if step>=0 else d
  mantissa,remainder=divmod(numerator,denominator)
  if remainder*2>denominator or (remainder*2==denominator and mantissa&1):mantissa+=1
  if mantissa==0:return sign
  if exponent<-126:return sign|mantissa
  if mantissa==1<<24:mantissa>>=1;exponent+=1
  if exponent>127:return sign|0x7f800000
  return sign|((exponent+127)<<23)|(mantissa&0x7fffff)


def add32(a,b):
  value=fraction32(a)+fraction32(b)
  if value==0:return 0x80000000 if a==b==0x80000000 else 0
  return round32(value)


def fma32(a,b,c):
  value=fraction32(a)*fraction32(b)+fraction32(c)
  if value==0:
    product_zero=(a&0x7fffffff)==0 or (b&0x7fffffff)==0
    return 0x80000000 if product_zero and ((a^b)>>31) and c==0x80000000 else 0
  return round32(value)


def dot32(terms,bias,panel,fused=True,bias_first=False):
  partials=[]
  for start in range(0,len(terms),panel):
    accumulator=bias if bias_first and start==0 else 0
    for a,b in terms[start:start+panel]:
      accumulator=fma32(a,b,accumulator) if fused else add32(round32(fraction32(a)*fraction32(b)),accumulator)
    partials.append(accumulator)
  total=partials[0]
  for partial in partials[1:]:total=add32(total,partial)
  return total if bias_first else add32(total,bias)


class Conv807DispatchTest(unittest.TestCase):
  def setUp(self):
    self.contract=dict(x_shape=(1,32,120,180),w_shape=(32,32,3,3),b_shape=(32,),auto_pad='NOTSET',
                       dilations=(1,1),group=1,kernel_shape=None,pads=(1,1,1,1),strides=(2,2))

  def test_only_the_measured_contract_is_selected(self):
    self.assertTrue(policy._proven_f32_conv807(**self.contract))
    self.assertTrue(policy._proven_f32_conv807(**{**self.contract,'kernel_shape':[3,3]}))
    self.assertTrue(policy._proven_f32_conv807(**{**self.contract,'x_shape':[1,32,120,180]}))

  def test_other_actual_mlas_dispatch_shapes_are_not_assumed_equivalent(self):
    cases=[{'x_shape':(1,32,60,90),'w_shape':(32,32,1,1),'pads':(0,0,0,0),'strides':(1,1)},
           {'x_shape':(1,32,60,90),'w_shape':(96,32,3,3),'b_shape':(96,)},
           {'x_shape':(1,960,1,1),'w_shape':(1280,960,1,1),'b_shape':(1280,),
            'pads':(0,0,0,0),'strides':(1,1)},
           {'x_shape':(1,192,30,45),'w_shape':(192,1,5,5),'b_shape':(192,),'group':192,'pads':(2,2,2,2)}]
    for changed in cases:
      with self.subTest(changed=changed):self.assertFalse(policy._proven_f32_conv807(**{**self.contract,**changed}))

  def test_changed_or_malformed_attributes_do_not_select_a_kernel(self):
    for key,value in (('x_shape',(True,32,120,180)),('x_shape',(1.,32,120,180)),('x_shape',(1,32,120)),
                      ('x_shape',None),('b_shape',None),('b_shape',(1,32)),('auto_pad','SAME_UPPER'),
                      ('auto_pad',b'NOTSET'),('group',True),('group',2),('kernel_shape',(1,1)),
                      ('pads',(0,0,0,0)),('strides',(1,1)),('dilations',(2,2))):
      with self.subTest(key=key,value=value):self.assertFalse(policy._proven_f32_conv807(**{**self.contract,key:value}))

  def test_install_preserves_the_original_path_for_other_dtypes_and_shapes(self):
    class FakeTensor:
      def __init__(self,shape,dtype='f32'):self.shape=shape;self.dtype=dtype;self.ndim=len(shape)
    fake=types.ModuleType('tinygrad');fake.Tensor=FakeTensor;fake.__path__=[]
    dtype=types.ModuleType('tinygrad.dtype');dtype.dtypes=types.SimpleNamespace(float32='f32',half='f16');dtype.AddrSpace=object()
    uop=types.ModuleType('tinygrad.uop');uop.__path__=[]
    ops=types.ModuleType('tinygrad.uop.ops');ops.UOp=ops.Ops=ops.KernelInfo=object()
    modules={'tinygrad':fake,'tinygrad.dtype':dtype,'tinygrad.uop':uop,'tinygrad.uop.ops':ops}
    calls=[]
    def original(*args,**kwargs):calls.append((args,kwargs));return 'original'
    runner=types.SimpleNamespace(onnx_ops={'Conv':original,'Tanh':lambda value:value})
    kwargs={key:self.contract[key] for key in ('auto_pad','dilations','group','kernel_shape','pads','strides')}
    x=FakeTensor((1,32,120,180));w=FakeTensor((32,32,3,3));b=FakeTensor((32,))
    with patch.dict(sys.modules,modules),patch.object(policy,'_conv_f32_mlas128',return_value='measured') as selected:
      policy.install(runner)
      self.assertEqual(runner.onnx_ops['Conv'](x,w,b,**kwargs),'measured');selected.assert_called_once_with(x,w,b)
      for arguments in ((x,w,None),(x,w,FakeTensor((32,),'f16')),
                        (x,FakeTensor((32,32,3,3),'f16'),b),(FakeTensor((2,32,120,180)),w,b)):
        with self.subTest(arguments=arguments):self.assertEqual(runner.onnx_ops['Conv'](*arguments,**kwargs),'original')
      self.assertEqual(selected.call_count,1)
    self.assertEqual(len(calls),4)

  def test_followup_selection_is_limited_to_the_two_new_measured_shapes(self):
    base={**self.contract,'x_shape':(1,32,60,90)}
    pointwise={**base,'w_shape':(32,32,1,1),'b_shape':(32,),'pads':(0,0,0,0),'strides':(1,1)}
    spatial={**base,'w_shape':(96,32,3,3),'b_shape':(96,)}
    for contract in (pointwise,spatial):
      self.assertTrue(policy._proven_f32_conv_followup(**contract))
      self.assertFalse(policy._proven_f32_conv807(**contract))
    self.assertFalse(policy._proven_f32_conv_followup(**self.contract))
    for key,value in (('group',True),('group',2),('dilations',(2,2)),('auto_pad','VALID'),
                      ('kernel_shape',(3,3)),('x_shape',(1.,32,60,90)),('b_shape',None)):
      with self.subTest(key=key,value=value):
        self.assertFalse(policy._proven_f32_conv_followup(**{**pointwise,key:value}))
    for changed in ({'x_shape':(1,96,30,45),'w_shape':(96,96,1,1),'b_shape':(96,)},
                    {'x_shape':(1,192,15,23),'w_shape':(128,192,1,1),'b_shape':(128,)},
                    {'x_shape':(1,384,15,24),'w_shape':(96,384,1,1),'b_shape':(96,)}):
      with self.subTest(changed=changed):self.assertFalse(policy._proven_f32_conv_followup(**{**pointwise,**changed}))

  def test_installed_dispatch_keeps_the_807_helper_and_routes_only_measured_followups(self):
    class FakeTensor:
      def __init__(self,shape,dtype='f32'):self.shape=shape;self.dtype=dtype;self.ndim=len(shape)
    fake=types.ModuleType('tinygrad');fake.Tensor=FakeTensor;fake.__path__=[]
    dtype=types.ModuleType('tinygrad.dtype');dtype.dtypes=types.SimpleNamespace(float32='f32',half='f16');dtype.AddrSpace=object()
    uop=types.ModuleType('tinygrad.uop');uop.__path__=[]
    ops=types.ModuleType('tinygrad.uop.ops');ops.UOp=ops.Ops=ops.KernelInfo=object()
    runner=types.SimpleNamespace(onnx_ops={'Conv':lambda *args,**kwargs:'original','Tanh':lambda value:value})
    modules={'tinygrad':fake,'tinygrad.dtype':dtype,'tinygrad.uop':uop,'tinygrad.uop.ops':ops}
    with (patch.dict(sys.modules,modules),patch.object(policy,'_conv_f32_mlas128',return_value='807') as old,
          patch.object(policy,'_conv_f32_mlas_followup',return_value='followup') as new):
      policy.install(runner);conv=runner.onnx_ops['Conv']
      kwargs={key:self.contract[key] for key in ('auto_pad','dilations','group','kernel_shape','pads','strides')}
      self.assertEqual(conv(FakeTensor((1,32,120,180)),FakeTensor((32,32,3,3)),FakeTensor((32,)),**kwargs),'807')
      self.assertEqual(old.call_count,1)
      for xshape,wshape,bshape,pads,strides in (
          ((1,32,60,90),(32,32,1,1),(32,),(0,0,0,0),(1,1)),
          ((1,32,60,90),(96,32,3,3),(96,),(1,1,1,1),(2,2)),
          ((1,96,30,45),(64,96,1,1),(64,),(0,0,0,0),(1,1)),
          ((1,192,15,23),(96,192,1,1),(96,),(0,0,0,0),(1,1)),
          ((1,96,15,23),(192,96,1,1),(192,),(0,0,0,0),(1,1)),
          ((1,384,15,23),(96,384,1,1),(96,),(0,0,0,0),(1,1))):
        self.assertEqual(conv(FakeTensor(xshape),FakeTensor(wshape),FakeTensor(bshape),
                              **{**kwargs,'pads':pads,'strides':strides}),'followup')
      self.assertEqual(new.call_count,6);self.assertEqual(old.call_count,1)
      self.assertEqual(conv(FakeTensor((1,32,60,90)),FakeTensor((32,32,1,1)),FakeTensor((32,),'f16'),
                            **{**kwargs,'pads':(0,0,0,0),'strides':(1,1)}),'original')
      self.assertEqual(new.call_count,6)

  def test_only_the_four_new_complete_pointwise_geometries_select(self):
    geometries=(((1,96,30,45),(64,96,1,1),(64,)),((1,192,15,23),(96,192,1,1),(96,)),
                ((1,96,15,23),(192,96,1,1),(192,)),((1,384,15,23),(96,384,1,1),(96,)))
    for x,w,b in geometries:
      contract={**self.contract,'x_shape':x,'w_shape':w,'b_shape':b,'pads':(0,0,0,0),'strides':(1,1)}
      with self.subTest(shapes=(x,w,b)):
        self.assertTrue(policy._proven_f32_conv_followup(**contract))
        self.assertFalse(policy._proven_f32_conv807(**contract))
      for key,value in (('x_shape',(1,x[1],x[2],x[3]+1)),('x_shape',(True,*x[1:])),('x_shape',(1.,*x[1:])),
                        ('w_shape',(w[0]+1,*w[1:])),('b_shape',(b[0]+1,)),('kernel_shape',(3,3)),
                        ('pads',(1,1,1,1)),('strides',(2,2)),('group',True),('group',x[1]),('dilations',(2,2))):
        with self.subTest(shapes=(x,w,b),key=key,value=value):
          self.assertFalse(policy._proven_f32_conv_followup(**{**contract,key:value}))

  def test_conv807_proven_helper_is_byte_for_byte_unchanged(self):
    source=SOURCE.read_text();function=next(node for node in ast.parse(source).body
      if isinstance(node,ast.FunctionDef) and node.name=='_conv_f32_mlas128')
    self.assertEqual(hashlib.sha256(ast.get_source_segment(source,function).encode()).hexdigest(),
                     'bb9edc63c6aca6cf16a47c689f735c0aaa009d1ff8c73931147252cbf85bb824')


class ExactScalarOracleTest(unittest.TestCase):
  def test_nearest_even_at_normal_subnormal_and_exponent_boundaries(self):
    for value,bits in ((Fraction(1)+Fraction(1,2**24),0x3f800000),
                       (Fraction(1)+Fraction(3,2**24),0x3f800002),
                       (Fraction(2)-Fraction(1,2**24),0x40000000),
                       (Fraction(1,2**150),0),(Fraction(3,2**150),2),
                       (-Fraction(1,2**150),0x80000000)):
      with self.subTest(value=value):self.assertEqual(round32(value),bits)

  def test_fused_result_cannot_be_replaced_with_two_roundings(self):
    a=0x3f800001;b=0x3f7ffffe;c=0xbf800000
    self.assertEqual(fma32(a,b,c),0xa8800000)
    self.assertEqual(add32(round32(fraction32(a)*fraction32(b)),c),0)

  def test_signed_zero_and_finite_domain_are_explicit(self):
    self.assertEqual(fma32(0x80000000,0x3f800000,0x80000000),0x80000000)
    self.assertEqual(fma32(0x80000000,0x3f800000,0),0)
    for bits in (True,-1,2**32,0x7f800000,0xff800000,0x7fc00000):
      with self.subTest(bits=bits),self.assertRaises(ValueError):fraction32(bits)

  def test_captured_cpu_bits_require_the_measured_panel_schedule(self):
    fixture=json.loads((Path(__file__).parent/'fixtures/cabin_conv807_f32.json').read_text())
    self.assertEqual(fixture['node'],'node_Conv_807');self.assertEqual(fixture['case_count'],2)
    self.assertEqual(fixture['installed_main_apk_sha256'],'a6688cd7fed267a07a79f5690ead023f6994db80be3b6ac776acd236ad43a6ee')
    source=ROOT/fixture['source_evidence']/'cabin-fp32-conv807.npz'
    if source.exists():
      with source.open('rb') as stream:self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),fixture['source_array_sha256'])
    different_single_chain=False
    modes=(('fma_k288_bias_last',288,True,False),('fma_k128_bias_last',128,True,False),
           ('separate_k288_bias_last',288,False,False),('fma_k256_bias_last',256,True,False),('fma_k288_bias_first',288,True,True))
    for case in fixture['cases']:
      terms=[tuple(int(value,16) for value in term) for term in case['terms']]
      self.assertEqual(len(terms),288);bias=int(case['bias_bits'],16)
      for name,panel,fused,bias_first in modes:
        with self.subTest(coordinates=case['coordinates'],mode=name):
          actual=dot32(terms,bias,panel,fused,bias_first)
          self.assertEqual(actual,int(case['measured_variant_bits'][name],16))
          if panel==128:self.assertEqual(actual,int(case['expected_bits'],16))
      different_single_chain|=case['measured_variant_bits']['fma_k288_bias_last']!=case['expected_bits']
    self.assertTrue(different_single_chain)

  def test_captured_followup_bits_require_fma32_and_panel128(self):
    fixture=json.loads((Path(__file__).parent/'fixtures/cabin_conv_followup_f32.json').read_text())
    self.assertEqual({row['node'] for row in fixture['nodes']},{'node_Conv_809','node_Conv_811'})
    for row in fixture['nodes']:
      source=ROOT/row['source_evidence']/'cabin-f32-followup.npz'
      if source.exists():
        with source.open('rb') as stream:self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),row['source_array_sha256'])
      legacy_different=False
      for case in row['cases']:
        terms=[tuple(int(value,16) for value in term) for term in case['terms']];bias=int(case['bias_bits'],16)
        for label,expected in case['measured_variant_bits'].items():
          if label=='legacy_tinygrad':
            legacy_different|=expected!=case['expected_bits'];continue
          panel=int(label.rsplit('k',1)[1]);fused=not label.startswith('separate_')
          with self.subTest(node=row['node'],coordinate=case['coordinates'],variant=label):
            actual=dot32(terms,bias,panel,fused)
            self.assertEqual(actual,int(expected,16))
            if label.startswith('candidate_'):self.assertEqual(actual,int(case['expected_bits'],16))
      self.assertTrue(legacy_different)

  def test_captured_four_pointwise_signatures_require_fma_panels_and_bias_last(self):
    fixture=json.loads((Path(__file__).parent/'fixtures/cabin_conv_batch_f32.json').read_text())
    self.assertEqual({row['node'] for row in fixture['nodes']},{'node_Conv_813','node_Conv_827','node_Conv_829','node_Conv_851'})
    self.assertEqual(fixture['installed_main_apk_sha256'],'ce6509d71607e8412065038e91285ffad1763aa075e051b39ea680b6ebb9d171')
    self.assertEqual(fixture['diagnostic_sha256'],'f50003bbeff0a197aee913e5f8cb4aadc696cd6736bbec35af4f9a22c2ebf49f')
    for row in fixture['nodes']:
      source=ROOT/row['source_evidence']/(row['node']+'.npz')
      if source.exists():
        with source.open('rb') as stream:self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),row['source_array_sha256'])
      for case in row['cases']:
        terms=[tuple(int(value,16) for value in term) for term in case['terms']];bias=int(case['bias_bits'],16)
        expected=int(case['expected_bits'],16);k=len(terms)
        with self.subTest(node=row['node'],coordinates=case['coordinates']):
          self.assertEqual(dot32(terms,bias,min(128,k)),expected)
          self.assertEqual(int(case['measured_variant_bits']['candidate_fma_k128'],16),expected)
          self.assertNotEqual(int(case['measured_variant_bits']['legacy_tinygrad'],16),expected)
          self.assertNotEqual(dot32(terms,bias,k,False),expected)
          if k>128:self.assertNotEqual(dot32(terms,bias,k),expected)


if __name__=='__main__':unittest.main()
