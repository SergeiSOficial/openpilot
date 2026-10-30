from setuptools import Extension, find_packages, setup
from Cython.Build import cythonize

core = ["msgq/" + name + ".cc" for name in ("ipc", "impl_msgq", "impl_fake", "msgq", "event")]
vision = ["msgq/visionipc/" + name + ".cc" for name in ("visionipc", "visionipc_server", "visionipc_client", "visionbuf")]
extensions = [
  Extension("msgq.ipc_pyx", ["msgq/ipc_pyx.pyx", *core], language="c++", include_dirs=["."], extra_compile_args=["-std=c++17"]),
  Extension("msgq.visionipc.visionipc_pyx", ["msgq/visionipc/visionipc_pyx.pyx", *core, *vision],
            language="c++", include_dirs=["."], extra_compile_args=["-std=c++17"]),
]
setup(name="msgq", version="0.0.1", packages=find_packages(), ext_modules=cythonize(extensions, language_level=3))
