"""Stdlib fake-ADB tests; never terminate a real host/device process."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('experiment_cleanup',Path(__file__).resolve().parents[1]/'experiment_lifecycle.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)


class CleanupTest(unittest.TestCase):
  def fake(self,*,linger=False,fail=False,missing_memory=False):
    calls=[];alive={p:100+i for i,p in enumerate(policy.PACKAGES)}
    def command(*items,timeout=20):
      calls.append(items)
      if items[:3]==('shell','am','force-stop'):
        if fail:return subprocess.CompletedProcess(items,1,b'',b'USB disappeared')
        if not linger:alive.pop(items[3],None)
        text=''
      elif items[:2]==('shell','ps'):
        text='PID NAME\n1 unrelated.app\n'+''.join(str(pid)+' '+name+':worker\n' for name,pid in alive.items())
      elif items[:2]==('shell','cat'):text='MemFree: 1024 kB\r\n'+('' if missing_memory else 'MemAvailable: 4096 kB\r\n')
      elif items[:3]==('shell','dumpsys','thermalservice'):text='Thermal Status: 0\n'
      elif items[:3]==('shell','dumpsys','meminfo'):text='TOTAL PSS: 12345\n'
      else:raise AssertionError(items)
      return subprocess.CompletedProcess(items,0,text.encode(),b'')
    return command,calls

  def test_only_allowlisted_apps_are_stopped_and_memory_evidence_is_retained(self):
    command,calls=self.fake()
    with tempfile.TemporaryDirectory() as directory:
      report=policy.cleanup_experiments(command,directory,'short-before')
      self.assertTrue(report['completed']);self.assertFalse(report['after']['processes'])
      self.assertEqual(report['before']['memory_kib']['MemAvailable'],4096)
      self.assertEqual(json.loads((Path(directory)/'short-before-cleanup.json').read_text()),report)
    self.assertEqual([c[3] for c in calls if c[:3]==('shell','am','force-stop')],list(policy.PACKAGES))
    self.assertFalse(any('kill' in c or 'drop_caches' in c for c in calls))

  def test_lingering_process_or_transport_failure_prevents_next_experiment(self):
    for options in ({'linger':True},{'fail':True},{'missing_memory':True}):
      with self.subTest(options=options),tempfile.TemporaryDirectory() as directory:
        command,_=self.fake(**options)
        with self.assertRaises((RuntimeError,ValueError)):policy.cleanup_experiments(command,directory,'blocked',wait_seconds=0)
        report=json.loads((Path(directory)/'blocked-cleanup.json').read_text())
        self.assertFalse(report['completed']);self.assertIn('error',report)
        self.assertEqual(set(report['force_stop']),set(policy.PACKAGES))

  def test_process_parser_includes_workers_without_matching_other_apps(self):
    package=policy.PACKAGES[0]
    raw='PID NAME\n42 '+package+'\n43 '+package+':sensor\n44 '+package+'.test\n45 '+package+'.unrelated\n'
    self.assertEqual([p['pid'] for p in policy.experiment_processes(raw)],[42,43,44])
    with self.assertRaises(ValueError):policy.experiment_processes('unrecognized output')

  def test_invalid_labels_and_waits_cannot_create_arbitrary_paths(self):
    for label in ('../escape','a/b','','x'*81):
      with self.assertRaises(ValueError):policy.cleanup_experiments(None,'.',label)
    for wait in (-1,6,True,float('nan')):
      with self.assertRaises(ValueError):policy.cleanup_experiments(None,'.','valid',wait_seconds=wait)


if __name__=='__main__':unittest.main()
