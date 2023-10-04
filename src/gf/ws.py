# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Web service to distribute precomputed GFs (:app:`fomosto server`).
'''

import time
import requests

import logging

from pyrocko import util
from pyrocko.util import DownloadError


logger = logging.getLogger('pyrocko.gf.ws')

g_url = '%(site)s/gfws/%(service)s/%(majorversion)i/%(method)s'
g_url_static = '%(site)s/gfws/%(service)s'

g_site_abbr = {
    'localhost': 'http://localhost:8080',
    'kinherd': 'http://kinherd.org:8080'}

g_default_site = 'localhost'


def sdatetime(t):
    return util.time_to_str(t, format='%Y-%m-%dT%H:%M:%S')


class EmptyResult(Exception):
    def __init__(self, url):
        Exception.__init__(self)
        self._url = url

    def __str__(self):
        return 'No results for request %s' % self._url


class RequestEntityTooLarge(Exception):
    def __init__(self, url):
        Exception.__init__(self)
        self._url = url

    def __str__(self):
        return 'Request entity too large: %s' % self._url


class InvalidRequest(Exception):
    pass


def _request(url, post=False, **kwargs):
    logger.debug('Accessing URL %s' % url)

    if post:
        logger.debug('POST data: \n%s' % post)
        req = requests.Request(
            'POST',
            url=url,
            params=kwargs,
            data=post)
    else:
        req = requests.Request(
            'GET',
            url=url,
            params=kwargs)

    ses = requests.Session()

    prep = ses.prepare_request(req)
    prep.headers['Accept'] = '*/*'

    resp = ses.send(prep, stream=True)
    resp.raise_for_status()

    if resp.status_code == 204:
        raise EmptyResult(url)
    return resp.raw


def fillurl(url, site, service, majorversion, method='query'):
    return url % dict(
        site=g_site_abbr.get(site, site),
        service=service,
        majorversion=majorversion,
        method=method)


def static(url=g_url_static, site=g_default_site, majorversion=1, **kwargs):

    url = fillurl(url, site, 'static', majorversion)
    return _request(url, **kwargs)


def ujoin(*args):
    return '/'.join(args)


def rget(url, path, force=False, method='download', stats=None,
         status_callback=None, entries_wanted=None):

    return util._download(
        url, path,
        force=force,
        method=method,
        status_callback=status_callback,
        entries_wanted=entries_wanted,
        recursive=True)


def download_gf_store(url=g_url_static, site=g_default_site, majorversion=1,
                      store_id=None, force=False, quiet=False):

    url = fillurl(url, site, 'static', majorversion)

    stores_url = ujoin(url, 'stores')

    tlast = [time.time()]

    if not quiet:
        def status_callback(d):
            i = d['nread_bytes_all_files']
            n = d['ntotal_bytes_all_files']
            tnow = time.time()
            if n != 0 and ((tnow - tlast[0]) > 5 or i == n):
                print('%s / %s [%.1f%%]' % (
                    util.human_bytesize(i), util.human_bytesize(n), i*100.0/n))

                tlast[0] = tnow
    else:
        def status_callback(d):
            pass

    wanted = ['config', 'extra/', 'index', 'phases/', 'traces/']

    try:
        if store_id is None:
            print(static(
                url=stores_url+'/', format='text').read().decode('utf-8'))

        else:
            store_url = ujoin(stores_url, store_id)
            stotal = rget(
                store_url, store_id, force=force, method='calcsize',
                entries_wanted=wanted)

            rget(
                store_url, store_id, force=force, stats=[0, stotal],
                status_callback=status_callback, entries_wanted=wanted)

    except Exception as e:
        raise DownloadError('download failed. Original error was: %s, %s' % (
            type(e).__name__, e))

        import shutil
        shutil.rmtree(store_id)


def seismosizer(url=g_url, site=g_default_site, majorversion=1,
                request=None):

    url = fillurl(url, site, 'seismosizer', majorversion)

    from pyrocko.gf import meta

    return meta.load(stream=_request(url, post={'request': request.dump()}))
