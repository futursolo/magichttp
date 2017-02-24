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

from typing import Union, Tuple, Callable, Any, Optional, Iterable

from . import abstracts

import asyncio
import abc
import weakref
import gc

__all__ = ["TcpServer", "TcpStreamHandler", "TcpStream"]


class TcpServer(asyncio.AbstractServer):
    def __init__(
        self, handler_factory: Callable[..., "TcpStreamHandler"], *,
            loop: asyncio.AbstractEventLoop) -> None:
        self._factory = handler_factory

        self._loop = loop

        self._loop_srv: Optional[asyncio.AbstractServer] = None

        self._handlers = weakref.WeakSet()  # type: ignore

        self._teardown_tasks = weakref.WeakSet()  # type: ignore

        self._closed_fur: "asyncio.Future[None]" = self._loop.create_future()

    @classmethod
    async def create(
        Cls, handler_factory: Callable[..., "TcpStreamHandler"],
        *args: Any, loop: Optional[asyncio.AbstractEventLoop]=None,
            **kwargs: Any) -> "TcpServer":
        loop = loop or asyncio.get_event_loop()
        srv = Cls(handler_factory, loop=loop)

        loop_srv = await loop.create_server(
            srv._peer_connected, *args, **kwargs)

        srv._attach_loop_srv(loop_srv)

        return srv

    def _peer_connected(self) -> asyncio.Protocol:
        assert self._loop_srv is not None

        handler = self._factory()

        self._handlers.add(handler)

        return handler

    def _attach_loop_srv(self, loop_srv: asyncio.AbstractServer) -> None:
        assert self._loop_srv is None
        self._loop_srv = loop_srv

    def close(self) -> None:
        assert self._loop_srv is not None
        if self._closed_fur.done():
            return

        self._loop_srv.close()

        gc.collect()

        for handler in self._handlers:
            tsk: "asyncio.Task[None]" = \
                self._loop.create_task(handler.teardown())

            self._teardown_tasks.add(tsk)

        self._closed_fur.set_result(None)

    async def wait_closed(self) -> None:  # type: ignore
        assert self._loop_srv is not None

        await self._closed_fur

        await asyncio.wait(self._teardown_tasks)

        await self._loop_srv.wait_closed()

    def __del__(self) -> None:
        if getattr(self, "_loop_srv", None) is not None:
            self.close()


class TcpStreamHandler(asyncio.Protocol, abstracts.AbstractStreamHandler):
    def __init__(self) -> None:
        raise NotImplementedError

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        raise NotImplementedError

    def data_received(self, data: bytes) -> None:
        raise NotImplementedError

    def eof_received(self) -> bool:
        raise NotImplementedError

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        raise NotImplementedError


class TcpStream(abstracts.AbstractStream):
    """
    The implementation of :class:`abstracts.AbstractStream` for tcp socket.
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
    def __aiter__(self) -> abstracts.AbstractStreamReader:
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
