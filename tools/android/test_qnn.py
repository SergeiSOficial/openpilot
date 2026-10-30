"""Bounded on-phone public QNN/HTP + GNSS test; no host native execution."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[2]
PACKAGE="ai.comma.openpilot.acceleration"


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--serial',required=True);args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.serial) or args.serial.startswith('emulator-'):parser.error('Select the physical Fold 3')
    adb=str(Path(os.environ['ANDROID_HOME'])/'platform-tools/adb.exe')
    def call(*items,timeout=120):return subprocess.run([adb,'-s',args.serial,*items],capture_output=True,timeout=timeout)
    def checked(*items):
        result=call(*items)
        if result.returncode:raise RuntimeError((result.stdout+result.stderr).decode(errors='replace'))
        return result.stdout
    if not checked('shell','getprop','ro.product.model').decode().strip().startswith('SM-F926'):raise RuntimeError('Wrong phone')
    state=checked('shell','cmd','device_state','print-state')
    if state.strip()!=b'0':raise RuntimeError('Keep the phone closed')
    size=checked('shell','wm','size');location=checked('shell','cmd','location','is-location-enabled')
    output=ROOT/'artifacts/android/qnn'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');output.mkdir(parents=True,exist_ok=True)
    (output/'thermal-before.txt').write_bytes(checked('shell','dumpsys','thermalservice'))
    apk=ROOT/'artifacts/android/qnn/build/apk/debug/app-debug.apk'
    test=ROOT/'artifacts/android/qnn/build/apk/androidTest/debug/app-debug-androidTest.apk'
    for path in (apk,test):checked('install','-r',str(path))
    (output/'apk.json').write_text(json.dumps({'sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),'bytes':apk.stat().st_size,
                                           'test_apk_sha256':hashlib.sha256(test.read_bytes()).hexdigest(),
                                           'ort':'1.29.0','qnn_plugin':'2.7.0','qnn_runtime':'2.51.0'},indent=2)+'\n')
    attempt=uuid.uuid4().hex
    timed_out=False
    try:
        result=call('shell','am','instrument','-w','-e','attemptId',attempt,'-e','class',
                    'ai.comma.openpilot.sim.QnnProbeTest,ai.comma.openpilot.sim.SensorsTest',
                    PACKAGE+'.test/androidx.test.runner.AndroidJUnitRunner',timeout=150)
        (output/'tests.txt').write_bytes(result.stdout+result.stderr)
        instrument_passed=result.returncode==0 and b'OK (2 tests)' in result.stdout
    except subprocess.TimeoutExpired as error:
        timed_out=True;instrument_passed=False
        (output/'tests.txt').write_bytes((error.stdout or b'')+(error.stderr or b'')+b'\nBounded test deadline exceeded\n')
        call('shell','am','force-stop',PACKAGE)
    report={}
    for name in ('qnn.json','sensors.json'):
        result=call('exec-out','run-as',PACKAGE,'cat','files/hardware/'+name)
        if result.returncode==0:
            (output/name).write_bytes(result.stdout)
            if name=='qnn.json':report=json.loads(result.stdout)
    if report and report.get('attempt_id')!=attempt:
        report={'passed':False,'htp_execution_verified':False,'error':'Stale report rejected'}
    (output/'thermal-after.txt').write_bytes(checked('shell','dumpsys','thermalservice'))
    if checked('shell','cmd','location','is-location-enabled')!=location:raise RuntimeError('GPS setting changed during test')
    if checked('shell','cmd','device_state','print-state')!=state or checked('shell','wm','size')!=size:raise RuntimeError('Phone display state changed')
    passed=instrument_passed and report.get('passed',False) and not timed_out
    if report.get('passed') and report.get('profile_file'):
        profile=checked('exec-out','run-as',PACKAGE,'cat',report['profile_file'])
        (output/'profile.json').write_bytes(profile)
        providers={item.get('args',{}).get('provider') for item in json.loads(profile) if item.get('args',{}).get('provider')}
        passed=passed and providers=={'QNNExecutionProvider'}
    else:providers=set()
    summary={'passed':passed,'instrumentation_passed':instrument_passed,'timed_out':timed_out,
             'htp_execution_verified':report.get('htp_execution_verified',False),'driving_model_accelerated':False,
             'executed_providers':sorted(providers),
             'location_enabled':location.decode().strip(),'evidence':str(output)}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
