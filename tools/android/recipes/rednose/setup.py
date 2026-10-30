import os
from pathlib import Path
from setuptools import Extension, find_packages, setup
from Cython.Build import cythonize

headers = [Path(entry) / "numpy/_core/include" for entry in os.environ["PYTHONPATH"].split(os.pathsep)]
numpy_include = next(str(path) for path in headers if path.is_dir())
extension = Extension("rednose.helpers.ekf_sym_pyx",
                      ["rednose/helpers/ekf_sym_pyx.pyx", "rednose/helpers/ekf_load.cc", "rednose/helpers/ekf_sym.cc"],
                      language="c++", include_dirs=[".", "rednose", "eigen", numpy_include],
                      libraries=["dl"], extra_compile_args=["-std=c++17"])
setup(name="rednose", version="0.0.1", packages=find_packages(),
      package_data={"rednose": ["templates/*"]}, ext_modules=cythonize([extension], language_level=3))
