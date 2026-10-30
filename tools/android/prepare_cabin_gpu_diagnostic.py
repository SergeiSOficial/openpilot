"""Static ONNX diagnostic preparation; no model is executed on this host.

Input is the exact NO_OPT mandatory CPU lowering exported on Android. Keep a
copy of the full graph and append a bounded prefix of its dynamic activations.
"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
  import onnx
  parser=argparse.ArgumentParser(description=__doc__)
  parser.add_argument('source',type=Path)
  parser.add_argument('output',type=Path)
  parser.add_argument('--count',type=int,default=24)
  parser.add_argument('--start',type=int,default=0)
  args=parser.parse_args()
  if not 1<=args.count<=64:parser.error('Choose 1 through64 activations')
  if args.start<0:parser.error('Start must be nonnegative')
  model=onnx.shape_inference.infer_shapes(onnx.load(args.source))
  values={v.name:v for v in (*model.graph.input,*model.graph.output,*model.graph.value_info)}
  for tensor in model.graph.initializer:
    values.setdefault(tensor.name,onnx.helper.make_tensor_value_info(tensor.name,tensor.data_type,tensor.dims))
  dynamic={v.name for v in model.graph.input};selected=[];total=0;position=0
  for node in model.graph.node:
    if not any(name in dynamic for name in node.input):continue
    dynamic.update(node.output)
    for name in node.output:
      value=values[name];tensor=value.type.tensor_type
      if tensor.elem_type not in (onnx.TensorProto.FLOAT,onnx.TensorProto.FLOAT16):continue
      position+=1
      if position<=args.start:continue
      size=1
      for dim in tensor.shape.dim:
        if not dim.HasField('dim_value'):raise ValueError('Diagnostic requires fixed shapes')
        size*=dim.dim_value
      # Reference transport is float32 regardless of original FP16/UINT8.
      total+=size*4
      if total>128*1024*1024:raise ValueError('Diagnostic activation prefix exceeds128MiB')
      selected.append({'name':name,'op':node.op_type,'node':node.name,'inputs':list(node.input),'dtype':tensor.elem_type,
                       'shape':[d.dim_value for d in tensor.shape.dim]})
      if len(selected)==args.count:break
    if len(selected)==args.count:break
  existing={v.name for v in model.graph.output}
  reference_names=list(dict.fromkeys([row['name'] for row in selected]+[
    name for row in selected for name in row['inputs'] if name in values and
    values[name].type.tensor_type.elem_type in (onnx.TensorProto.FLOAT,onnx.TensorProto.FLOAT16)]))
  import math
  total=sum(math.prod(dim.dim_value for dim in values[name].type.tensor_type.shape.dim)*4 for name in reference_names)
  if total>128*1024*1024 or len(reference_names)>255:raise ValueError('Complete diagnostic inputs exceed transport bound')
  for name in reference_names:
    if name not in existing:model.graph.output.append(values[name]);existing.add(name)
  onnx.checker.check_model(model,full_check=True)
  onnx.save(model,args.output)
  manifest={'schema':1,'source_sha256':hashlib.sha256(args.source.read_bytes()).hexdigest(),
            'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),'activations':selected,'reference_names':reference_names,
            'scope':'original cabin CPU mandatory lowering, diagnostic outputs only','bound_bytes':total}
  args.output.with_suffix('.json').write_text(json.dumps(manifest,indent=2)+'\n')
  print(json.dumps({'activations':len(selected),'bytes':total,'sha256':manifest['sha256']}))


if __name__=='__main__':main()
