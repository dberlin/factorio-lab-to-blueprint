from Cython.Build import cythonize
from setuptools import Extension, setup

setup(
    ext_modules=cythonize(
        [
            Extension(
                "flab2bp.layout._sequence_kernel",
                ["src/flab2bp/layout/_sequence_kernel.pyx"],
            ),
            Extension(
                "flab2bp.layout._route_kernel",
                ["src/flab2bp/layout/_route_kernel.pyx"],
            ),
        ],
        build_dir="build/cython",
        compiler_directives={"language_level": "3"},
    )
)
