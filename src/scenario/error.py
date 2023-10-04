# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Exceptions definitions.
'''


class ScenarioError(Exception):
    pass


class LocationGenerationError(ScenarioError):
    pass


class CannotCreatePath(ScenarioError):
    pass


__all__ = ['ScenarioError', 'LocationGenerationError', 'CannotCreatePath']
