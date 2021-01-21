from __future__ import absolute_import, division, print_function
import sys
import os
import re
import glob
import os.path as op
import time
import copy
import shutil
import tempfile
import collections
import numpy

import subprocess as sp
from distutils.sysconfig import get_config_var, get_python_inc
from setuptools import setup, Extension, Command
from setuptools.command.build_py import build_py
from setuptools.command.build_ext import build_ext
from setuptools.command.install import install
running_bdist_wheel = False
try:
    from wheel.bdist_wheel import bdist_wheel

    class CustomBDistWheelCommand(bdist_wheel):
        def run(self):
            global running_bdist_wheel
            running_bdist_wheel = True
            bdist_wheel.run(self)

except ImportError:
    CustomBDistWheelCommand = None

packname = 'pyrocko'
version = '2020.08.18'


class NotInAGitRepos(Exception):
    pass


def git_infos():
    '''Query git about sha1 of last commit and check if there are local \
       modifications.'''
    def q(c):
        return sp.Popen(c, stdout=sp.PIPE).communicate()[0]

    if not op.exists('.git'):
        raise NotInAGitRepos()

    sha1 = q(['git', 'log', '--pretty=oneline', '-n1']).split()[0]
    sha1 = re.sub(br'[^0-9a-f]', '', sha1)
    sha1 = str(sha1.decode('ascii'))
    sstatus = q(['git', 'status', '--porcelain', '-uno'])
    local_modifications = bool(sstatus.strip())
    return sha1, local_modifications


def bash_completions_dir():
    def q(c):
        return sp.Popen(c, stdout=sp.PIPE).communicate()[0]

    try:
        d = q(['pkg-config', 'bash-completion', '--variable=completionsdir'])
        return d.strip().decode('utf-8')
    except Exception:
        return None


def make_info_module(packname, version):
    '''Put version and revision information into file src/info.py.'''

    sha1, local_modifications = None, None
    combi = '%s-%s' % (packname, version)
    try:
        sha1, local_modifications = git_infos()
        combi += '-%s' % sha1
        if local_modifications:
            combi += '-modified'

    except (OSError, NotInAGitRepos):
        pass

    datestr = time.strftime('%Y-%m-%d_%H:%M:%S')
    combi += '-%s' % datestr

    s = '''# This module is automatically created from setup.py
git_sha1 = %s
local_modifications = %s
version = %s
long_version = %s  # noqa
installed_date = %s
''' % tuple([repr(x) for x in (
        sha1, local_modifications, version, combi, datestr)])

    try:
        f = open(op.join('src', 'info.py'), 'w')
        f.write(s)
        f.close()
    except Exception:
        pass


def make_prerequisites():
    try:
        sp.check_call(['sh', 'prerequisites/prerequisites.sh'])
    except Exception:
        sys.exit('error: failed to build the included prerequisites with '
                 '"sh prerequisites/prerequisites.sh"')


def get_readme_paths():
    paths = []

    for (path, dirnames, filenames) in os.walk(
            op.join(op.dirname(__file__), 'src')):
        paths.extend(
            [op.join(path.split('/', 1)[1], fn) for fn in filenames if
             fn == 'README.md'])
    return paths


def get_build_include(lib_name):
    return op.join(op.dirname(op.abspath(__file__)), lib_name)


def find_pyrocko_installs():
    found = []
    seen = set()
    orig_sys_path = sys.path
    for p in sys.path:

        ap = op.abspath(p)
        if ap == op.abspath('.'):
            continue

        if ap in seen:
            continue

        seen.add(ap)

        sys.path = [p]

        try:
            import pyrocko
            dpath = op.dirname(op.abspath(pyrocko.__file__))
            x = (pyrocko.installed_date, p, dpath,
                 pyrocko.long_version)
            found.append(x)
            del sys.modules['pyrocko']
            del sys.modules['pyrocko.info']
        except (ImportError, AttributeError):
            pass

    sys.path = orig_sys_path
    return found


def print_installs(found, file):
    print(
        '\nsys.path configuration is: \n  %s\n' % '\n  '.join(sys.path),
        file=file)

    dates = sorted([xx[0] for xx in found])
    i = 1

    for (installed_date, p, installed_path, long_version) in found:
        oldnew = ''
        if len(dates) >= 2:
            if installed_date == dates[0]:
                oldnew = ' (oldest)'

            if installed_date == dates[-1]:
                oldnew = ' (newest)'

        print('''Pyrocko installation #%i:
  date installed: %s%s
  version: %s
  path: %s
''' % (i, installed_date, oldnew, long_version, installed_path), file=file)
        i += 1


def check_multiple_install():
    found = find_pyrocko_installs()
    e = sys.stderr

    dates = sorted([xx[0] for xx in found])

    if len(found) > 1:
        print_installs(found, e)

    if len(found) > 1:
        print(
            '''Installation #1 is used with default sys.path configuration.

WARNING: Multiple installations of Pyrocko are present on this system.''',
            file=e)
        if found[0][0] != dates[-1]:
            print('WARNING: Not using newest installed version.', file=e)


def check_pyrocko_install_compat():
    found = find_pyrocko_installs()
    if len(found) == 0:
        return

    expected_submodules = ['gui', 'dataset', 'client',
                           'streaming', 'io', 'model']

    installed_date, p, install_path, long_version = found[0]

    installed_submodules = [d for d in os.listdir(install_path)
                            if op.isdir(op.join(install_path, d))]

    if not all([ed in installed_submodules for ed in expected_submodules]):

        print_installs(found, sys.stdout)

        print('''\n
###############################################################################

WARNING: Found an old, incompatible, Pyrocko installation!

Please purge the old installation and the 'build' directory before installing
this new version:

    sudo rm -rf '%s' build

###############################################################################
''' % install_path)

        sys.exit(1)


class CheckInstalls(Command):
    description = '''check for multiple installations of Pyrocko'''
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        check_multiple_install()


class Uninstall(Command):
    description = 'delete installations of Pyrocko known to the invoked ' \
                  'Python interpreter'''

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        found = find_pyrocko_installs()
        print_installs(found, sys.stdout)

        if found:
            print('''
Use the following commands to remove the Pyrocko installation(s) known to the
currently running Python interpreter:

  sudo rm -rf build''')

            for _, _, install_path, _ in found:
                print('  sudo rm -rf "%s"' % install_path)

            print()

        else:
            print('''
No Pyrocko installations found with the currently running Python interpreter.
''')


class CustomInstallCommand(install):

    def symlink_interpreter(self):
        if not running_bdist_wheel \
                and hasattr(self, 'install_scripts') \
                and sys.executable:

            target = op.join(self.install_scripts, 'pyrocko-python')
            if op.exists(target):
                os.unlink(target)

            os.symlink(sys.executable, target)

    def run(self):
        check_pyrocko_install_compat()
        install.run(self)
        self.symlink_interpreter()
        check_multiple_install()
        bd_dir = bash_completions_dir()
        if bd_dir:
            try:
                shutil.copy('extras/pyrocko', bd_dir)
                print('Installing pyrocko bash_completion to "%s"' % bd_dir)
            except Exception:
                print(
                    'Could not install pyrocko bash_completion to "%s" '
                    '(continuing without)'
                    % bd_dir)


class CustomBuildPyCommand(build_py):

    def make_compat_modules(self):
        mapping = [
            ('pyrocko', 'css', ['pyrocko.io.css']),
            ('pyrocko', 'datacube', ['pyrocko.io.datacube']),
            ('pyrocko.fdsn', '__init__', []),
            ('pyrocko.fdsn', 'enhanced_sacpz', ['pyrocko.io.enhanced_sacpz']),
            ('pyrocko.fdsn', 'station', ['pyrocko.io.stationxml']),
            ('pyrocko', 'gcf', ['pyrocko.io.gcf']),
            ('pyrocko', 'gse1', ['pyrocko.io.gse1']),
            ('pyrocko', 'gse2_io_wrap', ['pyrocko.io.gse2']),
            ('pyrocko', 'ims', ['pyrocko.io.ims']),
            ('pyrocko', 'io_common', ['pyrocko.io.io_common']),
            ('pyrocko', 'kan', ['pyrocko.io.kan']),
            ('pyrocko', 'mseed', ['pyrocko.io.mseed']),
            ('pyrocko', 'rdseed', ['pyrocko.io.rdseed']),
            ('pyrocko.fdsn', 'resp', ['pyrocko.io.resp']),
            ('pyrocko', 'sacio', ['pyrocko.io.sac']),
            ('pyrocko', 'segy', ['pyrocko.io.segy']),
            ('pyrocko', 'seisan_response', ['pyrocko.io.seisan_response']),
            ('pyrocko', 'seisan_waveform', ['pyrocko.io.seisan_waveform']),
            ('pyrocko', 'suds', ['pyrocko.io.suds']),
            ('pyrocko', 'yaff', ['pyrocko.io.yaff']),
            ('pyrocko', 'eventdata', ['pyrocko.io.eventdata']),
            ('pyrocko.fdsn', 'ws', ['pyrocko.client.fdsn']),
            ('pyrocko', 'catalog', ['pyrocko.client.catalog']),
            ('pyrocko', 'iris_ws', ['pyrocko.client.iris']),
            ('pyrocko', 'crust2x2', ['pyrocko.dataset.crust2x2']),
            ('pyrocko', 'crustdb', ['pyrocko.dataset.crustdb']),
            ('pyrocko', 'geonames', ['pyrocko.dataset.geonames']),
            ('pyrocko', 'tectonics', ['pyrocko.dataset.tectonics']),
            ('pyrocko', 'topo', ['pyrocko.dataset.topo']),
            ('pyrocko', 'automap', ['pyrocko.plot.automap']),
            ('pyrocko', 'beachball', ['pyrocko.plot.beachball']),
            ('pyrocko', 'cake_plot', ['pyrocko.plot.cake_plot']),
            ('pyrocko', 'gmtpy', ['pyrocko.plot.gmtpy']),
            ('pyrocko', 'hudson', ['pyrocko.plot.hudson']),
            ('pyrocko', 'response_plot', ['pyrocko.plot.response']),
            ('pyrocko', 'snuffling', ['pyrocko.gui.snuffling']),
            ('pyrocko', 'pile_viewer', ['pyrocko.gui.pile_viewer']),
            ('pyrocko', 'marker', ['pyrocko.gui.marker']),
            ('pyrocko', 'snuffler', ['pyrocko.gui.snuffler']),
            ('pyrocko', 'gui_util', ['pyrocko.gui.util']),
        ]

        for (package, compat_module, import_modules) in mapping:
            module_code = '''
import sys
import pyrocko
if pyrocko.grumpy:
    sys.stderr.write('using renamed pyrocko module: %s.%s\\n')
    sys.stderr.write('           -> should now use: %s\\n\\n')

''' % (package, compat_module, ', '.join(import_modules)) + ''.join(
                ['from %s import *\n' % module for module in import_modules])

            outfile = self.get_module_outfile(
                self.build_lib, package.split('.'), compat_module)

            dir = op.dirname(outfile)
            self.mkpath(dir)
            with open(outfile, 'w') as f:
                f.write(module_code)

    def run(self):
        make_info_module(packname, version)
        self.make_compat_modules()
        build_py.run(self)


IS_WINDOWS = sys.platform == 'win32'


def _find_cuda_home():
    """Finds the CUDA install path."""
    # Guess #1
    cuda_home = os.environ.get(
        'CUDA_HOME') or os.environ.get('CUDA_PATH')
    if cuda_home is not None:
        return cuda_home

    # Guess #2
    which = 'where' if IS_WINDOWS else 'which'
    with open(os.devnull, 'w') as devnull:
        try:
            nvcc = sp.check_output([which, 'nvcc'],
                                   stderr=devnull).decode().rstrip('\r\n')
            cuda_home = op.dirname(op.dirname(nvcc))
            if cuda_home is not None:
                return cuda_home
        except sp.CalledProcessError:
            pass

    # Guess #3
    if IS_WINDOWS:
        cuda_homes = glob.glob(
            'C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v*.*')
        if len(cuda_homes) > 0 and op.exists(cuda_homes[0]):
            return cuda_homes[0]
    else:
        for common_install_path in ['/usr/local/cuda', '/usr/lib/cuda']:
            if op.exists(common_install_path):
                return common_install_path
    return cuda_home


def _check_for_cuda():
    """Check whether the host system can compile CUDA kernels
    """
    libs, includes = [], []
    CUDA_HOME = _find_cuda_home()
    if not CUDA_HOME:
        print('CUDA not found. Continuing your build without CUDA support...')
        return False, None, libs, includes

    CUDNN_HOME = os.environ.get(
        'CUDNN_HOME') or os.environ.get('CUDNN_PATH')

    if IS_WINDOWS:
        lib_dir = 'lib/x64'
    else:
        lib_dir = 'lib64'
    if (not op.exists(op.join(CUDA_HOME, lib_dir)) and
            op.exists(op.join(CUDA_HOME, 'lib'))):
        lib_dir = 'lib'

    libs.append(op.join(CUDA_HOME, lib_dir))
    if CUDNN_HOME is not None:
        libs.append(op.join(CUDNN_HOME, lib_dir))

    cuda_home_include = op.join(CUDA_HOME, 'include')
    # if we have the Debian/Ubuntu packages for cuda, we get /usr as cuda home.
    # but gcc doesn't like having /usr/include passed explicitly
    if cuda_home_include != '/usr/include':
        includes.append(cuda_home_include)
    if CUDNN_HOME is not None:
        includes.append(os.path.join(CUDNN_HOME, 'include'))

    return True, op.join(CUDA_HOME, 'bin', 'nvcc'), libs, includes


can_compile_cuda, cuda_nvcc, cuda_libs, cuda_includes = _check_for_cuda()


class ProfileCudaCommand(Command):
    description = '''profile cuda kernels using a given set of examples'''
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        if not can_compile_cuda:
            sys.exit(
                'cannot profile CUDA kernels without a CUDA installation')
        try:
            sp.check_call(
                    ['make', '-C', 'src/ext/cuda', 'profile_parstack_visual'])
            sp.check_call(
                    ['make', '-C', 'src/ext/cuda', 'profile_minmax_visual'])
        except Exception:
            sys.exit((
                'Fatal error: failed to profile CUDA kernels.\n\n',
                'Make sure the CUDA driver and toolkit is properly installed ',
                'on your system.\n',
                'Make sure you run this command as root.\n',
                'Make sure you have the visual profiler installed ',
                '(e.g. apt install nvidia-visual-profiler).'))


class CustomBuildExtCommand(build_ext, object):

    def build_extensions(self):
        # Register .cu and .cuh as valid source extensions.
        self.compiler.src_extensions += ['.cu', '.cuh']
        # Save the original _compile method for later.
        if self.compiler.compiler_type == 'msvc':
            self.compiler._cpp_extensions += ['.cu', '.cuh']
            original_compile = self.compiler.compile
        else:
            original_compile = self.compiler._compile

        def _is_cuda_file(path):
            return op.splitext(path)[1] in ['.cu', '.cuh']

        def unix_cuda_flags(cflags):
            return ['--compiler-options', '"-fPIC"'] + \
                cflags + _get_cuda_arch_flags(cflags)

        def unix_wrap_single_compile(
                obj, src, ext, cc_args, extra_postargs, pp_opts):
            # Copy before we make any modifications.
            cflags = copy.deepcopy(extra_postargs)
            try:
                original_compiler = self.compiler.compiler_so
                if _is_cuda_file(src):  # or 'nvcc' in cflags:
                    if not can_compile_cuda:
                        print(
                            'skipping %s (CUDA toolkit is not installed)' %
                            src)
                        return
                    _cuda_nvcc = cuda_nvcc
                    if not isinstance(_cuda_nvcc, list):
                        _cuda_nvcc = [_cuda_nvcc]
                    self.compiler.set_executable(
                        'compiler_so', _cuda_nvcc)
                    if isinstance(cflags, dict):
                        cflags = cflags['nvcc']
                    cflags = unix_cuda_flags(cflags)
                elif isinstance(cflags, dict):
                    cflags = cflags['gcc']

                if os.environ.get('PYROCKO_VERBOSE_BUILD'):
                    print(obj, src, ext, cc_args, cflags, pp_opts)
                original_compile(
                    obj, src, ext, cc_args, cflags, pp_opts)
            finally:
                # restore the original compiler
                self.compiler.set_executable(
                    'compiler_so', original_compiler)

        if self.compiler.compiler_type == 'msvc':
            raise NotImplementedError('Windows not supported at the moment.')

        self.compiler._compile = unix_wrap_single_compile
        build_ext.build_extensions(self)

    def run(self):
        make_prerequisites()
        build_ext.run(self)


class CustomBuildAppCommand(build_ext, object):
    def run(self):
        self.make_app()

    def make_app(self):
        import glob
        import os
        import shutil
        from setuptools import setup

        APP = ['apps/snuffler']
        DATA_FILES = []
        OPTIONS = {
            'argv_emulation': True,
            'iconfile': 'src/data/snuffler.icns',
            'packages': 'pyrocko',
            'excludes': [
                'PyQt4.QtDesigner',
                'PyQt4.QtScript',
                'PyQt4.QtScriptTools',
                'PyQt4.QtTest',
                'PyQt4.QtCLucene',
                'PyQt4.QtDeclarative',
                'PyQt4.QtHelp',
                'PyQt4.QtSql',
                'PyQt4.QtTest',
                'PyQt4.QtXml',
                'PyQt4.QtXmlPatterns',
                'PyQt4.QtMultimedia',
                'PyQt4.phonon',
                'matplotlib.tests',
                'matplotlib.testing'],
            'plist': 'src/data/Info.plist'}

        setup(
            app=APP,
            data_files=DATA_FILES,
            options={'py2app': OPTIONS},
            setup_requires=['py2app'],
        )

        # Manually delete files which refuse to be ignored using 'excludes':
        want_delete = glob.glob(
            'dist/snuffler.app/Contents/Frameworks/libvtk*')

        map(os.remove, want_delete)

        want_delete_dir = glob.glob(
            'dist/Snuffler.app/Contents/Resources/lib/python2.7/'
            'matplotlib/test*')
        map(shutil.rmtree, want_delete_dir)


def _check_for_openmp():
    """Check  whether the default compiler supports OpenMP.
    This routine is adapted from pynbody // yt.
    Thanks to Nathan Goldbaum and Andrew Pontzen.
    """

    tmpdir = tempfile.mkdtemp(prefix='pyrocko')
    compiler = os.environ.get(
      'CC', get_config_var('CC')).split()[0]

    # Attempt to compile a test script.
    # See http://openmp.org/wp/openmp-compilers/
    tmpfile = op.join(tmpdir, 'check_openmp.c')
    with open(tmpfile, 'w') as f:
        f.write('''
#include <omp.h>
#include <stdio.h>
int main() {
    #pragma omp parallel
    printf("Hello from thread %d", omp_get_thread_num());
}
''')

    try:
        with open(os.devnull, 'w') as fnull:
            exit_code = sp.call([compiler, '-fopenmp', '-o%s'
                                 % op.join(tmpdir, 'check_openmp'),
                                 tmpfile],
                                stdout=fnull, stderr=fnull)
    except OSError:
        exit_code = 1
    finally:
        shutil.rmtree(tmpdir)

    if exit_code == 0:
        print('Continuing your build using OpenMP...')
        return True

    import multiprocessing
    import platform
    if multiprocessing.cpu_count() > 1:
        print('''WARNING
OpenMP support is not available in your default C compiler, even though
your machine has more than one core available.
Some routines in pyrocko are parallelized using OpenMP and these will
only run on one core with your current configuration.
''')
        if platform.uname()[0] == 'Darwin':
            print('''Since you are running on Mac OS, it's likely that the problem here
is Apple's Clang, which does not support OpenMP at all. The easiest
way to get around this is to download the latest version of gcc from
here: http://hpc.sourceforge.net. After downloading, just point the
CC environment variable to the real gcc and OpenMP support should
get enabled automatically. Something like this -
sudo tar -xzf /path/to/download.tar.gz /
export CC='/usr/local/bin/gcc'
python setup.py clean
python setup.py build
''')
    print('Continuing your build without OpenMP...')
    return False


if _check_for_openmp():
    omp_arg = ['-fopenmp']
    omp_lib = ['-lgomp']
else:
    omp_arg = []
    omp_lib = []

subpacknames = [
    'pyrocko.gf',
    'pyrocko.fomosto',
    'pyrocko.fomosto.report',
    'pyrocko.client',
    'pyrocko.apps',
    'pyrocko.io',
    'pyrocko.model',
    'pyrocko.plot',
    'pyrocko.gui',
    'pyrocko.gui.snufflings',
    'pyrocko.gui.snufflings.map',
    'pyrocko.dataset',
    'pyrocko.dataset.topo',
    'pyrocko.streaming',
    'pyrocko.scenario',
    'pyrocko.scenario.targets',
    'pyrocko.scenario.sources',
    'pyrocko.obspy_compat',
]

cmdclass = {
    'install': CustomInstallCommand,
    'build_py': CustomBuildPyCommand,
    # 'py2app': CustomBuildAppCommand,
    'profile_cuda': ProfileCudaCommand,
    'build_ext': CustomBuildExtCommand,
    'check_multiple_install': CheckInstalls,
    'uninstall': Uninstall}

if CustomBDistWheelCommand:
    cmdclass['bdist_wheel'] = CustomBDistWheelCommand


def _get_cuda_arch_flags(cflags=None):
    """ Determine CUDA arch compiler flags to use.
    (e.g. "6.1" -> ``-gencode=arch=compute_61,code=sm_61``.
    for "+PTX", ``-gencode=arch=compute_xx,code=compute_xx`` is added.
    """
    # user defined arch values (from `extra_compile_args`) take precedence
    if cflags is not None:
        for flag in cflags:
            if 'arch' in flag:
                return []

    named_arches = collections.OrderedDict([
        ('Kepler+Tesla', '3.7'),
        ('Kepler', '3.5+PTX'),
        ('Maxwell+Tegra', '5.3'),
        ('Maxwell', '5.0;5.2+PTX'),
        ('Pascal', '6.0;6.1+PTX'),
        ('Volta', '7.0+PTX'),
        ('Turing', '7.5+PTX'),
        ('Ampere', '8.0+PTX'),
    ])

    supported_arches = ['3.5', '3.7', '5.0', '5.2', '5.3', '6.0', '6.1', '6.2',
                        '7.0', '7.2', '7.5', '8.0']
    valid_arch_strings = supported_arches + \
        [s + '+PTX' for s in supported_arches]

    # can be one or more architectures, e.g. '6.1' or '3.5;5.2;6.0;6.1;7.0+PTX'
    arch_list = os.environ.get('CUDA_ARCH_LIST', None)

    if not arch_list:
        try:
            import ctypes
            libcudart = ctypes.CDLL('libcudart.so')

            # see
            # https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__TYPES.html
            cudaDevAttrComputeCapabilityMajor = 75
            cudaDevAttrComputeCapabilityMinor = 76

            c_enum = ctypes.c_uint
            libcudart.cudaDeviceGetAttribute.restype = c_enum
            libcudart.cudaDeviceGetAttribute.argtypes = [
                ctypes.POINTER(ctypes.c_int), c_enum, ctypes.c_int]

            minor, major = ctypes.c_int(), ctypes.c_int()
            device = 0  # for now, always detect the arch for gpu 0
            libcudart.cudaDeviceGetAttribute(ctypes.byref(
                major), cudaDevAttrComputeCapabilityMajor, device)
            libcudart.cudaDeviceGetAttribute(ctypes.byref(
                minor), cudaDevAttrComputeCapabilityMinor, device)
            arch_list = ['%s.%s' % (major.value, minor.value)]
        except OSError:
            print((
                'Note: calling libcudart.so to query the GPU device failed. ',
                'Proceeding without specifying a CUDA build arch ...'))
    else:
        arch_list = arch_list.replace(' ', ';')
        for named_arch, archval in named_arches.items():
            arch_list = arch_list.replace(named_arch, archval)

        arch_list = arch_list.split(';')

    flags = []
    for arch in arch_list:
        if arch not in valid_arch_strings:
            print(
                'Warning: unknown CUDA arch (%s) or GPU not supported' %
                (arch))
            return flags
        num = arch[0] + arch[2]
        flags.append(
            '-gencode=arch=compute_%s,code=sm_%s' % (num, num))
        if arch.endswith('+PTX'):
            flags.append(
                '-gencode=arch=compute_%s,code=compute_%s' % (num, num))

    return list(set(flags))


def compile_with_cuda(ex, omp=False):
    ex.extra_compile_args = {
        'gcc': ['-Wextra', '-Wno-write-strings'],
        'nvcc': [],
    }
    ex.libraries += ['stdc++', 'cudart']
    ex.library_dirs += cuda_libs
    ex.runtime_library_dirs += cuda_libs
    ex.include_dirs += [op.join('src', 'ext', 'cuda')] + cuda_includes
    ex.extra_compile_args['gcc'] += ['-D=_CUDA']
    if os.environ.get('CUDA_DEBUG'):
        ex.extra_compile_args['gcc'] += ['-D=CUDA_DEBUG', '-g']
        ex.extra_compile_args['nvcc'] += ['-D=CUDA_DEBUG', '-g']
    ex.extra_compile_args['nvcc'] += [
        '-c',
        '-O3',
        '-lineinfo',
        '-Xcompiler', '-rdynamic',
        '--use_fast_math',
        '--compiler-options', '"-fPIC"',
        '--compiler-options', '"-Wall"'
    ]
    if omp:
        ex.extra_compile_args['gcc'] += omp_arg
        ex.extra_compile_args['nvcc'] += [
            '-Xcompiler', *omp_arg,
        ]
    return ex


def minmax_ext():
    ex = Extension(
        'minmax_ext',
        include_dirs=[get_python_inc(), numpy.get_include()],
        extra_link_args=omp_lib,
        extra_compile_args=omp_arg,
        sources=[
            op.join('src', 'ext', 'minmax_ext.c'),
        ])
    if can_compile_cuda:
        ex = compile_with_cuda(ex, omp=True)
        ex.sources += [
            op.join('src', 'ext', 'cuda', 'utils.cu'),
            op.join('src', 'ext', 'cuda', 'minmax.cu'),
        ]
    return ex


def cuda_ext():
    ex = Extension(
        'cuda_ext',
        include_dirs=[get_python_inc()],
        sources=[
            op.join('src', 'ext', 'cuda_ext.c'),
        ])
    if can_compile_cuda:
        ex = compile_with_cuda(ex)
        ex.sources += [
            op.join('src', 'ext', 'cuda', 'utils.cu'),
        ]
    return ex


def parstack_ext():
    ex = Extension(
        'parstack_ext',
        include_dirs=[get_python_inc(), numpy.get_include()],
        extra_link_args=omp_lib,
        extra_compile_args=omp_arg,
        sources=[
            op.join('src', 'ext', 'parstack_ext.c'),
        ])
    if can_compile_cuda:
        ex = compile_with_cuda(ex, omp=True)
        ex.sources += [
            op.join('src', 'ext', 'cuda', 'parstack.cu'),
            op.join('src', 'ext', 'cuda', 'utils.cu'),
            op.join('src', 'ext', 'cuda', 'minmax.cu'),
        ]
    return ex


setup(
    cmdclass=cmdclass,
    name=packname,
    version=version,
    description='A versatile seismology toolkit for Python.',
    long_description=open(
        'maintenance/readme-pip.rst', 'rb').read().decode('utf8'),
    author='The Pyrocko Developers',
    author_email='info@pyrocko.org',
    url='https://pyrocko.org',
    license='GPLv3',
    classifiers=[
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Science/Research',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: C',
        'Programming Language :: Python :: Implementation :: CPython',
        'Operating System :: POSIX',
        'Operating System :: MacOS',
        'Topic :: Scientific/Engineering',
        'Topic :: Scientific/Engineering :: Physics',
        'Topic :: Scientific/Engineering :: Visualization',
        'Topic :: Scientific/Engineering :: Information Analysis',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
    ],
    keywords=[
        'seismology, waveform analysis, earthquake modelling, geophysics,'
        ' geophysical inversion'],
    python_requires='>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, <4',
    # Removed in favor of PEP 518 advocating `pyproject.toml`:
    # setup_requires=[
    #     'numpy>=1.8'
    # ],
    install_requires=[
        'numpy>=1.8',
        'scipy',
        'pyyaml',
        'matplotlib',
        'requests',
    ],

    extras_require={
        'gui_scripts': ['PyQt5'],
    },

    packages=[packname] + subpacknames,
    package_dir={'pyrocko': 'src'},
    ext_package=packname,
    ext_modules=[
        Extension(
            'util_ext',
            extra_compile_args=['-Wextra'],
            sources=[op.join('src', 'ext', 'util_ext.c')]),

        Extension(
            'signal_ext',
            include_dirs=[get_python_inc(), numpy.get_include()],
            extra_compile_args=['-Wextra'],
            sources=[op.join('src', 'ext', 'signal_ext.c')]),

        Extension(
            'mseed_ext',
            include_dirs=[get_python_inc(), numpy.get_include(),
                          get_build_include('libmseed/')],
            library_dirs=[get_build_include('libmseed/')],
            libraries=['mseed'],
            extra_compile_args=['-Wextra'],
            sources=[op.join('src', 'io', 'ext', 'mseed_ext.c')]),

        Extension(
            'evalresp_ext',
            include_dirs=[get_python_inc(), numpy.get_include(),
                          get_build_include('evalresp-3.3.0/include/')],
            library_dirs=[get_build_include('evalresp-3.3.0/lib/')],
            libraries=['evresp'],
            extra_compile_args=[
                '-Wextra',
                '-I%s' % get_build_include('evalresp-3.3.0/include')],
            sources=[op.join('src', 'ext', 'evalresp_ext.c')]),

        Extension(
            'ims_ext',
            include_dirs=[get_python_inc(), numpy.get_include()],
            extra_compile_args=['-Wextra'],
            sources=[op.join('src', 'io', 'ext', 'ims_ext.c')]),

        Extension(
            'datacube_ext',
            include_dirs=[get_python_inc(), numpy.get_include()],
            extra_compile_args=['-Wextra'],
            sources=[op.join('src', 'io', 'ext', 'datacube_ext.c')]),

        Extension(
            'autopick_ext',
            include_dirs=[get_python_inc(), numpy.get_include()],
            extra_compile_args=['-Wextra'],
            sources=[op.join('src', 'ext', 'autopick_ext.c')]),

        Extension(
            'gf.store_ext',
            include_dirs=[get_python_inc(), numpy.get_include()],
            extra_compile_args=['-D_FILE_OFFSET_BITS=64', '-Wextra'] + omp_arg,
            extra_link_args=[] + omp_lib,
            sources=[op.join('src', 'gf', 'ext', 'store_ext.c')]),

        Extension(
            'eikonal_ext',
            include_dirs=[get_python_inc(), numpy.get_include()],
            extra_compile_args=['-Wextra'] + omp_arg,
            extra_link_args=[] + omp_lib,
            sources=[op.join('src', 'ext', 'eikonal_ext.c')]),

        parstack_ext(),
        minmax_ext(),
        cuda_ext(),

        Extension(
            'ahfullgreen_ext',
            include_dirs=[get_python_inc(), numpy.get_include()],
            extra_compile_args=['-Wextra'],
            sources=[op.join('src', 'ext', 'ahfullgreen_ext.c')]),

        Extension(
            'orthodrome_ext',
            include_dirs=[get_python_inc(), numpy.get_include()],
            extra_compile_args=['-Wextra'],
            sources=[op.join('src', 'ext', 'orthodrome_ext.c')]),

        Extension(
            'avl',
            sources=[op.join('src', 'ext', 'pyavl-1.12', 'avl.c'),
                     op.join('src', 'ext', 'pyavl-1.12', 'avlmodule.c')],
            define_macros=[('HAVE_AVL_VERIFY', None),
                           ('AVL_FOR_PYTHON', None)],
            include_dirs=[get_python_inc()],
            extra_compile_args=['-Wno-parentheses', '-Wno-uninitialized'],
            extra_link_args=[] if sys.platform != 'sunos5' else ['-Wl,-x']),
    ],

    scripts=[
        'src/apps/gmtpy-epstopdf',
    ],

    entry_points={
        'console_scripts':
            ['fomosto = pyrocko.apps.fomosto:main',
             'cake = pyrocko.apps.cake:main',
             'automap = pyrocko.apps.automap:main',
             'hamster = pyrocko.apps.hamster:main',
             'jackseis = pyrocko.apps.jackseis:main',
             'colosseo = pyrocko.apps.colosseo:main'],
        'gui_scripts':
            ['snuffler = pyrocko.apps.snuffler:main']
    },

    package_data={
        packname: ['data/*.png',
                   'data/*.html',
                   'data/earthmodels/*.nd',
                   'data/colortables/*.cpt',
                   'data/tectonics/*.txt',
                   'data/fomosto_report/gfreport.*',
                   'gui/snufflings/map/*ml',
                   'gui/snufflings/map/*.js',
                   ] + get_readme_paths()}
)
