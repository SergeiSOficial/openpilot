"""Bounded target-only QNN phases, resumable calibration and evidence export.

Only reviewed Python stdlib orchestration runs here. No host model inference.
The separate ai.comma.openpilot.qnn APK never replaces the accepted CPU package.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[2]
PACKAGE="ai.comma.openpilot.qnn"


def capture_name(role):
    if role not in ("road","cabin"):raise ValueError("Unknown model role")
    return "capture" if role=="road" else "capture-cabin"


def evidence_name(role,name):
    capture_name(role)
    path=Path(name)
    return name if role=="road" else path.stem+"-cabin"+path.suffix


def validate_capture(directory,role):
    """Check an exported corpus with stdlib hashes; never open model arrays."""
    from qnn_graph import model_config
    directory=Path(directory)
    if (directory/"manifest.json").is_symlink():raise ValueError("Capture manifest must be a regular file")
    meta=json.loads((directory/"manifest.json").read_text())
    if (meta.get("model_role","road")!=role or type(meta.get("frames")) is not int or meta["frames"]!=60
        or meta.get("model_sha256")!=model_config(role)["sha256"]):
        raise ValueError("Capture model role/source/frame count differs")
    if meta.get("calibration_frames")!=[1,40] or meta.get("holdout_frames")!=[41,60]:
        raise ValueError("Capture must preserve calibration1..40 and holdout41..60")
    expected_names={f"{index:04d}.npz" for index in range(1,61)}
    if set(meta.get("sha256",{}))!=expected_names:raise ValueError("Capture must hash exactly60 frame files")
    for name,expected in meta["sha256"].items():
        path=directory/name
        if path.is_symlink() or not path.is_file():raise ValueError("Capture frame must be a regular file")
        if path.stat().st_size>16*1024*1024:raise ValueError("Capture frame exceeds transfer bound")
        with path.open("rb") as stream:actual=hashlib.file_digest(stream,"sha256").hexdigest()
        if actual!=expected:raise ValueError("Source capture hash mismatch: "+name)
    return meta


def capture_archive(directory,role):
    validate_capture(directory,role)
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode="w",dereference=True) as tar:
        for name in ("manifest.json",*(f"{index:04d}.npz" for index in range(1,61))):
            tar.add(Path(directory)/name,arcname=capture_name(role)+"/"+name,recursive=False)
    return archive.getvalue()


def import_capture(adb,serial,directory,role):
    archive=capture_archive(directory,role)
    subprocess.run([str(adb),"-s",serial,"shell","run-as",PACKAGE,"mkdir","-p","files/acceleration"],
                   capture_output=True,check=True,timeout=30)
    subprocess.run([str(adb),"-s",serial,"exec-in","run-as",PACKAGE,"tar","-xf","-","-C","files/acceleration"],
                   input=archive,capture_output=True,check=True,timeout=180)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--serial',required=True)
    parser.add_argument('--phase',required=True,choices=['prepare','calibrate','evaluate','sustain'])
    parser.add_argument('--install',action='store_true')
    parser.add_argument('--restore-default',action='store_true')
    parser.add_argument('--model',choices=['road','cabin'],default='road')
    parser.add_argument('--capture',type=Path,help='explicit exported60-frame corpus to transfer before the first phase')
    args=parser.parse_args()
    if args.capture is not None and args.phase=='prepare':parser.error('Prepare records a new corpus; --capture is for later phases')
    if args.capture is not None:validate_capture(args.capture,args.model)
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.serial):parser.error('Invalid explicit device serial')
    physical=not args.serial.startswith('emulator-')
    if not physical and args.phase in ('evaluate','sustain'):parser.error('HTP evaluation requires the physical Fold 3')
    adb=str(Path(os.environ['ANDROID_HOME'])/'platform-tools'/('adb.exe' if os.name=='nt' else 'adb'))
    def call(*items,timeout=60):
        return subprocess.run([adb,'-s',args.serial,*items],capture_output=True,check=True,timeout=timeout).stdout
    def read(name):return call('exec-out','run-as',PACKAGE,'cat','files/'+name)
    base=ROOT/'artifacts/android/qnn-experiment'
    if args.model=='cabin':base=base/'cabin'
    directory=base/args.serial/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory.mkdir(parents=True,exist_ok=True)
    print('Experiment evidence: '+str(directory),flush=True)
    success=False
    capture_sent=False
    def run(backends,install=False):
        nonlocal capture_sent
        command=[sys.executable,str(ROOT/'tools/android/test_acceleration.py'),'--serial',args.serial,
                 '--qnn-experiment','--model',args.model,'--candidate-timeout-seconds',('1800' if args.phase=='sustain' else '600'),'--backends',*backends]
        if args.capture is not None and not capture_sent:command.extend(['--capture',str(args.capture)])
        if physical:command.append('--modern-qnn')
        else:command.append('--modern-cpu-emulator')
        if install:command.append('--install')
        result=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=1860 if args.phase=='sustain' else 1500)
        output=result.stdout.decode(errors='replace');print(output,flush=True)
        name='-'.join(backends)+'-'+str(len(list(directory.glob('*.log'))))+'.log'
        (directory/name).write_bytes(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('Target phase failed; inspect '+name)
        capture_sent=True
    try:
        if args.phase=='prepare':
            run(['reference'],args.install)
            # Fixed whitelist extraction avoids trusting paths from a device TAR.
            archive=subprocess.run([adb,'-s',args.serial,'exec-out','run-as',PACKAGE,'tar','-cf','-',
                                               '-C','files/acceleration',capture_name(args.model)],capture_output=True,check=True,timeout=180).stdout
            capture=directory/capture_name(args.model);capture.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                for member in tar.getmembers():
                    if not member.isfile():continue
                    if not re.fullmatch(re.escape(capture_name(args.model))+r'/(manifest\.json|[0-9]{4}\.npz)',member.name) or member.size>16*1024*1024:
                        raise ValueError('Unexpected capture member')
                    (capture/Path(member.name).name).write_bytes(tar.extractfile(member).read())
            validate_capture(capture,args.model)
            run([*(['qnn_convolution'] if physical else []),'qnn_fp32'])
        elif args.phase=='calibrate':
            for group in range(96):
                run(['qnn_calibrate'],args.install and group==0)
                filename=evidence_name(args.model,'qnn-ranges.json')
                payload=read('acceleration/'+filename);ranges=json.loads(payload)
                if ranges.get('model_role','road')!=args.model:raise ValueError('Calibration role differs')
                (directory/filename).write_bytes(payload)
                print(f"Calibration groups: {len(ranges['groups'])}/{ranges['total_groups']}",flush=True)
                if ranges['complete']:break
            else:raise RuntimeError('Calibration group bound exceeded')
        else:run(['qnn_sustain' if args.phase=='sustain' else 'qnn_quantized'],args.install)
        (directory/'graph-manifest.json').write_bytes(read('model/qnn-graph-manifest.json'))
        success=True
    finally:
        summary={'phase':args.phase,'model_role':args.model,'passed':success,'serial':args.serial,'vehicle_control_enabled':False,
                 'default_backend_changed':False}
        if args.restore_default:
            call('shell','am','force-stop',PACKAGE)
            if physical:
                remote=call('shell','pm','path','ai.comma.openpilot.acceleration').decode().strip().removeprefix('package:')
                actual=call('shell','sha256sum',remote).decode().split()[0]
                expected=hashlib.sha256((ROOT/'artifacts/android/acceleration/qualified-build/apk/debug/app-arm64-v8a-debug.apk').read_bytes()).hexdigest()
                summary.update(cpu_app_sha256=actual,cpu_app_unchanged=actual==expected)
                if actual!=expected:summary['default_app_verification_error']='Installed CPU APK differs; not overwritten automatically'
        (directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({'passed':success,'evidence':str(directory)}),flush=True)


if __name__=='__main__':main()
