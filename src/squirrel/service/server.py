# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Web server component for Squirrel web services.
'''

import asyncio
import json
import logging
import os
import signal
import time
import uuid
import base64
from datetime import datetime

import numpy as num
from tornado import web, autoreload

from pyrocko import info
from pyrocko import util
from pyrocko import squirrel as squirrel_module
from pyrocko.squirrel import model
from pyrocko import guts
from pyrocko.squirrel.error import ToolError, SquirrelError
from pyrocko.squirrel import operators as ops
from pyrocko.squirrel.base import Squirrel

logger = logging.getLogger('psq.service.server')


def str_choice(s, choices):
    s = str(s)
    if s not in choices:
        raise ValueError(
            'Invalid argument: %s. Choices: %s' % (
                s, ', '.join(choices)))

    return s


def to_codes_list(x):
    return [model.to_codes_guess(s.strip()) for s in x.split(',')]


def get_parameters_dict(body):
    if not body:
        return {}

    parameters = json.loads(body)
    if not isinstance(parameters, dict):
        raise ValueError('Mapping required.')

    return parameters


class GutsJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, guts.Object):
            d = dict(
                (name, val) for (name, val) in o.T.inamevals_to_save(o))
            d['_T'] = o.T.tagname
            return d

        elif isinstance(o, datetime):
            return o.isoformat() + 'Z'

        elif isinstance(o, num.int64):
            return int(o)

        else:
            return json.JSONEncoder.default(self, o)


class SquirrelRequestHandler(web.RequestHandler):

    def initialize(self, squirrel=None, server_info=None):
        self._squirrel = squirrel
        self._server_info = server_info

    def prepare(self):
        self._server_info['n_requests'] += 1

    def get_cleaned(self, names, parameters):
        if isinstance(names, str):
            names = names.split()
        print("parameters: ", parameters)

        clean = {
            'kind': lambda x: str_choice(x, model.g_content_kinds),
            'tmin': util.str_to_time_fillup,
            'tmax': util.str_to_time_fillup,
            'codes': to_codes_list,
            'fmin': float,
            'fmax': float
        }

        def clean_or_none(f, x):
            return f(x) if x is not None else None

        try:
            return [
                clean_or_none(clean[name], parameters.get(name, None))
                for name in names]

        except Exception as e:
            raise web.HTTPError(400, 'Bad request: %s' % str(e))

    def post(self, method_name, extra=()):
        method = getattr(self, 'p_' + method_name, None)
        if method is None:
            raise web.HTTPError(
                400, reason='Invalid method: %s' % method_name)
        else:
            try:
                parameters = get_parameters_dict(self.request.body)

            except Exception as e:
                raise web.HTTPError(
                    400, reason='Bad request: %s' % str(e))

            try:
                raw = method(parameters, *extra)
            except SquirrelError as e:
                raise web.HTTPError(
                    400, reason='Squirrel error: %s' + str(e))

            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps(raw, cls=GutsJSONEncoder))


class SquirrelHeartbeatHandler(SquirrelRequestHandler):

    async def get(self):
        logger.info('Client connected.')
        self.set_header('Content-Type', 'application/octet-stream')
        self.set_header('X-Accel-Buffering', 'no')
        await self.flush()
        try:
            time_start = time.time()
            while True:
                if g_shutdown:
                    break

                self.write(
                    json.dumps(dict(
                        time_start=time_start,
                        time_now=time.time())))

                try:
                    await self.flush()
                    await asyncio.sleep(1)
                except (asyncio.exceptions.CancelledError, Exception):
                    break

        finally:
            logger.info('Client disconnected.')
            self.finish()


class SquirrelInfoHandler(SquirrelRequestHandler):
    def p_server(self, parameters):
        return self._server_info


class SquirrelRawHandler(SquirrelRequestHandler):

    def p_get_codes(self, parameters):
        kind, = self.get_cleaned('kind', parameters)
        return [c.safe_str for c in self._squirrel.get_codes(kind=kind)]

    def p_get_time_span(self, parameters, gate):
        kind, = self.get_cleaned('kind', parameters)
        return TimeSpan(
            *self._squirrel.get_time_span(
                kinds=[kind],
                dummy_limits=False))

    def p_get_events(self, parameters):
        tmin, tmax = self.get_cleaned('tmin tmax', parameters)
        return self._squirrel.get_events()

    def p_get_channels(self, parameters):
        tmin, tmax, codes = self.get_cleaned('tmin tmax codes', parameters)
        return self._squirrel.get_channels(tmin=tmin, tmax=tmax, codes=codes)

    def p_get_sensors(self, parameters):
        tmin, tmax, codes = self.get_cleaned('tmin tmax codes', parameters)
        return self._squirrel.get_sensors(tmin=tmin, tmax=tmax, codes=codes)

    def p_get_responses(self, parameters):
        tmin, tmax, codes = self.get_cleaned('tmin tmax codes', parameters)
        return self._squirrel.get_responses(tmin=tmin, tmax=tmax, codes=codes)

    def p_get_coverage(self, parameters):
        kind, tmin, tmax = self.get_cleaned('kind tmin tmax', parameters)
        return self._squirrel.get_coverage(kind, tmin=tmin, tmax=tmax)


class ScaleChoice(guts.StringChoice):
    choices = ['lin', 'log']


class SpectrogramImage(guts.Object):
    codes = model.CodesNSLCE.T()
    shape = guts.Tuple.T(2, guts.Int.T())
    tmin = guts.Timestamp.T()
    tmax = guts.Timestamp.T()
    fmin = guts.Float.T()
    fmax = guts.Float.T()
    fscale = ScaleChoice.T()
    image_data_base64 = guts.String.T()


class TimeSpan(guts.Object):
    tmin = model.Timestamp.T(optional=True)
    tmax = model.Timestamp.T(optional=True)

    def __init__(self, *args, **kwargs):
        if args:
            tmin, tmax = args
            kwargs['tmin'] = tmin
            kwargs['tmax'] = tmax

        guts.Object.__init__(self, **kwargs)


class Gate(guts.Object):

    tmin = guts.Timestamp.T(optional=True)
    tmax = guts.Timestamp.T(optional=True)
    operators = guts.List.T(ops.Operator.T())

    def post_init(self):
        self._outlet = None

    @classmethod
    def from_query_arguments(cls, codes=None, tmin=None, tmax=None, time=None):
        operators = []

        # operators.append(
        #     ops.MultiSpectrogramOperator(
        #         filtering=ops.CodesPatternFiltering(codes=codes),
        #         windowing=ops.Pow2Windowing(
        #             nblock=2**10,
        #             nlevels=3,
        #             weighting_exponent=4)))

        return cls(
            tmin=tmin,
            tmax=tmax,
            operators=operators)

    def set_squirrel(self, squirrel):
        source = squirrel
        for operator in self.operators:
            operator.set_input(source)
            source = operator

        self._outlet = source

    def get_time_span(self, *args, **kwargs):
        return self._outlet.get_time_span(*args, **kwargs)

    def get_codes(self, *args, **kwargs):
        return self._outlet.get_codes(*args, **kwargs)

    def get_channels(self, *args, **kwargs):
        return self._outlet.get_channels(*args, **kwargs)

    def get_sensors(self, *args, **kwargs):
        return self._outlet.get_sensors(*args, **kwargs)

    def get_responses(self, *args, **kwargs):
        return self._outlet.get_responses(*args, **kwargs)

    def get_coverage(self, *args, **kwargs):
        return self._outlet.get_coverage(*args, **kwargs)

    def get_spectrogram_images(self, *args, fmin=0.001, fmax=1000.0, **kwargs):
        if isinstance(self._outlet, Squirrel):
            return []

        images = []
        for group in self._outlet.get_spectrogram_groups(
                *args,
                **kwargs,
                nsamples_limit=1000000):

            fslice = slice(2, None)
            spectrogram = group \
                .get_multi_spectrogram() \
                .crop(fslice=fslice)

            ny = 200
            print(fmin, fmax)
            spectrogram_ = spectrogram.resample_band(fmin, fmax, ny)
            print(spectrogram_.stats)
            vmin, vmax = spectrogram_.stats.min, spectrogram_.stats.max

            image_data = num.zeros(
                spectrogram_.values.shape[::-1] + (4,), dtype=num.uint8)

            ok = num.isfinite(spectrogram_.values)
            values = num.zeros(spectrogram_.values.shape)
            values[ok] = spectrogram_.values[ok]
            values[ok] -= vmax
            values[ok] *= 255.0 / (vmin - vmax)

            image_data[::-1, :, :3] \
                = values.astype(num.uint8).T[:, :, num.newaxis]
            ok_alpha = num.array([[[False, False, False, True]]], dtype=bool)
            ok3 = num.logical_and(ok.T[:, :, num.newaxis], ok_alpha)
            image_data[ok3[::-1, :, :]] = 255

            from PIL import Image
            im = Image.fromarray(image_data, mode='RGBA')
            from io import BytesIO
            buffer = BytesIO()
            im.save(buffer, format='png')

            images.append(SpectrogramImage(
                codes=group.codes,
                tmin=spectrogram_.times[0],
                tmax=spectrogram_.times[-1],
                fmin=spectrogram_.frequencies[0],
                fmax=spectrogram_.frequencies[-1],
                fscale='log',
                shape=spectrogram_.values.shape,
                image_data_base64='data:image/png;base64,' + base64.b64encode(
                    buffer.getvalue()).decode('ascii')))

        return images


g_gates = {}


class SquirrelGatesHandler(SquirrelRequestHandler):
    icurrent = 0

    def next_name(self):
        while True:
            candidate = '%i' % self.icurrent
            if '%i' % self.icurrent not in g_gates:
                return candidate
            self.icurrent += 1

    def get(self, name=None):
        if not name:
            self.set_header('Content-Type', 'application/json')
            self.write(json.dumps(sorted(g_gates.keys())))

    def post(self, name=None):
        if not name:
            name = self.next_name()

        parameters = get_parameters_dict(self.request.body)
        parameters
        g_gates[name] = Gate()

        self.set_header('Content-Type', 'application/json')
        self.write(json.dumps(name))


class SquirrelGateHandler(SquirrelRequestHandler):

    def post(self, gate_name, method_name):
        try:
            gate = g_gates[gate_name]
        except KeyError:
            raise web.HTTPError(
                400, reason='Squirrel error: no such gate: %s' % gate_name)

        SquirrelRequestHandler.post(self, method_name, extra=(gate,))

    def p_get_codes(self, parameters, gate):
        kind, = self.get_cleaned('kind', parameters)
        return [c.safe_str for c in gate.get_codes(kind=kind)]

    def p_get_time_span(self, parameters, gate):
        kind, = self.get_cleaned('kind', parameters)
        return TimeSpan(*gate.get_time_span(kinds=[kind], dummy_limits=False))

    def p_get_events(self, parameters, gate):
        tmin, tmax = self.get_cleaned('tmin tmax codes', parameters)
        return gate.get_events(tmin=tmin, tmax=tmax)

    def p_get_channels(self, parameters, gate):
        tmin, tmax, codes = self.get_cleaned('tmin tmax codes', parameters)
        return gate.get_channels(tmin=tmin, tmax=tmax, codes=codes)

    def p_get_sensors(self, parameters, gate):
        tmin, tmax, codes = self.get_cleaned('tmin tmax codes', parameters)
        return gate.get_sensors(tmin=tmin, tmax=tmax, codes=codes)

    def p_get_responses(self, parameters, gate):
        tmin, tmax, codes = self.get_cleaned('tmin tmax codes', parameters)
        return gate.get_responses(tmin=tmin, tmax=tmax, codes=codes)

    def p_get_coverage(self, parameters, gate):
        kind, tmin, tmax = self.get_cleaned('kind tmin tmax', parameters)
        return gate.get_coverage(kind, tmin=tmin, tmax=tmax)

    def p_get_spectrograms(self, parameters, gate):
        tmin, tmax, fmin, fmax = self.get_cleaned(
            'tmin tmax fmin fmax',
            parameters)

        return gate.get_spectrogram_images(
            tmin=tmin,
            tmax=tmax,
            fmin=fmin,
            fmax=fmax)


def get_ip(host):
    if host == 'localhost':
        return '::1'

    elif host == 'public':
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('4.4.4.4', 80))
            try:
                return s.getsockname()[0]
            finally:
                s.close()

        except Exception:
            raise ToolError(
                'Could not determine default external IP address to bind to.')

    elif host == 'all':
        return ''
    else:
        return host


def describe_ip(ip):
    ip_describe = {
        '': 'all available interfaces',
        '::': 'all available IPv6 interfaces',
        '0.0.0.0': 'all available IPv4 interfaces'}

    return ip_describe.get(ip, 'ip "%s"' % ip)


def url_ip(ip):
    if '' == ip:
        return '[::1]'
    elif '0.0.0.0' == ip:
        return '127.0.0.1'
    elif ':' in ip:
        return '[%s]' % ip
    else:
        return ip


def log_request(handler):
    if handler.get_status() < 400:
        log_method = logger.debug
    elif handler.get_status() < 500:
        log_method = logger.warning
    else:
        log_method = logger.error
    request_time = 1000.0 * handler.request.request_time()
    log_method(
        "%d %s %.2fms",
        handler.get_status(),
        handler._request_summary(),
        request_time,
    )


async def serve(
        squirrel,
        host='localhost',
        port=8000,
        open=False,
        debug=False,
        page_path=None):

    ip = get_ip(host)

    if page_path is None:
        page_path = os.path.join(
            os.path.split(squirrel_module.__file__)[0],
            'service',
            'page')

    server_info = dict(
        run_id=str(uuid.uuid4()),
        n_requests=0,
        debug=debug,
        pyrocko_version=info.version,
    )

    if debug:
        server_info.update(
            ip=ip,
            port=port,
            page_path=page_path,
            pyrocko_long_version=info.long_version,
            pyrocko_src_path=info.src_path)

    squirrel_handler_dict = dict(
        squirrel=squirrel,
        server_info=server_info,
    )

    app = web.Application(
        [
            (
                r'/((?:css|js|images)/.*'
                r'|index.html|site.webmanifest|favicon.ico|)',
                web.StaticFileHandler,
                dict(
                    path=page_path,
                    default_filename='index.html'
                )
            ),
            (
                r'/squirrel/heartbeat',
                SquirrelHeartbeatHandler,
                squirrel_handler_dict,
            ),
            (
                r'/squirrel/info/([a-z0-9_]+)',
                SquirrelInfoHandler,
                squirrel_handler_dict,
            ),
            (
                r'/squirrel/raw/([a-z0-9_]+)',
                SquirrelRawHandler,
                squirrel_handler_dict,
            ),
            (
                r'/squirrel/gate(?:/([a-z0-9_]+|/?))',
                SquirrelGatesHandler,
                squirrel_handler_dict,
            ),
            (
                r'/squirrel/gate/([a-z0-9_]+)/([a-z0-9_]+)',
                SquirrelGateHandler,
                squirrel_handler_dict,
            ),
        ],
        log_function=log_request,
        debug=debug,
    )

    logger.info(
        'Binding service to %s, port %i.',
        describe_ip(ip), port)

    try:
        http_server = app.listen(port, ip)
    except OSError as e:
        if e.errno == 98:
            await fail(ToolError(
                'Address already in use, try specifying a different port '
                'number with --port INT.'))
            return

    url = 'http://%s:%d' % (url_ip(ip), port)
    if open:
        import webbrowser
        logger.info('Pointing browser to: %s', url)
        webbrowser.open(url)
    else:
        logger.info('Point browser to: %s', url)

    while True:
        try:
            await asyncio.sleep(3)
        finally:
            if g_shutdown:
                logger.info('Shutting down service.')
                http_server.stop()
                await http_server.close_all_connections()
                break


g_shutdown = False
g_exception = None


async def fail(e):
    global g_exception
    g_exception = e
    await shutdown()


async def shutdown(sig=None, loop=None):
    global g_shutdown

    if sig is not None:
        logger.debug(
            'Received exit signal %s.', sig.name)

    g_shutdown = True

    tasks = [
        t for t in asyncio.all_tasks()
        if t is not asyncio.current_task()]

    [task.cancel() for task in tasks]

    logger.debug(
        'Cancelling %s outstanding task%s.',
        len(tasks), '' if len(tasks) == 1 else 's')

    await asyncio.gather(*tasks)

    logger.debug(
        'Done waiting for tasks to finish.')

    loop = asyncio.get_event_loop()
    loop.stop()


def run(
        squirrel,
        gates={},
        host='localhost',
        port=2323,
        open=False,
        debug=False,
        page_path=None):

    for gate in gates.values():
        gate.set_squirrel(squirrel)

    g_gates.update(gates)

    if debug:
        logger.setLevel(logging.DEBUG)
        logger.debug('Debug mode activated.')
        autoreload.add_reload_hook(lambda: time.sleep(2))
        if page_path is None:
            dev_static_path = os.path.join(
                info.src_path, 'src', 'squirrel', 'service', 'page')
            if os.path.exists(dev_static_path):
                page_path = dev_static_path

        logger.debug('Serving static files from: %s', page_path)

    loop = asyncio.get_event_loop()
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(
            s, lambda s=s: asyncio.create_task(shutdown(s)))

    try:
        loop.create_task(
            serve(
                squirrel,
                host=host,
                port=port,
                open=open,
                debug=debug,
                page_path=page_path))

        loop.run_forever()

    finally:
        loop.close()
        if g_exception is not None:
            raise g_exception

        logger.debug('Shutdown complete.')
