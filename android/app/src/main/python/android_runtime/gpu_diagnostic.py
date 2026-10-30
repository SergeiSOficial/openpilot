"""Reviewed stdlib-only byte-view checks and scalar IEEE rounding oracle."""
import hashlib
import math
import struct
import itertools

MAX_CAPTURE_BYTES = 128*1024*1024


def workgroup_shape(extent, limit=64):
  """Pack an unchanged, proven independent index set into full workgroups."""
  if type(extent) is not int or not 1 <= extent <= 0x7fffffff:
    raise ValueError('Invalid static work extent')
  if type(limit) is not int or not 1 <= limit <= 64:
    raise ValueError('Invalid workgroup limit')
  lanes=1
  while lanes*2 <= limit and extent % (lanes*2) == 0:lanes*=2
  return extent//lanes,lanes


def linear_workgroup(axes):
  """Bijectively flatten proven axes, with contiguous output coordinates first."""
  if not isinstance(axes,(tuple,list)) or not 1<=len(axes)<=3:raise ValueError('Invalid independent axes')
  seen=set();total=1;ordered=[]
  for dimension,extent,stride in axes:
    if any(type(v) is not int for v in (dimension,extent,stride)) or not 0<=dimension<=2 or stride<=0 or dimension in seen:
      raise ValueError('Invalid independent-axis geometry')
    workgroup_shape(extent);seen.add(dimension);total*=extent
    if total>0x7fffffff:raise ValueError('Flattened GPU index would overflow')
    ordered.append((stride,-dimension,extent,dimension))
  groups,lanes=workgroup_shape(total);divisor=1;result=[]
  for stride,_,extent,dimension in sorted(ordered):
    result.append({'dimension':dimension,'extent':extent,'stride':stride,'divisor':divisor});divisor*=extent
  return {'dimension':0,'groups':groups,'lanes':lanes,'total_indices':total,'axes':result,'policy':'contiguous_flat_indices_v2'}


def affine_interval(form,bounds,excluded=()):
  """Exact integer extrema of an affine address over independent loop ranges."""
  constant,terms=form
  if type(constant) is not int:raise ValueError('Noninteger affine constant')
  lo=hi=constant
  for axis,coefficient in terms.items():
    if type(coefficient) is not int:raise ValueError('Noninteger affine coefficient')
    if axis in excluded:continue
    lower,upper=bounds[axis]
    if type(lower) is not int or type(upper) is not int or lower>upper:raise ValueError('Invalid affine bounds')
    a,b=coefficient*lower,coefficient*upper
    lo+=min(a,b);hi+=max(a,b)
  return lo,hi


def gated_affine_interval(form,bounds,predicate,limit=4096):
  """Bound an affine read only where its integer/boolean load mask is true.

  Enumerate at most 4096 mask-coordinate combinations; fold every other axis
  analytically. No tensor values, model execution or native code are involved.
  None means the budget cannot prove it; () means the read is never executed.
  """
  if type(limit) is not int or not 1<=limit<=4096:raise ValueError('Invalid masked-read proof budget')
  affine_interval(form,bounds)
  axes={};visited=0
  def inspect(node,depth=0):
    nonlocal visited
    visited+=1
    if visited>128 or depth>32:raise ValueError('Masked-read predicate is too large')
    if type(node) is bool:return
    if not isinstance(node,tuple) or len(node)!=3:raise ValueError('Invalid integer predicate')
    op,a,b=node
    if op in ('and','or'):
      inspect(a,depth+1);inspect(b,depth+1)
    elif op in ('lt','eq','ne'):
      for expression in (a,b):
        affine_interval(expression,bounds)
        for axis in expression[1]:axes[axis]=None
    else:raise ValueError('Unsupported integer predicate')
  inspect(predicate)
  combinations=1
  for axis in axes:
    lo,hi=bounds[axis];combinations*=hi-lo+1
    if combinations>limit:return None
  rest_lo,rest_hi=affine_interval(form,bounds,tuple(axes))
  def value(expression,point):return expression[0]+sum(coefficient*point[axis] for axis,coefficient in expression[1].items())
  def accepts(node,point):
    if type(node) is bool:return node
    op,a,b=node
    if op=='and':return accepts(a,point) and accepts(b,point)
    if op=='or':return accepts(a,point) or accepts(b,point)
    a,b=value(a,point),value(b,point)
    return a<b if op=='lt' else a==b if op=='eq' else a!=b
  result=None
  for values in itertools.product(*(range(bounds[a][0],bounds[a][1]+1) for a in axes)):
    point=dict(zip(axes,values))
    if not accepts(predicate,point):continue
    shift=sum(form[1].get(axis,0)*v for axis,v in point.items())
    lo,hi=rest_lo+shift,rest_hi+shift
    result=(lo,hi) if result is None else (min(result[0],lo),max(result[1],hi))
  return () if result is None else result


def residue_disjoint(writes,bounds,axis,excluded=()):
  """Prove interleaved writes disjoint for every value of one output axis.

  Other axes must move by complete periods. All stores for one worker must fit
  within one stride of that period. This handles planar/interleaved layouts
  whose bounding intervals overlap, without assuming anything about reads.
  """
  lower,upper=bounds[axis]
  if type(lower) is not int or type(upper) is not int or lower!=0 or upper<1:return False
  stride=None;regions=[];translations=None
  for (constant,terms),width in writes:
    current=tuple(terms.get(a,0) for a in excluded)
    if translations is None:translations=current
    elif translations!=current:return False
    step=terms.get(axis,0)
    if type(step) is not int or step<=0 or type(width) is not int or width<=0:return False
    if stride is None:stride=step
    if stride!=step:return False
    period=stride*(upper+1)
    if type(constant) is not int or any(type(c) is not int or c%period for a,c in terms.items() if a not in (axis,*excluded)):return False
    start=constant%period
    if start+width>period:return False
    regions.append((start,start+width))
  return bool(regions) and max(end for _,end in regions)-min(start for start,_ in regions)<=stride


def checked_view(capacity, offset, length):
  if any(type(v) is not int for v in (capacity, offset, length)) or min(capacity, offset, length)<0:
    raise ValueError("Invalid byte view")
  if length>MAX_CAPTURE_BYTES or offset+length>capacity:
    raise ValueError("Byte view exceeds buffer or diagnostic bound")
  return offset, length


def checked_uploads(views):
  """Check overlapping aliases before restoring CPU inputs into GPU storage."""
  total=0
  for index,(buffer_id,capacity,offset,data) in enumerate(views):
    checked_view(capacity,offset,len(data));total+=len(data)
    if total>MAX_CAPTURE_BYTES:raise ValueError("Input capture exceeds diagnostic bound")
    for old_id,_,old_offset,old_data in views[:index]:
      if old_id!=buffer_id:continue
      start,end=max(offset,old_offset),min(offset+len(data),old_offset+len(old_data))
      if start<end and data[start-offset:end-offset]!=old_data[start-old_offset:end-old_offset]:
        raise ValueError("Conflicting bytes in aliased GPU input views")
  return views


def digest(data):
  return hashlib.sha256(data).hexdigest()


def verify_capture(payload,size,sha256):
  """Verify complete bytes before using a diagnostic capture as evidence."""
  if type(size) is not int or not 0<=size<=MAX_CAPTURE_BYTES:
    raise ValueError("Invalid capture size")
  if not isinstance(sha256,str) or len(sha256)!=64 or any(c not in '0123456789abcdef' for c in sha256):
    raise ValueError("Invalid capture digest")
  if len(payload)!=size or digest(payload)!=sha256:
    raise ValueError("Capture integrity failure")
  return payload


def rounded(value,code):
  try:return struct.unpack('<'+code,struct.pack('<'+code,value))[0]
  except OverflowError:return math.copysign(math.inf,value)


def exact_f32_div(av,bv):
  """Independent-testable integer significand algorithm used by the CL helper."""
  bits=lambda x:struct.unpack('<I',struct.pack('<f',x))[0]
  value=lambda x:struct.unpack('<f',struct.pack('<I',x))[0]
  a,b=bits(av),bits(bv);sign=(a^b)&0x80000000
  ae,be=(a>>23)&255,(b>>23)&255;am,bm=a&0x7fffff,b&0x7fffff
  if (ae==255 and am) or (be==255 and bm) or (ae==255 and be==255):return value(0x7fc00000)
  if ae==255:return value(sign|0x7f800000)
  if be==255:return value(sign)
  if not (b&0x7fffffff):return value(sign|0x7f800000 if a&0x7fffffff else 0x7fc00000)
  if not (a&0x7fffffff):return value(sign)
  if b&0x7fffffff==0x3f800000:return value(a^(b&0x80000000))
  an,bn=ae-127 if ae else -126,be-127 if be else -126
  am|=0x800000 if ae else 0;bm|=0x800000 if be else 0
  while am<0x800000:am<<=1;an-=1
  while bm<0x800000:bm<<=1;bn-=1
  exponent=an-bn
  if am<bm:am<<=1;exponent-=1
  if exponent>127:return value(sign|0x7f800000)
  if exponent< -150:return value(sign)
  shift=exponent+149 if exponent< -126 else 23
  q,r,denominator=1,am-bm,bm
  if shift<0:q,r,denominator=0,am,bm<<1
  else:
    for _ in range(shift):
      r<<=1;q<<=1
      if r>=denominator:r-=denominator;q|=1
  q+=int(r*2>denominator or (r*2==denominator and q&1))
  if exponent< -126:return value(sign|q)
  if q>=0x1000000:q>>=1;exponent+=1
  if exponent>127:return value(sign|0x7f800000)
  return value(sign|((exponent+127)<<23)|(q&0x7fffff))


def exact_f32_sqrt(value):
  """Restoring square root of a 48-bit significand using 32-bit steps."""
  bits=struct.unpack('<I',struct.pack('<f',value))[0]
  decode=lambda word:struct.unpack('<f',struct.pack('<I',word))[0]
  if not bits&0x7fffffff:return decode(bits)
  exponent=(bits>>23)&255;mantissa=bits&0x7fffff
  if exponent==255:
    return decode(bits|0x400000) if mantissa else (math.nan if bits>>31 else math.inf)
  if bits>>31:return math.nan
  power=exponent-127 if exponent else -126
  mantissa|=0x800000 if exponent else 0
  while mantissa<0x800000:mantissa<<=1;power-=1
  if power&1:mantissa<<=1;power-=1
  high,low=mantissa>>9,(mantissa<<23)&0xffffffff
  root=remainder=0
  for index in range(23,-1,-1):
    shift=index*2
    pair=((high>>(shift-32)) if shift>=32 else (low>>shift))&3
    remainder=(remainder<<2)|pair;trial=(root<<2)|1;root<<=1
    if remainder>=trial:remainder-=trial;root|=1
  root+=remainder>root
  power//=2
  if root==0x1000000:root>>=1;power+=1
  return decode(((power+127)<<23)|(root&0x7fffff))


def exact_f32_fma(a,b,c):
  """Integer dyadic FMA oracle, with one nearest-even FP32 rounding."""
  word=lambda x:struct.unpack('<I',struct.pack('<f',x))[0]
  decode=lambda x:struct.unpack('<f',struct.pack('<I',x))[0]
  words=[word(x) for x in (a,b,c)]
  if any((w&0x7f800000)==0x7f800000 for w in words):raise ValueError('Finite FMA inputs required')
  def parts(w):
    exponent=(w>>23)&255;mantissa=(w&0x7fffff)|(0x800000 if exponent else 0)
    return (-mantissa if w>>31 else mantissa),(exponent-150 if exponent else -149)
  (am,ap),(bm,bp),(cm,cp)=map(parts,words);power=min(ap+bp,cp)
  total=(am*bm<<(ap+bp-power))+(cm<<(cp-power))
  if not total:
    negative=(not am or not bm) and not cm and bool((words[0]^words[1])&words[2]&0x80000000)
    return decode(0x80000000 if negative else 0)
  sign=0x80000000 if total<0 else 0;total=abs(total);exponent=total.bit_length()-1+power
  shift=(-149-power) if exponent< -126 else total.bit_length()-24
  if shift>0:
    q,r=divmod(total,1<<shift);half=1<<(shift-1);q+=r>half or (r==half and q&1)
  else:q=total<<-shift
  if exponent< -126:return decode(sign|q)
  if q>=0x1000000:q>>=1;exponent+=1
  if exponent>127:return decode(sign|0x7f800000)
  return decode(sign|((exponent+127)<<23)|(q&0x7fffff))


def mlas_tanh_f32(value):
  """ORT 1.23.2 ARM MLAS polynomial with the observed fused contraction."""
  if math.isnan(value):return value
  f=lambda value:rounded(value,'f')
  x=f(max(-9.,min(9.,value)));s=f(x*x)
  madd=lambda a,b,c:exact_f32_fma(a,b,f(c))
  p=madd(s,f(-2.76076847742355e-16),2.00018790482477e-13)
  for c in (-8.60467152213735e-11,5.12229709037114e-08,1.48572235717979e-05,6.37261928875436e-04,4.89352455891786e-03):
    p=madd(p,s,c)
  p=f(p*x)
  q=madd(s,f(1.19825839466702e-06),1.18534705686654e-04)
  for c in (2.26843463243900e-03,4.89352518554385e-03):q=madd(q,s,c)
  return exact_f32_div(p,q)


def half_dot(activation,weights,bias):
  """Retained C dot: left-associated FP32 products/adds, half cast, bias, ReLU."""
  if len(activation)!=len(weights) or not activation:raise ValueError("Dot dimensions differ")
  if not all(math.isfinite(x) for x in (*activation,*weights,bias)):raise ValueError("Nonfinite oracle input")
  acc=0.
  for a,w in zip(activation,weights):acc=rounded(acc+rounded(a*w,'f'),'f')
  before_bias=rounded(acc,'e')
  after_bias=rounded(rounded(before_bias+bias,'f'),'e')
  return {"accumulator":acc,"half_before_bias":before_bias,"bias":bias,"output":max(0.,after_bias)}


def native_half_dot(activation,weights,bias=0.):
  """Binary16 fused multiply/add, rounded once per accumulation step."""
  if len(activation)!=len(weights) or not activation:raise ValueError('Dot dimensions differ')
  if not all(math.isfinite(x) for x in (*activation,*weights,bias)):raise ValueError('Nonfinite oracle input')
  accumulator=rounded(bias,'e')
  for a,w in zip(activation,weights):accumulator=rounded(a*w+accumulator,'e')
  return accumulator


def exact_half_fma(a,b,c):
  """Mirror of the CL half-FMA midpoint fix, tested against a double oracle."""
  product=rounded(a*b,'f');summed=rounded(product+c,'f')
  if not math.isfinite(summed):return rounded(summed,'e')
  bits=struct.unpack('<I',struct.pack('<f',summed))[0]
  exponent=((bits>>23)&255)-112
  if exponent>30 or exponent< -10:return rounded(summed,'e')
  mantissa=bits&0x7fffff;shift=13
  if exponent<=0:mantissa|=0x800000;shift=14-exponent
  if mantissa&((1<<shift)-1)!=(1<<(shift-1)):return rounded(summed,'e')
  z=rounded(summed-product,'f')
  error=rounded(rounded(product-rounded(summed-z,'f'),'f')+rounded(c-z,'f'),'f')
  if not error:return rounded(summed,'e')
  magnitude=abs(summed)
  half=struct.unpack('<H',struct.pack('<e',rounded(magnitude,'e')))[0]
  decoded=lambda code:struct.unpack('<e',struct.pack('<H',code))[0]
  if decoded(half)>magnitude:half-=1
  if (error if summed>=0 else -error)>0:half+=1
  return math.copysign(decoded(half),summed)


def retained_gelu_mean(values,denominator):
  """Scalar oracle for the captured r_256_4_32 GELU/mean, finite fixture inputs."""
  if len(values)!=32 or not denominator or not all(math.isfinite(x) for x in (*values,denominator)):
    raise ValueError("Expected32 finite values and a nonzero normalization")
  f=lambda x:rounded(x,'f')
  h=lambda x:rounded(x,'e')
  def scale(bits):return struct.unpack('<e',struct.pack('<H',bits&65535))[0]
  terms=[]
  for x in values:
    t=h(f(x/denominator))
    z=h(f(f(t+f(f(f(h(.044708251953125)*t)*t)*t))*h(-2.302734375)))
    integer=int(f(z+(-.5 if z<0 else .5)))
    r=h(f(z-h(integer)))
    p=f(h(.00015354156494140625)*r)
    for c in (.001338958740234375,.00962066650390625,.055511474609375,.240234375,.693359375,1.):
      p=f(p+h(c))
      if c!=1.:p=f(p*r)
    p=f(p*scale(((integer>>1)+15)<<10));p=f(p*scale(((integer-(integer>>1))+15)<<10))
    exp=h(p) if -22<=z<23 else (0. if z<-22 else math.inf)
    terms.append(f(x/f(denominator*f(1.+exp))))
  total=terms[0]
  for value in terms[1:]:total=f(total+value)
  return {"sum":total,"output":h(f(total*.03125)),"terms":terms}
