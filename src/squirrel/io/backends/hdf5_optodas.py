# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel IO adaptor to :py:mod:`pyrocko.io.tdms_idas`.
'''
from __future__ import annotations

from typing import Any, Generator

from squirrel.model import Nut


def provided_formats() -> list[str]:
    return ["hdf5_optodas"]


def detect512(first512: bytes) -> bool:
    ...


def iload(format: str, file_path: str, segment: int, content: tuple[str,...]) -> Generator[Nut, Any, None]:
    ...
