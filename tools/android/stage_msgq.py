"""Apply the Android patch to an isolated copy of the pinned msgq submodule."""
from pathlib import Path
import shutil
import subprocess
import os

ROOT = Path(__file__).resolve().parents[2]
STAGED = ROOT / "tools/android/.cache/msgq"

def main():
  source = ROOT / "msgq_repo"
  git = "git"
  # A Windows-managed worktree records a Windows gitdir; native Linux Git cannot resolve it.
  if os.name == "posix" and ROOT.joinpath(".git").is_file() and ":/" in ROOT.joinpath(".git").read_text():
    git = shutil.which("git.exe") or "/mnt/c/Program Files/Git/cmd/git.exe"
  pinned = subprocess.check_output([git, "rev-parse", "HEAD:msgq_repo"], cwd=ROOT, text=True).strip()
  actual = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=source, text=True).strip()
  if actual != pinned:
    raise RuntimeError(f"msgq revision mismatch: expected {pinned}, got {actual}")
  if subprocess.check_output([git, "status", "--porcelain"], cwd=source):
    raise RuntimeError("msgq has local changes; refusing to stage an ambiguous native dependency")
  # This path is fixed beneath this script's repository; never accept a deletion target from input.
  if STAGED.exists():
    if not STAGED.resolve().is_relative_to((ROOT / "tools/android/.cache").resolve()):
      raise RuntimeError("Staging path escaped build cache")
    shutil.rmtree(STAGED)
  shutil.copytree(source, STAGED, ignore=shutil.ignore_patterns(".git", "__pycache__"))
  patch = str(ROOT / "tools/android/patches/msgq-android.patch")
  if git.endswith("git.exe"):
    patch = subprocess.check_output(["wslpath", "-w", patch], text=True).strip()
  directory = "--directory=tools/android/.cache/msgq"
  subprocess.run([git, "apply", "--check", directory, patch], cwd=ROOT, check=True)
  subprocess.run([git, "apply", directory, patch], cwd=ROOT, check=True)
  if not (STAGED / "msgq/android_path.h").is_file():
    raise RuntimeError("msgq Android patch was not applied to the staged package")
  print(f"Staged Android msgq from {pinned}")

if __name__ == "__main__":
  main()
