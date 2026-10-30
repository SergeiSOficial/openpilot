"""Reviewed stdlib transport bounds only; never imports a tensor/native runtime."""
import importlib.util
import copy
from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('cabin_arithmetic_transport',ROOT/'android/app/src/androidTest/assets/cabin_arithmetic_diagnostic.py')
diagnostic=importlib.util.module_from_spec(spec);spec.loader.exec_module(diagnostic)


class CpuReferenceBatchTest(unittest.TestCase):
  def test_complete_tail_is_never_silently_truncated_to_one_call(self):
    names=['tensor_'+str(index) for index in range(634)]
    batches=diagnostic._reference_batches(names)
    self.assertEqual([len(batch) for batch in batches],[200,200,200,34])
    self.assertEqual([name for batch in batches for name in batch],names)
    self.assertTrue(all(len(batch)<=256 for batch in batches))

  def test_driver_limit_and_short_reference_are_respected(self):
    names=['tensor_'+str(index) for index in range(257)]
    self.assertEqual([len(batch) for batch in diagnostic._reference_batches(names,256)],[256,1])
    self.assertEqual(diagnostic._reference_batches(['outputs','input','weights']),[['outputs','input','weights']])

  def test_invalid_bounds_names_and_duplicates_reject_before_any_runtime(self):
    for names,size in ((['outputs'],True),(['outputs'],0),(['outputs'],257),(['outputs'],200.),
                       ([],200),(None,200),('outputs',200),(['outputs','outputs'],200),
                       (['outputs',None],200),(['outputs',[]],200),([''],200),
                       (['t'+str(index) for index in range(1025)],200)):
      with self.subTest(names=names,size=size),self.assertRaises(ValueError):diagnostic._reference_batches(names,size)


class FollowupContractTest(unittest.TestCase):
  def test_only_the_two_bounded_declared_contracts_are_accepted(self):
    self.assertTrue(diagnostic._followup_contract('node_Conv_809',[[1,32,60,90],[32,32,1,1],[32],[1,32,60,90]],
      {'auto_pad':'NOTSET','group':1,'dilations':[1,1],'strides':[1,1],'pads':[0,0,0,0]}))
    self.assertTrue(diagnostic._followup_contract('node_Conv_811',[[1,32,60,90],[96,32,3,3],[96],[1,96,30,45]],
      {'auto_pad':'NOTSET','group':1,'dilations':[1,1],'strides':[2,2],'pads':[1,1,1,1]}))

  def test_changed_shapes_groups_and_implicit_padding_are_rejected(self):
    shapes=[[1,32,60,90],[96,32,3,3],[96],[1,96,30,45]]
    options={'auto_pad':'NOTSET','group':1,'dilations':[1,1],'strides':[2,2],'pads':[1,1,1,1]}
    for node,value in (('node_Conv_807',shapes),('node_Conv_811',None),
                       ('node_Conv_811',[[True,32,60,90],*shapes[1:]]),
                       ('node_Conv_811',[[1,32,600,900],*shapes[1:]])):
      with self.subTest(node=node,shapes=value):self.assertFalse(diagnostic._followup_contract(node,value,options))
    for key,value in (('group',True),('group',32),('auto_pad','SAME_UPPER'),('strides',[1,1]),('pads',[0,0,0,0])):
      changed=copy.deepcopy(options);changed[key]=value
      with self.subTest(key=key,value=value):self.assertFalse(diagnostic._followup_contract('node_Conv_811',shapes,changed))


if __name__=='__main__':unittest.main()
