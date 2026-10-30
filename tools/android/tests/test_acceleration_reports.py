"""Reviewed stdlib-only transport tests; no ADB/native/model execution."""
import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
import zipfile
import subprocess


spec=importlib.util.spec_from_file_location("acceleration_report_policy",Path(__file__).resolve().parents[1]/"test_acceleration.py")
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class CandidateReportTest(unittest.TestCase):
  def test_user_cancellation_releases_the_active_experiment_and_remains_a_cancellation(self):
    stopped=[]
    def cancelled(*items,**kwargs):raise KeyboardInterrupt()
    with self.assertRaises(KeyboardInterrupt):
      tool.bounded_capture(cancelled,'instrument',on_cancel=lambda:stopped.append(True))
    self.assertEqual(stopped,[True])

  def test_installed_apk_digest_comes_from_actual_android_file(self):
    calls=[]
    def checked(*items):
      calls.append(items)
      return 'package:/data/app/~~abc=/package-xyz/lib/../base.apk' if items[1]=='pm' else 'a'*64+'  /data/app/actual/base.apk'
    self.assertEqual(tool.installed_apk_sha256(checked,'ai.comma.openpilot.acceleration'),'a'*64)
    self.assertEqual(calls[1][1],'sha256sum')

  def test_ambiguous_paths_shell_metacharacters_and_bad_digests_are_rejected(self):
    for path in ('','package:/data/app/a/base.apk\npackage:/data/app/b/base.apk','package:/data/app/a$(command)/base.apk'):
      with self.subTest(path=path):
        with self.assertRaises(RuntimeError):tool.installed_apk_sha256(lambda *items:path,'app')
    with self.assertRaises(RuntimeError):tool.installed_apk_sha256(lambda *items:'package:/data/app/a/base.apk' if items[1]=='pm' else 'not-a-hash','app')

  def test_transport_timeout_retains_partial_bytes_and_rejects_even_valid_partial_json(self):
    payload=b'{"passed":true,"backend":"gpu","attempt_id":"attempt-unit-test","model_role":"road"}'
    def timeout(*items,**kwargs):raise subprocess.TimeoutExpired(items,kwargs['timeout'],output=payload,stderr=b'USB disappeared')
    result=tool.bounded_capture(timeout,'exec-out',timeout=3)
    self.assertEqual(result.returncode,124);self.assertEqual(result.stdout,payload)
    self.assertIn(b'USB disappeared',result.stderr);self.assertIn(b'incomplete',result.stderr)
    report,fresh=self.read(result.stdout,result.returncode)
    self.assertFalse(fresh);self.assertFalse(report['passed'])

  def test_transport_oserror_is_retained_and_success_preserves_the_result(self):
    def failed(*items,**kwargs):raise OSError('ADB unavailable')
    result=tool.bounded_capture(failed,'logcat')
    self.assertEqual(result.returncode,127);self.assertIn(b'ADB unavailable',result.stderr)
    expected=subprocess.CompletedProcess(['read'],0,b'valid',b'')
    self.assertIs(tool.bounded_capture(lambda *items,**kwargs:expected,'read'),expected)

  def test_python_zip_at_apk_path_is_rejected_before_adb(self):
    with tempfile.TemporaryDirectory() as directory:
      path=Path(directory)/'app.apk'
      with zipfile.ZipFile(path,'w') as archive:archive.writestr('android_runtime/gpu.pyc',b'python bytecode')
      with self.assertRaisesRegex(ValueError,'AndroidManifest'):tool.validate_apk(path)

  def test_truncated_and_non_apk_archive_headers_are_rejected(self):
    with tempfile.TemporaryDirectory() as directory:
      path=Path(directory)/'app.apk';path.write_bytes(b'PK truncated')
      with self.assertRaisesRegex(ValueError,'Invalid APK'):tool.validate_apk(path)
      with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('AndroidManifest.xml',b'<manifest/>')
        archive.writestr('classes.dex',b'dex\n')
        archive.writestr('resources.arsc',b'')
      with self.assertRaisesRegex(ValueError,'binary XML'):tool.validate_apk(path)

  def read(self,payload,code=0,role="road"):
    return tool.candidate_report(payload,code,"gpu","attempt-unit-test",role)

  def test_empty_missing_and_whitespace_reports_fail_without_json_decode_error(self):
    for payload,code in ((b"",0),(b" \r\n",0),(b"run-as failed",1)):
      with self.subTest(payload=payload,code=code):
        report,fresh=self.read(payload,code)
        self.assertFalse(fresh);self.assertIs(report["passed"],False)
        self.assertIn("Missing or empty",report["error"])

  def test_malformed_partial_and_non_utf8_payloads_fail_closed(self):
    for payload in (b'{"passed":',b'not JSON',b'\xff\xfe\xff',b'[]',b'null',b'true'):
      with self.subTest(payload=payload):
        report,fresh=self.read(payload)
        self.assertFalse(fresh);self.assertIs(report["passed"],False)

  def test_attempt_backend_and_role_must_all_match(self):
    good={"passed":True,"backend":"gpu","attempt_id":"attempt-unit-test","model_role":"road"}
    for key,value in (("backend","reference"),("attempt_id","old-attempt"),("model_role","cabin"),("passed",1),("passed","true")):
      payload=dict(good);payload[key]=value
      with self.subTest(key=key,value=value):
        report,fresh=self.read(json.dumps(payload).encode())
        self.assertFalse(fresh);self.assertIs(report["passed"],False)

  def test_fresh_success_and_fresh_target_failure_remain_distinct(self):
    for passed in (False,True):
      payload={"passed":passed,"backend":"gpu","attempt_id":"attempt-unit-test","model_role":"cabin"}
      report,fresh=self.read(json.dumps(payload).encode(),role="cabin")
      self.assertTrue(fresh);self.assertIs(report["passed"],passed)

  def test_timing_requires_verified_foreground_and_successful_fresh_run(self):
    good={"foreground_at_start":True,"foreground_at_end":True,"timing_qualified":True}
    self.assertEqual(tool.qualified_timing(good,True,True),(True,None))
    for field in good:
      for value in (False,None,1,"true"):
        report=dict(good);report[field]=value
        with self.subTest(field=field,value=value):
          qualified,reason=tool.qualified_timing(report,True,True)
          self.assertFalse(qualified);self.assertIn("foreground",reason)
    self.assertFalse(tool.qualified_timing(good,False,True)[0])
    self.assertFalse(tool.qualified_timing(good,True,False)[0])

  def test_successful_cpu_operator_check_never_qualifies_hardware_timing(self):
    report={"passed":True,"cpu_only":True,"backend":"qnn_preprocess_cpu",
            "foreground_at_start":True,"foreground_at_end":True,"timing_qualified":True}
    qualified,reason=tool.qualified_timing(report,True,True)
    self.assertFalse(qualified)
    self.assertIn("CPU-only",reason)


if __name__=="__main__":unittest.main()
