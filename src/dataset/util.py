# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Registry for dataset download progress notifications.
'''

DOWNLOAD_CALLBACK = None


def set_download_callback(callback):
    global DOWNLOAD_CALLBACK

    if not callable(callback):
        raise AttributeError('Callback has to be a function')
    DOWNLOAD_CALLBACK = callback


def get_download_callback(context_str):
    if not DOWNLOAD_CALLBACK:
        return None

    def callback(args):
        return DOWNLOAD_CALLBACK(context_str, args)

    return callback
