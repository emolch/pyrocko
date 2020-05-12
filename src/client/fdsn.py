# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Low-level FDSN web service client.

This module provides basic functionality to download station metadata, time
series data and event information from FDSN web services. Password and token
authentication are supported. Query responses are returned as open file-like
objects or can be parsed into Pyrocko's native data structures where
appropriate.

.. _registered-site-names:

Registered site names
.....................

A list of known FDSN site names is maintained within the module for quick
selection by the user. This list currently contains the following sites:

%s

Any other site can be specified by providing its full URL.
'''

from __future__ import absolute_import

import re
import logging
import ssl
import socket


from pyrocko import util
from pyrocko.util import DownloadError
from pyrocko import config

from pyrocko.util import \
    urlencode, Request, build_opener, HTTPDigestAuthHandler, urlopen, HTTPError

try:
    newstr = unicode
except NameError:
    newstr = str

logger = logging.getLogger('pyrocko.client.fdsn')

g_url = '%(site)s/fdsnws/%(service)s/%(majorversion)i/%(method)s'

g_site_abbr = {
    'geofon': 'https://geofon.gfz-potsdam.de',
    'iris': 'http://service.iris.edu',
    'orfeus': 'http://www.orfeus-eu.org',
    'bgr': 'http://eida.bgr.de',
    'geonet': 'http://service.geonet.org.nz',
    'knmi': 'http://rdsa.knmi.nl',
    'ncedc': 'http://service.ncedc.org',
    'scedc': 'http://service.scedc.caltech.edu',
    'usgs': 'http://earthquake.usgs.gov',
    'koeri': 'http://eida-service.koeri.boun.edu.tr',
    'ethz': 'http://eida.ethz.ch',
    'icgc': 'http://ws.icgc.cat',
    'ipgp': 'http://eida.ipgp.fr',
    'ingv': 'http://webservices.ingv.it',
    'isc': 'http://www.isc.ac.uk',
    'lmu': 'http://erde.geophysik.uni-muenchen.de',
    'noa': 'http://eida.gein.noa.gr',
    'resif': 'http://ws.resif.fr',
    'usp': 'http://seisrequest.iag.usp.br',
    'niep': 'http://eida-sc3.infp.ro'
}

g_default_site = 'geofon'


g_default_query_args = {
    'station': {
        'starttime', 'endtime', 'startbefore', 'startafter', 'endbefore',
        'endafter', 'network', 'station', 'location', 'channel', 'minlatitude',
        'maxlatitude', 'minlongitude', 'maxlongitude', 'latitude', 'longitude',
        'minradius', 'maxradius', 'level', 'includerestricted',
        'includeavailability', 'updatedafter', 'matchtimeseries', 'format',
        'nodata'},
    'dataselect': {
        'starttime', 'endtime', 'network', 'station', 'location', 'channel',
        'quality', 'minimumlength', 'longestonly', 'format', 'nodata'},
    'event': {
        'starttime', 'endtime', 'minlatitude', 'maxlatitude', 'minlongitude',
        'maxlongitude', 'latitude', 'longitude', 'minradius', 'maxradius',
        'mindepth', 'maxdepth', 'minmagnitude', 'maxmagnitude', 'eventtype',
        'includeallorigins', 'includeallmagnitudes', 'includearrivals',
        'eventid', 'limit', 'offset', 'orderby', 'catalog', 'contributor',
        'updatedafter', 'format', 'nodata'},
    'availability': {
        'starttime', 'endtime', 'network', 'station', 'location', 'channel',
        'quality', 'merge', 'orderby', 'limit', 'includerestricted', 'format',
        'nodata', 'mergegaps', 'show'}}


def doc_escape_slist(li):
    return ', '.join("``'%s'``" % s for s in li)


def doc_table_dict(d, khead, vhead, indent=''):
    keys, vals = zip(*sorted(d.items()))

    lk = max(max(len(k) for k in keys), len(khead))
    lv = max(max(len(v) for v in vals), len(vhead))

    hr = '=' * lk + ' ' + '=' * lv

    lines = [
        hr,
        '%s %s' % (khead.ljust(lk), vhead.ljust(lv)),
        hr]

    for k, v in zip(keys, vals):
        lines.append('%s %s' % (k.ljust(lk), v.ljust(lv)))

    lines.append(hr)
    return '\n'.join(indent + line for line in lines)


def strip_html(s):
    s = s.decode('utf-8')
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'\r', '', s)
    s = re.sub(r'\s*\n', '\n', s)
    return s


def indent(s, ind='  '):
    return '\n'.join(ind + line for line in s.splitlines())


def get_sites():
    '''
    Get sorted list of registered site names.
    '''
    return sorted(g_site_abbr.keys())


if config.config().fdsn_timeout is None:
    g_timeout = 20.
else:
    g_timeout = config.config().fdsn_timeout

re_realm_from_auth_header = re.compile(r'(realm)\s*[:=]\s*"([^"]*)"?')


class CannotGetRealmFromAuthHeader(DownloadError):
    '''
    Raised when failing to parse server response during authentication.
    '''
    pass


class CannotGetCredentialsFromAuthRequest(DownloadError):
    '''
    Raised when failing to parse server response during token authentication.
    '''
    pass


def get_realm_from_auth_header(headers):
    realm = dict(re_realm_from_auth_header.findall(
        headers['WWW-Authenticate'])).get('realm', None)

    if realm is None:
        raise CannotGetRealmFromAuthHeader('headers=%s' % str(headers))

    return realm


def sdatetime(t):
    return util.time_to_str(t, format='%Y-%m-%dT%H:%M:%S')


class EmptyResult(DownloadError):
    '''
    Raised when an empty server response is retrieved.
    '''
    def __init__(self, url):
        DownloadError.__init__(self)
        self._url = url

    def __str__(self):
        return 'No results for request %s' % self._url


class RequestEntityTooLarge(DownloadError):
    '''
    Raised when the server indicates that too much data was requested.
    '''
    def __init__(self, url):
        DownloadError.__init__(self)
        self._url = url

    def __str__(self):
        return 'Request entity too large: %s' % self._url


class InvalidRequest(DownloadError):
    '''
    Raised when an invalid request would be sent / has been sent.
    '''
    pass


class Timeout(DownloadError):
    '''
    Raised when the server does not respond within the allowed timeout period.
    '''
    pass


def _request(
        url,
        post=False,
        user=None,
        passwd=None,
        allow_TLSv1=False,
        timeout=g_timeout,
        **kwargs):

    url_values = urlencode(kwargs)
    if url_values:
        url += '?' + url_values

    logger.debug('Accessing URL %s' % url)
    url_args = {
        'timeout': timeout
    }

    if allow_TLSv1:
        url_args['context'] = ssl.SSLContext(ssl.PROTOCOL_TLSv1)

    opener = None

    req = Request(url)
    if post:
        if isinstance(post, newstr):
            post = post.encode('utf8')
        logger.debug('POST data: \n%s' % post.decode('utf8'))
        req.data = post

    req.add_header('Accept', '*/*')

    itry = 0
    while True:
        itry += 1
        try:
            urlopen_ = opener.open if opener else urlopen
            while True:
                try:
                    resp = urlopen_(req, **url_args)
                    break
                except TypeError:
                    del url_args['context']  # context not avail before 3.4.3

            logger.debug('Response: %s' % resp.getcode())
            if resp.getcode() == 204:
                raise EmptyResult(url)
            return resp

        except HTTPError as e:
            if e.code == 413:
                raise RequestEntityTooLarge(url)

            elif e.code == 401:
                headers = getattr(e, 'headers', e.hdrs)

                realm = get_realm_from_auth_header(headers)

                if itry == 1 and user is not None:
                    auth_handler = HTTPDigestAuthHandler()
                    auth_handler.add_password(
                        realm=realm,
                        uri=url,
                        user=user,
                        passwd=passwd or '')

                    opener = build_opener(auth_handler)
                    continue
                else:
                    raise DownloadError(
                        'Authentication failed for realm "%s" when accessing '
                        'url "%s". Original error was: %s' % (
                            realm, url, str(e)))

            else:
                raise DownloadError(
                    'Error content returned by server (HTML stripped):\n%s\n'
                    '  Original error was: %s' % (
                        indent(
                            strip_html(e.read()),
                            '  !  '),
                        str(e)))

        except socket.timeout:
            raise Timeout(
                'Timeout error. No response received within %i s. You '
                'may want to retry with a longer timeout setting.' % timeout)

        break


def fillurl(service, site, url, majorversion, method):
    return url % dict(
        site=g_site_abbr.get(site, site),
        service=service,
        majorversion=majorversion,
        method=method)


def fix_params(d):

    params = dict(d)
    for k in ['starttime',
              'endtime',
              'startbefore',
              'startafter',
              'endbefore',
              'endafter',
              'updatedafter']:

        if k in params:
            params[k] = sdatetime(params[k])

    if params.get('location', None) == '':
        params['location'] = '--'

    for k in params:
        if isinstance(params[k], bool):
            params[k] = ['false', 'true'][bool(params[k])]

    return params


def make_data_selection(
        stations, tmin, tmax,
        channel_prio=[['BHZ', 'HHZ'],
                      ['BH1', 'BHN', 'HH1', 'HHN'],
                      ['BH2', 'BHE', 'HH2', 'HHE']]):

    selection = []
    for station in stations:
        wanted = []
        for group in channel_prio:
            gchannels = []
            for channel in station.get_channels():
                if channel.name in group:
                    gchannels.append(channel)
            if gchannels:
                gchannels.sort(key=lambda a: group.index(a.name))
                wanted.append(gchannels[0])

        if wanted:
            for channel in wanted:
                selection.append((station.network, station.station,
                                  station.location, channel.name, tmin, tmax))

    return selection


def station(
        site=g_default_site,
        url=g_url,
        majorversion=1,
        timeout=g_timeout,
        check=True,
        selection=None,
        parsed=True,
        **kwargs):

    '''
    Query FDSN web service for station metadata.

    :param site:
        :ref:`Registered site name <registered-site-names>` or full base URL of
        the service (e.g. ``'https://geofon.gfz-potsdam.de'``).
    :type site: str, optional
    :param url:
        URL template (default should work in 99% of cases).
    :type url: str, optional
    :param majorversion:
        Major version of the service to query (always ``1`` at the time of
        writing).
    :type majorversion: int, optional
    :param timeout:
        Network timeout in [s]. Global default timeout can be configured in
        Pyrocko's configuration file under ``fdsn_timeout``.
    :type timeout: float, optional
    :param check:
        If ``True`` arguments are checked against self-description (WADL) of
        the queried web service if available or FDSN specification.
    :type check: bool, optional
    :param selection:
        If given, selection to be queried as a list of tuples
        ``(network, station, location, channel, tmin, tmax)``. Useful for
        detailed queries.
    :type selection: list of tuples, optional
    :param parsed:
        If ``True`` parse received content into
        :py:class:`~pyrocko.io.stationxml.FDSNStationXML`
        object, otherwise return open file handle to raw data stream.
    :type parsed: bool, optional
    :param \\*\\*kwargs:
        Parameters passed to the server (see `FDSN web services specification
        <https://www.fdsn.org/webservices>`_).

    :returns:
        See description of ``parsed`` argument above.

    :raises:
        On failure, :py:exc:`~pyrocko.util.DownloadError` or one of its
        sub-types defined in the :py:mod:`~pyrocko.client.fdsn` module is
        raised.
    '''

    service = 'station'

    if check:
        check_params(service, site, url, majorversion, timeout, **kwargs)

    params = fix_params(kwargs)

    url = fillurl(service, site, url, majorversion, 'query')
    if selection:
        lst = []
        for k, v in params.items():
            lst.append('%s=%s' % (k, v))

        for (network, station, location, channel, tmin, tmax) in selection:
            if location == '':
                location = '--'

            lst.append(' '.join((network, station, location, channel,
                                 sdatetime(tmin), sdatetime(tmax))))

        post = '\n'.join(lst)
        params = dict(post=post.encode())

    if parsed:
        from pyrocko.io import stationxml
        format = kwargs.get('format', 'xml')
        if format == 'text':
            if kwargs.get('level', 'station') == 'channel':
                return stationxml.load_channel_table(
                    stream=_request(url, timeout=timeout, **params))
            else:
                raise InvalidRequest('if format="text" shall be parsed, '
                                     'level="channel" is required')

        elif format == 'xml':
            return stationxml.load_xml(
                stream=_request(url, timeout=timeout, **params))
        else:
            raise InvalidRequest('format must be "xml" or "text"')
    else:
        return _request(url, timeout=timeout, **params)


def get_auth_credentials(service, site, url, majorversion, token, timeout):

    url = fillurl(service, site, url, majorversion, 'auth')

    f = _request(url, timeout=timeout, post=token)
    s = f.read().decode()
    try:
        user, passwd = s.strip().split(':')
    except ValueError:
        raise CannotGetCredentialsFromAuthRequest('data="%s"' % s)

    return user, passwd


def dataselect(
        site=g_default_site,
        url=g_url,
        majorversion=1,
        timeout=g_timeout,
        check=True,
        user=None,
        passwd=None,
        token=None,
        selection=None,
        **kwargs):

    '''
    Query FDSN web service for time series data in miniSEED format.

    :param site:
        :ref:`Registered site name <registered-site-names>` or full base URL of
        the service (e.g. ``'https://geofon.gfz-potsdam.de'``).
    :type site: str, optional
    :param url:
        URL template (default should work in 99% of cases).
    :type url: str, optional
    :param majorversion:
        Major version of the service to query (always ``1`` at the time of
        writing).
    :type majorversion: int, optional
    :param timeout:
        Network timeout in [s]. Global default timeout can be configured in
        Pyrocko's configuration file under ``fdsn_timeout``.
    :type timeout: float, optional
    :param check:
        If ``True`` arguments are checked against self-description (WADL) of
        the queried web service if available or FDSN specification.
    :type check: bool, optional
    :param user: User name for user/password authentication.
    :type user: str, optional
    :param passwd: Password for user/password authentication.
    :type passwd: str, optional
    :param token: Token for `token authentication
        <https://geofon.gfz-potsdam.de/waveform/archive/auth/auth-overview.php>`_.
    :type token: str, optional
    :param selection:
        If given, selection to be queried as a list of tuples
        ``(network, station, location, channel, tmin, tmax)``.
    :type selection: list of tuples, optional
    :param \\*\\*kwargs:
        Parameters passed to the server (see `FDSN web services specification
        <https://www.fdsn.org/webservices>`_).

    :returns:
        Open file-like object providing raw miniSEED data.
    '''

    service = 'dataselect'

    if user or token:
        method = 'queryauth'
    else:
        method = 'query'

    if token is not None:
        user, passwd = get_auth_credentials(
            service, site, url, majorversion, token, timeout)

    if check:
        check_params(service, site, url, majorversion, timeout, **kwargs)

    params = fix_params(kwargs)

    url = fillurl(service, site, url, majorversion, method)
    if selection:
        lst = []

        for k, v in params.items():
            lst.append('%s=%s' % (k, v))

        for (network, station, location, channel, tmin, tmax) in selection:
            if location == '':
                location = '--'

            lst.append(' '.join((network, station, location, channel,
                                 sdatetime(tmin), sdatetime(tmax))))

        post = '\n'.join(lst)
        return _request(
            url, user=user, passwd=passwd, post=post.encode(), timeout=timeout)
    else:
        return _request(
            url, user=user, passwd=passwd, timeout=timeout, **params)


def event(
        site=g_default_site,
        url=g_url,
        majorversion=1,
        timeout=g_timeout,
        check=True,
        user=None,
        passwd=None,
        token=None,
        parsed=False,
        **kwargs):

    '''
    Query FDSN web service for events.

    :param site:
        :ref:`Registered site name <registered-site-names>` or full base URL of
        the service (e.g. ``'https://geofon.gfz-potsdam.de'``).
    :type site: str, optional
    :param url:
        URL template (default should work in 99% of cases).
    :type url: str, optional
    :param majorversion:
        Major version of the service to query (always ``1`` at the time of
        writing).
    :type majorversion: int, optional
    :param timeout:
        Network timeout in [s]. Global default timeout can be configured in
        Pyrocko's configuration file under ``fdsn_timeout``.
    :type timeout: float, optional
    :param check:
        If ``True`` arguments are checked against self-description (WADL) of
        the queried web service if available or FDSN specification.
    :type check: bool, optional
    :param user: User name for user/password authentication.
    :type user: str, optional
    :param passwd: Password for user/password authentication.
    :type passwd: str, optional
    :param token: Token for `token authentication
        <https://geofon.gfz-potsdam.de/waveform/archive/auth/auth-overview.php>`_.
    :type token: str, optional
    :param parsed:
        If ``True`` parse received content into
        :py:class:`~pyrocko.io.quakeml.QuakeML`
        object, otherwise return open file handle to raw data stream. Note:
        by default unparsed data is retrieved, differently from the default
        behaviour of :py:func:`station` (for backward compatibility).
    :type parsed: bool, optional
    :param \\*\\*kwargs:
        Parameters passed to the server (see `FDSN web services specification
        <https://www.fdsn.org/webservices>`_).

    :returns:
        See description of ``parsed`` argument above.


    '''

    service = 'event'

    if user or token:
        method = 'queryauth'
    else:
        method = 'query'

    if token is not None:
        user, passwd = get_auth_credentials(
            service, site, url, majorversion, token, timeout)

    if check:
        check_params(service, site, url, majorversion, timeout, **kwargs)

    params = fix_params(kwargs)

    url = fillurl(service, site, url, majorversion, method)

    fh = _request(url, user=user, passwd=passwd, timeout=timeout, **params)
    if parsed:
        from pyrocko.io import quakeml
        format = kwargs.get('format', 'xml')
        if format != 'xml':
            raise InvalidRequest(
                'If parsed=True is selected, format="xml" must be selected.')

        return quakeml.load_xml(stream=fh)

    else:
        return fh


def availability(
        method='query',
        site=g_default_site,
        url=g_url,
        majorversion=1,
        timeout=g_timeout,
        check=True,
        user=None,
        passwd=None,
        token=None,
        selection=None,
        **kwargs):

    '''
    Query FDSN web service for time series data availablity.

    :param method: Availablility method to call: ``'query'``, or ``'extent'``.
    :param site:
        :ref:`Registered site name <registered-site-names>` or full base URL of
        the service (e.g. ``'https://geofon.gfz-potsdam.de'``).
    :type site: str, optional
    :param url:
        URL template (default should work in 99% of cases).
    :type url: str, optional
    :param majorversion:
        Major version of the service to query (always ``1`` at the time of
        writing).
    :type majorversion: int, optional
    :param timeout:
        Network timeout in [s]. Global default timeout can be configured in
        Pyrocko's configuration file under ``fdsn_timeout``.
    :type timeout: float, optional
    :param check:
        If ``True`` arguments are checked against self-description (WADL) of
        the queried web service if available or FDSN specification.
    :type check: bool, optional
    :param user: User name for user/password authentication.
    :type user: str, optional
    :param passwd: Password for user/password authentication.
    :type passwd: str, optional
    :param token: Token for `token authentication
        <https://geofon.gfz-potsdam.de/waveform/archive/auth/auth-overview.php>`_.
    :type token: str, optional
    :param selection:
        If given, selection to be queried as a list of tuples
        ``(network, station, location, channel, tmin, tmax)``.
    :type selection: list of tuples, optional
    :param \\*\\*kwargs:
        Parameters passed to the server (see `FDSN web services specification
        <https://www.fdsn.org/webservices>`_).

    :returns:
        Open file-like object providing raw response.
    '''

    service = 'availability'

    assert method in ('query', 'extent')

    if user or token:
        method += 'auth'

    if token is not None:
        user, passwd = get_auth_credentials(
            service, site, url, majorversion, token, timeout)

    if check:
        check_params(service, site, url, majorversion, timeout, **kwargs)

    params = fix_params(kwargs)

    url = fillurl(service, site, url, majorversion, method)
    if selection:
        lst = []

        for k, v in params.items():
            lst.append('%s=%s' % (k, v))

        for (network, station, location, channel, tmin, tmax) in selection:
            if location == '':
                location = '--'

            lst.append(' '.join((network, station, location, channel,
                                 sdatetime(tmin), sdatetime(tmax))))

        post = '\n'.join(lst)
        return _request(
            url, user=user, passwd=passwd, post=post.encode(), timeout=timeout)
    else:
        return _request(
            url, user=user, passwd=passwd, timeout=timeout, **params)


def check_params(
        service,
        site=g_default_site,
        url=g_url,
        majorversion=1,
        timeout=g_timeout,
        method='query',
        **kwargs):

    '''
    Check query parameters against self-description of web service.

    Downloads WADL description of the given service and site and checks
    parameters if they are available. Queried WADLs are cached in memory.

    :param service: ``'station'``, ``'dataselect'``, ``'event'`` or
        ``'availability'``.
    :param site:
        :ref:`Registered site name <registered-site-names>` or full base URL of
        the service (e.g. ``'https://geofon.gfz-potsdam.de'``).
    :type site: str, optional
    :param url:
        URL template (default should work in 99% of cases).
    :type url: str, optional
    :param majorversion:
        Major version of the service to query (always ``1`` at the time of
        writing).
    :type majorversion: int, optional
    :param timeout:
        Network timeout in [s]. Global default timeout can be configured in
        Pyrocko's configuration file under ``fdsn_timeout``.
    :type timeout: float, optional
    :param \\*\\*kwargs:
        Parameters that would be passed to the server (see `FDSN web services
        specification <https://www.fdsn.org/webservices>`_).

    :raises: :py:exc:`ValueError` is raised if unsupported parameters are
        encountered.
    '''

    avail = supported_params_wadl(
        service, site, url, majorversion, timeout, method)

    unavail = sorted(set(kwargs.keys()) - avail)
    if unavail:
        raise ValueError(
            'Unsupported parameter%s for service "%s" at site "%s": %s' % (
                '' if len(unavail) == 1 else 's',
                service,
                site,
                ', '.join(unavail)))


def supported_params_wadl(
        service,
        site=g_default_site,
        url=g_url,
        majorversion=1,
        timeout=g_timeout,
        method='query'):

    '''
    Get query parameter names supported by a given FDSN site and service.

    If no WADL is provided by the queried service, default parameter sets from
    the FDSN standard are returned. Queried WADLs are cached in memory.

    :param service: ``'station'``, ``'dataselect'``, ``'event'`` or
        ``'availability'``.
    :param site:
        :ref:`Registered site name <registered-site-names>` or full base URL of
        the service (e.g. ``'https://geofon.gfz-potsdam.de'``).
    :type site: str, optional
    :param url:
        URL template (default should work in 99% of cases).
    :type url: str, optional
    :param majorversion:
        Major version of the service to query (always ``1`` at the time of
        writing).
    :type majorversion: int, optional
    :param timeout:
        Network timeout in [s]. Global default timeout can be configured in
        Pyrocko's configuration file under ``fdsn_timeout``.
    :type timeout: float, optional

    :returns: Supported parameter names.
    :rtype: set of str
    '''

    wadl = cached_wadl(service, site, url, majorversion, timeout)

    if wadl:
        url = fillurl(service, site, url, majorversion, method)
        return set(wadl.supported_param_names(url))
    else:
        return g_default_query_args[service]


def patch_geonet_wadl(wadl):
    for r in wadl.resources_list:
        r.base = r.base.replace('1/station', 'station/1')
        r.base = r.base.replace('1/dataselect', 'dataselect/1')
        r.base = r.base.replace('1/event', 'event/1')


def wadl(
        service,
        site=g_default_site,
        url=g_url,
        majorversion=1,
        timeout=g_timeout):

    '''
    Retrieve self-description of a specific FDSN service.

    :param service: ``'station'``, ``'dataselect'``, ``'event'`` or
        ``'availability'``.
    :param site:
        :ref:`Registered site name <registered-site-names>` or full base URL of
        the service (e.g. ``'https://geofon.gfz-potsdam.de'``).
    :type site: str, optional
    :param url:
        URL template (default should work in 99% of cases).
    :type url: str, optional
    :param majorversion:
        Major version of the service to query (always ``1`` at the time of
        writing).
    :type majorversion: int, optional
    :param timeout:
        Network timeout in [s]. Global default timeout can be configured in
        Pyrocko's configuration file under ``fdsn_timeout``.
    :type timeout: float, optional
    '''

    from pyrocko.client.wadl import load_xml

    url = fillurl(service, site, url, majorversion, 'application.wadl')

    wadl = load_xml(stream=_request(url, timeout=timeout))

    if site == 'geonet' or site.find('geonet.org.nz') != -1:
        patch_geonet_wadl(wadl)

    return wadl


g_wadls = {}


def cached_wadl(
        service,
        site=g_default_site,
        url=g_url,
        majorversion=1,
        timeout=g_timeout):

    '''
    Get self-description of a specific FDSN service.

    Same as :py:func:`wadl`, but results are cached in memory.
    '''

    k = (service, site, url, majorversion)
    if k not in g_wadls:
        try:
            g_wadls[k] = wadl(service, site, url, majorversion, timeout)

        except Timeout:
            raise

        except DownloadError:
            logger.info(
                'No service description (WADL) found for "%s" at site "%s".'
                % (service, site))

            g_wadls[k] = None

    return g_wadls[k]


__doc__ %= doc_table_dict(g_site_abbr, 'Site name', 'URL', '    ')


if __name__ == '__main__':
    import sys

    util.setup_logging('pyrocko.client.fdsn', 'info')

    if len(sys.argv) == 1:
        sites = get_sites()
    else:
        sites = sys.argv[1:]

    for site in sites:
        print('=== %s (%s) ===' % (site, g_site_abbr[site]))

        for service in ['station', 'dataselect', 'event']:
            try:
                app = wadl(service, site=site, timeout=2.0)
                print(indent(str(app)))

            except Timeout as e:
                logger.error(str(e))
                print('%s: timeout' % (service,))

            except util.DownloadError as e:
                logger.error(str(e))
                print('%s: no wadl' % (service,))
