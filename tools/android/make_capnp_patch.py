"""Generate the Android directory-handle patch from the pinned bundled Cap'n Proto source."""
from pathlib import Path
import difflib

ROOT = Path(__file__).resolve().parents[2]
RELATIVE = "bundled/capnproto-c++/src/kj/filesystem-disk-unix.c++"

def main():
  source = Path.home() / ".cache/openpilot-android/chaquopy/server/pypi/packages/openpilot-pycapnp/build/2.1.0/cp312-cp312-android_24_x86_64/src" / RELATIVE
  original = source.read_text()
  before = '''  static AutoCloseFd openDir(const char* dir) {
    int newFd;
    KJ_SYSCALL(newFd = open(dir, O_RDONLY | MAYBE_O_CLOEXEC | MAYBE_O_DIRECTORY));'''
  after = '''  static AutoCloseFd openDir(const char* dir) {
    int newFd = -1;
    int flags = O_RDONLY | MAYBE_O_CLOEXEC | MAYBE_O_DIRECTORY;
#if defined(__ANDROID__) && defined(O_PATH)
    // Untrusted Android apps can traverse / but cannot open it for directory reads.
    // Schema lookup needs an openat anchor, which O_PATH provides without listing it.
    newFd = open(dir, flags);
    if (newFd < 0 && errno == EACCES) flags = O_PATH | MAYBE_O_CLOEXEC | MAYBE_O_DIRECTORY;
#endif
    if (newFd < 0) {
      KJ_SYSCALL(newFd = open(dir, flags));
    }'''
  if original.count(before) != 1:
    raise RuntimeError("Unexpected bundled Cap'n Proto directory implementation")
  patched = original.replace(before, after)
  destination = ROOT / "tools/android/recipes/pycapnp/android-directory-handles.patch"
  destination.parent.mkdir(parents=True, exist_ok=True)
  destination.write_text("".join(difflib.unified_diff(original.splitlines(True), patched.splitlines(True),
                                                   fromfile="a/" + RELATIVE, tofile="b/" + RELATIVE)))

if __name__ == "__main__":
  main()
