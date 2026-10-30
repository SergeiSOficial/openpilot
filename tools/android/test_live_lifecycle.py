"""On-phone lifecycle fault checks using stdlib Python and trusted adb only.

No camera-service dumpsys preflight, images, host FFI/JIT or native helpers.
The camera permission is restored and the app is stopped on every exit.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

PACKAGE="com.samsung.android.openpilot.shadow"
ROOT=Path(__file__).resolve().parents[2]


def main():
  parser=argparse.ArgumentParser()
  parser.add_argument("--serial",required=True)
  args=parser.parse_args()
  if not re.fullmatch(r"[A-Za-z0-9_-]+",args.serial) or args.serial.startswith("emulator-"):
    raise ValueError("Select the physical Fold3 explicitly")
  def shell(*words,check=True):
    result=subprocess.run(["adb","-s",args.serial,"shell",shlex.join(words)],capture_output=True,text=True,
                          encoding="utf-8",errors="replace",timeout=30,check=check)
    return result.stdout.strip()
  def read(session,name):
    raw=shell("run-as",PACKAGE,"cat","files/s/"+session+"/"+name,check=False)
    try:return json.loads(raw)
    except json.JSONDecodeError:return {}
  if shell("getprop","ro.product.model")!="SM-F926B" or shell("cmd","device_state","print-state")!="0":
    raise RuntimeError("Keep the selected SM-F926B folded")
  if ("mWakefulness=Awake" not in shell("dumpsys","power") or
      re.search(r"(?:mIsShowing|showing)=true",shell("dumpsys","window","policy"))):
    raise RuntimeError("Unlock the Fold3 for foreground lifecycle validation")
  out=ROOT/"artifacts/android/live"/("lifecycle-"+time.strftime("%Y%m%d-%H%M%S"))
  out.mkdir(parents=True,exist_ok=True)
  results=[]
  completed=False
  failure=None
  fixed_before=shell("wm","fixed-to-user-rotation")
  rotation_before=shell("wm","user-rotation")
  def record(name,session,passed,details):
    item={"case":name,"session":session,"passed":passed,**details};results.append(item)
    (out/"result.json").write_text(json.dumps({"checks":results,"completed":False,"passed":False},indent=2))
    print(json.dumps({"case":name,"session":session,"passed":passed}),flush=True)
    if not passed:raise RuntimeError("Lifecycle check failed: "+name+" "+str(details))
  def start(mode="cabin"):
    previous_session=shell("run-as",PACKAGE,"cat","files/last-live-session.txt",check=False)
    shell("am","force-stop",PACKAGE)
    cool_deadline=time.monotonic()+120
    while True:
      thermal=re.search(r"Thermal Status:\s*(\d+)",shell("dumpsys","thermalservice"))
      if thermal is None:raise RuntimeError("No measured thermal status for lifecycle precondition")
      if int(thermal.group(1))<=1:break
      if time.monotonic()>cool_deadline:raise TimeoutError("Phone did not cool for repeatable lifecycle startup")
      time.sleep(2)
    shell("am","start","-W","-n",PACKAGE+"/ai.comma.openpilot.sim.MainActivity","--es","mode",mode,
          "--es","driver_seat","right","--ez","autostart","true","--ei","seconds","120")
    fresh_deadline=time.monotonic()+30
    while True:
      session=shell("run-as",PACKAGE,"cat","files/last-live-session.txt",check=False)
      if re.fullmatch(r"[a-f0-9]{16}",session) and session!=previous_session:break
      if time.monotonic()>=fresh_deadline:raise RuntimeError("No fresh lifecycle session after launch")
      time.sleep(.25)
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
      camera,progress=read(session,"camera.json"),read(session,"progress.json")
      if camera.get("state")=="failed" or progress.get("state")=="failed":
        raise RuntimeError("Startup failed: "+str(camera.get("error",progress.get("error"))))
      sensors=progress.get("sensors",{})
      front_ready=progress.get("driver_frames",0)>=5 or (progress.get("thermal_action")=="paused" and bool(progress.get("driver_initialization")))
      if camera.get("state")=="running" and sensors.get("sensor_inputs_healthy") is True and (front_ready if mode=="cabin" else progress.get("fresh_capture_pairs",progress.get("frames",0))>=3):
        return session,progress
      time.sleep(.3)
    raise TimeoutError("Live startup did not deliver fresh inputs")
  def stopped(session):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
      camera=read(session,"camera.json")
      appops=shell("cmd","appops","get",PACKAGE,"CAMERA",check=False)
      sensor_pid=shell("pidof",PACKAGE+":sensord",check=False)
      if camera.get("state")=="stopped" and "running" not in appops.lower() and not sensor_pid:return camera,appops
      time.sleep(.3)
    return read(session,"camera.json"),appops
  try:
    # Three fresh process launches, without touching media.camera/dumpsys.
    for index in range(3):
      session,progress=start()
      record("cold_process_launch_"+str(index+1),session,True,{"driver_frames":progress["driver_frames"],"driver_seat":progress.get("driver_seat"),"thermal_action":progress.get("thermal_action"),"model_throughput_qualified":False})
    shell("am","start","-a","android.intent.action.MAIN","-c","android.intent.category.HOME")
    camera,appops=stopped(session)
    record("background_releases_camera",session,camera.get("state")=="stopped" and "running" not in appops.lower(),{"camera":camera,"camera_appop":appops})
    shell("wm","fixed-to-user-rotation","enabled")
    shell("wm","user-rotation","lock","1")
    session,_=start()
    shell("wm","user-rotation","lock","3")
    camera,appops=stopped(session)
    record("rotation_releases_camera",session,camera.get("state")=="stopped" and "running" not in appops.lower(),{"camera":camera,"camera_appop":appops})
    shell("wm","user-rotation","free")
    shell("wm","fixed-to-user-rotation",fixed_before)
    session,_=start()
    pid=shell("pidof",PACKAGE+":live")
    if not re.fullmatch(r"[0-9]+",pid):raise RuntimeError("Invalid live worker pid")
    shell("run-as",PACKAGE,"kill","-9",pid)
    camera,appops=stopped(session)
    record("worker_death_releases_camera",session,camera.get("state")=="stopped" and "running" not in appops.lower(),{"camera":camera,"camera_appop":appops})
    session,_=start()
    pid=shell("pidof",PACKAGE+":sensord")
    if not re.fullmatch(r"[0-9]+",pid):raise RuntimeError("Invalid sensor worker pid")
    shell("run-as",PACKAGE,"kill","-9",pid)
    camera,appops=stopped(session)
    record("sensor_death_releases_camera",session,camera.get("state")=="stopped" and "running" not in appops.lower(),{"camera":camera,"camera_appop":appops})
    session,_=start()
    pid=shell("pidof",PACKAGE+":camerad")
    if not re.fullmatch(r"[0-9]+",pid):raise RuntimeError("Invalid capture worker pid")
    shell("run-as",PACKAGE,"kill","-9",pid)
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
      appops=shell("cmd","appops","get",PACKAGE,"CAMERA",check=False)
      progress=read(session,"progress.json")
      if progress.get("state")=="failed" and "running" not in appops.lower():break
      time.sleep(.3)
    record("capture_process_death_is_reported",session,progress.get("state")=="failed" and "running" not in appops.lower(),{"progress":progress,"camera_appop":appops})
    session,_=start()
    shell("pm","revoke",PACKAGE,"android.permission.CAMERA")
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
      camera=read(session,"camera.json")
      appops=shell("cmd","appops","get",PACKAGE,"CAMERA",check=False)
      if camera.get("state") in ("stopped","failed") and "running" not in appops.lower():break
      time.sleep(.3)
    pids=shell("pidof",PACKAGE+":camerad",check=False)
    # Android may rebind an idle service process. Resource release is established
    # by the terminal capture state and absence of an active CAMERA AppOp.
    record("permission_revocation_releases_camera",session,camera.get("state") in ("stopped","failed") and "running" not in appops.lower(),{"camera_pid":pids,"camera":camera,"camera_appop":appops})
    shell("pm","grant",PACKAGE,"android.permission.CAMERA")
    session,progress=start()
    record("resume_after_permission_restore",session,bool(progress.get("driver_initialization")),{"driver_frames":progress["driver_frames"],"thermal_action":progress.get("thermal_action"),"model_throughput_qualified":False})
    # Rear startup is a separate gate; never use a shell camera preflight.
    for index in range(3):
      session,progress=start("live")
      record("rear_pair_cold_process_launch_"+str(index+1),session,True,{"camera":read(session,"camera.json"),"progress":progress})
    completed=True
  except BaseException as error:
    failure=str(error)
    raise
  finally:
    (out/"result.json").write_text(json.dumps({"checks":results,"completed":completed,"passed":completed and all(x["passed"] for x in results),"error":failure},indent=2))
    shell("pm","grant",PACKAGE,"android.permission.CAMERA",check=False)
    shell("wm","fixed-to-user-rotation",fixed_before,check=False)
    previous_lock=re.search(r"lock\s+(\d)",rotation_before)
    if previous_lock:shell("wm","user-rotation","lock",previous_lock.group(1),check=False)
    else:shell("wm","user-rotation","free",check=False)
    shell("am","force-stop",PACKAGE,check=False)
    print("Evidence: "+str(out),flush=True)


if __name__=="__main__":main()
