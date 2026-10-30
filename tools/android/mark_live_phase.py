"""Collect text-only model observations during a user-confirmed bench condition."""
import argparse
import json
from pathlib import Path
import re
import statistics
import subprocess
import time


def main():
  parser=argparse.ArgumentParser()
  parser.add_argument("--serial",required=True)
  parser.add_argument("--session",required=True)
  parser.add_argument("--phase",required=True)
  parser.add_argument("--seconds",type=int,default=10)
  args=parser.parse_args()
  if not re.fullmatch(r"[A-Za-z0-9_-]+",args.serial) or not re.fullmatch(r"[a-f0-9]{16}",args.session):
    raise ValueError("Explicit serial and session required")
  if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}",args.phase) or not 1<=args.seconds<=60:
    raise ValueError("Invalid phase or observation duration")
  samples=[];previous=None;deadline=time.monotonic()+args.seconds
  while time.monotonic()<deadline:
    result=subprocess.run(["adb","-s",args.serial,"shell","run-as","com.samsung.android.openpilot.shadow","cat",
                           "files/s/"+args.session+"/progress.json"],capture_output=True,text=True,timeout=15,check=True)
    report=json.loads(result.stdout)
    if report.get("state")!="running":raise RuntimeError("Bench session is not running")
    if report.get("driver_frame_id")!=previous and report.get("driver"):
      samples.append({k:report.get(k) for k in ("elapsed_seconds","driver_frame_id","driver_capture_timestamp_ns",
          "driver","driver_frame_age_ms","driver_visibility","driver_fresh_outputs_last_second","driver_monitoring_reason")})
      samples[-1]["capture"]=report.get("camera",{}).get("native",{}).get("streams",[])
      previous=report["driver_frame_id"]
    time.sleep(.4)
  if not samples:raise RuntimeError("No fresh driver observations")
  values={key:[sample["driver"][key] for sample in samples] for key in samples[0]["driver"] if key!="head_orientation"}
  record={"phase":args.phase,"user_confirmed_condition":True,"utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
          "samples":samples,"mean":{key:statistics.fmean(value) for key,value in values.items()},
          "mean_head_orientation":[statistics.fmean(s["driver"]["head_orientation"][axis] for s in samples) for axis in range(3)],
          "mean_cabin_luma":statistics.fmean(next((c["luma_mean"] for c in s["capture"] if c["stream"]==1),0) for s in samples),
          "acceptance":"bench_observation_only"}
  directory=Path(__file__).resolve().parents[2]/"artifacts/android/live"/args.session
  directory.mkdir(parents=True,exist_ok=True)
  with (directory/"bench-phases.jsonl").open("a",encoding="utf-8") as stream:stream.write(json.dumps(record)+"\n")
  print(json.dumps({k:record[k] for k in ("phase","mean","mean_head_orientation","mean_cabin_luma","acceptance")}))


if __name__=="__main__":main()
