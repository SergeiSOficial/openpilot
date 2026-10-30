"""Reviewed stdlib graph-contract checks; no tensor/native/model imports."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/'android/app/src/androidTest/assets/cabin_tail_diagnostic.py'
spec=importlib.util.spec_from_file_location('tail_contract',SOURCE)
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)


class TailContractTest(unittest.TestCase):
  def metadata(self):return json.loads((ROOT/'tools/android/.cache/cabin-f32-tail.json').read_text())
  def test_complete_static_reference_contract(self):
    m=self.metadata();self.assertTrue(policy.contract(m));self.assertEqual(m['total_output_values'],339200)
  def test_graph_role_transport_and_scalar_types_cannot_be_relabelled(self):
    for key,value in (('sha256','0'*64),('source_sha256','0'*64),('original_model_sha256','0'*64),
                      ('host_model_inference_executed',True),('bound_bytes',True),('total_output_values',1)):
      m=self.metadata();m[key]=value
      with self.subTest(key=key):self.assertFalse(policy.contract(m))
    for kind in ('group','shape','names','nodes'):
      m=self.metadata()
      if kind=='group':m['nodes']['node_Conv_867']['attributes']['group']=True
      if kind=='shape':m['nodes']['node_Conv_867']['shapes'][0][0]=True
      if kind=='names':m['reference_names'][0]=None
      if kind=='nodes':del m['nodes']['node_Conv_895']
      with self.subTest(kind=kind):self.assertFalse(policy.contract(m))
  def test_asset_syntax_and_no_host_inference_imports(self):
    tree=ast.parse(SOURCE.read_text());imports=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
    self.assertFalse(any(any(alias.name.startswith(('tinygrad','numpy','onnxruntime')) for alias in n.names) for n in imports))


if __name__=='__main__':unittest.main()
