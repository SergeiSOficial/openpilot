"""Static diagnostic output selection; no inference runtime is imported."""
import hashlib
import json
import math
from pathlib import Path

SOURCE_SHA='46143482893d608825ce400eb0b05afc9688d9cf8d2b2ef608ef936e8db2b22f'
ORIGINAL_SHA='dee5a294e8afaacc9295ac5d100e00733ecac278e79264b96331e40a3ede1b04'
GEOMETRY={867:(512,128,8,12),869:(128,512,8,12),873:(512,128,8,12),875:(128,384,8,12),
          879:(384,128,8,12),881:(128,512,8,12),885:(512,128,8,12),887:(128,512,8,12),
          891:(512,128,8,12),893:(128,960,8,12),895:(960,1280,1,1)}


def main():
  import onnx
  root=Path(__file__).resolve().parent/'.cache';source=root/'cabin-cpu-lowering.onnx'
  digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
  if digest(source)!=SOURCE_SHA:raise ValueError('CPU lowering changed')
  original=onnx.load(source);graph=onnx.shape_inference.infer_shapes(original,strict_mode=True)
  values={v.name:v for v in [*graph.graph.input,*graph.graph.value_info,*graph.graph.output]}
  nodes={n.name:n for n in graph.graph.node};names=['outputs'];selected={}
  for number,(cin,cout,height,width) in GEOMETRY.items():
    name='node_Conv_'+str(number);node=nodes[name]
    attrs={a.name:onnx.helper.get_attribute_value(a) for a in node.attribute}
    attrs={k:v.decode() if isinstance(v,bytes) else v for k,v in attrs.items()}
    expected={'auto_pad':'NOTSET','group':1,'dilations':[1,1],'strides':[1,1],'pads':[0,0,0,0]}
    if node.op_type!='Conv' or len(node.input)!=3 or len(node.output)!=1 or attrs!=expected:raise ValueError(name)
    tensors=[*node.input,node.output[0]];shapes=[]
    for tensor in tensors:
      info=values[tensor].type.tensor_type
      if info.elem_type!=onnx.TensorProto.FLOAT or any(not d.HasField('dim_value') for d in info.shape.dim):raise ValueError(tensor)
      shapes.append([d.dim_value for d in info.shape.dim])
      if tensor not in names:names.append(tensor)
    if shapes!=[[1,cin,height,width],[cout,cin,1,1],[cout],[1,cout,height,width]]:raise ValueError(name+' shapes')
    selected[name]={'inputs':list(node.input),'output':node.output[0],'shapes':shapes,'attributes':attrs}
  shapes={n:[d.dim_value for d in values[n].type.tensor_type.shape.dim] for n in names}
  bound=sum(math.prod(s)*4 for s in shapes.values());outputs=sum(math.prod(r['shapes'][3]) for r in selected.values())
  if len(names)>45 or bound>16*1024*1024:raise ValueError('Diagnostic exceeds transport bound')
  del graph.graph.output[:];graph.graph.output.extend(values[n] for n in names)
  for field in ('node','initializer','input'):
    if [v.SerializeToString() for v in getattr(original.graph,field)]!=[v.SerializeToString() for v in getattr(graph.graph,field)]:
      raise ValueError('Changed graph arithmetic')
  onnx.checker.check_model(graph);destination=root/'cabin-f32-tail.onnx';onnx.save(graph,destination)
  metadata={'schema':1,'source_sha256':SOURCE_SHA,'original_model_sha256':ORIGINAL_SHA,'sha256':digest(destination),
            'nodes':selected,'reference_names':names,'reference_shapes':shapes,'bound_bytes':bound,
            'total_output_values':outputs,'operators_and_constants_unchanged':True,'host_model_inference_executed':False}
  destination.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')
  print(json.dumps({k:metadata[k] for k in ('sha256','bound_bytes','total_output_values')}));print('names',len(names))


if __name__=='__main__':main()
