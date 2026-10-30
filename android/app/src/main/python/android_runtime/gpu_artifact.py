"""Retarget trusted packaged CPU TinyJit artifacts to Android OpenCL.

Loading never opens the CPU backend. CPU arena views are passed as full OpenCL
buffers and their byte offsets move into kernel pointer expressions. Retained
lowered arithmetic is rendered again; CPU source and executable bytes are unused.
This module is called only after gpu.configure has checked the Android runtime.
"""
from dataclasses import replace
import io
import hashlib
from pathlib import Path
import pickle
import struct
import time


class _StoredBuffer:
  """Inert pickle reconstruction, before any device allocation is permitted."""
  def __init__(self, device, nbytes, opaque=None, options=None, initial_value=None,
               base=None, offset=0, preallocate=False, **unused):
    self.device, self.nbytes, self.base, self.offset = device, nbytes, base, offset
    self.data = initial_value if initial_value is not None else opaque
    self.options, self.preallocate = options, preallocate


class _ArtifactUnpickler(pickle.Unpickler):
  def __init__(self, stream, weights=None, weights_offset=0):
    super().__init__(stream)
    self.weights, self.weights_offset, self.buffers = weights, weights_offset, {}

  def find_class(self, module, name):
    if (module, name) == ("tinygrad.device", "Buffer"):
      return _StoredBuffer
    # Artifacts are application assets verified by their package manifest, never
    # camera/network input. This is a device remapper, not an untrusted-pickle API.
    return super().find_class(module, name)

  def persistent_load(self, pid):
    if self.weights is None or not isinstance(pid, tuple) or len(pid) != 2:
      raise ValueError("Invalid out-of-band GPU artifact buffer")
    nbytes, offset = pid
    if not all(isinstance(x, int) and x >= 0 for x in pid):
      raise ValueError("Invalid GPU weight range")
    if pid not in self.buffers:
      self.weights.seek(self.weights_offset + offset)
      data = self.weights.read(nbytes)
      if len(data) != nbytes:
        raise ValueError("Truncated GPU weight data")
      self.buffers[pid] = _StoredBuffer("CPU", nbytes, initial_value=data)
    return self.buffers[pid]


def _read(path, out_of_band):
  with Path(path).open("rb") as stream:
    if not out_of_band:
      return _ArtifactUnpickler(stream).load()
    header = stream.read(8)
    if len(header) != 8:
      raise ValueError("Truncated GPU artifact header")
    size = struct.unpack("<q", header)[0]
    if not 0 < size <= 32 * 1024 * 1024:
      raise ValueError("Invalid GPU artifact opcode size")
    opcodes = stream.read(size)
    if len(opcodes) != size:
      raise ValueError("Truncated GPU artifact opcodes")
    return _ArtifactUnpickler(io.BytesIO(opcodes), stream, 8 + size).load()


def _pointer_access(node):
  """Return (parameter slot, byte start expression, access width)."""
  from tinygrad.uop.ops import Ops, UOp
  from tinygrad.dtype import AddrSpace
  if node.op is Ops.CAST:
    node = node.src[0]
  if node.op not in (Ops.INDEX, Ops.SHRINK) or len(node.src) < 2:
    return None
  if node.op is Ops.SHRINK:
    if len(node.marg)!=1:return None
    element_start=node.marg[0][0]
  else:
    element_start=node.src[1]
  pointer, start = node.src[0], element_start * node.src[0].dtype.itemsize
  width = node.max_numel() * node.dtype.itemsize
  while pointer.op in (Ops.SHRINK, Ops.BITCAST):
    if pointer.op is Ops.SHRINK:
      if len(pointer.marg)!=1:return None
      start = start + pointer.marg[0][0] * pointer.src[0].dtype.itemsize
    pointer = pointer.src[0]
  if pointer.op is not Ops.PARAM or pointer.addrspace is not AddrSpace.GLOBAL:
    return None
  # Keep the sink's exact RANGE objects. Heuristic simplification can rebuild
  # a range after stripping ordering wrappers from its bound, breaking the
  # identity used to prove and replace that loop during parallelization.
  return pointer.arg.slot, start if isinstance(start,UOp) else UOp.const(start), width


def _integer_affine(node,cache=None):
  """Prove affine integer addresses without relying on heuristic cancellation.

  AFTER controls ordering but does not change its first source's value. Typed
  arithmetic is accepted only when its complete interval cannot overflow.
  Nonlinear, floating, wrapping and unsupported expressions remain serial.
  """
  from tinygrad.uop.ops import Ops
  from tinygrad.dtype import dtypes
  from android_runtime.gpu_diagnostic import affine_interval
  cache={} if cache is None else cache
  if node in cache:return cache[node]
  cache[node]=None
  if not dtypes.is_int(node.dtype):return None
  if node.op is Ops.CONST:
    result=(node.arg,{}) if type(node.arg) is int else None
  elif node.op in (Ops.RANGE,Ops.SPECIAL):result=(0,{node:1})
  elif node.op in (Ops.CAST,Ops.AFTER):result=_integer_affine(node.src[0],cache)
  elif node.op is Ops.NEG:
    value=_integer_affine(node.src[0],cache)
    result=None if value is None else (-value[0],{axis:-v for axis,v in value[1].items()})
  elif node.op in (Ops.ADD,Ops.SUB,Ops.MUL,Ops.SHL,Ops.CDIV,Ops.CMOD,Ops.FLOORDIV,Ops.FLOORMOD):
    left,right=(_integer_affine(source,cache) for source in node.src[:2])
    if left is None or right is None:return None
    a,aa=left;b,bb=right
    if node.op in (Ops.ADD,Ops.SUB):
      if node.op is Ops.SUB:b=-b;bb={axis:-value for axis,value in bb.items()}
      terms=aa.copy()
      for axis,value in bb.items():terms[axis]=terms.get(axis,0)+value
      result=(a+b,{axis:value for axis,value in terms.items() if value})
    elif node.op is Ops.MUL:
      if aa and bb:return None
      constant,other=(b,left) if not bb else (a,right)
      result=(other[0]*constant,{axis:value*constant for axis,value in other[1].items()})
    elif bb:return None
    elif node.op is Ops.SHL:
      if not 0<=b<32:return None
      result=(a*(1<<b),{axis:value*(1<<b) for axis,value in aa.items()})
    elif b>0 and a%b==0 and all(value%b==0 for value in aa.values()):
      result=(a//b,{axis:value//b for axis,value in aa.items()}) if node.op in (Ops.CDIV,Ops.FLOORDIV) else (0,{})
    else:return None
  else:return None
  if result is not None and node.dtype not in dtypes.weaks:
    bounds={axis:(axis.vmin,axis.vmax) for axis in result[1]}
    lo,hi=affine_interval(result,bounds)
    if lo<node.dtype.min or hi>node.dtype.max:return None
  cache[node]=result
  return result


def _masked_read_interval(start,gate):
  """Prove masked address bounds using only non-overflowing integer forms."""
  from tinygrad.uop.ops import Ops
  from tinygrad.dtype import dtypes
  from android_runtime.gpu_diagnostic import gated_affine_interval
  bounds={};nodes=0
  def affine(node):
    form=_integer_affine(node)
    if form is None:raise ValueError('Non-affine masked read')
    for axis in form[1]:bounds[axis]=(axis.vmin,axis.vmax)
    return form
  def predicate(node,depth=0):
    nonlocal nodes
    nodes+=1
    if nodes>128 or depth>32 or node.dtype!=dtypes.bool:raise ValueError('Unproven load mask')
    if node.op is Ops.AFTER:return predicate(node.src[0],depth+1)
    if node.op is Ops.CONST and type(node.arg) is bool:return node.arg
    if node.op in (Ops.AND,Ops.OR):
      return ('and' if node.op is Ops.AND else 'or',*(predicate(n,depth+1) for n in node.src))
    if node.op in (Ops.CMPLT,Ops.CMPEQ,Ops.CMPNE):
      return ({Ops.CMPLT:'lt',Ops.CMPEQ:'eq',Ops.CMPNE:'ne'}[node.op],*(affine(n) for n in node.src))
    raise ValueError('Unsupported load mask')
  try:
    form=affine(start);condition=predicate(gate)
    return gated_affine_interval(form,bounds,condition)
  except (ValueError,KeyError,TypeError):return None


def _parallelize(sink, aliases, diagnostic=None, masked_reads=None):
  """Promote only output loops whose disjoint writes can be proven by intervals.

  Reduction loops fail the stride test. An overlapping alias additionally needs
  a proof that every read/write belongs to the same worker's byte residues.
  A failed proof retains the serial loop and all original arithmetic.
  """
  from tinygrad.uop.ops import Ops, UOp, AxisType, graph_rewrite
  from tinygrad.dtype import AddrSpace
  from tinygrad.codegen.late.linearizer import pm_split_ends
  # The artifact already contains late CPU loop-order edges on RANGE bounds.
  # Remove those edges before changing loops; otherwise a promoted SPECIAL
  # inherits stale serial ranges, and END expansion can close a loop twice.
  # Data dependencies and arithmetic are retained. load() rebuilds only CFG.
  ordering={node:node.replace(src=(node.src[0].without_after,)) for node in sink.toposort()
            if node.op is Ops.RANGE and node.src[0].op is Ops.AFTER}
  if ordering:sink=sink.substitute(ordering,walk=True)
  nodes = list(sink.toposort())
  for node in nodes:
    if node.op in (Ops.STORE,Ops.LOAD) and node.src[0].addrspace is AddrSpace.GLOBAL:
      if _pointer_access(node.src[0]) is None:
        if diagnostic is not None:diagnostic.append({'reason':'unproven_global_access'})
        return sink,0
  stores = [_pointer_access(x.src[0]) for x in nodes if x.op is Ops.STORE]
  stores = [x for x in stores if x is not None]
  loads=[]
  for node in nodes:
    if node.op is not Ops.LOAD or (access:=_pointer_access(node.src[0])) is None:continue
    slot,start,width=access;interval=(start.vmin,start.vmax)
    if len(node.src)==3:
      masked=_masked_read_interval(start,node.src[2])
      if masked==():continue
      if masked is not None and interval[0]<=masked[0]<=masked[1]<=interval[1]:
        if masked!=interval and masked_reads is not None:
          masked_reads.append({'slot':slot,'width':width,'original':list(interval),'masked':list(masked)})
        interval=masked
    loads.append((slot,start,width,interval))
  if not stores:
    if diagnostic is not None:diagnostic.append({'reason':'no_global_store'})
    return sink, 0
  # Disjoint intervals need no further alias argument. For overlapping state
  # arenas, candidate axes must also prove no dependency between workers.
  overlapping={};alias_evidence=[]
  for slot, start, width in stores:
    for read_slot, read_start, read_width,(read_lo,read_hi) in loads:
      if aliases.get(slot) is aliases.get(read_slot):
        if not (start.vmax + width <= read_lo or read_hi + read_width <= start.vmin):
          overlapping[aliases[slot]]=None
          alias_evidence.append({'reason':'overlapping_arena','write':[slot,start.vmin,start.vmax,width],
                                 'read':[read_slot,read_lo,read_hi,read_width]})
  selected = {}
  rejection=None;candidate_rejections=[]
  from android_runtime.gpu_diagnostic import affine_interval,residue_disjoint
  forms=[_integer_affine(start) for _,start,_ in stores]
  if any(form is None for form in forms):
    if diagnostic is not None:diagnostic.append({'reason':'unproven_integer_address'})
    return sink,0
  bounds={axis:(axis.vmin,axis.vmax) for form in forms for axis in form[1]}
  shared={alias:[] for alias in overlapping}
  for (slot,_,width),form in zip(stores,forms):
    if aliases[slot] in shared:shared[aliases[slot]].append((form,width))
  for slot,start,width,_ in loads:
    if aliases[slot] not in shared:continue
    form=_integer_affine(start)
    if form is None:
      if diagnostic is not None:diagnostic.append({**alias_evidence[0],'coordinate_proof':'non_affine_alias_read'})
      return sink,0
    shared[aliases[slot]].append((form,width))
    for axis in form[1]:bounds[axis]=(axis.vmin,axis.vmax)
  # Retained CPU artifacts carry WEAK output ranges as ordinary C loops. Both
  # forms require exactly the same interval/dependency proof before promotion.
  candidates = [x for x in nodes if x.op is Ops.RANGE and x.axis_type in (AxisType.LOOP,AxisType.WEAK) and x.vmax > 0]
  for _ in range(3):
    promoted = False
    for axis in candidates:
      if axis in selected:
        continue
      regions = {}
      valid = True
      for (slot, start, width),form in zip(stores,forms):
        lower,upper=affine_interval(form,bounds,(*selected,axis))
        stride=form[1].get(axis,0)
        if not isinstance(stride, int) or stride <= 0:
          rejection={'reason':'nonconstant_stride','stride':str(stride)[:256],'axis':str(axis)[:128]}
          valid = False
          break
        alias = aliases[slot]
        if alias not in regions:
          regions[alias] = (lower, upper + width, stride)
        else:
          lo, hi, previous_stride = regions[alias]
          if stride != previous_stride:
            valid = False
            break
          regions[alias] = (min(lo, lower), max(hi, upper + width), stride)
      modular={}
      for (slot,_,width),form in zip(stores,forms):modular.setdefault(aliases[slot],[]).append((form,width))
      disjoint=valid and (all(hi-lo<=stride for lo,hi,stride in regions.values()) or
                         all(residue_disjoint(writes,bounds,axis,tuple(selected)) for writes in modular.values()))
      if disjoint and not all(residue_disjoint(accesses,bounds,axis,tuple(selected)) for accesses in shared.values()):
        disjoint=False;valid=False;rejection={**alias_evidence[0],'coordinate_proof':'cross_worker_alias_not_proven'}
      if disjoint:
        selected[axis] = UOp(Ops.SPECIAL, src=axis.src, arg=f"gidx{len(selected)}")
        promoted = True
        break
      if valid:rejection={'reason':'write_intervals_overlap','intervals':list(regions.values())[:4]}
      if len(candidate_rejections)<8:
        candidate_rejections.append({'axis':str(axis.arg),'extent':axis.vmax+1,'failure':rejection})
    if not promoted:
      break
  if selected:
    sink = graph_rewrite(sink.substitute(selected, walk=True), pm_split_ends)
  elif diagnostic is not None:diagnostic.append({**(rejection or {'reason':'no_loop_candidate','stores':len(stores)}),
                                                'candidates':candidate_rejections})
  return sink, len(selected)


def _pack_workgroup(sink):
  """Flatten only already independent axes in contiguous output order.

  Mixed-radix coordinates enumerate the original Cartesian product exactly.
  There are no extra/padded threads, shared memory or changed reductions.
  """
  from tinygrad.uop.ops import Ops,UOp
  from tinygrad.dtype import AddrSpace,dtypes
  from android_runtime.gpu_diagnostic import linear_workgroup
  nodes=list(sink.toposort())
  if any(n.op is Ops.BARRIER or n.addrspace is AddrSpace.LOCAL or
         (n.op is Ops.SPECIAL and not str(n.arg).startswith('gidx')) for n in nodes):return sink,None
  candidates=[];original={}
  forms=[_integer_affine(access[1]) for n in nodes if n.op is Ops.STORE and (access:=_pointer_access(n.src[0])) is not None]
  if not forms or any(form is None for form in forms):return sink,None
  for node in nodes:
    if node.op is not Ops.SPECIAL or node.arg not in ('gidx0','gidx1','gidx2'):continue
    bound=node.src[0]
    if type(bound.vmin) is not int or bound.vmin != bound.vmax:return sink,None
    strides=[form[1].get(node,0) for form in forms]
    if min(strides)<=0:return sink,None
    dimension=int(node.arg[-1]);original[dimension]=node
    candidates.append((dimension,bound.vmin,max(strides)))
  if not candidates:return sink,None
  try:shape=linear_workgroup(candidates)
  except ValueError:return sink,None
  if shape['lanes']==1:return sink,None
  group=UOp(Ops.SPECIAL,src=(UOp.const(shape['groups']).cast(dtypes.int32),),arg='gidx0')
  lane=UOp(Ops.SPECIAL,src=(UOp.const(shape['lanes']).cast(dtypes.int32),),arg='lidx0');flat=group*shape['lanes']+lane
  temporaries={node:UOp(Ops.CUSTOM,arg=('android_flat_axis_'+str(dimension),node.dtype)) for dimension,node in original.items()}
  mapped={}
  for i,row in enumerate(shape['axes']):
    coordinate=flat if row['divisor']==1 else UOp(Ops.CDIV,src=(flat,UOp.const(row['divisor'])))
    if i!=len(shape['axes'])-1:coordinate=UOp(Ops.CMOD,src=(coordinate,UOp.const(row['extent'])))
    mapped[temporaries[original[row['dimension']]]]=coordinate
  # Two substitutions avoid rewriting the new gidx0 when it happens to be
  # identical to an old axis (same bound/name in UOp's interned graph).
  return sink.substitute(temporaries,walk=True).substitute(mapped,walk=True),shape


def load(path, *, out_of_band=False, parallel=True, inplace_states=False):
  """Load an application-owned artifact and compile it for the current CL GPU."""
  from android_runtime.gpu import configure, retained_renderer
  device = configure()
  renderer = retained_renderer()
  from tinygrad.codegen import to_program
  from tinygrad.device import Buffer
  from tinygrad.dtype import AddrSpace, dtypes
  from tinygrad.engine.realize import lower_and_compile
  from tinygrad.nn.state import get_parameters
  from tinygrad.uop.ops import Ops, UOp, ParamArg, ProgramInfo, KernelInfo, AxisType, graph_rewrite
  from tinygrad.uop.weak import pm_cast_const
  artifact = _read(path, out_of_band)
  captured = artifact["run"].captured
  alias_groups={};state_aliases={}
  if inplace_states:
    names=sorted(artifact['input_specs'])
    if captured.expected_names!=names or len(captured.expected_input_info)!=len(names)+len(artifact['output_specs']):
      raise ValueError('Unverified recurrent-state argument ABI')
    output_names=list(artifact['output_specs'])
    for name in names:
      next_name='next_'+name
      if next_name not in artifact['output_specs']:continue
      if artifact['input_specs'][name][:2]!=artifact['output_specs'][next_name][:2]:
        raise ValueError('Recurrent alias shape/type mismatch')
      token=object();a=names.index(name);b=len(names)+output_names.index(next_name)
      alias_groups[a]=alias_groups[b]=token
      state_aliases[name]={'next':next_name,'argument_slots':[a,b]}
  storage, mapped = {}, {}

  def root_storage(buffer):
    offset = 0
    while buffer.base is not None:
      offset += buffer.offset
      buffer = buffer.base
    if buffer not in storage:
      if buffer.device not in ("CPU", "CPU:CLANG"):
        raise ValueError(f"Unexpected artifact buffer device {buffer.device!r}")
      value = None if buffer.data is None else bytes(buffer.data)
      if value is not None and len(value) != buffer.nbytes:
        raise ValueError("GPU artifact buffer byte count differs")
      storage[buffer] = Buffer("CL", buffer.nbytes, initial_value=value)
    return storage[buffer], offset

  def map_graph(graph):
    replacements = {}
    for node in graph.toposort():
      if node in mapped:
        replacements[node] = mapped[node]
      elif isinstance(node.arg, ParamArg) and node.arg.device is not None:
        if node.arg.device == "CL":
          continue
        if node.arg.device not in ("CPU", "CPU:CLANG"):
          raise ValueError(f"Unexpected artifact graph device {node.arg.device!r}")
        if node.op is Ops.BUFFER and node.arg.buffer is not None:
          buffer, offset = root_storage(node.arg.buffer)
          result = UOp.from_buffer(buffer, node.dtype)
          if offset or result.max_numel() != node.max_numel():
            if offset % node.dtype.itemsize:
              raise ValueError("Misaligned artifact buffer view")
            start = offset // node.dtype.itemsize
            result = result[start:start + node.max_numel()]
        else:
          result = node.replace(arg=replace(node.arg, device="CL"))
        mapped[node] = replacements[node] = result
    return graph.substitute(replacements, walk=True, enter_calls=True)

  calls, argument_views, parallel_kernels, total_axes, copies = {}, {}, 0, 0, 0
  parallel_rejections=[];workgroups=[];masked_reads=[]
  original_linear = captured._linear
  for call in captured._linear.toposort():
    if call.op is not Ops.CALL or call.body.op not in (Ops.PROGRAM, Ops.STORE):
      continue
    original = call.body
    is_copy = original.op is Ops.STORE
    if not is_copy and (original.arg.target.device != "CPU" or original.src[-1].op is Ops.BINARY):
      raise ValueError("Expected a retained retargetable CPU program")
    sink = original.src[0] if not is_copy else None
    args, offsets, aliases = [], {}, {}
    for slot, argument in enumerate(call.src[1:]):
      # Resolve while metadata still says CPU: CL intentionally refuses host
      # subbuffer views. A bitcast changes interpretation, never byte offset.
      if argument.op in (Ops.PARAM, Ops.BUFFER):
        base, element_offset = argument, 0
      else:
        view = argument.contiguous_view()
        if view is None:
          raise ValueError("Noncontiguous argument in retained GPU artifact")
        base, element_offset = view
      byte_offset = element_offset * base.dtype.itemsize
      args.append(map_graph(base).bitcast(argument.dtype))
      offsets[slot]=byte_offset
      aliases[slot]=alias_groups.get(base.arg.slot,base) if base.op is Ops.PARAM else base
    argument_views[call] = [(offsets[slot], argument.nbytes()) for slot, argument in enumerate(call.src[1:])]
    if is_copy:
      if len(args) != 2 or call.src[1].nbytes() != call.src[2].nbytes():
        raise ValueError("Unexpected bulk transfer in retained GPU graph")
      args = [argument.bitcast(dtypes.uint8) for argument in args]
      parameters = [UOp.param(slot, dtypes.uint8, argument.nbytes(), "CL") for slot, argument in enumerate(args)]
      axis = UOp.range(call.src[1].nbytes(), 0, AxisType.GLOBAL)
      sink = parameters[0].index(axis + offsets[0]).store(parameters[1].index(axis + offsets[1]).load()).end(axis).sink(
        arg=KernelInfo(name="android_retained_copy"))
      calls[call] = call.replace(src=(sink, *args), arg=replace(call.arg, aux=None))
      copies += 1
      continue
    params = {}
    for parameter in sink.toposort():
      if parameter.op is Ops.PARAM and parameter.addrspace is AddrSpace.GLOBAL:
        slot = parameter.arg.slot
        byte_offset = offsets[slot]
        if byte_offset % parameter.dtype.itemsize:
          raise ValueError("Misaligned GPU kernel argument offset")
        full = UOp.param(slot, parameter.dtype, args[slot].nbytes() // parameter.dtype.itemsize, "CL")
        start = byte_offset // parameter.dtype.itemsize
        params[parameter] = full[start:start + parameter.max_numel()] if start or full.shape != parameter.shape else full
    sink = sink.substitute(params, walk=True)
    axes = 0
    if parallel:
      rejected_before=len(parallel_rejections)
      masked_before=len(masked_reads)
      sink, axes = _parallelize(sink, aliases, parallel_rejections,masked_reads)
      for row in masked_reads[masked_before:]:row['kernel']=original.src[0].arg.name
      for row in parallel_rejections[rejected_before:]:row['kernel']=original.src[0].arg.name
      if axes:
        sink,packed=_pack_workgroup(sink)
        if packed is not None:workgroups.append({'kernel':original.src[0].arg.name,**packed})
    parallel_kernels += bool(axes)
    total_axes += axes
    # Pointer rebasing and SPECIAL promotion introduce fresh shape/index
    # constants after the original lowering boundary. The renderer requires
    # committed CAST(CONST) operands, including the SHRINK extent.
    sink = graph_rewrite(sink, pm_cast_const, walk=True)
    if parallel:
      from tinygrad.codegen.late.linearizer import CFGContext,pm_add_control_flow
      sink=graph_rewrite(sink,pm_add_control_flow,ctx=CFGContext(sink),bottom_up=True)
    # Keep lowered arithmetic exactly as captured. Re-running optimization on
    # this already lowered AST can change reductions and is unnecessary.
    program = UOp(Ops.PROGRAM, src=(sink,), arg=ProgramInfo.from_sink(sink, renderer.target))
    calls[call] = call.replace(src=(program, *args), arg=replace(call.arg, aux=None))
  if not calls:
    raise ValueError("No retained GPU kernels found")
  started = time.monotonic()
  captured._linear = map_graph(captured._linear.substitute(calls, walk=True))
  compiled = {call: call.replace(src=(to_program(call.body, renderer), *call.src[1:]))
              for call in captured._linear.toposort() if call.op is Ops.CALL and call.body.op is Ops.PROGRAM}
  captured._linear = lower_and_compile(captured._linear.substitute(compiled, walk=True))
  for tensor in get_parameters(captured.ret):
    tensor.uop = map_graph(tensor.uop)
  captured.expected_input_info = [(view, variables, dtype, "CL") for view, variables, dtype, _ in captured.expected_input_info]
  for cache in ("linear", "_jit_bufs", "_symbolic_ret"):
    captured.__dict__.pop(cache, None)
  for key in ("input_specs", "output_specs"):
    if key in artifact:
      artifact[key] = {name: (shape, dtype, "CL") for name, (shape, dtype, _) in artifact[key].items()}
  artifact["gpu_retarget"] = {"kernels": len(calls), "parallel_kernels": parallel_kernels, "parallel_axes": total_axes,
                              "copy_kernels": copies, "compile_seconds": time.monotonic() - started, "weight_buffers": len(storage),
                              "scalar_half_semantics": "retained_clang_fp32_promotion_software_rne_and_subnormals"}
  from collections import Counter
  artifact['gpu_retarget']['parallel_rejections']={'counts':dict(Counter(row['reason'] for row in parallel_rejections)),
                                                  'samples':parallel_rejections[:8],'kernels':parallel_rejections}
  artifact['gpu_retarget']['workgroups']={'packed_kernels':len(workgroups),'kernels':workgroups}
  artifact['gpu_retarget']['masked_read_proofs']={'count':len(masked_reads),'reads':masked_reads}
  artifact['gpu_retarget']['inplace_state_aliases']=state_aliases
  artifact["_gpu_argument_views"] = [argument_views.get(call) for call in original_linear.src]
  artifact["_gpu_scratch_buffers"] = [mapped_buffer for source, mapped_buffer in storage.items() if source.data is None]
  return artifact


def _trace_kernel72(device,call,arguments,views,inputs,expected,row,capture_root):
  """Instrument the actual retained GPU source, never a different dot kernel."""
  import re
  import numpy as np
  import ctypes
  from tinygrad.device import Buffer,TinyELF
  from tinygrad.dtype import dtypes
  from tinygrad.runtime.autogen import opencl as cl
  from tinygrad.runtime.ops_cl import check
  from android_runtime.gpu_diagnostic import half_dot,checked_view,digest
  source=call.body.src[2].arg
  if 'float buf0[1];' not in source or not re.search(r'for \(int Lidx1 = 0; Lidx1 < 512;',source):
    return {"available":False,"reason":"unexpected_retained_reduction_shape"}
  if set(inputs)!={1,2,3} or [len(inputs[k]) for k in (1,2,3)]!=[4096,2097152,1024]:
    return {"available":False,"reason":"unexpected_retained_argument_views"}
  match=re.search(r'__kernel void (\w+)\(([^)]*)\)',source)
  if match is None:raise ValueError("Missing retained kernel declaration")
  source=source[:match.start()]+f'__kernel void op_accumulator_probe({match.group(2)}, __global float* op_accumulator)'+source[match.end():]
  source,count=re.subn(r'(^\s*float val2 =)',r'    op_accumulator[Lidx1] = *(buf0+0);\n\1',source,flags=re.MULTILINE)
  if count!=1:raise ValueError("Cannot identify unique pre-round accumulator boundary")
  trace=Buffer('CL',512*4).ensure_allocated()
  buffers=[a.buffer.ensure_allocated() for a in arguments]
  signature=tuple((None,i,dtypes.uint8,(b.nbytes,)) for i,b in enumerate((*buffers,trace)))
  program=device.runtime(TinyELF(source.encode(),'op_accumulator_probe',device.renderer.target,signature))
  program(*(b._buf for b in (*buffers,trace)),wait=True)
  values=np.empty(512,dtype=np.float32)
  check(cl.clEnqueueReadBuffer(device.queue,trace._buf,cl.CL_TRUE,0,values.nbytes,ctypes.c_void_p(values.ctypes.data),0,None,None))
  (capture_root/'kernel-0072-accumulators.f32').write_bytes(values.tobytes())
  activation=struct.unpack('<2048e',inputs[1])
  weights=struct.unpack('<2048e',inputs[2][row*4096:(row+1)*4096])
  bias=struct.unpack_from('<e',inputs[3],row*2)[0]
  oracle=half_dot(activation,weights,bias)
  return {"available":True,"row":row,"oracle":oracle,"oracle_matches_packaged_cpu":oracle['output']==float(expected[row]),
          "gpu_accumulator":float(values[row]),"accumulator_bit_equal":struct.pack('<f',oracle['accumulator'])==values[row].tobytes(),
          "accumulator_sha256":digest(values.tobytes()),"instrumented_gpu_source_sha256":digest(source.encode())}


def compare_intermediates(model_root, native_directory, progress=None, *, gpu_bundle=None, recurrent_probe=False):
  """On-phone diagnostic: stop at the first differing retained kernel output.

  CPU execution is exclusively the existing packaged AOT library: install()
  replaces Clang compilation with a strict symbol lookup before CPU is opened.
  This function never compiles a CPU helper, changes a tolerance or enables a
  failed GPU candidate. Live inference never calls it.
  """
  from android_runtime.gpu import configure, _verified_asset
  device = configure()
  import ctypes
  import numpy as np
  from tinygrad import Context
  from tinygrad.device import Buffer
  from tinygrad.dtype import _to_np_dtype
  from tinygrad.engine.jit import _prepare_jit_inputs
  from tinygrad.engine.realize import lower_and_compile, resolve_params, run_linear
  from tinygrad.runtime.autogen import opencl as cl
  from tinygrad.runtime.ops_cl import check
  from tinygrad.uop.ops import Ops, UOp
  from android_runtime.aot import install
  from openpilot_android_vendor.helpers import allocate_inputs, load_pickle
  root = Path(model_root)
  path, artifact_hash = _verified_asset(root, "driving_tinygrad.pkl")
  if progress:
    progress({"stage": "retained_kernel_diagnostic", "diagnostic_step": "synchronize", "diagnostic_reuses_gpu": gpu_bundle is not None})
  device.synchronize()
  if gpu_bundle is None:
    if progress:
      progress({"diagnostic_step": "load_gpu"})
    gpu = load(path, out_of_band=True, inplace_states=recurrent_probe)
    gpu_inputs, gpu_outputs = allocate_inputs(gpu["input_specs"]), allocate_inputs(gpu["output_specs"])
    if recurrent_probe:
      from android_runtime.gpu import _state_alias
      for name,value in gpu_inputs.items():
        if 'next_'+name in gpu_outputs:gpu_outputs['next_'+name]=_state_alias(value)
  else:
    gpu, gpu_inputs, gpu_outputs = gpu_bundle
  gpu_uops, gpu_vars, _, _ = _prepare_jit_inputs((), gpu_inputs | {"output_buffers": gpu_outputs})
  # The lookup patch is fail-closed: a CPU source missing from the packaged
  # library raises instead of invoking clang or creating any executable memory.
  install(str(Path(native_directory) / "libopenpilot_kernels.so"))
  if progress:
    progress({"diagnostic_step": "load_cpu_aot"})
  with Context(DEV="CPU:CLANG"):
    cpu = load_pickle(path, out_of_band=True)
    cpu["run"].captured._linear = lower_and_compile(cpu["run"].captured._linear)
    cpu_inputs, cpu_outputs = allocate_inputs(cpu["input_specs"]), allocate_inputs(cpu["output_specs"])
    if recurrent_probe:
      from tinygrad import Tensor
      for name,value in cpu_inputs.items():
        if 'next_'+name in cpu_outputs:
          view=value._buffer().view(value.nbytes(),0).ensure_allocated()
          cpu_outputs['next_'+name]=Tensor(UOp.from_buffer(view,value.dtype)).reshape(value.shape)
    cpu_uops, cpu_vars, _, _ = _prepare_jit_inputs((), cpu_inputs | {"output_buffers": cpu_outputs})
  cpu_linear, gpu_linear = cpu["run"].captured._linear, gpu["run"].captured._linear
  if len(cpu_linear.src) != len(gpu_linear.src) or len(gpu_linear.src) != len(gpu["_gpu_argument_views"]):
    raise RuntimeError("Diagnostic retained kernel sequences differ")
  scratch = set(gpu["_gpu_scratch_buffers"])
  if gpu_bundle is not None:
    scratch.update(tensor._buffer().base for tensor in (*gpu_inputs.values(), *gpu_outputs.values()))
  for backend, linear in (("cpu_aot", cpu_linear), ("gpu", gpu_linear)):
    buffers = {node.arg.buffer.base for node in linear.toposort() if node.op is Ops.BUFFER and node.arg.buffer is not None}
    if backend == "gpu":
      buffers.update(scratch)
    initialized = 0
    for buffer in buffers:
      if buffer in scratch or not buffer.is_allocated():
        if progress:
          progress({"diagnostic_step": "zero_" + backend, "diagnostic_buffer_index": initialized,
                    "diagnostic_buffer_bytes": buffer.nbytes})
        buffer.ensure_allocated().copy_from(Buffer("PYTHON", buffer.nbytes, initial_value=bytes(buffer.nbytes)))
        # Bound pending upload resources while preparing the diagnostic.
        if backend == "gpu":
          device.synchronize()
        initialized += 1
  if recurrent_probe:
    # Synthetic unique history planes expose overlapping state-copy ordering.
    # No fixture or live camera pixels enter this diagnostic.
    shape=cpu['input_specs']['state_img_q'][0]
    values=np.broadcast_to(np.arange(1,11,dtype=np.uint8).reshape(2,5,1,1,1)*16,shape).copy()
    payload=values.tobytes()
    for tensor in (cpu_inputs['state_img_q'],gpu_inputs['state_img_q']):
      tensor._buffer().ensure_allocated().copy_from(Buffer('PYTHON',len(payload),initial_value=payload))
    device.synchronize()
  from android_runtime.gpu_diagnostic import checked_view, checked_uploads, digest, MAX_CAPTURE_BYTES
  import json
  import os
  capture_root=Path(os.environ["OPENPILOT_ANDROID_ROOT"])/"gpu-capture"
  capture_root.mkdir(exist_ok=True)
  checked,first_bit_difference,kernel72_trace=0,None,None
  input_hashes=[]

  def gpu_bytes(argument,offset,nbytes):
    buffer=argument.buffer.ensure_allocated()
    checked_view(buffer.nbytes,offset,nbytes)
    out=ctypes.create_string_buffer(nbytes)
    check(cl.clEnqueueReadBuffer(device.queue,buffer._buf,cl.CL_TRUE,offset,nbytes,out,0,None,None))
    return out.raw

  def restore(arguments,views,snapshots):
    writes=[]
    for slot,payload in snapshots.items():
      buffer=arguments[slot].buffer.ensure_allocated()
      writes.append((int(ctypes.cast(buffer._buf,ctypes.c_void_p).value),buffer.nbytes,views[slot][0],payload))
    checked_uploads(writes)
    for slot,payload in snapshots.items():
      value=ctypes.create_string_buffer(payload)
      check(cl.clEnqueueWriteBuffer(device.queue,arguments[slot].buffer.ensure_allocated()._buf,cl.CL_TRUE,
                                   views[slot][0],len(payload),value,0,None,None))

  def save_inputs(index,cpu_inputs,gpu_inputs,rows):
    saved={}
    if sum(map(len,cpu_inputs.values()))+sum(map(len,gpu_inputs.values()))>MAX_CAPTURE_BYTES:
      raise ValueError("Complete input capture exceeds128MiB")
    for slot,payload in cpu_inputs.items():
      row={}
      for side,content in (("cpu",payload),("gpu",gpu_inputs[slot])):
        name=f"kernel-{index:04d}-slot-{slot}-{side}.bin"
        (capture_root/name).write_bytes(content)
        row[side]={"file":name,"nbytes":len(content),"sha256":digest(content)}
      saved[str(slot)]=row
    record={"schema":1,"kernel_index":index,"artifact_sha256":artifact_hash,"inputs":saved,"views":rows,
            "scope":"synthetic nonzero aliased history" if recurrent_probe else "synthetic retained-zero model, no live camera pixels"}
    for side,content,suffix in (("cpu",cpu_call.body.src[2].arg,"c"),("gpu",gpu_call.body.src[2].arg,"cl")):
      name=f"kernel-{index:04d}-{side}.{suffix}"
      (capture_root/name).write_text(content)
      record[side+"_source"]={"file":name,"sha256":digest(content.encode())}
    (capture_root/f"kernel-{index:04d}.json").write_text(json.dumps(record,indent=2))
    return record
  for index, (cpu_call, gpu_call, views) in enumerate(zip(cpu_linear.src, gpu_linear.src, gpu["_gpu_argument_views"])):
    cpu_call, gpu_call = cpu_call.without_after, gpu_call.without_after
    if views is None or cpu_call.op is not Ops.CALL or gpu_call.op is not Ops.CALL or cpu_call.body.op is not Ops.PROGRAM:
      raise RuntimeError("Unsupported call in retained kernel diagnostic")
    cpu_arguments,gpu_arguments=resolve_params(cpu_call,tuple(cpu_uops)),resolve_params(gpu_call,tuple(gpu_uops))
    before_cpu,before_gpu={},{}
    for slot in cpu_call.body.arg.ins:
      payload=bytes(cpu_arguments[slot].buffer.ensure_allocated().as_memoryview())
      offset,nbytes=views[slot]
      if len(payload)!=nbytes:raise ValueError("CPU/GPU logical input lengths differ")
      before_cpu[slot],before_gpu[slot]=payload,gpu_bytes(gpu_arguments[slot],offset,nbytes)
    rows={str(slot):{"offset":views[slot][0],"nbytes":len(payload),"cpu_sha256":digest(payload),
                     "gpu_sha256":digest(before_gpu[slot]),"identical":payload==before_gpu[slot]} for slot,payload in before_cpu.items()}
    input_hashes.append({"kernel_index":index,"inputs":rows})
    if progress:
      progress({"diagnostic_step": "kernel_cpu_aot", "diagnostic_kernel_index": index,
                "diagnostic_kernel": cpu_call.body.src[0].arg.function_name})
    with Context(DEV="CPU:CLANG"):
      run_linear(UOp(Ops.LINEAR, src=(cpu_call,)), cpu_vars, input_uops=cpu_uops, update_stats=False, jit=True)
    if progress:
      progress({"diagnostic_step": "kernel_gpu"})
    run_linear(UOp(Ops.LINEAR, src=(gpu_call,)), gpu_vars, input_uops=gpu_uops, update_stats=False, jit=True, wait=True)
    if progress:
      progress({"diagnostic_step": "compare_outputs"})
    for slot in cpu_call.body.arg.outs:
      expected = np.frombuffer(cpu_arguments[slot].buffer.ensure_allocated().as_memoryview(),
                               dtype=_to_np_dtype(cpu_arguments[slot].dtype)).copy()
      actual = np.empty_like(expected)
      offset, nbytes = views[slot]
      if actual.nbytes != nbytes:
        raise RuntimeError("Diagnostic retained argument byte count differs")
      gpu_buffer = gpu_arguments[slot].buffer.ensure_allocated()
      check(cl.clEnqueueReadBuffer(device.queue, gpu_buffer._buf, cl.CL_TRUE, offset, nbytes,
                                  ctypes.c_void_p(actual.ctypes.data), 0, None, None))
      close = np.isclose(actual, expected, rtol=1e-4, atol=1e-5, equal_nan=False)
      checked += 1
      bits_equal=actual.tobytes()==expected.tobytes()
      first_bits_now=not bits_equal and first_bit_difference is None
      if first_bits_now:
        bit_index=int(np.flatnonzero(np.any(actual.view(np.uint8).reshape(-1,actual.dtype.itemsize)!=expected.view(np.uint8).reshape(-1,expected.dtype.itemsize),axis=1))[0])
        first_bit_difference={"kernel_index":index,"kernel":cpu_call.body.src[0].arg.function_name,"output_slot":slot,
                              "element_index":bit_index,"expected":float(expected[bit_index]),"actual":float(actual[bit_index]),
                              "inputs_identical":all(row["identical"] for row in rows.values())}
        save_inputs(index,before_cpu,before_gpu,rows)
      teacher=None
      if first_bits_now or not np.all(close) or index==72:
        save_inputs(index,before_cpu,before_gpu,rows)
        (capture_root/"input-hashes.json").write_text(json.dumps(input_hashes))
        # Replay this kernel with byte-identical complete inputs. Restore the
        # original sequence state afterward, including aliased arenas.
        free_outputs={out_slot:gpu_bytes(gpu_arguments[out_slot],*views[out_slot]) for out_slot in cpu_call.body.arg.outs}
        restore(gpu_arguments,views,before_cpu)
        run_linear(UOp(Ops.LINEAR,src=(gpu_call,)),gpu_vars,input_uops=gpu_uops,update_stats=False,jit=True,wait=True)
        forced=np.frombuffer(gpu_bytes(gpu_arguments[slot],offset,nbytes),dtype=actual.dtype).copy()
        teacher={"identical_input_replay":True,"bit_equal":forced.tobytes()==expected.tobytes(),
                 "matches_tolerance":bool(np.all(np.isclose(forced,expected,rtol=1e-4,atol=1e-5))),
                 "max_abs_difference":float(np.max(np.abs(forced.astype(np.float64)-expected.astype(np.float64))))}
        if index==72:
          restore(gpu_arguments,views,before_cpu)
          first=int(np.flatnonzero(~close)[0]) if not np.all(close) else 416
          kernel72_trace=_trace_kernel72(device,gpu_call,gpu_arguments,views,before_cpu,expected,first,capture_root)
        restore(gpu_arguments,views,before_gpu)
        restore(gpu_arguments,views,free_outputs)
        if first_bits_now:first_bit_difference["teacher_forced"]=teacher
      if not np.all(close):
        difference = np.abs(actual.astype(np.float64) - expected.astype(np.float64))
        worst = int(np.argmax(np.where(np.isfinite(difference), difference, np.inf)))
        first = int(np.flatnonzero(~close)[0])
        def number(value):
          return float(value) if np.isfinite(value) else str(value)
        complete_capture=save_inputs(index,before_cpu,before_gpu,rows)
        (capture_root/"input-hashes.json").write_text(json.dumps(input_hashes))
        input_samples = {}
        for input_slot in cpu_call.body.arg.ins:
          cpu_argument = cpu_arguments[input_slot]
          cpu_values = np.frombuffer(before_cpu[input_slot], dtype=_to_np_dtype(cpu_argument.dtype))
          sample_size = min(cpu_values.size, 32 if cpu_values.size <= 32 else 8)
          gpu_values = np.frombuffer(before_gpu[input_slot],dtype=cpu_values.dtype)[:sample_size]
          input_samples[str(input_slot)] = {"cpu": [number(value) for value in cpu_values[:sample_size]],
                                            "gpu": [number(value) for value in gpu_values]}
        return {"matched": False, "backend_cpu": "PACKAGED_AOT", "artifact_sha256": artifact_hash,
                "kernel_index": index, "kernel": cpu_call.body.src[0].arg.function_name, "output_slot": slot,
                "cpu_source_sha256": hashlib.sha256(cpu_call.body.src[2].arg.encode()).hexdigest(),
                "gpu_source": gpu_call.body.src[2].arg, "input_samples": input_samples,
                "complete_inputs":complete_capture,"first_bit_difference":first_bit_difference,"teacher_forced":teacher,
                "kernel72_trace":kernel72_trace,
                "dtype": str(actual.dtype), "elements": int(actual.size), "mismatched_elements": int(np.count_nonzero(~close)),
                "first_mismatch_index": first, "expected_first": number(expected[first]), "actual_first": number(actual[first]),
                "maximum_absolute_difference": number(difference[worst]), "expected_worst": number(expected[worst]),
                "actual_worst": number(actual[worst]), "checked_outputs": checked, "rtol": 1e-4, "atol": 1e-5}
  (capture_root/"input-hashes.json").write_text(json.dumps(input_hashes))
  return {"matched": True, "backend_cpu": "PACKAGED_AOT", "artifact_sha256": artifact_hash,"first_bit_difference":first_bit_difference,"kernel72_trace":kernel72_trace,
          "kernels": len(cpu_linear.src), "checked_outputs": checked, "rtol": 1e-4, "atol": 1e-5}
