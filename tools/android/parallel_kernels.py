"""Prove independent outer output loops and stage Android kernel wrappers.

Pure standard library. Evaluates only whitelisted integer AST expressions, not C
or model arithmetic. Every output address is checked across the finite captured
loop domains. Runtime buffer overlap falls back to the original serial loop.
"""
import ast
import hashlib
import itertools
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
INPUT=ROOT/"tools/android/.cache/model-aot/kernels"
OUTPUT=ROOT/"tools/android/.cache/parallel/sources"
LOOP=re.compile(r"for \(int (Lidx\w+) = 0; \1 < (\d+); \1\+\+\) \{")


def evaluate(node, values, definitions):
    if isinstance(node,ast.Expression):return evaluate(node.body,values,definitions)
    if isinstance(node,ast.Constant) and type(node.value) is int:return node.value
    if isinstance(node,ast.Name):
        return values[node.id] if node.id in values else evaluate(definitions[node.id],values,definitions)
    if isinstance(node,ast.BinOp):
        a,b=evaluate(node.left,values,definitions),evaluate(node.right,values,definitions)
        if isinstance(node.op,ast.Add):return a+b
        if isinstance(node.op,ast.Sub):return a-b
        if isinstance(node.op,ast.Mult):return a*b
        if isinstance(node.op,ast.LShift):return a<<b
        if isinstance(node.op,ast.RShift):return a>>b
        if isinstance(node.op,ast.BitAnd):return a&b
        if isinstance(node.op,ast.BitOr):return a|b
    raise ValueError("Unproven integer address expression")


def offset(lhs, name):
    tail=lhs.split(name,1)[1].lstrip()
    if not tail.startswith('+'):return ast.parse('0',mode='eval')
    text,depth='',0
    for char in tail[1:]:
        if char==')' and depth==0:break
        text+=char
        if char=='(':depth+=1
        if char==')':depth-=1
    return ast.parse(text,mode='eval')


def prove(source):
    signature=re.search(r"void (op_[0-9a-f]{64})\(([^)]*)\) \{",source)
    if not signature:raise ValueError('Unexpected kernel signature')
    params=[]
    for declaration in signature[2].split(','):
        match=re.fullmatch(r'\s*(__fp16|float|unsigned char|int|unsigned int)\*\s*(?:restrict\s+)?(data\d+_(\d+))\s*',declaration)
        if not match:raise ValueError('Only fixed pointer parameters are supported')
        dtype,name,count=match.groups();params.append((dtype,name,int(count)))
    dtype,output,capacity=params[0]
    if dtype!='__fp16' or capacity<32768:raise ValueError('Small/non-half output stays serial')
    vectors={name:int(count) for name,count in re.findall(r'typedef \w+ (\w+) __attribute__\(\(aligned\(\d+\),ext_vector_type\((\d+)\)\)\);',source)}
    depth,active,definitions,stores=0,[],{},[]
    first=None
    for line in source.splitlines():
        if match:=LOOP.search(line):
            if first is None:first=match
            active.append((match[1],int(match[2]),depth+1))
        if match:=re.match(r'\s*int (alu\d+) = (.*);$',line):
            try:definitions[match[1]]=ast.parse(match[2],mode='eval')
            except SyntaxError:pass
        if output in line and not line.lstrip().startswith('void '):
            if '=' not in line:raise ValueError('Output is read or escaped')
            lhs,rhs=line.split('=',1)
            if output not in lhs or output in rhs:raise ValueError('Output is read or escaped')
            vector=re.search(r'\(\((\w+)\*\)',lhs)
            width=vectors[vector[1]] if vector else 1
            stores.append((offset(lhs,output),width,[(name,count) for name,count,_ in active]))
        depth+=line.count('{')-line.count('}')
        active=[entry for entry in active if entry[2]<=depth]
    if not stores or first is None or int(first[2])<4:raise ValueError('No substantial output loop')
    axis,bound=first[1],int(first[2])
    intervals=[]
    for outer in range(bound):
        lo,hi=capacity,-1
        for expression,width,loops in stores:
            if not loops or loops[0][0]!=axis:raise ValueError('Store outside the proposed outer loop')
            names=[name for name,_ in loops[1:]]
            for values in itertools.product(*(range(count) for _,count in loops[1:])):
                address=evaluate(expression,{axis:outer,**dict(zip(names,values))},definitions)
                if address<0 or address+width>capacity:raise ValueError('Output bounds proof failed')
                lo,hi=min(lo,address),max(hi,address+width)
        if hi<lo:raise ValueError('Empty output interval')
        if intervals and lo<intervals[-1][1]:raise ValueError('Outer iterations can overlap')
        intervals.append((lo,hi))
    if intervals[0][0]!=0 or intervals[-1][1]!=capacity:raise ValueError('Incomplete outer coverage')
    return signature,params,first,intervals


def wrap(source,proof):
    signature,params,loop,intervals=proof
    name=signature[1];serial=name.replace('op_','serial_',1)
    declarations=', '.join(f'{dtype}* {name}' for dtype,name,_ in params)
    nonalias_declarations=', '.join(f'{dtype}* restrict {name}' for dtype,name,_ in params)
    names=', '.join(name for _,name,_ in params)
    # The runtime check below proves the output cannot overlap any input for
    # the fast path. Keep that no-alias information available to the compiler.
    # The serial fallback deliberately has no such assertion.
    fallback_name=name.replace('op_','fallback_',1)
    fallback=source[signature.start():].replace(signature[0],f'static void {fallback_name}({declarations}) {{',1)
    fallback=re.sub(r'\brestrict\b','',fallback)
    source=source.replace(signature[0],f'static void {serial}({nonalias_declarations}, int op_begin, int op_end) {{',1)
    source=source.replace(loop[0],f'for (int {loop[1]} = op_begin; {loop[1]} < op_end; {loop[1]}++) {{',1)
    fields='; '.join(f'{dtype}* {name}' for dtype,name,_ in params)+';'
    args=', '.join('ctx->'+name for _,name,_ in params)
    first=params[0]
    checks=[]
    for dtype,parameter,count in params[1:]:
        checks.append(f'((unsigned long){first[1]} < (unsigned long){parameter}+sizeof({dtype})*{count}ul && '
                      f'(unsigned long){parameter} < (unsigned long){first[1]}+sizeof({first[0]})*{first[2]}ul)')
    return source+fallback+f'''
extern void op_parallel_launch(void (*callback)(void*,int,int), void* context, int total);
extern void op_parallel_fallback(void);
struct context_{name} {{ {fields} }};
static void callback_{name}(void* value, int begin, int end) {{
  struct context_{name}* ctx=value;
  {serial}({args},begin,end);
}}
void {name}({declarations}) {{
  if ({' || '.join(checks)}) {{ op_parallel_fallback(); {fallback_name}({names}); return; }}
  struct context_{name} context={{ {names} }};
  op_parallel_launch(callback_{name},&context,{loop[2]});
}}
'''


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    proofs,serial={},[]
    for path in sorted(INPUT.glob('*.c')):
        source=path.read_text()
        try:
            proof=prove(source)
            transformed=wrap(source,proof)
            proofs[path.stem]={'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                              'axis':proof[2][1],'iterations':int(proof[2][2]),
                              'output_intervals':proof[3],'runtime_alias_check':True}
        except (ValueError,KeyError,SyntaxError,RecursionError):
            transformed=source;serial.append(path.stem)
        (OUTPUT/path.name).write_text(transformed,encoding='utf-8')
    (OUTPUT.parent/'proof.json').write_text(json.dumps({'schema':1,'parallel':proofs,'serial':serial},indent=2)+'\n')
    print(f'Proved {len(proofs)} independent outer output loops; {len(serial)} kernels remain serial')


if __name__=='__main__':main()
