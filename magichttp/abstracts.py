#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2017 Kaede Hoshikawa
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from typing import AsyncIterator, Iterable, Any

import abc

__all__ = ["AbstractStreamReader", "AbstractStreamWriter", "AbstractStream"]

class _Identifier:
    pass


_DEFAULT_MARK = _Identifier()


class AbstractStreamReader(abc.ABC, AsyncIterator[bytes]):  # pragma: no cover
    """
    The abstract base class of the stream reader(read only stream).
    """
    def buflen(self) -> int:
        """
        Return the length of the internal buffer.

        If the reader has no internal buffer, it should raise a
        `NotImplementedError`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def read(self, n: int=-1) -> bytes:
        """
        Read at most n bytes data.

        When at_eof() is True, this method will raise a `StreamEOFError`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def readexactly(self, n: int=-1) -> bytes:
        """
        Read exactly n bytes data.

        If the eof reached before found the separator it will raise
        an `asyncio.IncompleteReadError`.

        When at_eof() is True, this method will raise a `StreamEOFError`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def readuntil(
        self, separator: bytes=b"\n",
            *, keep_separator: bool=True) -> bytes:
        """
        Read until the separator has been found.

        When limit(if any) has been reached, and the separator is not found,
        this method will raise an `asyncio.LimitOverrunError`.
        Similarly, if the eof reached before found the separator it will raise
        an `asyncio.IncompleteReadError`.

        When at_eof() is True, this method will raise a `StreamEOFError`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def at_eof(self) -> bool:
        """
        Return True if eof has been appended and the internal buffer is empty.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def has_eof(self) -> bool:
        """
        Return True if eof has been appended.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def wait_eof(self) -> None:
        """
        Wait for the eof has been appended.

        When limit(if any) has been reached, and the eof is not reached,
        this method will raise an `asyncio.LimitOverrunError`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_extra_info(
        self, name: str,
            default: Any=_DEFAULT_MARK) -> Any:  # pragma: no cover
        """
        Return optional stream information.

        If The specific name is not presented and the default is not provided,
        the method should raise a `KeyError`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def __aiter__(self) -> "AbstractStreamReader":
        """
        The `AbstractStreamReader` is an `AsyncIterator`,
        so this function will simply return the reader itself.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def __anext__(self) -> bytes:
        """
        Return the next line.

        This should be equivalent to`AbstractStreamReader.readuntil("\n")`
        """
        raise NotImplementedError


class AbstractStreamWriter(abc.ABC):  # pragma: no cover
    """
    The abstract base class of the stream writer(write only stream).
    """
    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        """
        Write the data.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def writelines(self, data: Iterable[bytes]) -> None:
        """
        Write a list (or any iterable) of data bytes.

        This is equivalent to call `AbstractStreamWriter.write` on each Element
        that the `Iterable` yields out, but in a more efficient way.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def drain(self) -> None:
        """
        Give the underlying implementation a chance to drain the pending data
        out of the internal buffer.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def can_write_eof(self) -> bool:
        """
        Return `True` if an eof can be written to the writer.
        """
        raise NotImplementedError

    def write_eof(self) -> None:
        """
        Write the eof.

        If the writer does not support eof(half-closed), it should raise a
        `NotImplementedError`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def eof_written(self) -> bool:
        """
        Return `True` if the eof has been written or
        the writer has been closed.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def closed(self) -> bool:
        """
        Return `True` if the writer has been closed.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """
        Close the writer.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def wait_closed(self) -> None:
        """
        Wait the writer to close.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def abort(self) -> None:
        """
        Abort the writer without draining out all the pending buffer.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_extra_info(
        self, name: str,
            default: Any=_DEFAULT_MARK) -> Any:  # pragma: no cover
        """
        Return optional stream information.

        If The specific name is not presented and the default is not provided,
        the method should raise a `KeyError`.
        """
        raise NotImplementedError


class AbstractStream(
        AbstractStreamReader, AbstractStreamWriter):  # pragma: no cover
    """
    The abstract base class of the bidirectional stream(read and write stream).
    """
    pass
