"""Android-only real UOp address/proof tests; never run by a host helper."""
from tinygrad.dtype import dtypes
from tinygrad.uop.ops import UOp,Ops,AxisType
from android_runtime.gpu_artifact import _pointer_access,_parallelize,_integer_affine,_pack_workgroup


def check():
  axis=UOp.range(16,0,AxisType.LOOP)
  output=UOp.param(0,dtypes.float,1024,'CL')
  source=UOp.param(1,dtypes.float,1024,'CL')
  aliases={0:output,1:source}
  proof=[]
  sink=output.index(axis).store(source.index(axis).load()).end(axis).sink()
  promoted,count=_parallelize(sink,aliases,proof)
  assert count==1,(count,proof)
  assert any(x.op is Ops.SPECIAL for x in promoted.toposort())
  packed,shape=_pack_workgroup(promoted)
  assert (shape['dimension'],shape['groups'],shape['lanes'],shape['total_indices'])==(0,1,16,16),shape
  specials={n.arg:n for n in packed.toposort() if n.op is Ops.SPECIAL}
  assert specials['gidx0'].src[0].vmax==1 and specials['lidx0'].src[0].vmax==16
  _,start,_=_pointer_access(next(n.src[0] for n in packed.toposort() if n.op is Ops.STORE))
  assert _integer_affine(start)==(0,{specials['gidx0']:64,specials['lidx0']:4}),_integer_affine(start)
  unchanged,shape=_pack_workgroup(packed)
  assert unchanged is packed and shape is None
  # The new flattened gidx0 can be identical to an old interned axis. Ensure
  # substitution resolves every temporary without recursively replacing it.
  g0=UOp(Ops.SPECIAL,src=(UOp.const(128).cast(dtypes.int32),),arg='gidx0')
  g1=UOp(Ops.SPECIAL,src=(UOp.const(8),),arg='gidx1');g2=UOp(Ops.SPECIAL,src=(UOp.const(8),),arg='gidx2')
  big_out=UOp.param(0,dtypes.float,8192,'CL');big_in=UOp.param(1,dtypes.float,8192,'CL')
  index=(g0*8+g1)*8+g2
  flat,shape=_pack_workgroup(big_out.index(index).store(big_in.index(index).load()).sink())
  specials={n.arg:n for n in flat.toposort() if n.op is Ops.SPECIAL}
  assert set(specials)=={'gidx0','lidx0'} and shape['groups']==128 and shape['lanes']==64,shape
  assert specials['gidx0'] is g0
  assert not any(n.op is Ops.NOOP for n in flat.toposort())
  assert not any(n.op is Ops.CUSTOM and n.arg[0].startswith('android_flat_axis_') for n in flat.toposort())
  # Planar packing: bounding intervals overlap, but each pixel owns exactly
  # eight byte residues in a complete 65536-byte plane. Reads are disjoint.
  pixel=UOp.range(8192,21,AxisType.WEAK);plane=UOp.range(6,22,AxisType.WEAK)
  large_output=UOp.param(0,dtypes.float,98304,'CL');large_source=UOp.param(1,dtypes.float,98304,'CL')
  stores=[large_output.index(plane*16384+pixel*2+i).store(large_source.index(plane*16384+pixel*2+i).load()) for i in range(2)]
  planar=stores[0].end(pixel,plane).sink(stores[1].end(pixel,plane))
  _,count=_parallelize(planar,{0:large_output,1:large_source},[])
  assert count>=1,count
  # A padded stencil can share an arena with a disjoint output even when the
  # unmasked pointer extrema would overlap the first output element.
  pixel=UOp.range(16,24,AxisType.WEAK);tap=UOp.range(3,25,AxisType.LOOP)
  index=pixel+tap-1;gate=(-1<index)&(index<16)
  value=source.index(index).load(UOp.const(0.).cast(dtypes.float32),gate)
  stencil=output.index(16+pixel).store(value).end(pixel,tap).sink()
  proofs=[]
  _,count=_parallelize(stencil,{0:output,1:output},[],proofs)
  assert count==1 and proofs,(count,proofs)
  unbounded=source.index(index).load(UOp.const(0.).cast(dtypes.float32),-1<index)
  _,count=_parallelize(output.index(16+pixel).store(unbounded).end(pixel,tap).sink(),{0:output,1:output},[])
  assert count==0,count
  weak=UOp.range(16,2,AxisType.WEAK)
  proof=[]
  sink=output.index(weak).store(source.index(weak).load()).end(weak).sink()
  _,count=_parallelize(sink,aliases,proof)
  assert count==1,(count,proof)

  # Two views in the same physical arena, but provably disjoint byte regions.
  viewed=output[256:512].index(axis)
  slot,start,width=_pointer_access(viewed)
  assert slot==0 and start.vmin==1024 and start.vmax==1084 and width==4,(slot,start,width)
  proof=[]
  sink=viewed.store(source.index(axis).load()).end(axis).sink()
  _,count=_parallelize(sink,{0:output,1:output},proof)
  assert count==1,(count,proof)

  # A neighboring-element read in an overlapping arena remains serial.
  proof=[]
  sink=output.index(axis).store(source.index(axis+1).load()).end(axis).sink()
  _,count=_parallelize(sink,{0:output,1:output},proof)
  assert count==0 and proof[0]['reason']=='overlapping_arena',(count,proof)
  # History planes remain ordered within each independently owned pixel.
  pixel=UOp.range(8,28,AxisType.WEAK);plane=UOp.range(3,29,AxisType.WEAK)
  sink=output.index(plane*8+pixel).store(source.index((plane+1)*8+pixel).load()).end(plane,pixel).sink()
  promoted,count=_parallelize(sink,{0:output,1:output},[])
  assert count==1 and plane in promoted.toposort() and pixel not in promoted.toposort(),count

  # A reduction index never becomes a global axis; its stores overlap.
  reduction=UOp.range(32,1,AxisType.LOOP)
  sink=output.index(axis).store(source.index(axis*32+reduction).load()).end(reduction,axis).sink()
  proof=[]
  promoted,count=_parallelize(sink,aliases,proof)
  assert count==1,(count,proof)
  assert reduction in promoted.toposort()
  # Factored terms need exact affine cancellation, not heuristic simplification.
  summed=UOp(Ops.ADD,src=(weak,reduction))
  factored=UOp(Ops.ADD,src=(UOp(Ops.MUL,src=(summed,UOp.const(4))),
                           UOp(Ops.MUL,src=(reduction,UOp.const(-4)))))
  form=_integer_affine(factored)
  assert form==(0,{weak:4}),form
  large=UOp.range(256,9,AxisType.WEAK)
  assert _integer_affine(large.cast(dtypes.int8)) is None
  bound=UOp.const(16).cast(dtypes.int32).after(UOp(Ops.NOOP))
  ordered=UOp.range(bound,8,AxisType.WEAK)
  _,address,_=_pointer_access(output.index(ordered))
  assert ordered in _integer_affine(address)[1]
  proof=[]
  sink=output.index(ordered).store(source.index(ordered).load()).end(ordered).sink()
  _,count=_parallelize(sink,aliases,proof)
  assert count==1,(count,proof)
  from tinygrad.dtype import AddrSpace
  serial=UOp.range(4,11,AxisType.LOOP)
  private=UOp.placeholder((1,),dtypes.float32,slot=200,addrspace=AddrSpace.REG)
  initialized=private.index(0).store(serial.cast(dtypes.float32))
  ordered=UOp.range(UOp.const(16).cast(dtypes.int32).after(initialized),12,AxisType.WEAK)
  value=source.index(ordered).load()+private.after(initialized).index(0).load()
  sink=output.index(ordered).store(value).end(ordered,serial).sink()
  promoted,count=_parallelize(sink,aliases,[])
  nodes=list(promoted.toposort())
  assert count==1,count
  assert initialized in nodes
  assert sum(n.op is Ops.END for n in nodes)==sum(n.op is Ops.RANGE for n in nodes)
  return {'passed':True,'checks':17,'scope':'Android real UOp addressing, masked/residue alias independence and bijective contiguous workgroups'}


def inspect_model(root,native,session):
  from pathlib import Path
  from android_runtime.worker import configure
  configure(session,native)
  from android_runtime.gpu import configure as configure_gpu
  from android_runtime.gpu_artifact import load
  device=configure_gpu()
  artifact=load(Path(root)/'driving_tinygrad.pkl',out_of_band=True,inplace_states=True)
  sources={call.without_after.body.src[2].arg for call in artifact['run'].captured._linear.src
           if call.without_after.op is Ops.CALL and call.without_after.body.op is Ops.PROGRAM}
  for source in sorted(sources):
    try:device.cl_compiler.compile_cached(source)
    except Exception:
      (Path(root).parent/'gpu-compile-failure.cl').write_text(source)
      raise
  # Text-only source/access evidence for the measured serial 7x7 bottleneck.
  # Exporting a padded load's gate does not prove that it is safe to parallelize.
  exported=None
  for call in artifact['run'].captured._linear.src:
    call=call.without_after
    if call.op is not Ops.CALL or call.body.op is not Ops.PROGRAM:continue
    body=call.body;source=body.src[2].arg
    if 'void r_128_16_8_4_7_7(' not in source:continue
    if any(node.op is Ops.SPECIAL for node in body.src[0].toposort()):continue
    accesses=[]
    for node in body.src[0].toposort():
      if node.op not in (Ops.LOAD,Ops.STORE):continue
      access=_pointer_access(node.src[0])
      if access is None:continue
      slot,start,width=access
      accesses.append({'operation':node.op.name,'slot':slot,'start_min':start.vmin,'start_max':start.vmax,
                       'width':width,'address':str(start)[:4096],
                       'gate':str(node.src[2])[:8192] if node.op is Ops.LOAD and len(node.src)>2 else None})
    import json
    (Path(root).parent/'gpu-serial-kernel.cl').write_text(source)
    (Path(root).parent/'gpu-serial-accesses.json').write_text(json.dumps(accesses,indent=2)+'\n')
    exported={'kernel':'r_128_16_8_4_7_7','accesses':len(accesses),'scope':'static source only; no new independence claim'}
    break
  return {'passed':True,'scope':'retained model load/native CL compile and interval proofs only; no model execution',
          'compiled_sources':len(sources),
          'retarget':artifact['gpu_retarget'],'identity':device._android_cache_report,'serial_source_export':exported}


def check_state_alias(root,native,session):
  import ctypes
  import numpy as np
  from android_runtime.worker import configure
  configure(session,native)
  from android_runtime.gpu import configure as configure_gpu,_state_alias,upload
  device=configure_gpu()
  from tinygrad import Tensor
  from tinygrad.runtime.autogen import opencl as cl
  from tinygrad.runtime.ops_cl import check
  source=Tensor(np.arange(16,dtype=np.uint8),device='CL').realize()
  original=source._buffer().ensure_allocated()
  def references():
    value=ctypes.c_uint()
    check(cl.clGetMemObjectInfo(original._buf,cl.CL_MEM_REFERENCE_COUNT,ctypes.sizeof(value),ctypes.byref(value),None))
    return value.value
  device.synchronize();before=references()
  alias=_state_alias(source);buffer=alias._buffer().ensure_allocated()
  assert buffer is not original and buffer.options.nolru and buffer._android_state_owner is original
  assert references()==before+1
  np.testing.assert_array_equal(alias.numpy(),np.arange(16,dtype=np.uint8))
  upload(alias,np.full(16,17,dtype=np.uint8));device.synchronize()
  np.testing.assert_array_equal(source.numpy(),np.full(16,17,dtype=np.uint8))
  buffer.deallocate();device.synchronize()
  assert references()==before
  np.testing.assert_array_equal(source.numpy(),np.full(16,17,dtype=np.uint8))
  return {'passed':True,'checks':4,'scope':'CL state alias ownership/visibility/retain/release'}


def inspect_recurrent_copy(root,native,session):
  from android_runtime.worker import configure
  from android_runtime.gpu_artifact import compare_intermediates
  configure(session,native)
  return compare_intermediates(root,native,recurrent_probe=True)


def profile_retained(root,native,session):
  import ctypes
  import time
  from android_runtime.worker import configure
  configure(session,native)
  from android_runtime.gpu import RoadRunner
  runner=RoadRunner(root,1344,760,native)
  from tinygrad.runtime.ops_cl import CLProgram,check
  from tinygrad.runtime.autogen import opencl as cl
  original=CLProgram.__call__;samples=[]
  def measured(program,*args,**kwargs):
    name=ctypes.create_string_buffer(256)
    check(cl.clGetKernelInfo(program.kernel,cl.CL_KERNEL_FUNCTION_NAME,256,name,None))
    kwargs['wait']=True
    started=time.monotonic();duration=original(program,*args,**kwargs)
    samples.append({'name':name.value.decode(),'device_ms':duration*1000,'wall_ms':(time.monotonic()-started)*1000,
                    'global_size':kwargs.get('global_size'),'local_size':kwargs.get('local_size')})
    return duration
  CLProgram.__call__=measured
  try:
    runner.model_run(output_buffers=runner.outputs,**runner.inputs)
    runner.device.synchronize()
  finally:CLProgram.__call__=original
  return {'passed':True,'scope':'separate synthetic diagnostic with per-kernel waits; not a timed/live qualification',
          'samples':samples,'total_device_ms':sum(row['device_ms'] for row in samples),'identity':runner.report}


def inspect_fixture_frame(root,native,session):
  import hashlib
  import json
  import numpy as np
  from pathlib import Path
  from android_runtime.worker import configure
  configure(session,native)
  from android_runtime.gpu import configure as configure_gpu
  configure_gpu()
  import openpilot_android_vendor.helpers as helpers
  from android_runtime.gpu_artifact import compare_intermediates
  path=Path(root).parent/'gpu-frame-inputs.npz'
  metadata=json.loads(path.with_suffix('.json').read_text())
  if path.stat().st_size>32*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['sha256']:
    raise ValueError('Recorded fixture input integrity failure')
  if json.loads((Path(root)/'provenance.json').read_text())['model_sha256']!=metadata['model_sha256']:
    raise ValueError('Recorded fixture input model mismatch')
  original=helpers.allocate_inputs
  with np.load(path,allow_pickle=False) as fixture:
    def allocate(specs,initialize=None):
      def fill(arrays):
        if initialize is not None:initialize(arrays)
        for name,array in arrays.items():
          if name in fixture:
            value=fixture[name]
            if value.shape!=array.shape or value.dtype!=array.dtype:raise ValueError('Fixture contract mismatch: '+name)
            array[:]=value
      return original(specs,initialize=fill)
    helpers.allocate_inputs=allocate
    try:
      result=compare_intermediates(root,native)
      # The generic diagnostic's default input scope is synthetic zero. This
      # explicit recorded-fixture invocation supplies different initial data.
      for record in (Path(session)/'gpu-capture').glob('kernel-*.json'):
        data=json.loads(record.read_text());data['scope']=metadata['scope'];data['input_capture_sha256']=metadata['sha256']
        record.write_text(json.dumps(data,indent=2)+'\n')
    finally:helpers.allocate_inputs=original
  return {**result,'input_capture':metadata,'scope':'identical recorded fixture inputs; diagnostic, no live qualification'}


def inspect_cabin_tanh(root,native,session):
  import hashlib,json,math
  import numpy as np
  from pathlib import Path
  from java import jclass,jarray
  from android_runtime.worker import configure
  configure(session,native)
  from android_runtime.gpu import configure as configure_gpu,retained_renderer
  device=configure_gpu();device.renderers=[type(retained_renderer())];device.cached_renderer.clear()
  from tinygrad import Tensor
  from tinygrad.uop.ops import KernelInfo
  base=Path(root).parent;path=base/'cabin-cpu-nodes.onnx';meta=json.loads(path.with_suffix('.json').read_text())
  assert hashlib.sha256(path.read_bytes()).hexdigest()==meta['sha256']
  row=next(row for row in meta['activations'] if row['op']=='Tanh');input_name=row['inputs'][0]
  reference=jclass('ai.comma.openpilot.sim.DriverReference')
  values=reference.zeroIntermediates(str(path),jarray(jclass('java.lang.String'))(['outputs',row['name'],input_name]))
  np.testing.assert_allclose(np.asarray(values.get('outputs'),dtype=np.float32),
                             np.asarray(reference.zeroInput(str(Path(root)/'dmonitoring_model.onnx')),dtype=np.float32),rtol=1e-4,atol=1e-5)
  inputs=np.asarray(values.get(input_name),dtype=np.float32);expected=np.asarray(values.get(row['name']),dtype=np.float32)
  tensor=Tensor(inputs,device='CL').realize();count=inputs.size;local=64
  while count%local:local//=2
  samples={};saved={'inputs':inputs,'expected':expected}
  for fused in (False,True):
    def kernel(out,source):
      block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
      lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0');index=block*local+lane
      value=source.index(index).load()
      c=lambda value:UOp.const(value).cast(dtypes.float32)
      # Keep both diagnostic variants independent of the now-corrected
      # production helper. CUSTOM plus FP_CONTRACT OFF prevents the
      # separate-expression variant from becoming an explicit FMA.
      expression='fma({0},{1},{2})' if fused else '(({0})*({1})+({2}))'
      madd=lambda a,b,v:UOp(Ops.CUSTOM,src=(a,b,c(v)),arg=(expression,dtypes.float32))
      x=value.maximum(c(-9.)).minimum(c(9.));s=x*x
      p=madd(s,c(-2.76076847742355e-16),2.00018790482477e-13)
      for constant in (-8.60467152213735e-11,5.12229709037114e-08,1.48572235717979e-05,6.37261928875436e-04,4.89352455891786e-03):p=madd(p,s,constant)
      p=p*x;q=madd(s,c(1.19825839466702e-06),1.18534705686654e-04)
      for constant in (2.26843463243900e-03,4.89352518554385e-03):q=madd(q,s,constant)
      result=UOp(Ops.CUSTOM,src=(p,q),arg=('op_cpu_f32_div({0},{1})',dtypes.float32))
      return out.index(index).store(result).sink(arg=KernelInfo(name='mlas_tanh_contraction_probe',opts_to_apply=()))
    actual=Tensor.empty(count,dtype=dtypes.float32,device='CL').custom_kernel(tensor,fxn=kernel)[0].numpy()
    name='fused' if fused else 'separate';different=actual.view(np.uint32)!=expected.view(np.uint32)
    samples[name]={'bit_equal':not bool(np.any(different)),'different_values':int(np.count_nonzero(different)),
                   'maximum_absolute_difference':float(np.max(np.abs(actual-expected)))}
    if np.any(different):
      first=int(np.flatnonzero(different)[0]);samples[name]['first']={'index':first,'input':float(inputs[first]),'expected':float(expected[first]),'actual':float(actual[first])}
    saved[name]=actual
  np.savez(base/'cabin-tanh-oracle.npz',**saved)
  return {'passed':True,'scope':'identical complete CPU activation inputs from synthetic zero model; no model qualification',
          'diagnostic_sha256':meta['sha256'],'values':int(count),'input_sha256':hashlib.sha256(inputs.tobytes()).hexdigest(),'results':samples,
          'original_cpu_outputs_unchanged':True}
