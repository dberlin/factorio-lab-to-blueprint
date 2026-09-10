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
            # `-ffp-contract=off` forbids fusing `a * b + c` into an FMA.  The
            # kernel has to round exactly where the Python reference rounds, and
            # an FMA rounds *less* -- which would disagree at the boundary, the
            # only place the overlap verdict is in doubt.
            Extension(
                "flab2bp.dsp._geometry_kernel",
                ["src/flab2bp/dsp/_geometry_kernel.pyx"],
                extra_compile_args=["-ffp-contract=off"],
            ),
        ],
        build_dir="build/cython",
        compiler_directives={"language_level": "3"},
    )
)
