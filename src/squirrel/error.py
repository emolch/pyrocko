# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel exception definitions.
'''


class SquirrelError(Exception):
    '''
    Base class for errors raised by the Pyrocko Squirrel framework.
    '''
    pass


class NotAvailable(SquirrelError):
    '''
    Raised when a required data entity cannot be found.
    '''
    pass


class Duplicate(SquirrelError):
    '''
    Raised when a query leads to multiple/ambiguous results.
    '''
    pass


class Inconsistencies(SquirrelError):
    '''
    Raised when there is an inconsistency between two or more related entities.
    '''
    pass


class ConversionError(SquirrelError):
    '''
    Raised when a conversion failed.
    '''
    pass


class ToolError(Exception):
    '''
    Raised by Squirrel CLI tools to request a graceful exit on error.
    '''
    pass


__all__ = [
    'SquirrelError',
    'NotAvailable',
    'Duplicate',
    'Inconsistencies',
    'ConversionError',
    'ToolError']
