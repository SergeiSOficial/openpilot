"""Numerical acceptance uses the repository's process replay comparisons unchanged."""
from collections import Counter
import hashlib
import json


def compare(reference, actual, configs):
  from openpilot.selfdrive.test.process_replay.compare_logs import compare_logs
  result = {}
  for config in configs:
    left = [message for message in reference if message.which() in config.subs]
    right = [message for message in actual if message.which() in config.subs]
    try:
      diffs = []
      for service in config.subs:
        diffs.extend(compare_logs([m for m in left if m.which() == service], [m for m in right if m.which() == service],
                                  ignore_fields=config.ignore, tolerance=config.tolerance))
      result[config.proc_name] = {"passed": not diffs, "messages": len(right), "differences": len(diffs),
                                  "first_differences": [str(diff) for diff in diffs[:20]],
                                  "ignore": config.ignore, "tolerance": config.tolerance}
    except Exception as failure:
      result[config.proc_name] = {"passed": False, "error": str(failure)}
  return {"passed": all(item["passed"] for item in result.values()), "processes": result,
          "reference_counts": dict(Counter(m.which() for m in reference)), "android_counts": dict(Counter(m.which() for m in actual))}


def verify(root, actual, configs):
  from openpilot.cereal import log
  fixture = root.parents[1] / "fixture"
  reference = json.loads((fixture / "reference.json").read_text())
  metadata = json.loads((root.parents[1] / "model/build.json").read_text())
  model = json.loads((root.parents[1] / "model/provenance.json").read_text())
  if reference["source_sha256"] != metadata["source_sha256"]:
    raise ValueError("Desktop reference source hash does not match this APK; regenerate the reference")
  if reference["model_sha256"] != model["model_sha256"]:
    raise ValueError("Desktop reference model hash does not match this APK")
  fixture_log = (fixture / "fixture.rlog").read_bytes()
  if hashlib.sha256(fixture_log).hexdigest() != reference["fixture_sha256"]:
    raise ValueError("Desktop reference fixture hash does not match this APK")
  raw = (fixture / "reference.rlog").read_bytes()
  if hashlib.sha256(raw).hexdigest() != reference["output_sha256"]:
    raise ValueError("Corrupted desktop reference log")
  result = compare(list(log.Event.read_multiple_bytes(raw)), actual, configs)
  result.update(source_sha256=reference["source_sha256"], source_revision=reference["source_revision"],
                model_sha256=reference["model_sha256"], fixture_sha256=reference["fixture_sha256"])
  return result
