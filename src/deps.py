# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Library dependency checkup utilities.
'''

import sys
import os.path as op
from importlib import import_module
import logging

logger = logging.getLogger('pyrocko.deps')


_pyrocko_deps = {
    'required': [
        ('python', 'sys', lambda x: '.'.join(map(str, x.version_info[:3]))),
        ('pyyaml', 'yaml', '__version__'),
        ('numpy', 'numpy', '__version__'),
        ('scipy', 'scipy', '__version__'),
        ('matplotlib', 'matplotlib', '__version__'),
        ('requests', 'requests', '__version__'),
    ],
    'optional': [
        ('PyQt5', 'PyQt5.Qt', 'PYQT_VERSION_STR'),
        ('PyQtWebEngine', 'PyQt5.QtWebEngine', 'PYQT_WEBENGINE_VERSION_STR'),
        ('vtk', 'vtk', 'VTK_VERSION'),
        ('pyserial', 'serial', '__version__'),
        ('kite', 'kite', '__version__'),
    ],
}


_module_to_package_name = dict(
    (module_name, package_name)
    for (package_name, module_name, _)
    in _pyrocko_deps['required'] + _pyrocko_deps['optional'])


def dependencies(group):

    d = {}
    for (package_name, module_name, version_attr) in _pyrocko_deps[group]:
        try:
            mod = import_module(module_name)
            d[package_name] = getattr(mod, version_attr) \
                if isinstance(version_attr, str) \
                else version_attr(mod)
        except ImportError:
            d[package_name] = None

    return d


def str_dependencies():
    lines = []
    lines.append('dependencies:')
    for group in ['required', 'optional']:
        lines.append('  %s:' % group)

        for package, version in dependencies(group).items():
            lines.append('    %s: %s' % (
                package,
                version or 'N/A'))

    return '\n'.join(lines)


def print_dependencies():
    print(str_dependencies())


class MissingPyrockoDependency(ImportError):
    pass


def require(module_name):
    try:
        return import_module(module_name)
    except ImportError as e:
        package_name = _module_to_package_name[module_name]

        raise MissingPyrockoDependency('''

Missing Pyrocko requirement: %s

The Python package '%s' is required to run this program, but it doesn't seem to
be available or an error occured while importing it. Use your package manager
of choice (apt / yum / conda / pip) to install it. To verify that '%s' is
available in your Python environment, check that "python -c \'import %s\'"
exits without error. The original error was:

  %s
''' % (
                package_name,
                package_name,
                package_name,
                module_name,
                str(e))) from None


def import_optional(module_name, needed_for):
    try:
        return import_module(module_name)
    except ImportError as e:
        package_name = _module_to_package_name[module_name]

        logger.info(
            'Optional Pyrocko dependency "%s" is not available '
            '(needed for %s): %s' % (
                package_name,
                needed_for,
                str(e)))

        return None


def require_all(group):
    for (_, module_name, _) in _pyrocko_deps[group]:
        require(module_name)


def find_pyrocko_installations():
    found = []
    seen = set()
    orig_sys_path = list(sys.path)
    while sys.path:

        try:
            import pyrocko
            dpath = op.dirname(op.abspath(pyrocko.__file__))
            if dpath not in seen:
                x = (pyrocko.installed_date, dpath,
                     pyrocko.long_version,
                     pyrocko.src_path if hasattr(pyrocko, 'src_path') else '?')

                found.append(x)
            seen.add(dpath)

            del sys.modules['pyrocko']
            del sys.modules['pyrocko.info']
        except (ImportError, AttributeError):
            pass

        sys.path.pop(0)

    sys.path = orig_sys_path
    return found


def str_installations(found):
    lines = [
        'Python library path (sys.path): \n  %s\n' % '\n  '.join(sys.path)]

    dates = sorted([xx[0] for xx in found])
    i = 1

    for (installed_date, installed_path, long_version, src_path) in found:
        oldnew = ''
        if len(dates) >= 2:
            if installed_date == dates[0]:
                oldnew = ' (oldest)'

            if installed_date == dates[-1]:
                oldnew = ' (newest)'

        lines.append('''Pyrocko installation #%i %s:
  date installed: %s%s
  version: %s
  path: %s
  src path: %s
''' % (
            i, '(used)' if i == 1 else '(not used)',
            installed_date,
            oldnew,
            long_version,
            installed_path,
            src_path))

        i += 1

    return '\n'.join(lines)


def print_installations():
    found = find_pyrocko_installations()
    print(str_installations(found))


if __name__ == '__main__':
    print_dependencies()
    print()
    print_installations()
