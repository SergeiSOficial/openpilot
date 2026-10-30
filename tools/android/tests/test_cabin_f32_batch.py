"""Reviewed stdlib-only bounds/identity checks; no tensor runtime or host inference."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('cabin_f32_batch_bounds',ROOT/'android/app/src/androidTest/assets/cabin_arithmetic_diagnostic.py')
diagnostic=importlib.util.module_from_spec(spec);spec.loader.exec_module(diagnostic)


def contract():
  metadata={'schema':1,'sha256':diagnostic.BATCH_DIAGNOSTIC_SHA256,'source_sha256':diagnostic.LOWERING_SHA256,
    'original_model_sha256':diagnostic.ORIGINAL_SHA256,'operators_and_constants_unchanged':True,
    'host_model_inference_executed':False,'nodes':{},'reference_names':['outputs'],
    'reference_shapes':{'outputs':[1,553]},'bound_bytes':5003300,'total_output_values':450720}
  for number,cin,cout,height,width in ((813,96,64,30,45),(827,192,96,15,23),(829,96,192,15,23),
      (833,192,96,15,23),(835,96,192,15,23),(839,192,96,15,23),(841,96,192,15,23),
      (845,192,96,15,23),(851,384,96,15,23)):
    names=[label+'_'+str(number) for label in ('x','w','b','y')]
    shapes=[[1,cin,height,width],[cout,cin,1,1],[cout],[1,cout,height,width]]
    metadata['nodes']['node_Conv_'+str(number)]={'inputs':names[:3],'output':names[3],'shapes':shapes,
      'attributes':{'auto_pad':'NOTSET','group':1,'dilations':[1,1],'strides':[1,1],'pads':[0,0,0,0]},'candidate_panel':128}
    metadata['reference_names'].extend(names)
    metadata['reference_shapes'].update(zip(names,copy.deepcopy(shapes)))
  return metadata


class F32BatchContractTest(unittest.TestCase):
  def test_complete_nine_node_domain_and_memory_bound(self):
    metadata=contract()
    self.assertTrue(diagnostic._batch_contract(metadata))
    self.assertEqual(len(metadata['reference_names']),37)
    self.assertEqual(sum(math.prod(s)*4 for s in metadata['reference_shapes'].values()),5003300)
    self.assertEqual(sum(math.prod(r['shapes'][-1]) for r in metadata['nodes'].values()),450720)
    self.assertLess(metadata['bound_bytes'],16*1024*1024)

  def test_incomplete_extra_or_other_nodes_are_rejected(self):
    for change in ('missing','extra','wrong'):
      metadata=contract();nodes=metadata['nodes']
      if change=='missing':del nodes['node_Conv_813']
      elif change=='extra':nodes['node_Conv_895']=copy.deepcopy(nodes['node_Conv_813'])
      else:nodes['node_Conv_811']=nodes.pop('node_Conv_813')
      with self.subTest(change=change):self.assertFalse(diagnostic._batch_contract(metadata))

  def test_dtype_like_booleans_nonintegers_and_different_geometry_reject(self):
    for value in (True,96.,-96,0,96000):
      metadata=contract();metadata['nodes']['node_Conv_813']['shapes'][0][1]=value
      with self.subTest(value=value):self.assertFalse(diagnostic._batch_contract(metadata))
    metadata=contract();metadata['nodes']['node_Conv_813']['shapes'][1][2]=3
    self.assertFalse(diagnostic._batch_contract(metadata))

  def test_group_padding_panel_and_implicit_dispatch_changes_reject(self):
    for key,value in (('group',True),('group',96),('pads',[1,1,1,1]),('pads',[False,0,0,0]),
                      ('dilations',[2,2]),('strides',[2,2]),('auto_pad','SAME_UPPER')):
      metadata=contract();metadata['nodes']['node_Conv_813']['attributes'][key]=value
      with self.subTest(key=key,value=value):self.assertFalse(diagnostic._batch_contract(metadata))
    for panel in (True,96,256,None):
      metadata=contract();metadata['nodes']['node_Conv_813']['candidate_panel']=panel
      with self.subTest(panel=panel):self.assertFalse(diagnostic._batch_contract(metadata))

  def test_missing_duplicate_or_malformed_reference_names_reject(self):
    for replacement in ([],['outputs'],['outputs']*37,[[]]*37):
      metadata=contract();metadata['reference_names']=replacement
      with self.subTest(replacement=replacement):self.assertFalse(diagnostic._batch_contract(metadata))
    metadata=contract();metadata['reference_shapes']['extra']=[1000000000]
    self.assertFalse(diagnostic._batch_contract(metadata))
    metadata=contract();metadata['nodes']['node_Conv_813']['inputs'][0]=[]
    self.assertFalse(diagnostic._batch_contract(metadata))

  def test_forged_sizes_output_counts_and_numeric_booleans_reject(self):
    for key in ('schema','bound_bytes','total_output_values'):
      for value in (True,-1,16*1024*1024+1,450720.):
        metadata=contract();metadata[key]=value
        with self.subTest(key=key,value=value):self.assertFalse(diagnostic._batch_contract(metadata))
    metadata=contract();metadata['reference_shapes']['outputs']=[553]
    self.assertFalse(diagnostic._batch_contract(metadata))

  def test_provenance_and_static_only_guards_fail_closed(self):
    for key,value in (('sha256','0'*64),('source_sha256',''),('original_model_sha256',None),
                      ('operators_and_constants_unchanged',1),('host_model_inference_executed',0),('host_model_inference_executed',True)):
      metadata=contract();metadata[key]=value
      with self.subTest(key=key):self.assertFalse(diagnostic._batch_contract(metadata))
    for malformed in (None,[],True,{'schema':1}):self.assertFalse(diagnostic._batch_contract(malformed))

  def test_target_entrypoint_refuses_host_before_runtime_imports(self):
    with self.assertRaisesRegex(RuntimeError,'Android target only'):
      diagnostic.inspect_f32_batch('unused','unused','unused','0'*32)


if __name__=='__main__':unittest.main()
