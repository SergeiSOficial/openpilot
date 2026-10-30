"""Explicit Android-only Conv807 arithmetic probe; no production operator edits.

Pinned ORT 1.23.2 sources: mlas/lib/convolve.cpp (NCHW im2col and bias
after SGEMM), mlasi.h (SGEMM_STRIDEK=128), sgemm.cpp (K panels), and
aarch64/SgemmKernelNeon.S (zero accumulators and sequential FMLA).
Only the target runs tensor arithmetic. Host checks may parse this source.
"""
import hashlib
import json
from pathlib import Path


ORIGINAL_SHA256="dee5a294e8afaacc9295ac5d100e00733ecac278e79264b96331e40a3ede1b04"
LOWERING_SHA256="46143482893d608825ce400eb0b05afc9688d9cf8d2b2ef608ef936e8db2b22f"
DIAGNOSTIC_SHA256="bb7bed7e82d0bd0ec2e0d3f2ff89dbae3a0b2ad85d366671f6cf429b889b173f"
SHORT_DIAGNOSTIC_SHA256="4395a895abe4079f996396c3ce7c099d76d7acea5a9643f0065b51000dc63766"
FOLLOWUP_DIAGNOSTIC_SHA256="cc0245dac85856bbbb402a67b4d9cc519898a0934f2f727348e1571d678f0400"
BATCH_DIAGNOSTIC_SHA256="f50003bbeff0a197aee913e5f8cb4aadc696cd6736bbec35af4f9a22c2ebf49f"
DEPTHWISE_DIAGNOSTIC_SHA256="2f1f11fde210043baa65be3cb5292ec835df13413cb7aa3edea799d7873d864c"


def _depthwise_contract(metadata):
  geometry={819:(192,30,45,5,2,2),825:(192,15,23,3,1,1),831:(192,15,23,3,1,1),
    837:(192,15,23,3,1,1),843:(192,15,23,3,1,1),857:(576,15,23,3,2,1),
    865:(512,8,12,5,1,2),871:(512,8,12,5,1,2),877:(384,8,12,5,1,2),
    883:(512,8,12,3,1,1),889:(512,8,12,3,1,1)}
  if (not isinstance(metadata,dict) or type(metadata.get('schema')) is not int or metadata['schema']!=1
      or metadata.get('sha256')!=DEPTHWISE_DIAGNOSTIC_SHA256 or metadata.get('source_sha256')!=LOWERING_SHA256
      or metadata.get('original_model_sha256')!=ORIGINAL_SHA256
      or metadata.get('operators_and_constants_unchanged') is not True
      or metadata.get('host_model_inference_executed') is not False):return False
  nodes=metadata.get('nodes');names=metadata.get('reference_names');shapes=metadata.get('reference_shapes')
  if not isinstance(nodes,dict) or set(nodes)!={'node_Conv_'+str(n) for n in geometry}:return False
  if (not isinstance(names,list) or len(names)!=45 or any(not isinstance(n,str) or not n for n in names)
      or len(set(names))!=len(names) or not isinstance(shapes,dict) or set(shapes)!=set(names)):return False
  expected_shapes={'outputs':[1,553]};total=0
  for number,(channels,height,width,kernel,stride,pad) in geometry.items():
    row=nodes['node_Conv_'+str(number)]
    if not isinstance(row,dict):return False
    inputs=row.get('inputs');output=row.get('output');actual=row.get('shapes');attrs=row.get('attributes')
    if (not isinstance(inputs,list) or len(inputs)!=3 or any(not isinstance(n,str) or not n for n in inputs)
        or not isinstance(output,str) or not output or len(set([*inputs,output]))!=4):return False
    oh=(height+2*pad-kernel)//stride+1;ow=(width+2*pad-kernel)//stride+1
    expected=[[1,channels,height,width],[channels,1,kernel,kernel],[channels],[1,channels,oh,ow]]
    if (not isinstance(actual,list) or len(actual)!=4
        or any(not isinstance(s,list) or any(type(d) is not int for d in s) for s in actual) or actual!=expected):return False
    if (not isinstance(attrs,dict) or type(attrs.get('group')) is not int
        or attrs!={'auto_pad':'NOTSET','group':channels,'dilations':[1,1],'strides':[stride,stride],'pads':[pad]*4}
        or any(not isinstance(attrs.get(key),list) or any(type(d) is not int for d in attrs[key])
               for key in ('pads','strides','dilations'))):return False
    for tensor,shape in zip([*inputs,output],actual):expected_shapes[tensor]=shape
    total+=channels*oh*ow
  if shapes!=expected_shapes:return False
  bound=0
  for shape in shapes.values():
    if not isinstance(shape,list) or any(type(d) is not int or d<=0 for d in shape):return False
    count=1
    for dim in shape:count*=dim
    bound+=count*4
  return (type(metadata.get('bound_bytes')) is int and metadata['bound_bytes']==bound==6568612 and bound<=16*1024*1024
          and type(metadata.get('total_output_values')) is int and metadata['total_output_values']==total==619968)


def _depthwise_probe(source,weights,bias,options,*,fused,bias_first):
  """Test-only NCHW kH,kW sequence; production operators are never modified."""
  from tinygrad import Tensor
  from tinygrad.dtype import AddrSpace,dtypes
  from tinygrad.uop.ops import AxisType,KernelInfo,Ops,UOp
  n,channels,height,width=source.shape;cout,per_group,kh,kw=weights.shape
  if (n!=1 or cout!=channels or per_group!=1 or options['group']!=channels
      or any(value.dtype!=dtypes.float32 for value in (source,weights,bias))):raise ValueError('Invalid depthwise probe contract')
  sy,sx=options['strides'];pt,pl,pb,pr=options['pads'];dy,dx=options['dilations']
  oh=(height+pt+pb-dy*(kh-1)-1)//sy+1;ow=(width+pl+pr-dx*(kw-1)-1)//sx+1
  count=channels*oh*ow;local=64
  while count%local:local//=2
  def kernel(out,image,weight,biases):
    block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
    lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0');index=block*local+lane
    channel=index//(oh*ow);oy=(index//ow)%oh;ox=index%ow
    accumulator=UOp.alloc((1,),dtypes.float32,addrspace=AddrSpace.REG)
    initial=biases.index(channel).load() if bias_first else UOp.const(0.).cast(dtypes.float32)
    state=accumulator.after(accumulator.index(0).store(initial))
    reduction=UOp.range(kh*kw,1,AxisType.LOOP)
    ky=reduction//kw;kx=reduction%kw;iy=oy*sy-pt+ky*dy;ix=ox*sx-pl+kx*dx
    valid=(iy>=0)&(iy<height)&(ix>=0)&(ix<width)
    by=iy.maximum(0).minimum(height-1);bx=ix.maximum(0).minimum(width-1)
    x=image.index((channel*height+by)*width+bx).load();x=valid.where(x,UOp.const(0.).cast(dtypes.float32))
    w=weight.index(channel*kh*kw+reduction).load();previous=state.after(reduction).index(0).load()
    if fused:updated=UOp(Ops.CUSTOM,src=(x,w,previous),arg=('fma({0},{1},{2})',dtypes.float32))
    else:
      product=UOp(Ops.CUSTOM,src=(x,w),arg=('({0} * {1})',dtypes.float32))
      updated=UOp(Ops.CUSTOM,src=(product,previous),arg=('({0} + {1})',dtypes.float32))
    finished=state.index(0).store(updated).end(reduction);value=state.after(finished).index(0).load()
    if not bias_first:value=UOp(Ops.CUSTOM,src=(value,biases.index(channel).load()),arg=('({0} + {1})',dtypes.float32))
    return out.index(index).store(value).sink(arg=KernelInfo(
      name='depthwise_f32_'+str(kh)+'_'+str(count)+'_'+str(int(fused))+'_'+str(int(bias_first)),opts_to_apply=()))
  return Tensor.empty(count,dtype=dtypes.float32,device='CL').custom_kernel(
    source.flatten().contiguous(),weights.flatten().contiguous(),bias.contiguous(),fxn=kernel)[0].reshape(1,channels,oh,ow)


def inspect_f32_depthwise(root,native,session,attempt_id,node_name):
  if not Path('/system/bin/app_process').exists():raise RuntimeError('Android target only')
  import gc
  import numpy as np
  from java import jarray,jclass
  from android_runtime.worker import configure
  configure(session,native)
  root=Path(root);base=root.parent;session=Path(session);session.mkdir(parents=True,exist_ok=True)
  path=base/'cabin-f32-depthwise.onnx';metadata=json.loads(path.with_suffix('.json').read_text())
  if (not _depthwise_contract(metadata) or _digest(path)!=DEPTHWISE_DIAGNOSTIC_SHA256
      or _digest(base/'driver-cpu-lowering.onnx')!=LOWERING_SHA256
      or _digest(root/'dmonitoring_model.onnx')!=ORIGINAL_SHA256):raise ValueError('Depthwise graph contract changed')
  selected=metadata['nodes'] if node_name=='all' else {
    name:row for name,row in metadata['nodes'].items() if name!='node_Conv_819'} if node_name=='remaining' else {
    node_name:metadata['nodes'][node_name]} if node_name in metadata['nodes'] else None
  if selected is None:raise ValueError('Unknown bounded depthwise selection')
  names=['outputs']
  for row in selected.values():
    for name in [*row['inputs'],row['output']]:
      if name not in names:names.append(name)
  version=str(jclass('ai.onnxruntime.OrtEnvironment').getEnvironment().getVersion())
  if version!='1.23.2':raise ValueError('Original ORT 1.23.2 required')
  reference=jclass('ai.comma.openpilot.sim.DriverReference');device=None;production=None
  report={'schema':1,'attempt_id':attempt_id,'completed':False,'qualified':False,'timing_qualified':False,
    'scope':'Complete teacher-forced FP32 depthwise arithmetic only; no production operator changes',
    'selection':node_name,'selected_count':len(selected),'ort_version':version,'original_model_sha256':ORIGINAL_SHA256,
    'cpu_lowering_sha256':LOWERING_SHA256,'diagnostic_sha256':DEPTHWISE_DIAGNOSTIC_SHA256,
    'cpu_reference_names':len(names),'all_reference_bound_bytes':metadata['bound_bytes'],
    'native_sha256':{p.name:_digest(p) for p in sorted(Path(native).glob('*.so'))},
    'results':{},'completed_output_values':0,'current_node':None,'current_variant':'cpu_reference','rtol':1e-4,'atol':1e-5}
  report_path=session/'report.json'
  def save():report_path.write_text(json.dumps(report,indent=2)+'\n')
  save()
  try:
    values=reference.zeroIntermediates(str(path),jarray(jclass('java.lang.String'))(names))
    cpu={name:np.asarray(values.get(name),dtype=np.float32).reshape(metadata['reference_shapes'][name]).copy() for name in names}
    if any(not np.isfinite(value).all() for value in cpu.values()):raise ValueError('Nonfinite depthwise reference')
    original=np.asarray(reference.zeroInput(str(root/'dmonitoring_model.onnx')),dtype=np.float32).reshape(1,553).copy()
    comparison=_compare(cpu['outputs'],original,np)
    np.savez_compressed(session/'original-553.npz',original=original,diagnostic=cpu['outputs'])
    report.update(original_cpu_outputs_unchanged=comparison['bit_equal'],original_553_comparison=comparison,
                  original_553_array_sha256=_digest(session/'original-553.npz'));save()
    del values,original;reference.close();gc.collect()
    if not comparison['bit_equal']:raise ValueError('Depthwise diagnostic changed original 553 CPU bits')
    from android_runtime.gpu import configure as configure_gpu,retained_renderer
    device=configure_gpu();device.renderers=[type(retained_renderer())];device.cached_renderer.clear()
    from tinygrad import Tensor
    from tinygrad.dtype import dtypes
    from tinygrad.nn.onnx import OnnxRunner
    runner=OnnxRunner(path);runner.onnx_ops=dict(runner.onnx_ops)
    nodes={node.outputs[0]:node for node in runner.graph_nodes if node.op=='Conv'}
    legacy={output:runner._select_op(node.op,node.opset_id) for output,node in nodes.items()}
    from android_runtime import onnx_half
    production=getattr(onnx_half,'_conv_f32_mlas_depthwise',None)
    if not callable(production):raise ValueError('Final production depthwise helper unavailable')
    calls=[]
    def counted(*args,**kwargs):
      calls.append({'node':report['current_node'],'input_shapes':[list(value.shape) for value in args],
        'input_dtypes':[str(value.dtype) for value in args],
        'same_input_objects':len(args)==len(tensors)==3 and all(value is original for value,original in zip(args,tensors))})
      return production(*args,**kwargs)
    onnx_half._conv_f32_mlas_depthwise=counted;onnx_half.install(runner)
    report.update(gpu_device=device.device_name,gpu_driver=device.driver_version)
    for name,row in selected.items():
      report.update(current_node=name,current_variant='exact_import');save()
      node=nodes[row['output']]
      options={key:list(node.opts[key]) if key in ('pads','strides','dilations') else node.opts[key]
               for key in ('auto_pad','group','dilations','strides','pads')}
      if list(node.inputs)!=row['inputs'] or options!=row['attributes']:raise ValueError('Actual depthwise attributes changed')
      arrays=[cpu[tensor] for tensor in row['inputs']];expected=cpu[row['output']]
      tensors=[Tensor(array,dtype=dtypes.float32,device='CL').realize() for array in arrays]
      saved={'inputs':arrays[0],'weights':arrays[1],'bias':arrays[2],'expected':expected}
      result={'contract':row,'results':{},'imports':{},'input_sha256':{
        tensor:hashlib.sha256(array.tobytes()).hexdigest() for tensor,array in zip(row['inputs'],arrays)}}
      report['results'][name]=result;array_path=session/(name+'.npz')
      try:
        result['production_guard']=(all(value.dtype==dtypes.float32 for value in tensors)
          and onnx_half._proven_f32_depthwise(tensors[0].shape,tensors[1].shape,tensors[2].shape,
            node.opts.get('auto_pad','NOTSET'),node.opts.get('dilations',(1,1)),node.opts.get('group',1),
            node.opts.get('kernel_shape'),node.opts.get('pads',(0,0,0,0)),node.opts.get('strides',(1,1))))
        for tensor,value,array in zip(row['inputs'],tensors,arrays):
          imported=value.numpy();result['imports'][tensor]={'dtype':str(imported.dtype),'tensor_dtype':str(value.dtype),
            'itemsize':int(imported.itemsize),'sha256':hashlib.sha256(imported.tobytes()).hexdigest(),'comparison':_compare(imported,array,np)}
        result['input_bytes_equal']=all(value['comparison']['bit_equal'] and value['sha256']==result['input_sha256'][tensor]
                                       for tensor,value in result['imports'].items())
        if not result['production_guard'] or not result['input_bytes_equal']:raise ValueError('Depthwise guard or exact CL import failed')
        previous_calls=len(calls)
        for label in ('legacy_tinygrad','sequential_fma_bias_last','sequential_fma_bias_first','separate_bias_last',
                      'production_direct','production_dispatch'):
          report['current_variant']=label;save()
          if label=='legacy_tinygrad':output=legacy[row['output']](*tensors,**node.opts)
          elif label=='production_direct':output=production(*tensors,pads=node.opts['pads'],strides=node.opts['strides'],group=node.opts['group'])
          elif label=='production_dispatch':output=runner._select_op(node.op,node.opset_id)(*tensors,**node.opts)
          else:output=_depthwise_probe(*tensors,options,fused=label!='separate_bias_last',bias_first=label=='sequential_fma_bias_first')
          actual=output.numpy();del output
          saved[label]=actual;result['results'][label]=_compare(actual,expected,np)
          np.savez_compressed(array_path,**saved);result.update(array_file=str(array_path),array_sha256=_digest(array_path));save()
        result['production_dispatch_called']=(len(calls)==previous_calls+1 and calls[-1]['node']==name and calls[-1]['same_input_objects'])
        result['production_call']=calls[-1] if len(calls)>previous_calls else None
        report['completed_output_values']+=int(expected.size)
      finally:
        device.synchronize();del tensors,saved,arrays
        if 'actual' in locals():del actual
        gc.collect();device.allocator.free_cache()
      save()
    report.update(completed=True,current_node=None,current_variant=None,
      all_input_bytes_equal=all(row['input_bytes_equal'] for row in report['results'].values()),
      sequential_fma_bias_last_bit_equal=all(row['results']['sequential_fma_bias_last']['bit_equal'] for row in report['results'].values()),
      all_production_guards_selected=all(row['production_guard'] for row in report['results'].values()),
      all_production_direct_bit_equal=all(row['results']['production_direct']['bit_equal'] for row in report['results'].values()),
      all_production_dispatch_bit_equal=all(row['results']['production_dispatch']['bit_equal'] for row in report['results'].values()),
      all_production_dispatch_called=all(row['production_dispatch_called'] for row in report['results'].values()),
      production_dispatch_call_count=len(calls))
    save();return report
  except Exception as error:
    report.update(error_type=type(error).__name__,error=str(error));save();return report
  finally:
    if production is not None:onnx_half._conv_f32_mlas_depthwise=production
    reference.close()
    if device is not None:device.synchronize()


def _digest(path):
  with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _compare(actual,expected,np):
  if actual.shape!=expected.shape or actual.dtype!=np.float32 or expected.dtype!=np.float32:
    raise ValueError('Complete FP32 tensor contract changed')
  if not np.isfinite(actual).all() or not np.isfinite(expected).all():raise ValueError('Nonfinite diagnostic output')
  different=actual.view(np.uint32)!=expected.view(np.uint32)
  close=np.isclose(actual,expected,rtol=1e-4,atol=1e-5,equal_nan=False)
  result={'values':int(actual.size),'bit_equal':not bool(np.any(different)),
          'different_values':int(np.count_nonzero(different)),'tolerance_passed':bool(np.all(close)),
          'outside_tolerance':int(np.count_nonzero(~close)),
          'maximum_absolute_difference':float(np.max(np.abs(actual.astype(np.float64)-expected.astype(np.float64))))}
  for label,mask in (('first_bit_difference',different),('first_tolerance_failure',~close)):
    indices=np.flatnonzero(mask)
    if indices.size:
      index=int(indices[0]);result[label]={'index':index,'coordinates':[int(v) for v in np.unravel_index(index,actual.shape)],
        'expected':float(expected.flat[index]),'actual':float(actual.flat[index]),
        'expected_bits':f'{int(expected.view(np.uint32).flat[index]):08x}',
        'actual_bits':f'{int(actual.view(np.uint32).flat[index]):08x}'}
  return result


def _reference_batches(names,size=200):
  """Respect DriverReference's 256-name call limit without dropping tail nodes."""
  if (type(size) is not int or not 1<=size<=256 or not isinstance(names,list) or not 1<=len(names)<=1024
      or any(type(name) is not str or not name for name in names) or len(set(names))!=len(names)):
    raise ValueError('Invalid bounded reference-name batches')
  return [names[start:start+size] for start in range(0,len(names),size)]


def _tanh_helper(source):
  from tinygrad import Tensor
  from tinygrad.dtype import dtypes
  from tinygrad.uop.ops import KernelInfo,Ops,UOp
  count=source.numel();local=64
  while count%local:local//=2
  def kernel(out,value):
    block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
    lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0');index=block*local+lane
    result=UOp(Ops.CUSTOM,src=(value.index(index).load(),),arg=('op_ort_tanh_f32({0})',dtypes.float32))
    return out.index(index).store(result).sink(arg=KernelInfo(name='production_token1_tanh_probe',opts_to_apply=()))
  return Tensor.empty(count,dtype=dtypes.float32,device='CL').custom_kernel(source.flatten().contiguous(),fxn=kernel)[0].reshape(source.shape)


def _full_graph_probe(path,metadata,cpu,report,saved,save,np,include_window):
  from tinygrad import Tensor
  from tinygrad.dtype import dtypes
  from tinygrad.nn.onnx import OnnxRunner
  from android_runtime import onnx_half
  runner=OnnxRunner(path).to('CL')
  conv=next(node for node in runner.graph_nodes if metadata['output'] in node.outputs)
  real_helper=onnx_half._conv_f32_mlas128;calls=[];phase='forced_dispatch'
  def counted(X,W,B):
    calls.append({'phase':phase,'shapes':[list(value.shape) for value in (X,W,B)],'dtypes':[str(value.dtype) for value in (X,W,B)]})
    return real_helper(X,W,B)
  def guard(values):
    X,W,B=values;options=conv.opts
    return (X.dtype==W.dtype==B.dtype==dtypes.float32 and onnx_half._proven_f32_conv807(
      X.shape,W.shape,B.shape,options.get('auto_pad','NOTSET'),options.get('dilations',(1,1)),
      options.get('group',1),options.get('kernel_shape'),options.get('pads',(0,0,0,0)),options.get('strides',(1,1))))
  tensors=[Tensor(cpu[name],dtype=dtypes.float32,device='CL').realize() for name in metadata['inputs']]
  direct=real_helper(*tensors).numpy();saved['production_direct_807']=direct
  report['production_direct_807']=_compare(direct,cpu[metadata['output']],np)
  onnx_half._conv_f32_mlas128=counted
  try:
    onnx_half.install(runner)
    dispatch=runner._select_op(conv.op,conv.opset_id)
    actual=dispatch(*tensors,**conv.opts).numpy();saved['production_dispatch_807']=actual
    report['production_dispatch_807']=_compare(actual,cpu[metadata['output']],np)
    report['actual_conv807_options']={key:{'type':type(value).__name__,'value':value} for key,value in conv.opts.items()}
    report['forced_dispatch_guard']=bool(guard(tensors));report['production_helper_calls']=calls;save()
    if not include_window:
      report['full_graph']={'completed':False,'skipped':'Explicit cabinWindow=true opt-in is required'};save();return
    phase='full_graph';onnx_half.materialize_operators(runner)
    output=runner({'input_img':Tensor.zeros(1,1440*960,dtype=dtypes.uint8,device='CL'),
                   'calib':Tensor.zeros(1,3,dtype=dtypes.float32,device='CL')})
    live=[runner.graph_values[name] for name in metadata['inputs']]
    report['actual_full_graph_conv807']={'guard':bool(guard(live)),
      'inputs':[{'shape':list(value.shape),'dimension_types':[type(dim).__name__ for dim in value.shape],
                 'dtype':str(value.dtype)} for value in live]}
    report['production_helper_calls']=calls
    report['full_graph_807_inputs']={name:_compare(value.numpy().astype(np.float32),cpu[name],np)
                                     for name,value in zip(metadata['inputs'],live)}
    report['full_graph_807_output']=_compare(runner.graph_values[metadata['output']].numpy().astype(np.float32),cpu[metadata['output']],np)
    actual_final=output['outputs'].numpy().astype(np.float32);saved['full_graph_553']=actual_final
    report['full_graph_final_553']=_compare(actual_final,cpu['outputs'],np)
    tanh=metadata['tanh'];tanh_input=runner.graph_values[tanh['input']].numpy().astype(np.float32)
    tanh_output=runner.graph_values[tanh['output']].numpy().astype(np.float32)
    saved['full_graph_tanh_input']=tanh_input;saved['full_graph_tanh_output']=tanh_output
    report['full_graph_tanh_input']=_compare(tanh_input,cpu[tanh['input']],np)
    report['full_graph_tanh_output']=_compare(tanh_output,cpu[tanh['output']],np)
    checked=[];first_failure=None
    for position,row in enumerate(metadata['window']['activations'],metadata['window']['start']):
      actual=runner.graph_values[row['name']].numpy().astype(np.float32);expected=cpu[row['name']]
      comparison=_compare(actual,expected,np);item={**row,'position':position,**comparison};checked.append(item)
      if not comparison['tolerance_passed']:
        first_failure=item;saved['first_failure_actual']=actual;saved['first_failure_expected']=expected
        node=next(node for node in runner.graph_nodes if row['name'] in node.outputs);forced=[];inputs={}
        for index,name in enumerate(node.inputs):
          value=runner._get_python_const(name,node.op,index)
          if isinstance(value,Tensor) and name in cpu:
            actual_input=value.to('CL',force=True).numpy().astype(np.float32)
            inputs[name]=_compare(actual_input,cpu[name],np)
            saved['failure_cpu_input_'+str(index)]=cpu[name];saved['failure_gpu_input_'+str(index)]=actual_input
            forced.append(Tensor(cpu[name],dtype=value.dtype,device='CL'))
          else:forced.append(value);inputs[name]={'forced':False,'type':type(value).__name__}
        item['complete_floating_inputs']=inputs
        try:
          phase='first_failure_teacher';teacher=runner._select_op(node.op,node.opset_id)(*forced,**node.opts)
          teacher=teacher[node.outputs.index(row['name'])] if isinstance(teacher,tuple) else teacher
          teacher=teacher.numpy().astype(np.float32);saved['first_failure_teacher']=teacher
          item['teacher_forced_floating_inputs']=_compare(teacher,expected,np)
        except Exception as failure:item['teacher_error']=str(failure)
        break
    report['window']={'start':metadata['window']['start'],'available':metadata['window']['count'],
      'checked':checked,'complete':first_failure is None,'first_tolerance_failure':first_failure,
      'first_bit_difference':next((row for row in checked if not row['bit_equal']),None)}
    report['full_graph']={'completed':True,'scope':'Unchanged full graph, ordered production operators; zero input only'}
    save()
  finally:onnx_half._conv_f32_mlas128=real_helper


def _conv_candidate(source,weight,bias,panel,fused,bias_first=False):
  from tinygrad import Tensor
  from tinygrad.dtype import AddrSpace,dtypes
  from tinygrad.uop.ops import AxisType,KernelInfo,Ops,UOp
  # This probe deliberately binds exactly the measured Conv807, rather than
  # asserting that all MLAS convolution algorithms use the same panel size.
  if source.shape!=(1,32,120,180) or weight.shape!=(32,32,3,3) or bias.shape!=(32,):
    raise ValueError('Review changed Conv807 geometry')
  count=32*60*90;local=64;k_total=32*3*3

  def kernel(out,image,weights,biases):
    block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
    lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0');index=block*local+lane
    ox=index%90;oy=(index//90)%60;channel=index//(60*90)
    parts=[]
    for slot,start in enumerate(range(0,k_total,panel)):
      # Distinct allocation shapes also prevent accidental scratch identity
      # reuse while the partial sums are kept until the final panel add.
      acc=UOp.alloc((slot+1,),dtypes.float32,addrspace=AddrSpace.REG)
      initial=biases.index(channel).load() if bias_first and slot==0 else UOp.const(0.).cast(dtypes.float32)
      initialized=acc.index(0).store(initial);state=acc.after(initialized)
      reduction=UOp.range(min(panel,k_total-start),slot+1,AxisType.LOOP)
      term=reduction+start;ic=term//9;ky=(term//3)%3;kx=term%3
      iy=oy*2-1+ky;ix=ox*2-1+kx
      valid=(iy>=0)&(iy<120)&(ix>=0)&(ix<180)
      bounded_y=iy.maximum(0).minimum(119);bounded_x=ix.maximum(0).minimum(179)
      value=image.index((ic*120+bounded_y)*180+bounded_x).load()
      value=valid.where(value,UOp.const(0.).cast(dtypes.float32))
      w=weights.index(channel*k_total+term).load();previous=state.after(reduction).index(0).load()
      if fused:updated=UOp(Ops.CUSTOM,src=(value,w,previous),arg=('fma({0},{1},{2})',dtypes.float32))
      else:
        product=UOp(Ops.CUSTOM,src=(value,w),arg=('({0} * {1})',dtypes.float32))
        updated=UOp(Ops.CUSTOM,src=(product,previous),arg=('({0} + {1})',dtypes.float32))
      finished=state.index(0).store(updated).end(reduction)
      parts.append(state.after(finished).index(0).load())
    result=parts[0]
    for part in parts[1:]:result=UOp(Ops.CUSTOM,src=(result,part),arg=('({0} + {1})',dtypes.float32))
    if not bias_first:result=UOp(Ops.CUSTOM,src=(result,biases.index(channel).load()),arg=('({0} + {1})',dtypes.float32))
    return out.index(index).store(result).sink(arg=KernelInfo(name='conv807_f32_arithmetic_probe',opts_to_apply=()))

  output=Tensor.empty(count,dtype=dtypes.float32,device='CL')
  return output.custom_kernel(source.flatten().contiguous(),weight.flatten().contiguous(),bias.contiguous(),fxn=kernel)[0].reshape(1,32,60,90)


def _followup_contract(node,shapes,options):
  expected={
    'node_Conv_809':([[1,32,60,90],[32,32,1,1],[32],[1,32,60,90]],
      {'auto_pad':'NOTSET','group':1,'dilations':[1,1],'strides':[1,1],'pads':[0,0,0,0]}),
    'node_Conv_811':([[1,32,60,90],[96,32,3,3],[96],[1,96,30,45]],
      {'auto_pad':'NOTSET','group':1,'dilations':[1,1],'strides':[2,2],'pads':[1,1,1,1]})}
  if node not in expected or not isinstance(shapes,list) or len(shapes)!=4:return False
  if any(not isinstance(shape,list) or any(type(dim) is not int for dim in shape) for shape in shapes):return False
  if not isinstance(options,dict) or type(options.get('group')) is not int:return False
  for key in ('dilations','strides','pads'):
    if not isinstance(options.get(key),list) or any(type(value) is not int for value in options[key]):return False
  return (shapes,options)==expected[node]


def _followup_conv(source,weights,bias,options,panel,fused):
  from tinygrad import Tensor
  from tinygrad.dtype import AddrSpace,dtypes
  from tinygrad.uop.ops import AxisType,KernelInfo,Ops,UOp
  n,cin,height,width=source.shape;cout,channels,kh,kw=weights.shape
  if n!=1 or options['group']!=1 or channels!=cin:raise ValueError('Unproven follow-up geometry')
  sy,sx=options['strides'];dy,dx=options['dilations'];pt,pl,pb,pr=options['pads']
  oh=(height+pt+pb-dy*(kh-1)-1)//sy+1;ow=(width+pl+pr-dx*(kw-1)-1)//sx+1
  count=cout*oh*ow;k_total=channels*kh*kw;local=64
  while count%local:local//=2
  def kernel(out,image,weight,biases):
    block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
    lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0');index=block*local+lane
    ox=index%ow;oy=(index//ow)%oh;channel=index//(oh*ow);parts=[]
    for slot,start in enumerate(range(0,k_total,panel)):
      acc=UOp.alloc((slot+1,),dtypes.float32,addrspace=AddrSpace.REG)
      initialized=acc.index(0).store(UOp.const(0.).cast(dtypes.float32));state=acc.after(initialized)
      reduction=UOp.range(min(panel,k_total-start),slot+1,AxisType.LOOP)
      term=reduction+start;ic=term//(kh*kw);ky=(term//kw)%kh;kx=term%kw
      iy=oy*sy-pt+ky*dy;ix=ox*sx-pl+kx*dx
      valid=(iy>=0)&(iy<height)&(ix>=0)&(ix<width)
      bounded_y=iy.maximum(0).minimum(height-1);bounded_x=ix.maximum(0).minimum(width-1)
      value=image.index((ic*height+bounded_y)*width+bounded_x).load()
      value=valid.where(value,UOp.const(0.).cast(dtypes.float32))
      w=weight.index(channel*k_total+term).load();previous=state.after(reduction).index(0).load()
      if fused:result=UOp(Ops.CUSTOM,src=(value,w,previous),arg=('fma({0},{1},{2})',dtypes.float32))
      else:
        product=UOp(Ops.CUSTOM,src=(value,w),arg=('({0} * {1})',dtypes.float32))
        result=UOp(Ops.CUSTOM,src=(product,previous),arg=('({0} + {1})',dtypes.float32))
      finished=state.index(0).store(result).end(reduction);parts.append(state.after(finished).index(0).load())
    result=parts[0]
    for part in parts[1:]:result=UOp(Ops.CUSTOM,src=(result,part),arg=('({0} + {1})',dtypes.float32))
    result=UOp(Ops.CUSTOM,src=(result,biases.index(channel).load()),arg=('({0} + {1})',dtypes.float32))
    return out.index(index).store(result).sink(arg=KernelInfo(name='f32_conv_schedule_'+str(count)+'_'+str(panel)+'_'+str(int(fused)),opts_to_apply=()))
  return Tensor.empty(count,dtype=dtypes.float32,device='CL').custom_kernel(
    source.flatten().contiguous(),weights.flatten().contiguous(),bias.contiguous(),fxn=kernel)[0].reshape(1,cout,oh,ow)


def _batch_contract(metadata):
  """Bound every test-only family geometry and CPU transport before import/run."""
  geometry={
    'node_Conv_813':(96,64,30,45),'node_Conv_827':(192,96,15,23),'node_Conv_829':(96,192,15,23),
    'node_Conv_833':(192,96,15,23),'node_Conv_835':(96,192,15,23),'node_Conv_839':(192,96,15,23),
    'node_Conv_841':(96,192,15,23),'node_Conv_845':(192,96,15,23),'node_Conv_851':(384,96,15,23)}
  if not isinstance(metadata,dict) or type(metadata.get('schema')) is not int or metadata['schema']!=1:return False
  if (metadata.get('sha256')!=BATCH_DIAGNOSTIC_SHA256 or metadata.get('source_sha256')!=LOWERING_SHA256
      or metadata.get('original_model_sha256')!=ORIGINAL_SHA256
      or metadata.get('operators_and_constants_unchanged') is not True
      or metadata.get('host_model_inference_executed') is not False):return False
  nodes=metadata.get('nodes');names=metadata.get('reference_names');shapes=metadata.get('reference_shapes')
  if not isinstance(nodes,dict) or set(nodes)!=set(geometry):return False
  if (not isinstance(names,list) or len(names)!=37 or any(not isinstance(name,str) or not name for name in names)
      or len(set(names))!=len(names) or not isinstance(shapes,dict) or set(shapes)!=set(names)):return False
  expected_shapes={'outputs':[1,553]};options={
    'auto_pad':'NOTSET','group':1,'dilations':[1,1],'strides':[1,1],'pads':[0,0,0,0]}
  output_values=0
  for name,(cin,cout,height,width) in geometry.items():
    row=nodes[name]
    if not isinstance(row,dict) or type(row.get('candidate_panel')) is not int or row['candidate_panel']!=128:return False
    tensors=row.get('inputs');output=row.get('output');actual_shapes=row.get('shapes');attrs=row.get('attributes')
    if (not isinstance(tensors,list) or len(tensors)!=3 or any(not isinstance(t,str) or not t for t in tensors)
        or not isinstance(output,str) or not output or len(set([*tensors,output]))!=4):return False
    if (not isinstance(actual_shapes,list) or len(actual_shapes)!=4
        or any(not isinstance(s,list) or any(type(v) is not int for v in s) for s in actual_shapes)
        or actual_shapes!=[[1,cin,height,width],[cout,cin,1,1],[cout],[1,cout,height,width]]):return False
    if (not isinstance(attrs,dict) or type(attrs.get('group')) is not int or attrs!=options
        or any(not isinstance(attrs.get(key),list) or any(type(v) is not int for v in attrs[key])
               for key in ('pads','strides','dilations'))):return False
    for tensor,shape in zip([*tensors,output],actual_shapes):
      if tensor in expected_shapes and expected_shapes[tensor]!=shape:return False
      expected_shapes[tensor]=shape
    output_values+=cout*height*width
  if shapes!=expected_shapes:return False
  bound=0
  for shape in shapes.values():
    if not isinstance(shape,list) or any(type(dim) is not int or dim<=0 for dim in shape):return False
    count=1
    for dim in shape:count*=dim
    bound+=count*4
  return (type(metadata.get('bound_bytes')) is int and metadata['bound_bytes']==bound==5003300
          and bound<=16*1024*1024 and type(metadata.get('total_output_values')) is int
          and metadata['total_output_values']==output_values==450720)


def inspect_f32_batch(root,native,session,attempt_id):
  """Nine complete identical-CPU-input probes, one node's CL storage at a time."""
  if not Path('/system/bin/app_process').exists():raise RuntimeError('Android target only')
  import gc
  import numpy as np
  from java import jarray,jclass
  from android_runtime.worker import configure
  configure(session,native)
  root=Path(root);base=root.parent;session=Path(session);session.mkdir(parents=True,exist_ok=True)
  path=base/'cabin-f32-batch.onnx';metadata=json.loads(path.with_suffix('.json').read_text())
  if (not _batch_contract(metadata) or _digest(path)!=BATCH_DIAGNOSTIC_SHA256
      or _digest(base/'driver-cpu-lowering.onnx')!=LOWERING_SHA256
      or _digest(root/'dmonitoring_model.onnx')!=ORIGINAL_SHA256):raise ValueError('Batch reference graph contract changed')
  version=str(jclass('ai.onnxruntime.OrtEnvironment').getEnvironment().getVersion())
  if version!='1.23.2':raise ValueError('Original ORT 1.23.2 reference required')
  reference=jclass('ai.comma.openpilot.sim.DriverReference');device=None;production=None
  report={'schema':1,'attempt_id':attempt_id,'completed':False,'qualified':False,'timing_qualified':False,
    'scope':'Nine sequential teacher-forced CPU-zero activation probes; no full-model GPU qualification',
    'production_scope':'Four additional exact measured pointwise geometries',
    'ort_version':version,'original_model_sha256':ORIGINAL_SHA256,
    'cpu_lowering_sha256':LOWERING_SHA256,'diagnostic_sha256':BATCH_DIAGNOSTIC_SHA256,
    'cpu_reference_names':len(metadata['reference_names']),'cpu_transport_bound_bytes':metadata['bound_bytes'],
    'total_output_values':metadata['total_output_values'],'completed_output_values':0,'results':{},
    'current_node':None,'current_variant':'cpu_reference','rtol':1e-4,'atol':1e-5,
    'native_sha256':{p.name:_digest(p) for p in sorted(Path(native).glob('*.so'))}}
  report_path=session/'report.json'
  def save():report_path.write_text(json.dumps(report,indent=2)+'\n')
  save()
  try:
    names=metadata['reference_names']
    values=reference.zeroIntermediates(str(path),jarray(jclass('java.lang.String'))(names))
    cpu={name:np.asarray(values.get(name),dtype=np.float32).reshape(metadata['reference_shapes'][name]).copy() for name in names}
    if any(not np.isfinite(array).all() for array in cpu.values()):raise ValueError('Nonfinite CPU reference')
    original=np.asarray(reference.zeroInput(str(root/'dmonitoring_model.onnx')),dtype=np.float32).reshape(1,553).copy()
    comparison=_compare(cpu['outputs'],original,np)
    report.update(original_cpu_outputs_unchanged=comparison['bit_equal'],original_553_comparison=comparison)
    np.savez_compressed(session/'original-553.npz',original=original,diagnostic=cpu['outputs'])
    report['original_553_array_sha256']=_digest(session/'original-553.npz');save()
    # Release all Java arrays and ORT sessions before CL allocation. The bound
    # covers exported FP32 arrays, not runtime/model caches or driver memory.
    del values,original;reference.close();gc.collect()
    if not comparison['bit_equal']:raise ValueError('Batch diagnostic changed original 553 CPU bits')
    from android_runtime.gpu import configure as configure_gpu,retained_renderer
    device=configure_gpu();device.renderers=[type(retained_renderer())];device.cached_renderer.clear()
    from tinygrad import Tensor
    from tinygrad.dtype import dtypes
    from tinygrad.nn.onnx import OnnxRunner
    # Retain legacy callables before installing onto a private operator dict;
    # no unrelated OnnxRunner or graph initializer is transferred/modified.
    runner=OnnxRunner(path);runner.onnx_ops=dict(runner.onnx_ops)
    nodes={node.outputs[0]:node for node in runner.graph_nodes if node.op=='Conv'}
    legacy={output:runner._select_op(node.op,node.opset_id) for output,node in nodes.items()}
    from android_runtime import onnx_half
    production=getattr(onnx_half,'_conv_f32_mlas_followup',None)
    if not callable(production):raise ValueError('Final production FP32 helper unavailable')
    calls=[]
    def counted(*args,**kwargs):
      calls.append({'node':report['current_node'],'input_shapes':[list(value.shape) for value in args],
                    'input_dtypes':[str(value.dtype) for value in args],
                    'same_input_objects':len(args)==len(tensors)==3 and all(value is supplied for value,supplied in zip(args,tensors))})
      return production(*args,**kwargs)
    onnx_half._conv_f32_mlas_followup=counted;onnx_half.install(runner)
    report.update(gpu_device=device.device_name,gpu_driver=device.driver_version)
    for name,selected in metadata['nodes'].items():
      report.update(current_node=name,current_variant='validate_actual_node');save()
      node=nodes[selected['output']]
      actual_options={key:list(node.opts[key]) if key in ('pads','strides','dilations') else node.opts[key]
                      for key in ('auto_pad','group','dilations','strides','pads')}
      if (list(node.inputs)!=selected['inputs'] or actual_options!=selected['attributes']
          or ('kernel_shape' in node.opts and tuple(node.opts['kernel_shape'])!=(1,1))):
        raise ValueError('Actual OnnxRunner Conv attributes changed: '+name)
      arrays=[cpu[tensor] for tensor in selected['inputs']];expected=cpu[selected['output']]
      saved={'inputs':arrays[0],'weights':arrays[1],'bias':arrays[2],'expected':expected}
      row={'contract':selected,'results':{},'input_sha256':{
        tensor:hashlib.sha256(array.tobytes()).hexdigest() for tensor,array in zip(selected['inputs'],arrays)}}
      report['results'][name]=row;array_path=session/(name+'.npz')
      tensors=[Tensor(array,dtype=dtypes.float32,device='CL').realize() for array in arrays]
      try:
        row['production_guard']=(all(value.dtype==dtypes.float32 for value in tensors)
          and onnx_half._proven_f32_conv_followup(tensors[0].shape,tensors[1].shape,tensors[2].shape,
            node.opts.get('auto_pad','NOTSET'),node.opts.get('dilations',(1,1)),node.opts.get('group',1),
            node.opts.get('kernel_shape'),node.opts.get('pads',(0,0,0,0)),node.opts.get('strides',(1,1))))
        row['imports']={}
        for tensor,array,value in zip(selected['inputs'],arrays,tensors):
          imported=value.numpy()
          row['imports'][tensor]={'tensor_dtype':str(value.dtype),'dtype':str(imported.dtype),'itemsize':int(imported.itemsize),
            'sha256':hashlib.sha256(imported.tobytes()).hexdigest(),'comparison':_compare(imported,array,np)}
        row['input_bytes_equal']=all(item['comparison']['bit_equal'] and item['sha256']==row['input_sha256'][tensor]
                                     and item['itemsize']==4 for tensor,item in row['imports'].items())
        if not row['production_guard'] or not row['input_bytes_equal']:raise ValueError('Production guard or exact import failed: '+name)
        previous_calls=len(calls)
        for label in ('legacy_tinygrad','candidate_fma_k128','production_direct','production_dispatch'):
          report['current_variant']=label;save()
          if label=='legacy_tinygrad':output=legacy[selected['output']](*tensors,**node.opts)
          elif label=='candidate_fma_k128':output=_followup_conv(*tensors,selected['attributes'],128,True)
          elif label=='production_direct':output=production(*tensors,pads=node.opts['pads'],strides=node.opts['strides'])
          else:output=runner._select_op(node.op,node.opset_id)(*tensors,**node.opts)
          actual=output.numpy();del output
          saved[label]=actual;row['results'][label]=_compare(actual,expected,np)
          np.savez_compressed(array_path,**saved)
          row.update(array_file=str(array_path),array_sha256=_digest(array_path));save()
        row['production_dispatch_called']=(len(calls)==previous_calls+1 and calls[-1]['node']==name
                                           and calls[-1]['same_input_objects'])
        row['production_call']=calls[-1] if len(calls)>previous_calls else None
        report['completed_output_values']+=int(expected.size)
      finally:
        device.synchronize();del tensors,saved,arrays
        if 'actual' in locals():del actual
        gc.collect();device.allocator.free_cache()
      save()
    report.update(completed=True,current_node=None,current_variant=None,
      all_candidate_outputs_bit_equal=all(row['results']['candidate_fma_k128']['bit_equal'] for row in report['results'].values()),
      all_candidate_outputs_tolerance_passed=all(row['results']['candidate_fma_k128']['tolerance_passed'] for row in report['results'].values()),
      production_measured_contracts_enabled=all(row['production_guard'] for row in report['results'].values()),
      all_input_bytes_equal=all(row['input_bytes_equal'] for row in report['results'].values()),
      all_production_direct_bit_equal=all(row['results']['production_direct']['bit_equal'] for row in report['results'].values()),
      all_production_dispatch_bit_equal=all(row['results']['production_dispatch']['bit_equal'] for row in report['results'].values()),
      all_production_dispatch_called=all(row['production_dispatch_called'] for row in report['results'].values()),
      production_dispatch_call_count=len(calls))
    save();return report
  except Exception as error:
    report.update(error_type=type(error).__name__,error=str(error));save();return report
  finally:
    if production is not None:onnx_half._conv_f32_mlas_followup=production
    reference.close()
    if device is not None:device.synchronize()


def inspect_f32_followup(root,native,session,attempt_id,node_name):
  if not Path('/system/bin/app_process').exists():raise RuntimeError('Android target only')
  import numpy as np
  from java import jarray,jclass
  from android_runtime.worker import configure
  configure(session,native)
  from android_runtime.gpu import configure as configure_gpu,retained_renderer
  device=configure_gpu();device.renderers=[type(retained_renderer())];device.cached_renderer.clear()
  from tinygrad import Tensor
  from tinygrad.dtype import dtypes
  from tinygrad.nn.onnx import OnnxRunner
  root=Path(root);base=root.parent;session=Path(session);session.mkdir(parents=True,exist_ok=True)
  path=base/'cabin-conv809-811.onnx';metadata=json.loads(path.with_suffix('.json').read_text())
  if (_digest(path)!=FOLLOWUP_DIAGNOSTIC_SHA256 or metadata['sha256']!=FOLLOWUP_DIAGNOSTIC_SHA256
      or metadata['source_sha256']!=LOWERING_SHA256 or _digest(base/'driver-cpu-lowering.onnx')!=LOWERING_SHA256
      or _digest(root/'dmonitoring_model.onnx')!=ORIGINAL_SHA256):raise ValueError('Follow-up graph or original model identity changed')
  selected=metadata['nodes'].get(node_name,{})
  if not _followup_contract(node_name,selected.get('shapes'),selected.get('attributes')):raise ValueError('Unproven follow-up node')
  if type(selected.get('candidate_panel')) is not int or selected['candidate_panel']!=(32 if node_name=='node_Conv_809' else 128):
    raise ValueError('Unexpected follow-up panel schedule')
  if metadata['bound_bytes']>4*1024*1024:raise ValueError('Follow-up CPU transport exceeds4MiB')
  version=str(jclass('ai.onnxruntime.OrtEnvironment').getEnvironment().getVersion())
  if version!='1.23.2':raise ValueError('Original ORT 1.23.2 reference required')
  reference=jclass('ai.comma.openpilot.sim.DriverReference');names=['outputs',*selected['inputs'],selected['output']]
  values=reference.zeroIntermediates(str(path),jarray(jclass('java.lang.String'))(names))
  arrays=[np.asarray(values.get(name),dtype=np.float32).reshape(shape).copy()
          for name,shape in zip(names[1:],selected['shapes'])]
  expected=arrays[-1];original=np.asarray(reference.zeroInput(str(root/'dmonitoring_model.onnx')),dtype=np.float32).reshape(1,553)
  lowered=np.asarray(values.get('outputs'),dtype=np.float32).reshape(1,553);comparison=_compare(lowered,original,np)
  report={'schema':1,'attempt_id':attempt_id,'completed':False,'qualified':False,'node':node_name,'ort_version':version,
    'scope':'One isolated complete original-CPU zero activation per process; no model qualification',
    'original_model_sha256':ORIGINAL_SHA256,'cpu_lowering_sha256':LOWERING_SHA256,'diagnostic_sha256':FOLLOWUP_DIAGNOSTIC_SHA256,
    'original_cpu_outputs_unchanged':comparison['bit_equal'],'original_553_comparison':comparison,'contract':selected,
    'input_sha256':{name:hashlib.sha256(array.tobytes()).hexdigest() for name,array in zip(selected['inputs'],arrays[:3])},
    'native_sha256':{p.name:_digest(p) for p in sorted(Path(native).glob('*.so')) if 'onnxruntime' in p.name},
    'gpu_device':device.device_name,'gpu_driver':device.driver_version,'results':{},'rtol':1e-4,'atol':1e-5}
  saved={'inputs':arrays[0],'weights':arrays[1],'bias':arrays[2],'expected':expected,'original_553':original,'diagnostic_553':lowered}
  output_path=session/'cabin-f32-followup.npz';report_path=session/'report.json'
  def save():
    np.savez_compressed(output_path,**saved);report.update(array_file=str(output_path),array_sha256=_digest(output_path))
    report_path.write_text(json.dumps(report,indent=2)+'\n')
  save()
  if not comparison['bit_equal']:raise ValueError('Follow-up diagnostic changed original 553 CPU bits')
  tensors=[Tensor(array,dtype=dtypes.float32,device='CL').realize() for array in arrays[:3]]
  runner=OnnxRunner(path).to('CL');node=next(node for node in runner.graph_nodes if selected['output'] in node.outputs)
  legacy=runner._select_op(node.op,node.opset_id)
  try:
    report['current_variant']='legacy_tinygrad';actual=legacy(*tensors,**node.opts).numpy()
    saved['legacy_tinygrad']=actual;report['results']['legacy_tinygrad']=_compare(actual,expected,np);save()
    k_total=int(np.prod(arrays[1].shape[1:]));panel=selected['candidate_panel']
    modes=[('candidate_fma_k'+str(panel),panel,True),('separate_k'+str(k_total),k_total,False)]
    if k_total!=panel:modes.append(('single_fma_k'+str(k_total),k_total,True))
    for label,panel,fused in modes:
      report['current_variant']=label;report_path.write_text(json.dumps(report,indent=2)+'\n')
      actual=_followup_conv(*tensors,selected['attributes'],panel,fused).numpy()
      saved[label]=actual;report['results'][label]=_compare(actual,expected,np);save()
    from android_runtime import onnx_half
    production=getattr(onnx_half,'_conv_f32_mlas_followup',None)
    report['production_available']=callable(production)
    if callable(production):
      guard=onnx_half._proven_f32_conv_followup(
        tensors[0].shape,tensors[1].shape,tensors[2].shape,node.opts.get('auto_pad','NOTSET'),
        node.opts.get('dilations',(1,1)),node.opts.get('group',1),node.opts.get('kernel_shape'),
        node.opts.get('pads',(0,0,0,0)),node.opts.get('strides',(1,1)))
      report['production_guard']=bool(guard)
      actual=production(*tensors,pads=node.opts['pads'],strides=node.opts['strides']).numpy()
      saved['production_direct']=actual;report['results']['production_direct']=_compare(actual,expected,np);save()
      calls=[]
      def counted(*args,**kwargs):calls.append(True);return production(*args,**kwargs)
      onnx_half._conv_f32_mlas_followup=counted
      try:
        onnx_half.install(runner)
        actual=runner._select_op(node.op,node.opset_id)(*tensors,**node.opts).numpy()
      finally:onnx_half._conv_f32_mlas_followup=production
      saved['production_dispatch']=actual;report['results']['production_dispatch']=_compare(actual,expected,np)
      report['production_dispatch_called']=len(calls)==1
    report.update(completed=True,current_variant=None,bit_exact_variants=[name for name,row in report['results'].items() if row['bit_equal']]);save()
    return report
  finally:device.synchronize();reference.close()


def inspect_fp32_conv(root,native,session,attempt_id,include_window=False):
  if not Path('/system/bin/app_process').exists():raise RuntimeError('Android target only')
  import numpy as np
  from java import jarray,jclass
  from android_runtime.worker import configure
  configure(session,native)
  from android_runtime.gpu import configure as configure_gpu,retained_renderer
  device=configure_gpu();device.renderers=[type(retained_renderer())];device.cached_renderer.clear()
  from tinygrad import Tensor
  from tinygrad.dtype import dtypes
  root=Path(root);base=root.parent;session=Path(session);session.mkdir(parents=True,exist_ok=True)
  path=base/('cabin-arithmetic-nodes.onnx' if include_window else 'cabin-arithmetic-short.onnx')
  diagnostic_hash=DIAGNOSTIC_SHA256 if include_window else SHORT_DIAGNOSTIC_SHA256
  metadata=json.loads(path.with_suffix('.json').read_text())
  if (_digest(root/'dmonitoring_model.onnx')!=ORIGINAL_SHA256 or _digest(path)!=diagnostic_hash
      or metadata['sha256']!=diagnostic_hash or metadata['source_sha256']!=LOWERING_SHA256
      or _digest(base/'driver-cpu-lowering.onnx')!=LOWERING_SHA256):
    raise ValueError('Original model, actual CPU lowering or diagnostic graph identity changed')
  if (metadata['node']!='node_Conv_807' or metadata['shapes']!=[[1,32,120,180],[32,32,3,3],[32],[1,32,60,90]]
      or metadata['attributes']!={'strides':[2,2],'group':1,'pads':[1,1,1,1],'dilations':[1,1],'auto_pad':'NOTSET'}):
    raise ValueError('Review changed original Conv807 contract')
  version=str(jclass('ai.onnxruntime.OrtEnvironment').getEnvironment().getVersion())
  if version!='1.23.2':raise ValueError('Pinned original ORT 1.23.2 CPU reference is required')
  reference=jclass('ai.comma.openpilot.sim.DriverReference')
  cpu={};batches=_reference_batches(metadata['reference_names'],metadata['reference_batch_size'])
  if metadata['bound_bytes']>128*1024*1024:raise ValueError('CPU reference transport exceeds128MiB')
  for names in batches:
    values=reference.zeroIntermediates(str(path),jarray(jclass('java.lang.String'))(names))
    for name in names:cpu[name]=np.asarray(values.get(name),dtype=np.float32).reshape(metadata['reference_shapes'][name]).copy()
  arrays=[cpu[name] for name in (*metadata['inputs'],metadata['output'])]
  source,weights,bias,expected=arrays
  original=np.asarray(reference.zeroInput(str(root/'dmonitoring_model.onnx')),dtype=np.float32).reshape(1,553)
  lowered=cpu['outputs']
  original_comparison=_compare(lowered,original,np)
  report={'schema':2,'attempt_id':attempt_id,'completed':False,'qualified':False,'ort_version':version,'include_window':include_window,
    'scope':'Identical complete original-CPU zero activation, weights and bias; isolated CL arithmetic only',
    'original_model_sha256':ORIGINAL_SHA256,'cpu_lowering_sha256':LOWERING_SHA256,'diagnostic_sha256':diagnostic_hash,
    'node':metadata['node'],'input_names':metadata['inputs'],'output_name':metadata['output'],
    'original_cpu_outputs_unchanged':original_comparison['bit_equal'],'original_553_comparison':original_comparison,
    'input_sha256':{name:hashlib.sha256(array.tobytes()).hexdigest() for name,array in zip(metadata['inputs'],arrays[:3])},
    'native_sha256':{p.name:_digest(p) for p in sorted(Path(native).glob('*.so')) if 'onnxruntime' in p.name},
    'gpu_device':device.device_name,'gpu_driver':device.driver_version,'results':{},
    'rtol':1e-4,'atol':1e-5,'host_model_inference_executed':False}
  report['cpu_reference_batches']=[len(batch) for batch in batches]
  report['known_cpu807_hashes_match']=all(hashlib.sha256(cpu[name].tobytes()).hexdigest()==expected
                                         for name,expected in metadata['known_cpu807_sha256'].items())
  saved={'inputs':source,'weights':weights,'bias':bias,'expected':expected,'original_553':original,'diagnostic_553':lowered}
  output_path=session/'cabin-fp32-conv807.npz';report_path=session/'report.json'
  def save():
    np.savez_compressed(output_path,**saved)
    report.update(array_file=str(output_path),array_sha256=_digest(output_path))
    report_path.write_text(json.dumps(report,indent=2)+'\n')
  save()
  if not original_comparison['bit_equal']:raise ValueError('Diagnostic changed the original 553 CPU output bits')
  if not report['known_cpu807_hashes_match']:raise ValueError('Known complete CPU Conv807 tensors changed')
  tensors=[Tensor(array,device='CL',dtype=dtypes.float32).realize() for array in arrays[:3]]
  try:
    variants=(
      ('fma_k288_bias_last',288,True,False),('fma_k128_bias_last',128,True,False),
      ('separate_k288_bias_last',288,False,False),('fma_k256_bias_last',256,True,False),
      ('fma_k288_bias_first',288,True,True)) if include_window else ()
    for label,panel,fused,bias_first in variants:
      report['current_variant']=label;report_path.write_text(json.dumps(report,indent=2)+'\n')
      actual=_conv_candidate(*tensors,panel,fused,bias_first).numpy()
      report['results'][label]=_compare(actual,expected,np);saved[label]=actual;save()
    tanh=metadata['tanh'];tanh_input=cpu[tanh['input']];tanh_expected=cpu[tanh['output']]
    tanh_actual=_tanh_helper(Tensor(tanh_input,dtype=dtypes.float32,device='CL').realize()).numpy()
    report['tanh_identical_cpu_input']=_compare(tanh_actual,tanh_expected,np)
    report['tanh_input_domain']={'minimum':float(tanh_input.min()),'maximum':float(tanh_input.max()),
      'abs_greater_than_9':int(np.count_nonzero(np.abs(tanh_input)>9)),
      'input_sha256':hashlib.sha256(tanh_input.tobytes()).hexdigest()}
    for label in ('first_bit_difference','first_tolerance_failure'):
      if label in report['tanh_identical_cpu_input']:
        row=report['tanh_identical_cpu_input'][label];row['input']=float(tanh_input.flat[row['index']])
        row['input_bits']=f"{int(tanh_input.view(np.uint32).flat[row['index']]):08x}"
    saved.update(tanh_inputs=tanh_input,tanh_expected=tanh_expected,tanh_helper=tanh_actual);save()
    _full_graph_probe(path,metadata,cpu,report,saved,save,np,include_window)
    report.update(completed=True,current_variant=None,
                  bit_exact_variants=[name for name,row in report['results'].items() if row['bit_equal']],
                  tolerance_passed_variants=[name for name,row in report['results'].items() if row['tolerance_passed']])
    save();return report
  finally:
    device.synchronize();reference.close()
