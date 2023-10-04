# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Base class for Squirrel remote data clients.
'''

from pyrocko.guts import Object, Timestamp, List

from ..model import CodesNSLCE


guts_prefix = 'squirrel'


class Constraint(Object):

    '''
    Used by some data-sources to grow or join locally mirrored data selections.

    Squirrel data-sources typically try to mirror only a subset of the remotely
    available data. This subset may need to be grown or updated when data from
    other time intervals or from locations outside the initially requested
    region is requested. This class helps in the involved bookeeping.

    The current implementation only supports a time interval selection with a
    single time span but more sophisticated constraints, including e.g.
    location boxes could be thought of.
    '''

    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)
    codes = List.T(CodesNSLCE.T(), optional=True)

    def __init__(self, **kwargs):
        codes = kwargs.pop('codes', None)

        if codes is None:
            pass
        elif not isinstance(codes, list):
            codes = [CodesNSLCE(codes)]
        else:
            codes = [CodesNSLCE(sc) for sc in codes]

        Object.__init__(self, codes=codes, **kwargs)

    def contains(self, constraint):
        '''
        Check if the constraint completely includes a more restrictive one.

        :param constraint:
            Other constraint.
        :type constraint:
            :py:class:`Constraint`
        '''

        if self.tmin is not None and constraint.tmin is not None:
            b1 = self.tmin <= constraint.tmin
        elif self.tmin is None:
            b1 = True
        else:
            b1 = False

        if self.tmax is not None and constraint.tmax is not None:
            b2 = constraint.tmax <= self.tmax
        elif self.tmax is None:
            b2 = True
        else:
            b2 = False

        return b1 and b2

    def expand(self, constraint):
        '''
        Widen constraint to include another given constraint.

        :param constraint:
            Other constraint.
        :type constraint:
            :py:class:`Constraint`

        Update is done in-place.
        '''

        if constraint.tmin is None or self.tmin is None:
            self.tmin = None
        else:
            self.tmin = min(constraint.tmin, self.tmin)

        if constraint.tmax is None or self.tmax is None:
            self.tmax = None
        else:
            self.tmax = max(constraint.tmax, self.tmax)


class Source(Object):

    '''
    Base class for Squirrel data-sources.

    Data-sources can be attached to a Squirrel instance to allow transparent
    access to remote (or otherwise generated) resources, e.g. through FDSN web
    services (:py:class:`~pyrocko.squirrel.client.fdsn.FDSNSource`) or online
    event catalogs
    (:py:class:`~pyrocko.squirrel.client.catalog.CatalogSource`).

    Derived classes implement the details of querying, caching, updating and
    bookkeeping of the accessed data.
    '''

    def update_channel_inventory(self, squirrel, constraint):
        '''
        Let local inventory be up-to-date with remote for a given constraint.
        '''

        pass

    def update_event_inventory(self, squirrel, constraint):
        '''
        Let local inventory be up-to-date with remote for a given constraint.
        '''

        pass

    def update_waveform_promises(self, squirrel, constraint):
        '''
        Let local inventory be up-to-date with remote for a given constraint.
        '''

        pass

    def remove_waveform_promises(self, squirrel, from_database='selection'):
        '''
        Remove waveform promises from live selection or global database.

        :param from_database:
            Remove from live selection ``'selection'`` or global database
            ``'global'``.
        '''

        pass

    def update_response_inventory(self, squirrel, constraint):
        '''
        Let local inventory be up-to-date with remote for a given constraint.
        '''

        pass


__all__ = [
    'Source',
    'Constraint',
]
