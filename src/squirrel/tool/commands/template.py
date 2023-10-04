# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel template`.
'''

import re
import logging

from pyrocko.guts import load_string, dump

from pyrocko.squirrel.error import ToolError
from ..common import dq, ldq

logger = logging.getLogger('psq.cli.template')

headline = 'Print configuration snippets.'

path_prefix = '''
# All file paths given below are treated relative to the location of this
# configuration file. Here we may give a common prefix. For example, if the
# configuration file is in the sub-directory 'PROJECT/config/', set it to '..'
# so that all paths are relative to 'PROJECT/'.
path_prefix: '.'
'''.strip()


def _template_online_dataset(**kwargs):
    lqargs = []
    for k in ['network', 'station', 'channel']:
        if k in kwargs:
            v = kwargs.pop(k)
            lqargs.append("    %s: '%s'" % (k, v))

    kwargs['qargs'] = '\n' + '\n'.join(lqargs) if lqargs else '{}'
    return '''
--- !squirrel.Dataset

{path_prefix}

# Data sources to be added (LocalData, FDSNSource, CatalogSource, ...)
sources:
- !squirrel.FDSNSource

  # URL or alias of FDSN site.
  site: {site}

  # Uncomment to let metadata expire in 10 days:
  #expires: 10d

  # Waveforms can be optionally shared with other FDSN client configurations,
  # so that data is not downloaded multiple times. The downside may be that in
  # some cases more data than expected is available (if data was previously
  # downloaded for a different application).
  #shared_waveforms: true

  # FDSN query arguments to make metadata queries.
  # See http://www.fdsn.org/webservices/fdsnws-station-1.1.pdf
  # Time span arguments should not be added here, because they are handled
  # automatically by Squirrel.
  query_args: {qargs}
'''.format(path_prefix=path_prefix, **kwargs).strip()


templates = {
    'local.dataset': {
        'description':
            'A typical collection of local files.',
        'yaml': '''
--- !squirrel.Dataset

{path_prefix}

# Data sources to be added (LocalData, FDSNSource, CatalogSource, ...)
sources:
- !squirrel.LocalData  # This data source is for local files.

  # These paths are scanned for waveforms, stations, events.
  paths:
  - 'catalogs/events.txt'
  - 'meta/stations.xml'
  - 'data/waveforms'

  # Select file format or 'detect' for autodetection.
  format: 'detect'
'''.format(path_prefix=path_prefix).strip()},

    'geofon.dataset': {
        'description':
            'Everything available through GEOFON.',
        'yaml': _template_online_dataset(
            site='geofon',
        ),
    },

    'iris-seis.dataset': {
        'description':
            'High- and low-gain seismometer channels from IRIS.',
        'yaml': _template_online_dataset(
            site='iris',
            channel='?H?,?L?',
        ),
    },

    'iris-seis-bb.dataset': {
        'description':
            'Broad-band high-gain seismometer channels from IRIS.',
        'yaml': _template_online_dataset(
            site='iris',
            channel='VH?,LH?,BH?,HH?',
        ),
    },

    'bgr-gr-lh.dataset': {
        'description': 'LH channels for network GR from BGR.',
        'yaml': _template_online_dataset(
            site='bgr',
            network='GR',
            channel='LH?',
        ),
    },

    'gcmt-m7.dataset': {
        'description': 'Global-CMT events with Mw >= 7.0.',
        'yaml': '''
--- !squirrel.Dataset

{path_prefix}

# Data sources to be added (LocalData, FDSNSource, CatalogSource, ...)
sources:
- !squirrel.CatalogSource
  catalog: gcmt
  query_args:
    magmin: '7.0'
'''.format(path_prefix=path_prefix).strip()
    },
}

names = sorted(templates.keys())

template_listing = '\n'.join(
    '%-30s %s' % (
        '%s:' % name,
        templates[name]['description']) for name in templates)


def make_subparser(subparsers):
    return subparsers.add_parser(
        'template',
        help=headline,
        description=headline + '''

Available SNIPPETs

{}
'''.format('\n'.join('    ' + line for line in template_listing.splitlines())))


def setup(parser):
    parser.add_argument(
        'name',
        choices=names,
        nargs='?',
        metavar='SNIPPET',
        help='Name of template snippet to print.')

    format_default = 'commented'
    format_choices = ['commented', 'normal', 'brief']

    parser.add_argument(
        '--format', '-f',
        choices=format_choices,
        default=format_default,
        metavar='FMT',
        help='Set verbosity level of output YAML. Choices: %s. '
             'Default: %s.' % (ldq(format_choices), dq(format_default)))

    parser.add_argument(
        '--write', '-w',
        action='store_true',
        help='Write to file.')


def decomment(s):
    out = []
    for line in s.splitlines():
        line = re.sub(r'#.+', '', line)
        if line.strip():
            out.append(line)

    return '\n'.join(out)


def brief(s):
    return dump(load_string(s))


def run(parser, args):

    if not args.name:
        print(template_listing)

    else:
        func = {
            'brief': brief,
            'commented': lambda s: s,
            'normal': decomment}[args.format]

        s = func(templates[args.name]['yaml'])

        if args.write:
            path = args.name + '.yaml'
            try:
                with open(path, 'x') as f:
                    f.write(s)
                    f.write('\n')

                logger.info('File written: %s' % path)

            except FileExistsError:
                raise ToolError('File exists: %s' % path)
        else:
            print(s)
