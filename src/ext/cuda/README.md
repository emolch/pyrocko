## pyrocko CUDA extensions

This directory contains CUDA kernels that enable fast parallel processing if supported hardware is available.

#### Prerequisites

Compiling pyrocko with CUDA support requires a recent CUDA toolkit to be installed on the build machine, which can be downloaded from the [nvidia website](https://developer.nvidia.com/cuda-toolkit).
For testing and development, a docker container (`pyrocko-gpu-nest`) with all the required build tooling is provided, however, cuda supported hardware and suitable nvidia drivers are required for execution of the kernels on the client's system.

Given a pyrocko installation that was compiled with CUDA support, a runtime check will determine if the client system runs on supported hardware and CUDA kernels can be used. 

#### Building

The kernels are build as part of the `build_ext` stage when running `python setup.py install` and are compiled using the `nvcc` compiler and `gcc` to link with the C python extensions.

#### Debugging

To facilitate debugging, the CUDA extensions can be build with the `CUDA_DEBUG` flag set.
Doing so will enable assertions and debug output to stdout.
```bash
CUDA_DEBUG=enabled python setup.py install
```

For debugging a segfault, standard tools like `gdb` and `valgrind` can be used, which work best with a custom compiled python installation
```bash
# it is nice to recompile python for debugging (note: the interpreter will be slower)
git clone --depth 1 --branch v3.9.1 git@github.com:python/cpython.git cpython
cd cpython
./configure --with-pydebug --with-valgrind --without-pymalloc --prefix /my/install/path
make -j
make install
# assuming you use pipenv as your modern venv for the project dir
pipenv install --dev --python /my/intstall/path/bin/python3
pipenv shell

# run the test case in gdb to see what caused the segfault
gdb -ex=r --args $(which python) -m nose test.base.test_parstack:ParstackTestCase.your_test_case

# to get a clean valgrind report, use the official python suppression file
# for newer versions of python, this might no longer be necessary
wget -o valgrind-python.supp http://svn.python.org/projects/python/trunk/Misc/valgrind-python.supp
valgrind --tool=memcheck --suppressions=valgrind-python.supp python -E -tt -m nose -s test.base.test_parstack:ParstackTestCase.your_test_case
```

Furthermore, tools such as `cuda-gdb` and `cuda-memcheck` are helpful to debug illegal memory accesses or data races.
To check for various problems, e.g. illegal memory accesses or out-of-bounds errors:
```bash
cuda-memcheck nosetests -s test.base.test_parstack:ParstackTestCase.your_test_case
cuda-memcheck --racecheck-report analysis nosetests -s test.base.test_parstack:ParstackTestCase.your_test_case
cuda-memcheck --leak-check full nosetests -s test.base.test_parstack:ParstackTestCase.your_test_case
```

#### Testing

To make sure compilation succeeds with cuda enabled or disabled (Note: this only test successful builds, the tests should be run on supported hardware):
```bash
drone exec --pipeline=tests-base # compiles and tests both with and wihthout CUDA
drone exec --pipeline=tests-base --inclue tests-cuda # only compiles and tests with CUDA support
# to test the kernels, make sure to run the test suite on CUDA enabled hardware
# pyrocko will automatically check which implementations to test at runtime
nosetests -s --ignore-files="test_avl\.py" --ignore-files="test_pile\.py" test.base
```

#### Profiling

To improve kernel performance, the nvidia profiler (`nvvp`) should be used to guide optimization.
On ubuntu, `nvvp` can be installed via `apt` (note, this requires a JRE 1.8):
```bash
sudo apt install nvidia-visual-profiler
```

There are sample executables in `src/ext/cuda/profiling`. To build and profile, see `src/ext/cuda/Makefile` or use the wrapper command:
```bash
# this will profile all implemented kernels, save profiling information and open each in nvvp
sudo python setup.py profile_cuda # sudo is required to profile the GPU
```

To run the benchmarks and plot a graph:
```bash
PLOT_BENCHMARK=enable nosetests -s test.base.test_parstack:ParstackTestCase.benchmark
```
