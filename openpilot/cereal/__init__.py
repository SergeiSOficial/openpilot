import os
import capnp
from pathlib import Path
from importlib.resources import as_file, files

capnp.remove_import_hook()

with as_file(files("openpilot.cereal")) as fspath, as_file(files("opendbc")) as opendbc_path:
  CEREAL_PATH = fspath.resolve().as_posix()
  opendbc_import_path = os.path.join(os.path.realpath(opendbc_path.as_posix()), 'car')
  imports = [opendbc_import_path]
  if os.environ.get("OPENPILOT_ANDROID_ROOT"):
    # Both loaders use one real directory, independent of APK package extraction paths.
    CEREAL_PATH = os.environ["OPENPILOT_ANDROID_SCHEMAS"]
    imports = [CEREAL_PATH]
    imports.append(str(Path(capnp.__file__).resolve().parent.parent))
  log = capnp.load(os.path.join(CEREAL_PATH, "log.capnp"), imports=imports)
  custom = capnp.load(os.path.join(CEREAL_PATH, "custom.capnp"), imports=imports)
