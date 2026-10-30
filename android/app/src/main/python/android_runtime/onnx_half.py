"""Android CL lowering of measured ORT Conv and Tanh arithmetic.

Original graph inputs, weights and outputs are unchanged. Selection still
requires all original-model numerical gates; this is not a qualification.
"""


def _proven_f32_conv807(x_shape,w_shape,b_shape,auto_pad,dilations,group,kernel_shape,pads,strides):
  """Select only the complete Conv807 contract proven on ORT 1.23.2 ARM64.

  Later pointwise N=1 and grouped/depthwise convolutions have other MLAS
  dispatch conditions. A matching dtype alone cannot select this schedule.
  """
  def exact(value,expected):
    return isinstance(value,(tuple,list)) and all(type(v) is int for v in value) and tuple(value)==expected
  return (exact(x_shape,(1,32,120,180)) and exact(w_shape,(32,32,3,3)) and exact(b_shape,(32,))
          and auto_pad=='NOTSET' and type(group) is int and group==1
          and exact(dilations,(1,1)) and exact(pads,(1,1,1,1)) and exact(strides,(2,2))
          and (kernel_shape is None or exact(kernel_shape,(3,3))))


def _proven_f32_conv_followup(x_shape,w_shape,b_shape,auto_pad,dilations,group,kernel_shape,pads,strides):
  """Only the six follow-up shape contracts measured completely on Fold3.

  Four pointwise geometries cover the nine additional measured nodes; this
  does not infer a schedule for arbitrary channel counts or spatial sizes.
  """
  def exact(value,expected):
    return isinstance(value,(tuple,list)) and all(type(v) is int for v in value) and tuple(value)==expected
  if not (auto_pad=='NOTSET' and type(group) is int and group==1 and exact(dilations,(1,1))):return False
  pointwise=(any(exact(x_shape,x) and exact(w_shape,w) and exact(b_shape,b) for x,w,b in (
    ((1,32,60,90),(32,32,1,1),(32,)),
    ((1,96,30,45),(64,96,1,1),(64,)),
    ((1,192,15,23),(96,192,1,1),(96,)),
    ((1,96,15,23),(192,96,1,1),(192,)),
    ((1,384,15,23),(96,384,1,1),(96,))))
    and exact(pads,(0,0,0,0)) and exact(strides,(1,1)) and (kernel_shape is None or exact(kernel_shape,(1,1))))
  spatial=(exact(x_shape,(1,32,60,90)) and exact(w_shape,(96,32,3,3)) and exact(b_shape,(96,))
           and exact(pads,(1,1,1,1)) and exact(strides,(2,2)) and (kernel_shape is None or exact(kernel_shape,(3,3))))
  return pointwise or spatial


def _conv_f32_mlas_followup(X,W,B,*,pads,strides):
  """Measured pointwise/spatial FMA panels of min(128,K), then bias last.

  The original Conv807 helper below stays unchanged. Conv809 still has one
  32-term panel and Conv811 still has 128/128/32; four further measured
  pointwise contracts use K96, K192 or K384. Other geometries are rejected.
  """
  from tinygrad import Tensor
  from tinygrad.dtype import AddrSpace,dtypes
  from tinygrad.uop.ops import AxisType,KernelInfo,Ops,UOp
  if (X.dtype!=dtypes.float32 or W.dtype!=dtypes.float32 or B.dtype!=dtypes.float32
      or not _proven_f32_conv_followup(X.shape,W.shape,B.shape,'NOTSET',(1,1),1,None,pads,strides)):
    raise ValueError('Unproven FP32 Conv follow-up contract')
  _,channels,height,width=X.shape;cout,_,kh,kw=W.shape
  sy,sx=strides;pt,pl,pb,pr=pads
  oh=(height+pt+pb-kh)//sy+1;ow=(width+pl+pr-kw)//sx+1
  count=cout*oh*ow;k_total=channels*kh*kw;panel=min(128,k_total);local=64
  while count%local:local//=2
  def kernel(out,source,weight,bias):
    block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
    lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0');index=block*local+lane
    ox=index%ow;oy=(index//ow)%oh;channel=index//(oh*ow);parts=[]
    for slot,start in enumerate(range(0,k_total,panel)):
      acc=UOp.alloc((slot+1,),dtypes.float32,addrspace=AddrSpace.REG)
      initialized=acc.index(0).store(UOp.const(0.).cast(dtypes.float32));state=acc.after(initialized)
      reduction=UOp.range(min(panel,k_total-start),slot+1,AxisType.LOOP)
      term=reduction+start;ic=term//(kh*kw);ky=(term//kw)%kh;kx=term%kw
      iy=oy*sy-pt+ky;ix=ox*sx-pl+kx
      valid=(iy>=0)&(iy<height)&(ix>=0)&(ix<width)
      bounded_y=iy.maximum(0).minimum(height-1);bounded_x=ix.maximum(0).minimum(width-1)
      value=source.index((ic*height+bounded_y)*width+bounded_x).load()
      value=valid.where(value,UOp.const(0.).cast(dtypes.float32))
      w=weight.index(channel*k_total+term).load();previous=state.after(reduction).index(0).load()
      fused=UOp(Ops.CUSTOM,src=(value,w,previous),arg=('fma({0},{1},{2})',dtypes.float32))
      finished=state.index(0).store(fused).end(reduction);parts.append(state.after(finished).index(0).load())
    result=parts[0]
    for part in parts[1:]:result=UOp(Ops.CUSTOM,src=(result,part),arg=('({0} + {1})',dtypes.float32))
    result=UOp(Ops.CUSTOM,src=(result,bias.index(channel).load()),arg=('({0} + {1})',dtypes.float32))
    return out.index(index).store(result).sink(arg=KernelInfo(name='ort_mlas_f32_conv_'+str(cout)+'_'+str(k_total)+'_'+str(panel),opts_to_apply=()))
  return Tensor.empty(count,dtype=dtypes.float32,device=X.device).custom_kernel(
    X.flatten().contiguous(),W.flatten().contiguous(),B.contiguous(),fxn=kernel)[0].reshape(1,cout,oh,ow)


def _conv_f32_mlas128(X,W,B):
  """NCHW im2col C,kH,kW order, 128/128/32 FMA panels, bias last.

  Pinned MLAS convolve.cpp adds bias after SGEMM; sgemm.cpp and mlasi.h
  specify 128-term K panels here (N=5400,K=288). All 172800 Conv807 outputs
  matched original CPU bits in cabin-conv807-20261030T115405Z.
  """
  from tinygrad import Tensor
  from tinygrad.dtype import AddrSpace,dtypes
  from tinygrad.uop.ops import AxisType,KernelInfo,Ops,UOp
  count=32*60*90;local=64;k_total=32*3*3

  def kernel(out,source,weight,bias):
    block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
    lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0');index=block*local+lane
    ox=index%90;oy=(index//90)%60;channel=index//(60*90)
    parts=[]
    for slot,start in enumerate(range(0,k_total,128)):
      # Keep each completed partial in distinct scratch storage until the
      # rounded panel additions. Continuing one FMA chain changes CPU bits.
      acc=UOp.alloc((slot+1,),dtypes.float32,addrspace=AddrSpace.REG)
      initialized=acc.index(0).store(UOp.const(0.).cast(dtypes.float32));state=acc.after(initialized)
      reduction=UOp.range(min(128,k_total-start),slot+1,AxisType.LOOP)
      term=reduction+start;ic=term//9;ky=(term//3)%3;kx=term%3
      iy=oy*2-1+ky;ix=ox*2-1+kx
      valid=(iy>=0)&(iy<120)&(ix>=0)&(ix<180)
      bounded_y=iy.maximum(0).minimum(119);bounded_x=ix.maximum(0).minimum(179)
      value=source.index((ic*120+bounded_y)*180+bounded_x).load()
      value=valid.where(value,UOp.const(0.).cast(dtypes.float32))
      w=weight.index(channel*k_total+term).load();previous=state.after(reduction).index(0).load()
      fused=UOp(Ops.CUSTOM,src=(value,w,previous),arg=('fma({0},{1},{2})',dtypes.float32))
      finished=state.index(0).store(fused).end(reduction)
      parts.append(state.after(finished).index(0).load())
    result=parts[0]
    for part in parts[1:]:result=UOp(Ops.CUSTOM,src=(result,part),arg=('({0} + {1})',dtypes.float32))
    result=UOp(Ops.CUSTOM,src=(result,bias.index(channel).load()),arg=('({0} + {1})',dtypes.float32))
    return out.index(index).store(result).sink(arg=KernelInfo(name='ort_mlas_f32_conv807_k128',opts_to_apply=()))

  out=Tensor.empty(count,dtype=dtypes.float32,device=X.device)
  return out.custom_kernel(X.flatten().contiguous(),W.flatten().contiguous(),B.contiguous(),fxn=kernel)[0].reshape(1,32,60,90)


def _proven_f32_depthwise(x_shape,w_shape,b_shape,auto_pad,dilations,group,kernel_shape,pads,strides):
  """Only six complete depthwise contracts, measured across all eleven nodes."""
  def exact(value,expected):
    return isinstance(value,(tuple,list)) and all(type(v) is int for v in value) and tuple(value)==expected
  if not (auto_pad=='NOTSET' and type(group) is int and exact(dilations,(1,1))):return False
  return any(group==channels and exact(x_shape,(1,channels,height,width))
    and exact(w_shape,(channels,1,kernel,kernel)) and exact(b_shape,(channels,))
    and exact(strides,(stride,stride)) and exact(pads,(pad,pad,pad,pad))
    and (kernel_shape is None or exact(kernel_shape,(kernel,kernel)))
    for channels,height,width,kernel,stride,pad in (
      (192,30,45,5,2,2),(192,15,23,3,1,1),(576,15,23,3,2,1),
      (512,8,12,5,1,2),(384,8,12,5,1,2),(512,8,12,3,1,1)))


def _conv_f32_mlas_depthwise(X,W,B,*,pads,strides,group):
  """Pinned ARM64 MLAS SGEMV: zero, sequential kH/kW FMA, bias last.

  MlasConvOperation reaches the M=1, NoTrans SGEMV path for these groups;
  SgemvKernelNeon.S uses sequential FMLA and MlasActivation adds bias after.
  All 619968 outputs matched original ORT CPU bits on complete CPU inputs.
  """
  from tinygrad import Tensor
  from tinygrad.dtype import AddrSpace,dtypes
  from tinygrad.uop.ops import AxisType,KernelInfo,Ops,UOp
  if (X.dtype!=dtypes.float32 or W.dtype!=dtypes.float32 or B.dtype!=dtypes.float32
      or not _proven_f32_depthwise(X.shape,W.shape,B.shape,'NOTSET',(1,1),group,None,pads,strides)):
    raise ValueError('Unproven FP32 depthwise contract')
  _,channels,height,width=X.shape;_,_,kh,kw=W.shape
  sy,sx=strides;pt,pl,pb,pr=pads
  oh=(height+pt+pb-kh)//sy+1;ow=(width+pl+pr-kw)//sx+1;count=channels*oh*ow;local=64
  while count%local:local//=2
  def kernel(out,source,weight,bias):
    block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
    lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0');index=block*local+lane
    channel=index//(oh*ow);oy=(index//ow)%oh;ox=index%ow
    accumulator=UOp.alloc((1,),dtypes.float32,addrspace=AddrSpace.REG)
    initialized=accumulator.index(0).store(UOp.const(0.).cast(dtypes.float32));state=accumulator.after(initialized)
    reduction=UOp.range(kh*kw,1,AxisType.LOOP)
    ky=reduction//kw;kx=reduction%kw;iy=oy*sy-pt+ky;ix=ox*sx-pl+kx
    valid=(iy>=0)&(iy<height)&(ix>=0)&(ix<width)
    by=iy.maximum(0).minimum(height-1);bx=ix.maximum(0).minimum(width-1)
    x=source.index((channel*height+by)*width+bx).load();x=valid.where(x,UOp.const(0.).cast(dtypes.float32))
    w=weight.index(channel*kh*kw+reduction).load();previous=state.after(reduction).index(0).load()
    fused=UOp(Ops.CUSTOM,src=(x,w,previous),arg=('fma({0},{1},{2})',dtypes.float32))
    finished=state.index(0).store(fused).end(reduction);value=state.after(finished).index(0).load()
    value=UOp(Ops.CUSTOM,src=(value,bias.index(channel).load()),arg=('({0} + {1})',dtypes.float32))
    return out.index(index).store(value).sink(arg=KernelInfo(
      name='ort_mlas_f32_depthwise_'+str(channels)+'_'+str(kh)+'_'+str(count),opts_to_apply=()))
  return Tensor.empty(count,dtype=dtypes.float32,device=X.device).custom_kernel(
    X.flatten().contiguous(),W.flatten().contiguous(),B.contiguous(),fxn=kernel)[0].reshape(1,channels,oh,ow)


def install(runner):
  from tinygrad import Tensor
  from tinygrad.dtype import dtypes,AddrSpace
  from tinygrad.uop.ops import UOp,Ops,KernelInfo
  original=runner.onnx_ops['Conv']

  def conv(X,W,B=None,auto_pad='NOTSET',dilations=(1,1),group=1,kernel_shape=None,pads=(0,0,0,0),strides=(1,1)):
    if B is not None and X.dtype==W.dtype==B.dtype==dtypes.float32:
      if _proven_f32_conv807(X.shape,W.shape,B.shape,auto_pad,dilations,group,kernel_shape,pads,strides):
        return _conv_f32_mlas128(X,W,B)
      if _proven_f32_conv_followup(X.shape,W.shape,B.shape,auto_pad,dilations,group,kernel_shape,pads,strides):
        return _conv_f32_mlas_followup(X,W,B,pads=pads,strides=strides)
      if _proven_f32_depthwise(X.shape,W.shape,B.shape,auto_pad,dilations,group,kernel_shape,pads,strides):
        return _conv_f32_mlas_depthwise(X,W,B,pads=pads,strides=strides,group=group)
    if X.dtype!=dtypes.half or W.dtype!=dtypes.half or B is None or X.ndim!=4 or auto_pad!='NOTSET':
      return original(X,W,B,auto_pad=auto_pad,dilations=dilations,group=group,kernel_shape=kernel_shape,pads=pads,strides=strides)
    n,cin,height,width=X.shape;cout,channels,kh,kw=W.shape
    if cin!=channels*group or cout%group:raise ValueError('Invalid retained half Conv groups')
    sy,sx=strides;dy,dx=dilations;pt,pl,pb,pr=pads
    oh=(height+pt+pb-dy*(kh-1)-1)//sy+1;ow=(width+pl+pr-dx*(kw-1)-1)//sx+1
    if min(oh,ow)<=0:raise ValueError('Invalid retained half Conv output')
    count=n*cout*oh*ow;local=64
    while count%local:local//=2

    def kernel(out,source,weight,bias):
      block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
      lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0')
      index=block*local+lane
      ox=index%ow;oy=(index//ow)%oh;channel=(index//(ow*oh))%cout;batch=index//(ow*oh*cout)
      acc=UOp.alloc((1,),dtypes.float32,addrspace=AddrSpace.REG)
      initialized=acc.index(0).store(bias.flatten().index(channel).load().cast(dtypes.float32))
      acc_i=acc.after(initialized)
      from tinygrad.uop.ops import AxisType
      reduction=UOp.range(channels*kh*kw,1,AxisType.LOOP)
      # ORT 1.23.2 FusedConvFp16 transposes NCHW to NHWC and packs
      # filters as (kH,kW,C/group) x M before its half GEMM. Keep that
      # reduction order: half FMA is not associative across channels/taps.
      ky=reduction//(kw*channels);kx=(reduction//channels)%kw;local_ic=reduction%channels
      ic=local_ic+(channel//(cout//group))*channels
      iy=oy*sy-pt+ky*dy;ix=ox*sx-pl+kx*dx
      valid=(iy>=0)&(iy<height)&(ix>=0)&(ix<width)
      iy=iy.maximum(0).minimum(height-1);ix=ix.maximum(0).minimum(width-1)
      value=source.flatten().index(((batch*cin+ic)*height+iy)*width+ix).load().cast(dtypes.float32)
      value=valid.where(value,UOp.const(0.).cast(dtypes.float32))
      w=weight.flatten().index(((channel*channels+local_ic)*kh+ky)*kw+kx).load().cast(dtypes.float32)
      fused=UOp(Ops.CUSTOM,src=(value,w,acc_i.after(reduction).index(0).load()),
                arg=('op_cpu_half_fma({0},{1},{2})',dtypes.float32))
      updated=acc_i.index(0).store(fused).end(reduction)
      result=acc_i.after(updated).index(0).load().cast(dtypes.half)
      return out.flatten().index(index).store(result).sink(arg=KernelInfo(name='ort_native_half_conv_bias_first',opts_to_apply=()))

    out=Tensor.empty(n,cout,oh,ow,dtype=dtypes.half,device=X.device)
    return out.custom_kernel(X.contiguous(),W.contiguous(),B.contiguous(),fxn=kernel)[0]

  runner.onnx_ops={**runner.onnx_ops,'Conv':conv}
  original_tanh=runner.onnx_ops['Tanh']
  def tanh(X):
    if X.dtype!=dtypes.float32:return original_tanh(X)
    count=X.numel();local=64
    while count%local:local//=2
    def kernel(out,source):
      block=UOp(Ops.SPECIAL,src=(UOp.const(count//local),),arg='gidx0')
      lane=UOp(Ops.SPECIAL,src=(UOp.const(local),),arg='lidx0');index=block*local+lane
      value=source.flatten().index(index).load()
      result=UOp(Ops.CUSTOM,src=(value,),arg=('op_ort_tanh_f32({0})',dtypes.float32))
      return out.flatten().index(index).store(result).sink(arg=KernelInfo(name='ort_mlas_tanh_f32',opts_to_apply=()))
    out=Tensor.empty(*X.shape,dtype=X.dtype,device=X.device)
    return out.custom_kernel(X.contiguous(),fxn=kernel)[0]
  runner.onnx_ops={**runner.onnx_ops,'Tanh':tanh}


def materialize_operators(runner):
  """Diagnostic candidate: explicit CL storage between original ONNX nodes.

  This isolates lazy graph/fusion and custom-kernel storage lifetimes. It changes
  no operator, weight, dtype or tolerance; full-model checks remain mandatory.
  """
  from tinygrad import Tensor
  select=runner._select_op
  def realize(value):
    if isinstance(value,Tensor):return value.to('CL',force=True).realize()
    if isinstance(value,tuple):return tuple(realize(item) for item in value)
    if isinstance(value,list):return [realize(item) for item in value]
    return value
  def ordered(op,opset):
    operation=select(op,opset)
    def execute(*args,**kwargs):return realize(operation(*args,**kwargs))
    return execute
  runner._select_op=ordered
