"""Maintainer helper: regenerate the narrow Android portability patch."""
from pathlib import Path
import difflib

ROOT = Path(__file__).resolve().parents[2]
CHANGES = {
  "msgq/msgq.cc": [("#ifdef __APPLE__\n  std::string base_path", "#ifdef __ANDROID__\n  std::string base_path = android_msgq_root() + \"/msgq_\";\n#elif defined(__APPLE__)\n  std::string base_path")],
  "msgq/event.cc": [
    ('  int shm_fd = shm_open(name.c_str(), O_RDWR | O_CREAT, 0664);',
     '#ifdef __ANDROID__\n  name = android_msgq_root() + name;\n  int shm_fd = open(name.c_str(), O_RDWR | O_CREAT, 0600);\n#else\n  int shm_fd = shm_open(name.c_str(), O_RDWR | O_CREAT, 0664);\n#endif'),
    ('    std::string base = "/tmp/msgq_event_"', '    std::string base = android_msgq_tmp() + "/msgq_event_"'),
    ('    shm_unlink(this->shm_name.c_str());', '#ifdef __ANDROID__\n    unlink(this->shm_name.c_str());\n#else\n    shm_unlink(this->shm_name.c_str());\n#endif'),
  ],
  "msgq/visionipc/visionbuf.cc": [
    ('#ifdef __APPLE__\n  snprintf(full_path', '#ifdef __ANDROID__\n  snprintf(full_path, sizeof(full_path)-1, "%s/visionbuf_%d_%d", android_msgq_root().c_str(), getpid(), offset++);\n#elif defined(__APPLE__)\n  snprintf(full_path'),
  ],
  "msgq/visionipc/visionipc_server.cc": [('  std::string path = "/tmp/";', '  std::string path = android_msgq_tmp() + "/";')],
}
HEADER = '''#pragma once
#include <cstdlib>
#include <stdexcept>
#include <string>

inline std::string android_msgq_root() {
  const char *root = std::getenv("MSGQ_ROOT");
  if (!root || root[0] != '/') throw std::runtime_error("Android MSGQ_ROOT must be an absolute app-private path");
  return root;
}

inline std::string android_msgq_tmp() {
#ifdef __ANDROID__
  return android_msgq_root();
#else
  return "/tmp";
#endif
}
'''

def main():
  patches = []
  for path, replacements in CHANGES.items():
    original = (ROOT / "msgq_repo" / path).read_text()
    modified = '#include "msgq/android_path.h"\n' + original
    for before, after in replacements:
      if modified.count(before) != 1:
        raise RuntimeError(f"Expected one replacement in {path}: {before}")
      modified = modified.replace(before, after)
    patches.extend(difflib.unified_diff(original.splitlines(True), modified.splitlines(True), fromfile="a/" + path, tofile="b/" + path))
  patches.extend(difflib.unified_diff([], HEADER.splitlines(True), fromfile="/dev/null", tofile="b/msgq/android_path.h"))
  out = ROOT / "tools/android/patches/msgq-android.patch"
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text("".join(patches), newline="\n")

if __name__ == "__main__":
  main()
