"""Reviewed stdlib exact scalar/dispatch regressions, without a tensor backend."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from tools.android.tests.test_cabin_conv_mlas import ROOT,SOURCE,policy,dot32

GEOMETRIES=((192,30,45,5,2,2),(192,15,23,3,1,1),(576,15,23,3,2,1),
            (512,8,12,5,1,2),(384,8,12,5,1,2),(512,8,12,3,1,1))


def contract(geometry):
  channels,height,width,kernel,stride,pad=geometry
  return {'x_shape':(1,channels,height,width),'w_shape':(channels,1,kernel,kernel),'b_shape':(channels,),
          'auto_pad':'NOTSET','dilations':(1,1),'group':channels,'kernel_shape':None,'pads':(pad,)*4,'strides':(stride,)*2}


class MeasuredDepthwiseDispatchTest(unittest.TestCase):
  def test_only_six_complete_contracts_accept(self):
    for geometry in GEOMETRIES:
      values=contract(geometry)
      with self.subTest(geometry=geometry):
        self.assertTrue(policy._proven_f32_depthwise(**values))
        self.assertTrue(policy._proven_f32_depthwise(**{**values,'kernel_shape':list(values['w_shape'][2:])}))
        self.assertFalse(policy._proven_f32_conv807(**values))
        self.assertFalse(policy._proven_f32_conv_followup(**values))

  def test_neighbor_shapes_group_multipliers_and_other_attributes_reject(self):
    for geometry in GEOMETRIES:
      values=contract(geometry);channels,height,width,kernel,stride,pad=geometry
      for key,value in (('x_shape',(1,channels,height,width+1)),('x_shape',(2,channels,height,width)),
                        ('w_shape',(channels,2,kernel,kernel)),('w_shape',(channels+1,1,kernel,kernel)),
                        ('b_shape',(channels+1,)),('group',1),('group',channels//2),
                        ('strides',(3-stride,)*2),('pads',(pad+1,)*4),('dilations',(2,2)),
                        ('auto_pad','SAME_UPPER'),('kernel_shape',(kernel+2,)*2)):
        with self.subTest(geometry=geometry,key=key,value=value):
          self.assertFalse(policy._proven_f32_depthwise(**{**values,key:value}))

  def test_malformed_types_do_not_select_production(self):
    values=contract(GEOMETRIES[0])
    for key,value in (('group',True),('group',192.),('group',None),('auto_pad',b'NOTSET'),
                      ('x_shape',None),('x_shape',(True,192,30,45)),('x_shape',(1.,192,30,45)),
                      ('w_shape',(192,True,5,5)),('b_shape',(192.,)),('pads',[True,2,2,2]),
                      ('strides',[2.,2]),('kernel_shape',[5.,5]),('dilations',None)):
      with self.subTest(key=key,value=value):self.assertFalse(policy._proven_f32_depthwise(**{**values,key:value}))

  def test_installed_dispatch_selects_only_measured_float32_inputs(self):
    class FakeTensor:
      def __init__(self,shape,dtype='f32'):self.shape=shape;self.dtype=dtype;self.ndim=len(shape)
    fake=types.ModuleType('tinygrad');fake.Tensor=FakeTensor;fake.__path__=[]
    dtype=types.ModuleType('tinygrad.dtype');dtype.dtypes=types.SimpleNamespace(float32='f32',half='f16');dtype.AddrSpace=object()
    uop=types.ModuleType('tinygrad.uop');uop.__path__=[]
    ops=types.ModuleType('tinygrad.uop.ops');ops.UOp=ops.Ops=ops.KernelInfo=object()
    modules={'tinygrad':fake,'tinygrad.dtype':dtype,'tinygrad.uop':uop,'tinygrad.uop.ops':ops}
    runner=types.SimpleNamespace(onnx_ops={'Conv':lambda *args,**kwargs:'original','Tanh':lambda value:value})
    with patch.dict(sys.modules,modules),patch.object(policy,'_conv_f32_mlas_depthwise',return_value='measured') as helper:
      policy.install(runner);conv=runner.onnx_ops['Conv']
      for geometry in GEOMETRIES:
        values=contract(geometry);x,w,b=[FakeTensor(values[key]) for key in ('x_shape','w_shape','b_shape')]
        options={key:value for key,value in values.items() if key not in ('x_shape','w_shape','b_shape')}
        self.assertEqual(conv(x,w,b,**options),'measured')
        helper.assert_called_with(x,w,b,pads=options['pads'],strides=options['strides'],group=options['group'])
        for arguments in ((x,w,None),(x,w,FakeTensor(b.shape,'f16')),
                          (x,FakeTensor(w.shape,'f16'),b),(FakeTensor((2,*x.shape[1:])),w,b)):
          with self.subTest(geometry=geometry,arguments=arguments):self.assertEqual(conv(*arguments,**options),'original')
        self.assertEqual(conv(x,w,b,**{**options,'group':1}),'original')
      self.assertEqual(helper.call_count,6)

  def test_all_prior_twelve_node_guard_and_helper_bodies_remain_unchanged(self):
    expected={'_proven_f32_conv807':'0b49d95807386a523635c8b6cf9f68803cb9f1134f1a58d881796bc5a80aeb64',
      '_proven_f32_conv_followup':'0b57f7fc522caf40f5deb0c93ca3a226c4c62a411a8b06fcd52495368bda8e7f',
      '_conv_f32_mlas_followup':'de31d7ca085a167f6dda2e31c204316d0d7ec50ed14bb17820fc079faa8e6df8',
      '_conv_f32_mlas128':'bb9edc63c6aca6cf16a47c689f735c0aaa009d1ff8c73931147252cbf85bb824'}
    source=SOURCE.read_text();actual={node.name:hashlib.sha256(ast.get_source_segment(source,node).encode()).hexdigest()
      for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name in expected}
    self.assertEqual(actual,expected)


class CapturedDepthwiseScalarTest(unittest.TestCase):
  def test_complete_cpu_operands_require_zero_init_fma_and_bias_last(self):
    fixture=json.loads((Path(__file__).parent/'fixtures/cabin_conv_depthwise_f32.json').read_text())
    self.assertEqual({row['node'] for row in fixture['nodes']},{'node_Conv_819','node_Conv_825','node_Conv_857',
      'node_Conv_865','node_Conv_877','node_Conv_883'})
    for row in fixture['nodes']:
      self.assertEqual(row['installed_main_apk_sha256'],'7eb25b7e5c132bb3be3d917398aa2fff2b72cfc18868756f1701ddb575703cce')
      self.assertEqual(row['diagnostic_sha256'],'2f1f11fde210043baa65be3cb5292ec835df13413cb7aa3edea799d7873d864c')
      source=ROOT/row['source_evidence']/(row['node']+'.npz')
      if source.exists():
        with source.open('rb') as stream:self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),row['source_array_sha256'])
      separate_different=bias_first_different=False
      for case in row['cases']:
        terms=[tuple(int(value,16) for value in term) for term in case['terms']];bias=int(case['bias_bits'],16)
        self.assertIn(len(terms),(9,25));expected=int(case['expected_bits'],16)
        with self.subTest(node=row['node'],coordinates=case['coordinates']):
          self.assertEqual(dot32(terms,bias,len(terms)),expected)
          for label,fused,bias_first in (('sequential_fma_bias_last',True,False),
              ('sequential_fma_bias_first',True,True),('separate_bias_last',False,False)):
            self.assertEqual(dot32(terms,bias,len(terms),fused,bias_first),int(case['measured_variant_bits'][label],16))
          separate_different|=int(case['measured_variant_bits']['separate_bias_last'],16)!=expected
          bias_first_different|=int(case['measured_variant_bits']['sequential_fma_bias_first'],16)!=expected
      self.assertTrue(separate_different);self.assertTrue(bias_first_different)


if __name__=='__main__':unittest.main()
