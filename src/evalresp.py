# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Wrapper for the `evalresp
<https://ds.iris.edu/ds/nodes/dmc/software/downloads/evalresp/>`_ C library.
'''

import time


class EvalrespNotAvailable(Exception):
    pass


def import_ext():
    try:
        from pyrocko import evalresp_ext as ext
        return ext
    except ImportError:
        raise EvalrespNotAvailable(
            'The pyrocko.evalresp module is not supported on your platform.')


def have_evalresp():
    try:
        import_ext()
        return True
    except EvalrespNotAvailable:
        return False


def evalresp(
        sta_list='*',
        cha_list='*',
        net_code='*',
        locid='*',
        instant=None,
        units='VEL',         # VEL, DIS, ACC, DEF
        file='',
        freqs=None,
        rtype='AP',          # CS, AP
        verbose='',
        start_stage=-1,
        stop_stage=0,
        stdio_flag=0,
        listinterp_out_flag=0,
        listinterp_in_flag=0,
        listinterp_tension=1000.0):

    ext = import_ext()

    datime = time.strftime('%Y,%j,%H:%M:%S', time.gmtime(instant))

    return ext.evalresp(sta_list, cha_list, net_code, locid, datime,
                        units, file, freqs, rtype, verbose,
                        start_stage, stop_stage, stdio_flag,
                        listinterp_out_flag, listinterp_in_flag,
                        listinterp_tension)
