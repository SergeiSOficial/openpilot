"""Reviewed stdlib orchestration: release only this project's experiment apps.

No host native helper, cache eviction, unrelated process termination or device
memory-pressure command is used. Android owns reclamation after force-stop.
"""
import json
from pathlib import Path
import re
import time

PACKAGES=('com.samsung.android.openpilot.shadow','ai.comma.openpilot.acceleration','ai.comma.openpilot.qnn')


def _output(command,*items):
  result=command(*items,timeout=20)
  if result.returncode:raise RuntimeError('Experiment cleanup command failed: '+str(items)+': '+result.stderr.decode(errors='replace')[:512])
  return result.stdout.decode(errors='replace')


def experiment_processes(raw):
  lines=raw.splitlines()
  if not lines or lines[0].split()!=['PID','NAME']:raise ValueError('Unrecognized Android process inventory')
  result=[]
  for line in lines[1:]:
    fields=line.split(maxsplit=1)
    if len(fields)!=2:continue
    pid,name=fields
    if any(name==p or name.startswith(p+':') or name==p+'.test' for p in PACKAGES):
      if not pid.isdecimal() or int(pid)<=0:raise ValueError('Invalid experiment PID')
      result.append({'pid':int(pid),'name':name})
  return result


def _snapshot(command):
  processes=experiment_processes(_output(command,'shell','ps','-A','-o','PID,NAME'))
  raw=_output(command,'shell','cat','/proc/meminfo')
  memory={name:int(value) for name,value in re.findall(r'^(MemAvailable|MemFree|SwapFree|SwapTotal):\s+(\d+) kB\r?$',raw,re.M)}
  if 'MemAvailable' not in memory:raise ValueError('Android available-memory reading is unavailable')
  thermal=_output(command,'shell','dumpsys','thermalservice')
  status=re.search(r'Thermal Status:\s*(\d+)',thermal)
  result={'monotonic_seconds':time.monotonic(),'processes':processes,'memory_kib':memory,
          'thermal_status':int(status.group(1)) if status else None,'package_meminfo':{}}
  for package in PACKAGES:
    if not any(p['name']==package or p['name'].startswith(package+':') for p in processes):continue
    reply=command('shell','dumpsys','meminfo',package,timeout=20)
    text=(reply.stdout+reply.stderr).decode(errors='replace')
    result['package_meminfo'][package]={'available':reply.returncode==0,'text':text[:65536],'truncated':len(text)>65536}
  return result


def cleanup_experiments(command,directory,label,*,wait_seconds=5):
  """Fail closed unless all experiment processes exit; retain bounded evidence.

  MemAvailable is a system reading, not proof of a particular allocation's
  reclamation. PID exit establishes that no previous app runtime remains alive.
  """
  if not isinstance(label,str) or re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',label) is None:raise ValueError('Invalid cleanup label')
  if type(wait_seconds) not in (int,float) or not 0<=wait_seconds<=5:raise ValueError('Invalid cleanup wait')
  directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
  path=directory/(label+'-cleanup.json');report={'schema':1,'completed':False,'packages':list(PACKAGES),
    'scope':'App process/runtime release only; Android controls memory reclamation; system caches untouched'}
  try:
    report['before']=_snapshot(command)
    report['force_stop']={}
    for package in PACKAGES:
      report['force_stop'][package]={'attempted':True}
      _output(command,'shell','am','force-stop',package)
      report['force_stop'][package]['completed']=True
    deadline=time.monotonic()+wait_seconds
    while True:
      remaining=experiment_processes(_output(command,'shell','ps','-A','-o','PID,NAME'))
      if not remaining:break
      if time.monotonic()>=deadline:raise RuntimeError('Experiment processes still alive: '+str(remaining))
      time.sleep(.1)
    report['after']=_snapshot(command)
    if report['after']['processes']:raise RuntimeError('Experiment process restarted during cleanup')
    report['completed']=True
  except Exception as error:
    report['error']=type(error).__name__+': '+str(error)
    # A failed memory/log reading must not leave an old experiment running.
    for package in PACKAGES:
      if package in report.get('force_stop',{}):continue
      try:
        result=command('shell','am','force-stop',package,timeout=20)
        report.setdefault('force_stop',{})[package]={'attempted':True,'completed':result.returncode==0}
      except Exception as stop_error:
        report.setdefault('force_stop',{})[package]={'attempted':True,'completed':False,'error':str(stop_error)}
    raise
  finally:path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
  return report
