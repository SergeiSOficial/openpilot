"""Collect bounded synthetic-model diagnostics using stdlib and trusted adb."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import importlib.util

ROOT=Path(__file__).resolve().parents[2]
PACKAGE='com.samsung.android.openpilot.shadow'
_spec=importlib.util.spec_from_file_location('capture_integrity',ROOT/'android/app/src/main/python/android_runtime/gpu_diagnostic.py')
_policy=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_policy)


def main():
  parser=argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--serial',required=True)
  parser.add_argument('--session',required=True)
  args=parser.parse_args()
  if not re.fullmatch('[A-Za-z0-9_-]+',args.serial) or not re.fullmatch('[a-f0-9]{16}',args.session):raise ValueError('Invalid device/session')
  def read(name):
    return subprocess.run(['adb','-s',args.serial,'exec-out','run-as',PACKAGE,'cat','files/s/'+args.session+'/'+name],
                          check=True,capture_output=True,timeout=90).stdout
  out=ROOT/'artifacts/android/gpu-repair'/args.session;out.mkdir(parents=True,exist_ok=True)
  report=read('verification.json');(out/'verification.json').write_bytes(report)
  diagnostic=json.loads(report).get('gpu_validation',{}).get('intermediate_diagnostic',{})
  indices={row['kernel_index'] for row in [diagnostic,diagnostic.get('first_bit_difference',{})] if 'kernel_index' in row}
  total=0
  for index in sorted(indices):
    if type(index) is not int or not 0<=index<4096:raise ValueError('Invalid diagnostic kernel index')
    name=f'kernel-{index:04d}.json';raw=read('gpu-capture/'+name);record=json.loads(raw)
    (out/name).write_bytes(raw)
    for side in ('cpu','gpu'):
      source=record.get(side+'_source')
      if not source:continue
      filename=source['file']
      if not re.fullmatch(r'kernel-\d{4}-(cpu|gpu)\.(c|cl)',filename):raise ValueError('Invalid source capture')
      payload=read('gpu-capture/'+filename)
      if len(payload)>1024*1024 or hashlib.sha256(payload).hexdigest()!=source['sha256']:raise ValueError('Source integrity failure')
      (out/filename).write_bytes(payload)
    for pair in record['inputs'].values():
      for tensor in pair.values():
        filename=tensor['file'];size=tensor['nbytes']
        if not re.fullmatch(r'kernel-\d{4}-slot-\d+-(cpu|gpu)\.bin',filename) or type(size) is not int or not 0<=size<=128*1024*1024:
          raise ValueError('Invalid tensor capture')
        total+=size
        if total>256*1024*1024:raise ValueError('Capture exceeds total bound')
        content=read('gpu-capture/'+filename)
        _policy.verify_capture(content,size,tensor['sha256'])
        (out/filename).write_bytes(content)
  (out/'input-hashes.json').write_bytes(read('gpu-capture/input-hashes.json'))
  if diagnostic.get('kernel72_trace',{}).get('available'):
    (out/'kernel-0072-accumulators.f32').write_bytes(read('gpu-capture/kernel-0072-accumulators.f32'))
  print(json.dumps({'directory':str(out),'bytes_verified':total,'kernels':sorted(indices)}))


if __name__=='__main__':main()
