from __future__ import division, print_function, absolute_import
import unittest
import os
import sys
import time
from pyrocko import util
from pyrocko.cuda_ext import CUDA_COMPILED, check_cuda_supported
import functools
import logging
import socket
import shutil
from io import StringIO

try:
    new_str = unicode
except NameError:
    new_str = str

logger = logging.getLogger("pyrocko.test.common")

mpl_logger = logging.getLogger("matplotlib")
mpl_logger.setLevel(logging.WARNING)

benchmark_results = []

g_matplotlib_inited = False

TEST_CUDA = CUDA_COMPILED and check_cuda_supported()

require_cuda = unittest.skipIf(
    not TEST_CUDA, "compiled without CUDA support or no CUDA device available"
)

implementations = ["numpy", "openmp"]
if TEST_CUDA:
    implementations += ["cuda", "cuda_thrust", "cuda_atomic"]


def matplotlib_use_agg():
    global g_matplotlib_inited
    if not g_matplotlib_inited:
        import matplotlib

        matplotlib.use("Agg")  # noqa
        g_matplotlib_inited = True


def test_data_file_no_download(fn):
    return os.path.join(os.path.split(__file__)[0], "data", fn)


def test_data_file(fn):
    fpath = test_data_file_no_download(fn)
    if not os.path.exists(fpath):
        if not have_internet():
            raise unittest.SkipTest(
                "need internet access to download data file"
            )

        url = "http://data.pyrocko.org/testing/" + fn
        logger.info("downloading %s" % url)
        util.download_file(url, fpath)

    return fpath


def measure(func, nrepeats, *args, **kwargs):
    nrepeats = max(1, nrepeats)
    t0 = time.time()
    for _ in range(nrepeats):
        ans = func(*args, **kwargs)
    t1 = time.time()
    return ans, (t1 - t0) / nrepeats


def have_internet():
    try:
        return 0 < len(
            [
                (s.connect(("8.8.8.8", 80)), s.close())
                for s in [socket.socket(socket.AF_INET, socket.SOCK_DGRAM)]
            ]
        )

    except OSError:
        return False


require_internet = unittest.skipUnless(have_internet(), "need internet access")


def skip_on(*exceptions):
    def skip_on(f):
        @functools.wraps(f)
        def wrap_f(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except exceptions as e:
                raise unittest.SkipTest(
                    'skipped due to %s: "%s"' % (e.__class__.__name__, str(e))
                )

        return wrap_f

    return skip_on


def skip_on_download_error(f):
    @functools.wraps(f)
    def wrap_f(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except util.DownloadError:
            raise unittest.SkipTest("download failed")

    return wrap_f


def have_gui():
    display = os.environ.get("DISPLAY", "")
    if not display:
        return False

    try:
        from pyrocko.gui.qt_compat import qc  # noqa
    except ImportError:
        return False

    return True


require_gui = unittest.skipUnless(have_gui(), "no gui support configured")


def have_obspy():
    try:
        import obspy  # noqa

        return True
    except ImportError:
        return False


require_obspy = unittest.skipUnless(have_obspy(), "obspy not installed")


class Benchmark(object):
    def __init__(self, prefix=None):
        self.prefix = prefix or ""
        self.show_factor = False
        self.results = []

    def __call__(self, func):
        def stopwatch(*args):
            t0 = time.time()
            name = self.prefix + func.__name__
            result = func(*args)
            elapsed = time.time() - t0
            self.results.append((name, elapsed))
            return result

        return stopwatch

    def labeled(self, label):
        def wrapper(func):
            @functools.wraps(func)
            def stopwatch(*args):
                t0 = time.time()
                result = func(*args)
                elapsed = time.time() - t0
                self.results.append((label, elapsed))
                return result

            return stopwatch

        return wrapper

    def __str__(self, header=True):
        if not self.results:
            return "No benchmarks ran"
        tmax = max([r[1] for r in self.results])

        rstr = ["Benchmark results"]
        if self.prefix != "":
            rstr[-1] += " - %s" % self.prefix

        if self.results:
            indent = max([len(name) for name, _ in self.results])
        else:
            indent = 0
        rstr.append("=" * (indent + 17))
        rstr.insert(0, rstr[-1])

        if not header:
            rstr = []

        for res in self.results:
            rstr.append(
                "{0:<{indent}}{1:.8f} s".format(*res, indent=indent + 5)
            )
            if self.show_factor:
                rstr[-1] += "{0:8.2f} x".format(tmax / res[1])
        if len(self.results) == 0:
            rstr.append("None ran!")

        return "\n".join(rstr)

    def clear(self):
        self.results = []


class PyrockoExit(Exception):
    def __init__(self, res):
        Exception.__init__(self, str(res))
        self.result = res


class Capture(object):
    def __init__(self, tee=False):
        self.file = StringIO()
        self.tee = tee

    def __enter__(self):
        self.orig_stdout = sys.stdout
        self.orig_exit = sys.exit
        sys.stdout = self

        def my_exit(res):
            raise PyrockoExit(res)

        sys.exit = my_exit

    def __exit__(self, *args):
        sys.stdout = self.orig_stdout
        sys.exit = self.orig_exit

    def write(self, data):
        data = new_str(data)
        self.file.write(data)
        if self.tee:
            self.orig_stdout.write(data)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        self.file.flush()

    def isatty(self):
        return False

    def getvalue(self):
        return self.file.getvalue()


def call(program, *args, **kwargs):
    if program == "fomosto":
        from pyrocko.apps.fomosto import main
    else:
        assert False, "program %s not available" % program

    # tee = True
    tee = kwargs.get("tee", False)
    logger.info("Calling: %s %s" % (program, " ".join(args)))
    cap = Capture(tee=tee)
    with cap:
        main(list(args))

    return cap.getvalue()


def call_assert_usage(program, *args):
    res = None
    try:
        call(program, *args)
    except PyrockoExit as e:
        res = e.result

    assert res.startswith("Usage")


class chdir(object):
    def __init__(self, path):
        self._path = path

    def __enter__(self):
        self._oldwd = os.getcwd()
        os.chdir(self._path)

    def __exit__(self, *args):
        os.chdir(self._oldwd)


class run_in_temp(object):
    def __init__(self, path=None):
        self._must_delete = False
        self._path = path

    def __enter__(self):
        if self._path is None:
            from tempfile import mkdtemp

            self._path = mkdtemp(prefix="pyrocko-test")
            self._must_delete = True

        self._oldwd = os.getcwd()
        os.chdir(self._path)

    def __exit__(self, *args):
        os.chdir(self._oldwd)
        if self._must_delete:
            shutil.rmtree(self._path)
