"""Reviewed stdlib-only target-diagnostic bounds, without any tensor imports."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('cabin_depthwise_bounds',ROOT/'android/app/src/androidTest/assets/cabin_arithmetic_diagnostic.py')
diagnostic=importlib.util.module_from_spec(spec);spec.loader.exec_module(diagnostic)


def contract():
  metadata={'schema':1,'sha256':diagnostic.DEPTHWISE_DIAGNOSTIC_SHA256,'source_sha256':diagnostic.LOWERING_SHA256,
    'original_model_sha256':diagnostic.ORIGINAL_SHA256,'operators_and_constants_unchanged':True,
    'host_model_inference_executed':False,'nodes':{},'reference_names':['outputs'],'reference_shapes':{'outputs':[1,553]},
    'bound_bytes':6568612,'total_output_values':619968}
  for number,channels,height,width,kernel,stride,pad in ((819,192,30,45,5,2,2),(825,192,15,23,3,1,1),
      (831,192,15,23,3,1,1),(837,192,15,23,3,1,1),(843,192,15,23,3,1,1),(857,576,15,23,3,2,1),
      (865,512,8,12,5,1,2),(871,512,8,12,5,1,2),(877,384,8,12,5,1,2),(883,512,8,12,3,1,1),(889,512,8,12,3,1,1)):
    names=[key+'_'+str(number) for key in ('x','w','b','y')]
    shapes=[[1,channels,height,width],[channels,1,kernel,kernel],[channels],
            [1,channels,(height+2*pad-kernel)//stride+1,(width+2*pad-kernel)//stride+1]]
    metadata['nodes']['node_Conv_'+str(number)]={'inputs':names[:3],'output':names[3],'shapes':shapes,
      'attributes':{'auto_pad':'NOTSET','group':channels,'dilations':[1,1],'strides':[stride]*2,'pads':[pad]*4}}
    metadata['reference_names'].extend(names);metadata['reference_shapes'].update(zip(names,copy.deepcopy(shapes)))
  return metadata


class DepthwiseReferenceBoundsTest(unittest.TestCase):
  def test_all_eleven_complete_contracts_have_bounded_data(self):
    metadata=contract();self.assertTrue(diagnostic._depthwise_contract(metadata))
    self.assertEqual(len(metadata['reference_names']),45)
    self.assertEqual(sum(math.prod(s)*4 for s in metadata['reference_shapes'].values()),6568612)
    self.assertEqual(sum(math.prod(row['shapes'][-1]) for row in metadata['nodes'].values()),619968)
    self.assertLess(metadata['bound_bytes'],16*1024*1024)

  def test_missing_extra_or_other_grouped_nodes_reject(self):
    for operation in ('missing','extra','renamed'):
      metadata=contract()
      if operation=='missing':del metadata['nodes']['node_Conv_819']
      elif operation=='extra':metadata['nodes']['node_Conv_867']=copy.deepcopy(metadata['nodes']['node_Conv_819'])
      else:metadata['nodes']['node_Conv_867']=metadata['nodes'].pop('node_Conv_819')
      with self.subTest(operation=operation):self.assertFalse(diagnostic._depthwise_contract(metadata))

  def test_noninteger_changed_rank_or_non_depthwise_shape_reject(self):
    for index,value in ((0,True),(0,1.),(1,193),(2,3000),(3,44)):
      metadata=contract();metadata['nodes']['node_Conv_819']['shapes'][0][index]=value
      with self.subTest(index=index,value=value):self.assertFalse(diagnostic._depthwise_contract(metadata))
    metadata=contract();metadata['nodes']['node_Conv_819']['shapes'][1][1]=2
    self.assertFalse(diagnostic._depthwise_contract(metadata))

  def test_implicit_or_changed_attributes_reject(self):
    for key,value in (('group',True),('group',1),('group',96),('strides',[1,1]),('pads',[0,0,0,0]),
                      ('pads',[True,2,2,2]),('dilations',[2,2]),('auto_pad','SAME_UPPER')):
      metadata=contract();metadata['nodes']['node_Conv_819']['attributes'][key]=value
      with self.subTest(key=key,value=value):self.assertFalse(diagnostic._depthwise_contract(metadata))

  def test_name_and_size_bounds_fail_closed(self):
    for names in ([],['outputs']*45,[[]]*45):
      metadata=contract();metadata['reference_names']=names
      self.assertFalse(diagnostic._depthwise_contract(metadata))
    for key,value in (('bound_bytes',True),('bound_bytes',16*1024*1024+1),('total_output_values',619968.),('schema',True)):
      metadata=contract();metadata[key]=value
      with self.subTest(key=key,value=value):self.assertFalse(diagnostic._depthwise_contract(metadata))

  def test_graph_and_reference_identities_are_mandatory(self):
    for key,value in (('sha256','0'*64),('source_sha256',''),('original_model_sha256',None),
                      ('operators_and_constants_unchanged',1),('host_model_inference_executed',0)):
      metadata=contract();metadata[key]=value
      with self.subTest(key=key):self.assertFalse(diagnostic._depthwise_contract(metadata))
    for bad in (None,[],{'schema':1}):self.assertFalse(diagnostic._depthwise_contract(bad))

  def test_entrypoint_refuses_host_before_tensor_runtime_imports(self):
    with self.assertRaisesRegex(RuntimeError,'Android target only'):
      diagnostic.inspect_f32_depthwise('unused','unused','unused','0'*32,'node_Conv_819')


if __name__=='__main__':unittest.main()
