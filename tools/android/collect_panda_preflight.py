"""Collect Android preflight evidence without native host helpers or USB traffic to Panda."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--serial', required=True)
  args = parser.parse_args()
  if not re.fullmatch(r'[A-Za-z0-9_-]+', args.serial):
    raise ValueError('Invalid Android serial')
  adb = Path(os.environ['ANDROID_HOME'])/'platform-tools/adb.exe'
  command = [str(adb), '-s', args.serial]
  out = ROOT/'artifacts/android/fold3/panda'
  out.mkdir(parents=True, exist_ok=True)
  for name in ('latest.json', 'usb-test-evidence.json', 'usb-readiness.png'):
    path = 'files/panda/'+name
    size = subprocess.check_output([*command,'shell','run-as','ai.comma.openpilot.sim','stat','-c','%s',path],text=True)
    data = subprocess.check_output([*command,'exec-out','run-as','ai.comma.openpilot.sim','cat',path])
    if len(data) != int(size.strip()):
      raise ValueError('Evidence size mismatch: '+name)
    if name.endswith('.json'):
      json.loads(data)
    elif not data.startswith(b'\x89PNG\r\n\x1a\n'):
      raise ValueError('Invalid UI capture')
    (out/name).write_bytes(data)
  evidence = json.loads((out/'usb-test-evidence.json').read_text())
  suite = ROOT/'tools/android/.cache/fold3/phone-tests.txt'
  text = suite.read_text()
  count = re.search(r'OK \((\d+) tests\)',text)
  if count is None or int(count[1]) < 12 or 'FAILURES' in text:
    raise ValueError('Complete Android suite did not pass')
  protocol = ROOT/'android/app/src/main/assets/panda/protocol.json'
  shutil.copy2(protocol, out/'protocol.json')
  shutil.copy2(suite, out/'phone-tests.txt')
  evidence.update(android_tests_passed=int(count[1]),target_vehicle='Hyundai Ioniq PHEV 2018',
                  candidate_profile='HYUNDAI_IONIQ_PHEV_2019',candidate_verified=False,
                  application_usb_mode='read_only',actuation_allowed=False,
                  protocol_asset_sha256=hashlib.sha256(protocol.read_bytes()).hexdigest())
  (out/'readiness.json').write_text(json.dumps(evidence,indent=2)+'\n')
  print(json.dumps(evidence))


if __name__ == '__main__':
  main()
