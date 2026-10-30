"""Generate Android wire metadata/goldens from pinned source using only Python stdlib.

Never import panda: its package imports native USB/FFI dependencies. Only the
audited, pure byte-packing/checksum functions are extracted as Python AST nodes.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[2]


def main():
  health = ROOT/'panda/board/health.h'
  can = ROOT/'opendbc_repo/opendbc/safety/can.h'
  python = ROOT/'panda/python/__init__.py'
  body = re.search(r'struct __attribute__\(\(packed\)\) health_t \{(.*?)\};', health.read_text(), re.S).group(1)
  fields, offset = [], 0
  sizes = {'uint8_t':1, 'uint16_t':2, 'uint32_t':4}
  for line in body.splitlines():
    if not line.strip():
      continue
    match = re.fullmatch(r'\s*(uint8_t|uint16_t|uint32_t) (\w+);\s*', line)
    if not match:
      raise ValueError(f'Unsupported health field: {line}')
    kind, name = match.groups()
    fields.append({'name':name, 'offset':offset, 'bytes':sizes[kind]})
    offset += sizes[kind]
  dlc = [0,1,2,3,4,5,6,7,8,12,16,20,24,32,48,64]
  tree = ast.parse(python.read_text())
  functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('calculate_checksum','pack_can_buffer')]
  if len(functions) != 2 or any(node.decorator_list for node in functions):
    raise ValueError('Upstream pure packer functions changed')
  scope = {'CANPACKET_HEAD_SIZE':6, 'LEN_TO_DLC':{n:i for i,n in enumerate(dlc)}}
  exec(compile(ast.Module(body=functions, type_ignores=[]), str(python), 'exec'), scope)
  cases = [(0x123, b'\x01\x02\x03', 0, False), (0x18daf110, bytes(range(8)), 1, False),
           (0x456, bytes(range(64)), 2, True), (0x7ff, b'', 0, False)]
  vectors = [{'address':addr, 'data':data.hex(), 'bus':bus, 'fd':fd,
              'wire':scope['pack_can_buffer']([(addr,data,bus)], fd=fd)[0].hex()} for addr,data,bus,fd in cases]
  report = {'schema':1, 'hardware_type':7, 'health_size':offset, 'health_fields':fields, 'dlc_to_length':dlc,
            'health_version':int.from_bytes(hashlib.sha256(health.read_bytes().replace(b'\r',b'')).digest()[:4],'little'),
            'can_version':int.from_bytes(hashlib.sha256(can.read_bytes().replace(b'\r',b'')).digest()[:4],'little'),
            'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (health,can,python)},
            'golden_vectors':vectors}
  out = ROOT/'android/app/src/main/assets/panda/protocol.json'
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(json.dumps(report, indent=2)+'\n')
  print(f'Pinned Red Panda protocol: health {offset} bytes; {len(vectors)} upstream wire goldens')


if __name__ == '__main__':
  main()
