"""Run approved Android GPU diagnostics, with process/memory isolation per case.

Reviewed stdlib host orchestration only. All UOp/model/native execution occurs
in Android instrumentation. Results are diagnostics, never live certificates.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[2]
PACKAGE='com.samsung.android.openpilot.shadow'
CASES={'realUopViewsAndIndependentLoops':None,'recurrentAliasOwnership':None,
       'retainedModelProofDiagnostic':'gpu-kernel-proof.json','recurrentCopyDiagnostic':'gpu-recurrent-copy.json',
       'retainedFixtureDiagnostic':'gpu-fixture-frame.json','retainedKernelTimingDiagnostic':'gpu-kernel-timing.json'}


def main():
  from experiment_lifecycle import cleanup_experiments
  from test_acceleration import validate_apk,installed_apk_sha256
  parser=argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--serial',required=True)
  parser.add_argument('--install',action='store_true')
  parser.add_argument('--cases',nargs='+',choices=tuple(CASES),required=True)
  args=parser.parse_args()
  if not re.fullmatch(r'[A-Za-z0-9_-]+',args.serial) or args.serial.startswith('emulator-'):parser.error('Select the physical Fold3')
  def command(*items,timeout=20):return subprocess.run(['adb','-s',args.serial,*items],capture_output=True,timeout=timeout)
  def checked(*items,timeout=20):
    result=command(*items,timeout=timeout)
    if result.returncode:raise RuntimeError((result.stdout+result.stderr).decode(errors='replace')[:2000])
    return result.stdout.decode().strip()
  if checked('shell','getprop','ro.product.model')!='SM-F926B' or checked('shell','cmd','device_state','print-state')!='0':
    raise RuntimeError('Keep the selected Fold3 folded')
  out=ROOT/'artifacts/android/gpu-repair'/('native-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
  out.mkdir();print('Evidence: '+str(out),flush=True)
  summary={'completed':False,'scope':'Android diagnostics only; no sustained/live qualification','cases':[],'apks':{}}
  try:
    cleanup_experiments(command,out,'initial')
    for package,relative in ((PACKAGE,'debug/app-arm64-v8a-debug.apk'),(PACKAGE+'.test','androidTest/debug/app-debug-androidTest.apk')):
      path=ROOT/'android/app/build/outputs/apk'/relative
      if args.install:
        validate_apk(path);expected=hashlib.sha256(path.read_bytes()).hexdigest()
        checked('install','-r','--no-streaming',str(path),timeout=180)
      actual=installed_apk_sha256(checked,package)
      if args.install and actual!=expected:raise RuntimeError('Installed APK mismatch: '+package)
      summary['apks'][package]=actual
    for case in args.cases:
      before=cleanup_experiments(command,out,case+'-before')
      if before['after']['thermal_status'] not in (0,1,2):raise RuntimeError('Thermal precondition prevents diagnostic')
      filename=CASES[case]
      def modified():return checked('shell','run-as',PACKAGE,'stat','-c','%y','files/'+filename) if filename else ''
      old=command('shell','run-as',PACKAGE,'stat','-c','%y','files/'+filename).stdout.decode().strip() if filename else ''
      try:
        result=command('shell','am','instrument','-w','-r','-e','class','ai.comma.openpilot.sim.GpuArtifactPolicyTest#'+case,
                       PACKAGE+'.test/androidx.test.runner.AndroidJUnitRunner',timeout=240)
        (out/(case+'.txt')).write_bytes(result.stdout+result.stderr)
        passed=result.returncode==0 and b'OK (1 test)' in result.stdout and b'INSTRUMENTATION_STATUS_CODE: -3' not in result.stdout
        row={'case':case,'instrumentation_passed':passed}
        if filename and passed:
          stamp=modified()
          if stamp==old:raise RuntimeError('No fresh diagnostic file: '+filename)
          payload=checked('exec-out','run-as',PACKAGE,'cat','files/'+filename)
          report=json.loads(payload);(out/filename).write_text(payload,encoding='utf-8')
          row.update(fresh_report=True,report=filename,device_file_modified=stamp)
          if 'matched' in report:row['numerical_passed']=report['matched'] is True
          if report.get('passed') is False or row.get('numerical_passed') is False:passed=False
        summary['cases'].append(row)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(row),flush=True)
        if not passed:raise RuntimeError('Rejected diagnostic: '+case)
      finally:cleanup_experiments(command,out,case+'-after')
    summary['completed']=True
  except BaseException as error:
    summary['error']=type(error).__name__+': '+str(error)
    raise
  finally:
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    try:cleanup_experiments(command,out,'final')
    except BaseException as error:
      summary.update(completed=False,cleanup_error=type(error).__name__+': '+str(error))
      raise
    finally:(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
