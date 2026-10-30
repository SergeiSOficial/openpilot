"""Explicit Fold3 on-target live test and text-only evidence collection.

Host execution uses standard-library Python and trusted adb only. It never runs
model code, compilers, generated native host helpers, FFI or JIT on the host.
"""
from pathlib import Path
import argparse
import json
import re
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "com.samsung.android.openpilot.shadow"


def main():
  from experiment_lifecycle import cleanup_experiments
  parser = argparse.ArgumentParser()
  parser.add_argument("--serial", required=True)
  parser.add_argument("--mode", choices=("gpucheck","drivergpucheck","live","cabin","capture"), default="live")
  parser.add_argument("--duration", type=int, default=1200)
  parser.add_argument("--timeout", type=int, default=1800)
  parser.add_argument("--seat", choices=("left","right","unset"), default="right", help="Explicit bench setting; user selected right-hand drive")
  parser.add_argument("--collect", help="Collect an existing session without starting anything")
  args = parser.parse_args()
  if not re.fullmatch(r"[A-Za-z0-9_-]+",args.serial) or args.serial.startswith("emulator-"):
    raise ValueError("Select the physical Fold3 explicitly")

  def adb(*command,check=True,timeout=30):
    return subprocess.run(["adb","-s",args.serial,*command],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout,check=check)

  def cleanup_command(*command,timeout=20):
    return subprocess.run(['adb','-s',args.serial,*command],capture_output=True,timeout=timeout)

  def shell(*command,check=True):
    return adb("shell",shlex.join(command),check=check)

  def read(name):
    result=shell("run-as",PACKAGE,"cat",name,check=False)
    return result.stdout if result.returncode==0 else ""

  model=shell("getprop","ro.product.model").stdout.strip()
  if model!="SM-F926B":
    raise RuntimeError("Expected the selected SM-F926B, got "+model)
  if not args.collect:
    if "mWakefulness=Awake" not in shell("dumpsys","power").stdout:
      raise RuntimeError("Unlock the Fold3 and leave it awake for foreground validation")
    policy=shell("dumpsys","window","policy").stdout
    if re.search(r"(?:mIsShowing|showing)=true",policy):
      raise RuntimeError("Unlock the Fold3; locked-screen timing cannot qualify foreground operation")
    if shell("cmd","device_state","print-state").stdout.strip()!="0":
      raise RuntimeError("Folded-device validation requires the phone to stay folded")
    previous_session=read('files/last-live-session.txt').strip()
    cleanup=cleanup_experiments(cleanup_command,ROOT/'artifacts/android/experiment-cleanup','live-before')
    shell("am","start","-W","-n",PACKAGE+"/ai.comma.openpilot.sim.MainActivity",
          "--es","mode",args.mode,"--es","driver_seat",args.seat,"--ez","autostart","true","--ei","seconds",str(args.duration))
    # Activity/worker startup is asynchronous, especially under joint host load.
    # Never attribute an old completed/failed report to this new request.
    fresh_deadline=time.monotonic()+30
    while True:
      started_session=read('files/last-live-session.txt').strip()
      if re.fullmatch(r'[a-f0-9]{16}',started_session) and started_session!=previous_session:break
      if time.monotonic()>=fresh_deadline:raise RuntimeError('No fresh live session appeared after launch')
      time.sleep(.25)
  session=args.collect or read("files/last-live-session.txt").strip()
  if not re.fullmatch(r"[a-f0-9]{16}",session or ""):
    raise RuntimeError("No valid live session was started")
  out=ROOT/"artifacts/android/live"/session
  out.mkdir(parents=True,exist_ok=True)
  if not args.collect:(out/'before-cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n')
  print("Session "+session+" mode="+args.mode,flush=True)
  deadline=time.monotonic()+(0 if args.collect else args.timeout)
  previous=None
  samples=out/"samples.jsonl"
  while True:
    for name in ("progress.json","camera.json","verification.json","sensors.json","sensor-cleanup.json"):
      raw=read("files/s/"+session+"/"+name)
      if raw:
        (out/name).write_text(raw,encoding="utf-8")
    try:
      progress=json.loads((out/"progress.json").read_text())
    except (FileNotFoundError,json.JSONDecodeError):
      progress={}
    key=(progress.get("state"),progress.get("stage"))
    if not args.collect and progress:
      # Text probabilities, counters and timings only. Never persist camera pixels.
      with samples.open("a",encoding="utf-8") as log:
        log.write(json.dumps(progress,allow_nan=False)+"\n")
    if key!=previous:
      print(json.dumps({"state":key[0],"stage":key[1],"elapsed_seconds":progress.get("elapsed_seconds"),"error":progress.get("error")}),flush=True)
      previous=key
    if args.collect or progress.get("state") in ("completed","failed","stopped"):
      break
    if time.monotonic()>deadline:
      shell("am","force-stop",PACKAGE)
      raise TimeoutError("On-phone live test exceeded its bound; existing evidence retained at "+str(out))
    time.sleep(2)
  if not args.collect:cleanup_experiments(cleanup_command,out,'live-after')
  (out/"logcat.txt").write_text(adb("logcat","-d","-t","4000").stdout,encoding="utf-8")
  (out/"crash.txt").write_text(adb("logcat","-b","crash","-d","-t","100").stdout,encoding="utf-8")
  print(json.dumps({"evidence":str(out),"state":progress.get("state"),"frames":progress.get("frames"),
                    "driver_frames":progress.get("driver_frames"),"verification_passed":progress.get("verification_passed"),
                    "road_timing":progress.get("road_timing"),"driver_timing":progress.get("driver_timing")}),flush=True)
  if progress.get("state")=="failed":
    raise SystemExit(1)
  if not args.collect and progress.get("state")!="completed":
    raise SystemExit("Session stopped before completion; evidence retained without a pass")


if __name__=="__main__":
  main()
