# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Base class for earthquake catalog clients.
'''


class EarthquakeCatalog(object):
    '''
    Base class for Pyrocko's earthquake catalog clients.
    '''

    def get_event(self, name):
        raise NotImplementedError

    def iter_event_names(self, time_range, **kwargs):
        raise NotImplementedError

    def get_event_names(self, time_range, **kwargs):
        return list(self.iter_event_names(time_range, **kwargs))

    def get_events(self, time_range, **kwargs):
        return list(self.iter_events(time_range, **kwargs))

    def iter_events(self, time_range, **kwargs):
        for name in self.iter_event_names(time_range, **kwargs):
            yield self.get_event(name)


class NotFound(Exception):
    def __init__(self, url=None):
        Exception.__init__(self)
        self._url = url

    def __str__(self):
        if self._url:
            return 'No results for request %s' % self._url
        else:
            return 'No results for request'
