"""Android-only complete-input probes for the remaining pointwise convolutions."""
import gc
import hashlib
import json
import math
from pathlib import Path

GRAPH_SHA='400d9f0e060891a471a3f4889158e9c55fe7fb68a3c873bacfafc74c590b9d82'
SOURCE_SHA='46143482893d608825ce400eb0b05afc9688d9cf8d2b2ef608ef936e8db2b22f'
MODEL_SHA='dee5a294e8afaacc9295ac5d100e00733ecac278e79264b96331e40a3ede1b04'
GEOMETRY={867:(512,128,8,12),869:(128,512,8,12),873:(512,128,8,12),875:(128,384,8,12),
          879:(384,128,8,12),881:(128,512,8,12),885:(512,128,8,12),887:(128,512,8,12),
          891:(512,128,8,12),893:(128,960,8,12),895:(960,1280,1,1)}


def contract(m):
  if not isinstance(m,dict) or m.get('sha256')!=GRAPH_SHA or m.get('source_sha256')!=SOURCE_SHA or m.get('original_model_sha256')!=MODEL_SHA:return False
  if m.get('operators_and_constants_unchanged') is not True or m.get('host_model_inference_executed') is not False:return False
  nodes=m.get('nodes');names=m.get('reference_names');shapes=m.get('reference_shapes')
  if not isinstance(nodes,dict) or set(nodes)!={'node_Conv_'+str(n) for n in GEOMETRY}:return False
  if (not isinstance(names,list) or len(names)!=45 or any(not isinstance(n,str) or not n for n in names)
      or len(set(names))!=45 or not isinstance(shapes,dict)):return False
  expected={'outputs':[1,553]};total=0
  for number,(cin,cout,h,w) in GEOMETRY.items():
    row=nodes['node_Conv_'+str(number)];ss=[[1,cin,h,w],[cout,cin,1,1],[cout],[1,cout,h,w]]
    if not isinstance(row,dict):return False
    if row.get('shapes')!=ss or any(type(v) is not int for s in row['shapes'] for v in s):return False
    if row.get('attributes')!={'auto_pad':'NOTSET','group':1,'dilations':[1,1],'strides':[1,1],'pads':[0,0,0,0]}:return False
    if type(row['attributes']['group']) is not int or any(type(v) is not int for k in ('pads','strides','dilations') for v in row['attributes'][k]):return False
    tensors=[*row.get('inputs',[]),row.get('output')]
    if len(tensors)!=4 or any(not isinstance(n,str) or not n for n in tensors):return False
    expected.update(zip(tensors,ss));total+=cout*h*w
  return (shapes==expected and set(names)==set(expected) and type(m.get('bound_bytes')) is int
          and m['bound_bytes']==sum(math.prod(s)*4 for s in expected.values())==10196644
          and type(m.get('total_output_values')) is int and m['total_output_values']==total==339200)


def run(root,native,session,attempt,common):
  if not Path('/system/bin/app_process').exists():raise RuntimeError('Android only')
  import numpy as np
  from java import jclass,jarray
  from android_runtime.worker import configure
  configure(session,native);root=Path(root);base=root.parent;session=Path(session)
  digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
  graph=base/'cabin-f32-tail.onnx';meta=json.loads(graph.with_suffix('.json').read_text())
  if not contract(meta) or digest(graph)!=GRAPH_SHA or digest(base/'driver-cpu-lowering.onnx')!=SOURCE_SHA or digest(root/'dmonitoring_model.onnx')!=MODEL_SHA:
    raise ValueError('Tail graph identity/contract changed')
  if str(jclass('ai.onnxruntime.OrtEnvironment').getEnvironment().getVersion())!='1.23.2':raise ValueError('Pinned reference required')
  report={'schema':1,'attempt_id':attempt,'completed':False,'qualified':False,'scope':'CPU-zero complete-input operator probes only',
          'graph_sha256':GRAPH_SHA,'model_sha256':MODEL_SHA,'source_sha256':SOURCE_SHA,'results':{},'completed_output_values':0}
  def save(): (session/'report.json').write_text(json.dumps(report,indent=2)+'\n')
  reference=jclass('ai.comma.openpilot.sim.DriverReference');device=None;save()
  try:
    values=reference.zeroIntermediates(str(graph),jarray(jclass('java.lang.String'))(meta['reference_names']))
    cpu={n:np.asarray(values.get(n),dtype=np.float32).reshape(meta['reference_shapes'][n]).copy() for n in meta['reference_names']}
    original=np.asarray(reference.zeroInput(str(root/'dmonitoring_model.onnx')),dtype=np.float32).reshape(1,553)
    report['original_553']=common._compare(cpu['outputs'],original,np)
    if not report['original_553']['bit_equal'] or any(not np.isfinite(v).all() for v in cpu.values()):raise ValueError('Reference integrity')
    del values,original;reference.close();gc.collect()
    from android_runtime.gpu import configure as configure_gpu,retained_renderer
    device=configure_gpu();device.renderers=[type(retained_renderer())];device.cached_renderer.clear()
    report.update(gpu_device=device.device_name,gpu_driver=device.driver_version,identity=device._android_cache_report)
    from tinygrad import Tensor
    from tinygrad.dtype import dtypes
    from tinygrad.nn.onnx import OnnxRunner
    runner=OnnxRunner(graph);runner.onnx_ops=dict(runner.onnx_ops)
    nodes={n.outputs[0]:n for n in runner.graph_nodes if n.op=='Conv'}
    for name,selected in meta['nodes'].items():
      report['current_node']=name;save();node=nodes[selected['output']]
      opts={k:list(node.opts[k]) if k in ('pads','strides','dilations') else node.opts[k] for k in ('auto_pad','group','dilations','strides','pads')}
      if opts!=selected['attributes'] or list(node.inputs)!=selected['inputs']:raise ValueError('Actual Conv attributes changed')
      arrays=[cpu[n] for n in selected['inputs']];expected=cpu[selected['output']]
      tensors=[Tensor(a,dtype=dtypes.float32,device='CL').realize() for a in arrays]
      saved={'input':arrays[0],'weights':arrays[1],'bias':arrays[2],'expected':expected};row={'contract':selected,'results':{},'inputs':{}}
      report['results'][name]=row
      try:
        for n,t,a in zip(selected['inputs'],tensors,arrays):
          imported=t.numpy();row['inputs'][n]={'cpu_sha256':hashlib.sha256(a.tobytes()).hexdigest(),
            'gpu_sha256':hashlib.sha256(imported.tobytes()).hexdigest(),'dtype':str(imported.dtype),'shape':list(a.shape)}
          if imported.dtype!=a.dtype or imported.tobytes()!=a.tobytes():raise ValueError('Complete input import differs')
        k=arrays[1].shape[1]
        variants=[('legacy',None)]+[('fma_k'+str(p),p) for p in dict.fromkeys([128,256,512,k]) if p<=k]
        for label,panel in variants:
          report['current_variant']=label;save()
          output=runner._select_op(node.op,node.opset_id)(*tensors,**node.opts) if panel is None else common._followup_conv(*tensors,opts,panel,True)
          actual=output.numpy();del output
          row['results'][label]=common._compare(actual,expected,np);saved[label]=actual
          np.savez_compressed(session/(name+'.npz'),**saved);row['array_sha256']=digest(session/(name+'.npz'));save()
        report['completed_output_values']+=int(expected.size)
      finally:
        device.synchronize();del tensors,saved,arrays;gc.collect();device.allocator.free_cache()
    report.update(completed=True,current_node=None,current_variant=None);save();return report
  except Exception as error:
    report.update(error_type=type(error).__name__,error=str(error));save();return report
  finally:reference.close()
