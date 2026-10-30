from functools import cache
import json
import os
from pathlib import Path
import subprocess
from openpilot.common.utils import run_cmd, run_cmd_default


def _android_metadata():
  if not os.environ.get("OPENPILOT_ANDROID_ROOT"):
    return None
  return json.loads(Path(os.environ["OPENPILOT_ANDROID_METADATA"]).read_text())


@cache
def get_commit(cwd: str | None = None, branch: str = "HEAD") -> str:
  if (metadata := _android_metadata()) is not None:
    if branch != "HEAD":
      raise ValueError("Android metadata contains only the packaged HEAD revision")
    return metadata["openpilot"]["git_commit"]
  return run_cmd_default(["git", "rev-parse", branch], cwd=cwd)


@cache
def get_commit_date(cwd: str | None = None, commit: str = "HEAD") -> str:
  if (metadata := _android_metadata()) is not None:
    if commit != "HEAD":
      raise ValueError("Android metadata contains only the packaged HEAD revision")
    return metadata["openpilot"]["git_commit_date"]
  return run_cmd_default(["git", "show", "--no-patch", "--format='%ct %ci'", commit], cwd=cwd)


@cache
def get_short_branch(cwd: str | None = None) -> str:
  if (metadata := _android_metadata()) is not None:
    return metadata["channel"]
  return run_cmd_default(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)


@cache
def get_branch(cwd: str | None = None) -> str:
  if (metadata := _android_metadata()) is not None:
    return metadata["channel"]
  return run_cmd_default(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=cwd)


@cache
def get_origin(cwd: str | None = None) -> str:
  if (metadata := _android_metadata()) is not None:
    return metadata["openpilot"]["git_origin"]
  try:
    local_branch = run_cmd(["git", "name-rev", "--name-only", "HEAD"], cwd=cwd)
    tracking_remote = run_cmd(["git", "config", "branch." + local_branch + ".remote"], cwd=cwd)
    return run_cmd(["git", "config", "remote." + tracking_remote + ".url"], cwd=cwd)
  except subprocess.CalledProcessError:  # Not on a branch, fallback
    return run_cmd_default(["git", "config", "--get", "remote.origin.url"], cwd=cwd)
