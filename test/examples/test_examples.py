# python 2/3
from __future__ import division, print_function, absolute_import
import sys
import unittest
import os
import glob
try:
    from urllib2 import HTTPError
except ImportError:
    from urllib.error import HTTPError

from .. import common

from pyrocko import ExternalProgramMissing

from pyrocko import util
from pyrocko import example
from pyrocko import pile
from pyrocko.plot import gmtpy
from pyrocko import orthodrome

from pyrocko.gui.snuffler import snuffler
from pyrocko.dataset import topo


op = os.path

project_dir = op.join(op.dirname(op.abspath(__file__)), '..', '..')


skip_examples = [
    'trace_restitution_dseed.py',
    'gf_forward_viscoelastic.py'
]

need_sys_argv_examples = {
    'squirrel_rms3b.py': [
        ['', 'rms', '--tmin=2022-01-14', '--tmax=2022-01-15',
         '--codes=*.*.*.LHZ'],
    ]
}

# these tests fail to mmap on some systems (ubuntu 18.04) when example_run_dir
# is in virtualbox shared folder
need_run_dir_local = ['plot_radiation_pattern.py']


def tutorial_run_dir():
    return op.join(project_dir, 'test', 'example_run_dir')


def tutorial_run_dir_local():
    return op.join(project_dir, 'test', 'example_run_dir_local')


def noop(*args, **kwargs):
    pass


class ExamplesTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from matplotlib import pyplot as plt

        cls.dn = open(os.devnull, 'w')
        sys.stdout = cls.dn

        plt.show_orig_testex = plt.show
        plt.show = noop

        snuffler.snuffle_orig_testex = snuffler.snuffle
        snuffler.snuffle = noop

        cls._show_progress_force_off_orig = pile.show_progress_force_off
        pile.show_progress_force_off = True

        orthodrome.raise_if_slow_path_contains_points = True

    @classmethod
    def tearDownClass(cls):
        from matplotlib import pyplot as plt

        cls.dn.close()
        sys.stdout = sys.__stdout__

        snuffler.snuffle = snuffler.snuffle_orig_testex
        plt.show = plt.show_orig_testex
        pile.show_progress_force_off = cls._show_progress_force_off_orig

        orthodrome.raise_if_slow_path_contains_points = False


example_files = [
    fn for fn in glob.glob(op.join(project_dir, 'examples', '*.py'))
    if os.path.basename(fn) not in skip_examples]


def _make_function(test_name, fn):
    def f(self):
        imp = imp2 = None
        try:
            import imp

        except ImportError:
            import importlib.machinery as imp2

        basename = os.path.basename(fn)

        for argv in need_sys_argv_examples.get(basename, [['']]):
            cwd = os.getcwd()
            try:
                sys_argv_original, sys.argv = sys.argv, argv

                if basename in need_run_dir_local:
                    run_dir = tutorial_run_dir_local()
                else:
                    run_dir = tutorial_run_dir()

                util.ensuredir(run_dir)
                os.chdir(run_dir)

                if imp:
                    imp.load_source(test_name, fn)
                else:
                    imp2.SourceFileLoader(project_dir, fn)

            except example.util.DownloadError:
                raise unittest.SkipTest(
                    'could not download required data file')

            except HTTPError as e:
                raise unittest.SkipTest('skipped due to %s: "%s"' % (
                    e.__class__.__name__, str(e)))

            except ExternalProgramMissing as e:
                raise unittest.SkipTest(str(e))

            except ImportError as e:
                raise unittest.SkipTest(str(e))

            except topo.AuthenticationRequired:
                raise unittest.SkipTest(
                    'cannot download topo data (no auth credentials)')

            except gmtpy.GMTInstallationProblem:
                raise unittest.SkipTest('GMT not installed or not usable')

            except orthodrome.Slow:
                raise unittest.SkipTest(
                    'skipping test using slow point-in-poly')

            except Exception as e:
                raise e

            finally:
                sys.argv = sys_argv_original
                os.chdir(cwd)

    f.__name__ = 'test_example_' + test_name

    return f


for fn in sorted(example_files):
    test_name = op.splitext(op.split(fn)[-1])[0]
    setattr(
        ExamplesTestCase,
        'test_example_' + test_name,
        _make_function(test_name, fn))


if __name__ == '__main__':
    util.setup_logging('test_examples', 'warning')
    common.matplotlib_use_agg()
    unittest.main()
