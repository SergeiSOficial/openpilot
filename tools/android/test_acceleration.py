"""Install/run the isolated Android benchmark and retain candidate failures.

Reviewed standard-library host orchestration. Only ADB runs on the host; model
inference, native kernels, CL compilation and NNAPI probing run on Android.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shlex
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "ai.comma.openpilot.acceleration"


def bounded_capture(command,*items,timeout=30,on_cancel=None):
    """Keep transport failures as evidence; never accept their partial payload."""
    try:return command(*items,timeout=timeout)
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(items,124,error.stdout or b"",(error.stderr or b"")+b"\nADB command timed out; collection incomplete\n")
    except OSError as error:
        return subprocess.CompletedProcess(items,127,b"",str(error).encode()+b"\n")
    except BaseException:
        if on_cancel is not None:on_cancel()
        raise


def installed_apk_sha256(checked,package):
    paths=checked('shell','pm','path',package).splitlines()
    if len(paths)!=1 or re.fullmatch(r'package:/data/app/[A-Za-z0-9_+~=/.-]+/base\.apk',paths[0]) is None:
        raise RuntimeError('Missing or ambiguous installed APK path: '+package)
    output=checked('shell','sha256sum',shlex.quote(paths[0][8:])).split()
    if not output or re.fullmatch(r'[0-9a-f]{64}',output[0]) is None:raise RuntimeError('Invalid installed APK digest')
    return output[0]


def validate_apk(path):
    """Reject stale Gradle Python archives before submitting them to Android."""
    try:
        with zipfile.ZipFile(path) as archive:
            for name in ('AndroidManifest.xml','classes.dex','resources.arsc'):
                if name not in archive.namelist():raise ValueError('APK is missing '+name)
            with archive.open('AndroidManifest.xml') as manifest:
                if manifest.read(4)!=b'\x03\x00\x08\x00':raise ValueError('APK manifest is not Android binary XML')
            with archive.open('classes.dex') as dex:
                if dex.read(4)!=b'dex\n':raise ValueError('APK is missing DEX bytecode')
            bad=archive.testzip()
            if bad is not None:raise ValueError('APK entry CRC failed: '+bad)
    except (OSError,zipfile.BadZipFile) as error:
        raise ValueError('Invalid APK archive: '+str(path)) from error


def candidate_report(payload,returncode,backend,attempt,model_role="road"):
    """Fail closed when a native abort leaves no fresh JSON report."""
    failure={"passed":False,"backend":backend,"model_role":model_role,"requested_attempt_id":attempt,
             "fresh_report_received":False,"report_returncode":returncode}
    if returncode or not payload.strip():
        return {**failure,"error":"Missing or empty candidate report; inspect instrumentation and crash logs"},False
    try:
        report=json.loads(payload)
    except (ValueError,UnicodeError):
        return {**failure,"error":"Malformed candidate JSON report; inspect retained raw payload and crash logs"},False
    if not isinstance(report,dict) or type(report.get("passed")) is not bool:
        return {**failure,"error":"Malformed candidate report object or passed flag"},False
    if (report.get("attempt_id")!=attempt or report.get("model_role","road")!=model_role
        or report.get("backend")!=backend):
        return {**failure,"error":"No fresh matching benchmark report; inspect retained stale payload"},False
    return {**report,"fresh_report_received":True},True


def qualified_timing(report,fresh,instrumentation_passed):
    if not fresh or not instrumentation_passed:
        return False,"No fresh successful instrumentation report"
    if report.get("cpu_only") is True or report.get("backend")=="qnn_preprocess_cpu":
        return False,"CPU-only operator equivalence does not qualify hardware performance"
    if (report.get("foreground_at_start") is not True or report.get("foreground_at_end") is not True
        or report.get("timing_qualified") is not True):
        return False,"Unlocked interactive foreground activity was not verified at both test boundaries"
    return True,None


def main():
    from experiment_lifecycle import cleanup_experiments
    parser=argparse.ArgumentParser()
    parser.add_argument("--serial",required=True)
    parser.add_argument("--install",action="store_true")
    parser.add_argument("--modern-qnn",action="store_true")
    parser.add_argument("--qnn-experiment",action="store_true")
    parser.add_argument("--modern-cpu-emulator",action="store_true")
    parser.add_argument("--model",choices=("road","cabin"),default="road")
    parser.add_argument("--capture",type=Path,help="explicit role-bound exported corpus for the isolated QNN experiment")
    parser.add_argument("--backends",nargs="+",default=["capabilities","reference","cpu_tuned","cpu","nnapi","gpu_onnx"],
                        choices=["capabilities","reference","cpu_tuned","cpu_parallel","cpu_parallel_v82","cpu","xnnpack","nnapi","qnn","qnn_convolution","qnn_fp32","qnn_calibrate","qnn_quantized","qnn_sustain","qnn_boundary","qnn_intermediate","qnn_preprocess","qnn_preprocess_cpu","gpu","gpu_onnx","gpu_hybrid"])
    parser.add_argument("--threads",type=int,choices=range(1,5),default=2)
    parser.add_argument("--frames",type=int,choices=range(1,61),default=60,help="Short GPU diagnostics never satisfy the full 60-frame sequence gate")
    parser.add_argument("--candidate-timeout-seconds",type=int,default=1200)
    args=parser.parse_args()
    if args.frames!=60 and any(name not in ('gpu','gpu_onnx','gpu_hybrid') for name in args.backends):
        parser.error('Short frame counts are supported only for explicit GPU diagnostics')
    global PACKAGE
    if args.qnn_experiment:PACKAGE="ai.comma.openpilot.qnn"
    if (args.model=="cabin" or args.capture is not None) and not args.qnn_experiment:
        parser.error("Model/capture experiments require the isolated QNN package")
    if args.capture is not None:
        from test_qnn_experiment import validate_capture
        validate_capture(args.capture,args.model)
    if not 30<=args.candidate_timeout_seconds<=1800:parser.error("Candidate timeout must be between 30 and 1800 seconds")
    if any(n in ("qnn","qnn_convolution","qnn_quantized","qnn_sustain","qnn_boundary","qnn_intermediate","qnn_preprocess") for n in args.backends) and not args.modern_qnn:parser.error("HTP execution requires the --modern-qnn build")
    if "qnn_preprocess_cpu" in args.backends and (not args.qnn_experiment or not (args.modern_qnn or args.modern_cpu_emulator)):
        parser.error("CPU preprocessing requires the isolated QNN experiment and pinned modern runtime")
    if not re.fullmatch(r"[A-Za-z0-9_-]+",args.serial):parser.error("Invalid device serial")
    sdk=Path(os.environ["ANDROID_HOME"])
    adb=sdk/("platform-tools/adb.exe" if os.name=="nt" else "platform-tools/adb")
    def command(*items,timeout=120):
        return subprocess.run([str(adb),"-s",args.serial,*items],capture_output=True,timeout=timeout)
    def checked(*items):
        result=command(*items)
        if result.returncode:raise RuntimeError(result.stderr.decode(errors="replace"))
        return result.stdout.decode().strip()
    model=checked("shell","getprop","ro.product.model")
    emulator=args.serial.startswith("emulator-")
    if emulator and args.modern_qnn:parser.error("The QNN build targets ARM64 hardware")
    if args.modern_cpu_emulator and (not emulator or not args.qnn_experiment or any(n not in ('reference','qnn_fp32','qnn_calibrate','qnn_preprocess_cpu') for n in args.backends)):
        parser.error('The modern CPU emulator build only supports reference, calibration and CPU preprocessing diagnostics')
    if not emulator and not model.startswith("SM-F926"):raise RuntimeError("Select the authorized Fold 3 explicitly")
    initial_state=checked("shell","cmd","device_state","print-state")
    if not emulator and initial_state!="0":raise RuntimeError("Keep the phone folded")
    size=checked("shell","wm","size")
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory=ROOT/"artifacts/android/acceleration"/args.serial/stamp
    directory.mkdir(parents=True,exist_ok=True)
    print("Evidence: "+str(directory),flush=True)
    (directory/"thermal-before.txt").write_text(checked("shell","dumpsys","thermalservice"),encoding="utf-8")
    if args.install:
        abi="x86_64" if emulator else "arm64-v8a"
        build=ROOT/("artifacts/android/qnn-experiment-emulator/build/apk" if args.modern_cpu_emulator else "artifacts/android/qnn-experiment/build/apk" if args.qnn_experiment else "artifacts/android/qnn/build/apk" if args.modern_qnn else "artifacts/android/acceleration/build/apk")
        apk=build/"debug"/("app-debug.apk" if args.modern_qnn or args.modern_cpu_emulator else f"app-{abi}-debug.apk")
        test=build/"androidTest/debug/app-debug-androidTest.apk"
        for path in (apk,test):
            validate_apk(path)
            result=command("install","-r",str(path),timeout=300)
            if result.returncode:raise RuntimeError(result.stdout.decode(errors="replace")+result.stderr.decode(errors="replace"))
        (directory/"apk.json").write_text(json.dumps({"sha256":hashlib.sha256(apk.read_bytes()).hexdigest(),"bytes":apk.stat().st_size,
                                                  "test_apk_sha256":hashlib.sha256(test.read_bytes()).hexdigest(),
                                                  "modern_qnn":args.modern_qnn,"model":model,"model_role":args.model,"serial":args.serial},indent=2)+"\n")
    actual=installed_apk_sha256(checked,PACKAGE);actual_test=installed_apk_sha256(checked,PACKAGE+'.test')
    apk_identity_path=directory/'apk.json'
    apk_identity=json.loads(apk_identity_path.read_text()) if apk_identity_path.exists() else {'model':model,'model_role':args.model,'serial':args.serial,'modern_qnn':args.modern_qnn}
    if args.install and (actual!=apk_identity['sha256'] or actual_test!=apk_identity['test_apk_sha256']):
        raise RuntimeError('Installed APK differs from the structurally verified candidate')
    apk_identity.update(sha256=actual,test_apk_sha256=actual_test,actual_installed_bytes_verified=True)
    apk_identity_path.write_text(json.dumps(apk_identity,indent=2)+'\n')
    if args.capture is not None:
        from test_qnn_experiment import import_capture
        import_capture(adb,args.serial,args.capture,args.model)
    results={}
    for backend in args.backends:
        clean=cleanup_experiments(command,directory,backend+'-before')
        status=clean['after']['thermal_status']
        if type(status) is not int or status>=3:raise RuntimeError('Thermal precondition prevents accelerator warmup')
        attempt=uuid.uuid4().hex
        (directory/f"{backend}-{args.threads}-request.json").write_text(json.dumps({
            "attempt_id":attempt,"backend":backend,"model_role":args.model,"threads":args.threads,
            "frames":args.frames,
            "candidate_timeout_seconds":args.candidate_timeout_seconds,"started_utc":datetime.now(timezone.utc).isoformat()},indent=2)+"\n")
        result=bounded_capture(command,"shell","am","instrument","-w","-e","class","ai.comma.openpilot.sim.AccelerationTest",
                           "-e","attemptId",attempt,
                           "-e","backend",backend,"-e","model_role",args.model,"-e","threads",str(args.threads),"-e","frames",str(args.frames),
                           PACKAGE+".test/androidx.test.runner.AndroidJUnitRunner",timeout=args.candidate_timeout_seconds,
                           on_cancel=lambda:cleanup_experiments(command,directory,backend+'-cancel'))
        if result.returncode:bounded_capture(command,"shell","am","force-stop",PACKAGE)
        (directory/f"{backend}-{args.threads}-tests.txt").write_bytes(result.stdout+result.stderr)
        prefix="" if args.model=="road" else "cabin-"
        payload=bounded_capture(command,"exec-out","run-as",PACKAGE,"cat",f"files/acceleration/{prefix}{backend}-{args.threads}.json")
        report,fresh=candidate_report(payload.stdout,payload.returncode,backend,attempt,args.model)
        instrumentation_passed=result.returncode==0 and b"OK (1 test)" in result.stdout
        if not fresh and payload.stdout:(directory/f"{backend}-{args.threads}-stale-raw.bin").write_bytes(payload.stdout)
        if payload.stderr:(directory/f"{backend}-{args.threads}-report-stderr.txt").write_bytes(payload.stderr)
        results[backend]=instrumentation_passed and fresh and report.get("passed") is True
        report["passed"]=results[backend]
        report["instrumentation_passed"]=instrumentation_passed
        report['requested_frames']=args.frames
        report['sequence_60_frames_passed']=results[backend] and type(report.get('frames')) is int and report['frames']>=60
        report["timing_qualified"],timing_reason=qualified_timing(report,fresh,instrumentation_passed)
        if timing_reason:report["timing_unqualified_reason"]=timing_reason
        # Persist the primary result before optional logcat/USB operations.
        report_path=directory/f"{backend}-{args.threads}.json"
        report_path.write_text(json.dumps(report,indent=2)+"\n")
        cleanup_experiments(command,directory,backend+'-after')
        report['diagnostic_collection']={}
        if backend.startswith(("qnn","gpu")) and type(report.get("pid")) is int and report["pid"]>0:
            log=bounded_capture(command,"logcat","-d","--pid",str(report["pid"]),"-t","6000",timeout=30)
            (directory/f"{backend}-{args.threads}-logcat.txt").write_bytes(log.stdout+log.stderr)
            report['diagnostic_collection']['logcat_complete']=log.returncode==0
        if backend.startswith(("qnn","gpu")) and not results[backend]:
            crash=bounded_capture(command,"logcat","-d","-b","crash","-t","240",timeout=30)
            (directory/f"{backend}-{args.threads}-crash.txt").write_bytes(crash.stdout+crash.stderr)
            report['diagnostic_collection']['crash_complete']=crash.returncode==0
        report_path.write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps({"backend":backend,"passed":results[backend],"timing":report.get("timing"),
                          "timing_qualified":report.get("timing_qualified",False),
                          "error":next(iter(str(report.get("error") or "").splitlines()),"")}),flush=True)
        if backend=="reference" and not results[backend]:break
    final={"completed":False,"candidates":results,"model":model,"model_role":args.model,"physical_device":not emulator,
           "vehicle_control_verified":False}
    try:
        if checked("shell","cmd","device_state","print-state")!=initial_state or checked("shell","wm","size")!=size:
            raise RuntimeError("Device display state changed during benchmark")
        (directory/"thermal-after.txt").write_text(checked("shell","dumpsys","thermalservice"),encoding="utf-8")
        (directory/"build.json").write_text(checked("exec-out","run-as",PACKAGE,"cat","files/acceleration-build.json"),encoding="utf-8")
        final['completed']=True
    except (subprocess.TimeoutExpired,RuntimeError,OSError) as error:
        final['postflight_error']=str(error)
        for backend in results:
            path=directory/f"{backend}-{args.threads}.json"
            report=json.loads(path.read_text())
            report.update(postflight_complete=False,timing_qualified=False,timing_unqualified_reason='Incomplete device postflight: '+str(error))
            path.write_text(json.dumps(report,indent=2)+"\n")
    (directory/"summary.json").write_text(json.dumps(final,indent=2)+"\n")
    if not final['completed'] or not all(results.values()):raise SystemExit(1)


if __name__=="__main__":main()
