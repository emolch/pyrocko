# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Functionality to check for common data/metadata problems.
'''

from pyrocko.guts import StringChoice, Object, String, List
from pyrocko import util

from pyrocko.squirrel.model import CodesNSLCE
from pyrocko.squirrel.operators.base import CodesPatternFiltering
from pyrocko.squirrel.model import codes_patterns_for_kind, to_kind_id

guts_prefix = 'squirrel'


def get_matching(coverages, coverage):
    matching = []
    for candidate in coverages:
        if candidate.codes == coverage.codes:
            matching.append(candidate)

    matching.sort(
        key=lambda c: (coverage.deltat == c.deltat, not c.deltat))

    matching.reverse()

    return matching


class SquirrelCheckProblemType(StringChoice):
    '''
    Potential dataset/metadata problem types.

    .. list-table:: Squirrel check problem types
       :widths: 10 90
       :header-rows: 1

       * - Type
         - Description
%%(table)s

    '''

    types = {
        'p1': 'Waveform duplicates.',
        'p2': 'Overlaps in channel/response epochs.',
        'p3': 'No waveforms available for a channel/response listed in '
              'metadata.',
        'p4': 'Channel/response information missing for an available '
              'waveform.',
        'p5': 'Multiple channel/response entries matching an available '
              'waveform.',
        'p6': 'Sampling rate of waveform does not match rate listed in '
              'metadata.',
        'p7': 'Waveform incompletely covered by channel/response epochs.'}

    choices = list(types.keys())


SquirrelCheckProblemType.__doc__ %= {
    'table': '\n'.join('''
       * - %s
         - %s''' % (k, v) for (k, v) in SquirrelCheckProblemType.types.items())
}


class SquirrelCheckProblem(Object):
    '''
    Diagnostics about a potential problem reported by Squirrel check.
    '''
    type = SquirrelCheckProblemType.T(
        help='Coding indicating the type of problem detected.')
    symptom = String.T(
        help='Short description of the problem.')
    details = List.T(
        String.T(),
        help='Details about the problem.')


class KindChoiceWCR(StringChoice):
    choices = ['waveform', 'channel', 'response']


class SquirrelCheckEntry(Object):
    '''
    Squirrel check result for a given channel/response/waveform.
    '''
    codes = CodesNSLCE.T(
        help='Codes denominating a seismic channel.')
    available = List.T(
        KindChoiceWCR.T(),
        help='Available content kinds.')
    problems = List.T(
        SquirrelCheckProblem.T(),
        help='Potential problems detected.')

    def get_text(self):
        lines = []
        lines.append('  %s: %s' % (
            self.codes.channel
            + ('.%s' % self.codes.extra if self.codes.extra != '' else ''),
            ', '.join(self.available)))

        for problem in self.problems:
            lines.append('    - %s [%s]' % (problem.symptom, problem.type))
            for detail in problem.details:
                lines.append('      - %s' % detail)

        return '\n'.join(lines)


class SquirrelCheck(Object):
    '''
    Container for Squirrel check results.
    '''
    entries = List.T(SquirrelCheckEntry.T(), help='')

    def get_nproblems(self):
        '''
        Total number of problems detected.

        :rtype: int
        '''
        return sum(len(entry.problems) for entry in self.entries)

    def get_summary(self):
        '''
        Textual summary of check result.

        :rtype: str
        '''
        nproblems = self.get_nproblems()
        lines = []
        lines.append('%i potential problem%s discovered.' % (
            nproblems, util.plural_s(nproblems)))

        by_type = {}
        for entry in self.entries:
            for problem in entry.problems:
                t = problem.type
                if t not in by_type:
                    by_type[t] = 0

                by_type[t] += 1

        for t in sorted(by_type.keys()):
            lines.append('  %5i [%s]: %s' % (
                by_type[t], t, SquirrelCheckProblemType.types[t]))

        return '\n'.join(lines)

    def get_text(self, verbosity=0):
        '''
        Textual representation of check result.

        :param verbosity:
            Set verbosity level.
        :type verbosity:
            int

        :rtype: str
        '''
        lines = []
        by_nsl = {}
        for entry in self.entries:
            nsl = entry.codes.codes_nsl
            if nsl not in by_nsl:
                by_nsl[nsl] = []

            by_nsl[nsl].append(entry)

        for nsl in sorted(by_nsl.keys()):
            entries_this = by_nsl[nsl]
            nproblems = sum(len(entry.problems) for entry in entries_this)
            ok = nproblems == 0
            if ok and verbosity >= 1:
                lines.append('')
                lines.append('%s: ok' % str(nsl))

            if not ok:
                lines.append('')
                lines.append('%s: %i potential problem%s' % (
                    str(nsl),
                    nproblems,
                    util.plural_s(nproblems)))

            if not ok or verbosity >= 2:
                for entry in entries_this:
                    lines.append(entry.get_text())

        if self.get_nproblems() > 0 or verbosity >= 1:
            lines.append('')
            lines.append(self.get_summary())

        return '\n'.join(lines)


def do_check(squirrel, codes=None, tmin=None, tmax=None, time=None, ignore=[]):
    '''
    Check for common data/metadata problems.

    :param squirrel:
        The Squirrel instance to be checked.
    :type squirrel:
        :py:class:`~pyrocko.squirrel.base.Squirrel`

    :param tmin:
        Start time of query interval.
    :type tmin:
        :py:func:`pyrocko.util.get_time_float`

    :param tmax:
        End time of query interval.
    :type tmax:
        :py:func:`pyrocko.util.get_time_float`

    :param time:
        Time instant to query. Equivalent to setting ``tmin`` and ``tmax``
        to the same value.
    :type time:
        :py:func:`pyrocko.util.get_time_float`

    :param codes:
        Pattern of channel codes to query.
    :type codes:
        :class:`list` of :py:class:`~pyrocko.squirrel.model.CodesNSLCE`
        objects

    :param ignore:
        Problem types to be ignored.
    :type ignore:
        :class:`list` of :class:`str` (:py:class:`SquirrelCheckProblemType`)

    :returns:
        :py:class:`SquirrelCheck` object containing the results of the check.
    '''

    codes_set = set()
    for kind in ['waveform', 'channel', 'response']:
        if codes is not None:
            codes_pat = codes_patterns_for_kind(to_kind_id(kind), codes)
        else:
            codes_pat = None

        codes_filter = CodesPatternFiltering(codes=codes_pat)
        codes_set.update(
            codes_filter.filter(squirrel.get_codes(kind=kind)))

    entries = []
    for codes_ in list(sorted(codes_set)):
        problems = []
        coverage = {}
        for kind in ['waveform', 'channel', 'response']:
            coverage[kind] = squirrel.get_coverage(
                kind,
                codes=[codes_],
                tmin=tmin if tmin is not None else time,
                tmax=tmax if tmax is not None else time)

        available = [
            kind for kind in ['waveform', 'channel', 'response']
            if coverage[kind] and any(
                cov.total is not None for cov in coverage[kind])]

        for kind in ['waveform']:
            for cov in coverage[kind]:
                if any(count > 1 for (_, count) in cov.changes):
                    problems.append(SquirrelCheckProblem(
                        type='p1',
                        symptom='%s: %s' % (kind, 'duplicates')))

        for kind in ['channel', 'response']:
            for cov in coverage[kind]:
                if any(count > 1 for (_, count) in cov.changes):
                    problems.append(SquirrelCheckProblem(
                        type='p2',
                        symptom='%s: %s' % (kind, 'overlapping epochs')))

        if 'waveform' not in available:
            problems.append(SquirrelCheckProblem(
                type='p3',
                symptom='no waveforms'))

        for cw in coverage['waveform']:
            for kind in ['channel', 'response']:
                ccs = get_matching(coverage[kind], cw)
                if not ccs:
                    problems.append(SquirrelCheckProblem(
                        type='p4',
                        symptom='no %s information' % kind))

                elif len(ccs) > 1:
                    problems.append(SquirrelCheckProblem(
                        type='p5',
                        symptom='multiple %s matches (waveform: %g Hz, %s: %s)'
                        % (kind, 1.0 / cw.deltat, kind, ', '.join(
                            '%g Hz' % (1.0 / cc.deltat)
                            if cc.deltat else '? Hz' for cc in ccs))))

                if ccs:
                    cc = ccs[0]
                    if cc.deltat and cc.deltat != cw.deltat:
                        problems.append(SquirrelCheckProblem(
                            type='p6',
                            symptom='sampling rate mismatch '
                            '(waveform: %g Hz, %s: %g Hz)' % (
                                1.0 / cw.deltat, kind, 1.0 / cc.deltat)))

                    uncovered_spans = list(cw.iter_uncovered_by_combined(cc))
                    if uncovered_spans:
                        problems.append(SquirrelCheckProblem(
                            type='p7',
                            symptom='incompletely covered by %s:' % kind,
                            details=[
                                '%s - %s' % (
                                    util.time_to_str(span[0]),
                                    util.time_to_str(span[1]))
                                for span in uncovered_spans]))

        entries.append(SquirrelCheckEntry(
            codes=codes_,
            available=available,
            problems=[p for p in problems if p.type not in ignore]))

    return SquirrelCheck(entries=entries)


__all__ = [
    'SquirrelCheckProblemType',
    'SquirrelCheckProblem',
    'SquirrelCheckEntry',
    'SquirrelCheck',
    'do_check']
