#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2021 Kaede Hoshikawa
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

from collections import deque
from typing import (  # Awaitable,
    Any,
    Coroutine,
    Deque,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
)
import asyncio
import contextlib
import socket
import ssl

from ._abc import AbstractIo, AbstractSocket, AbstractTask

_T = TypeVar("_T")

_SOCKET_INFO = Union[Tuple[str, int, int, int], Tuple[str, int]]


class SocketProtocol(asyncio.Protocol):

    __slots__ = (
        "_transport",
        "_chunks",
        "_connected",
        "_data_ready",
        "_read_lock",
        "_data_flushed",
        "_write_lock",
        "_eof",
        "_closed",
        "_exc",
    )
    _transport: asyncio.Transport

    def __init__(self) -> None:
        self._chunks: Deque[bytes] = deque()
        self._data_ready = asyncio.Event()

        self._data_flushed = asyncio.Event()
        self._data_flushed.set()

        self._connected = asyncio.Event()
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

        self._eof = False
        self._closed = asyncio.Event()
        self._exc: Optional[Exception] = None

    def connection_made(  # type: ignore
        self, transport: asyncio.Transport
    ) -> None:
        self._transport = transport
        self._connected.set()

    def data_received(self, data: bytes) -> None:
        self._chunks.append(data)
        self._data_ready.set()

        if len(self._chunks) >= 4 and self._transport.is_reading():
            self._transport.pause_reading()

    def pause_writing(self) -> None:
        self._data_flushed.clear()

    def resume_writing(self) -> None:
        self._data_flushed.set()

    def eof_received(self) -> Optional[bool]:
        self._eof = True
        self._data_ready.set()
        return (
            True
            if self._transport.get_extra_info("sslcontext") is None
            else None
        )

    def connection_lost(self, exc: Optional[Exception]) -> None:
        self._closed.set()
        self._connected.set()
        self._data_ready.set()
        self._data_flushed.set()
        self._exc = exc

    async def recv(self) -> bytes:
        async with self._read_lock:
            while not self._chunks:
                if self._eof or self._closed.is_set():
                    if self._exc:
                        raise self._exc

                    raise EOFError

                if not self._transport.is_reading():
                    self._transport.resume_reading()

                self._data_ready.clear()
                await self._data_ready.wait()

            return self._chunks.popleft()

    async def send_all(self, buf: Union[bytes, bytearray, memoryview]) -> None:
        async with self._write_lock:
            if self._exc:
                raise self._exc

            self._transport.write(buf)

            await asyncio.sleep(0)
            await self._data_flushed.wait()

    async def close(self) -> None:
        self._transport.close()
        await self._closed.wait()


class Socket(AbstractSocket):
    """
    A 'socket'-ish object for asyncio.
    """

    __slots__ = (
        "_proto",
        "_srv",
        "_pending_sockets",
        "_socket_ready",
        "_accept_lock",
        "_closed",
    )

    def __init__(self, proto: Optional[SocketProtocol] = None) -> None:
        self._proto = proto

        self._srv: Optional[asyncio.AbstractServer] = None
        self._pending_sockets: Deque["Socket"] = deque()
        self._socket_backlog = 16
        self._socket_ready = asyncio.Event()

        self._accept_lock = asyncio.Lock()
        self._closed = False

    def _set_server(self, srv: asyncio.AbstractServer) -> None:
        self._srv = srv

    def _accept_socket(self) -> SocketProtocol:
        proto = SocketProtocol()
        self._pending_sockets.append(Socket(proto))

        self._socket_ready.set()
        return proto

    async def recv(self, n: int) -> bytes:
        if self._proto:
            return await self._proto.recv()

        raise OSError("You cannot receive from this socket.")

    async def send_all(
        self, data: Union[bytes, bytearray, memoryview]
    ) -> None:
        if self._proto:
            return await self._proto.send_all(data)

        raise OSError("You cannot send from this socket.")

    async def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        if self._proto:
            return await self._proto.close()

        elif self._srv:
            self._srv.close()
            await self._srv.wait_closed()

            self._socket_ready.set()
            return

        raise OSError("Server is not ready, so cannot close.")

    @classmethod
    async def connect(
        cls,
        host: str,
        port: int,
        *,
        tls: Optional[ssl.SSLContext] = None,
        family: int = 0,
        proto: int = 0,
        flags: int = 0,
        server_hostname: Optional[str] = None,
    ) -> AbstractSocket:
        loop = asyncio.get_running_loop()
        proto_ = SocketProtocol()
        await loop.create_connection(
            lambda: proto_,
            host=host,
            port=port,
            ssl=tls,
            family=family,
            proto=proto,
            flags=flags,
            server_hostname=server_hostname,
        )
        await proto_._connected.wait()

        return cls(proto_)

    @classmethod
    async def bind_listen(
        cls,
        host: str,
        port: int,
        *,
        family: int = socket.AF_UNSPEC,
        flags: int = socket.AI_PASSIVE,
        backlog: int = 100,
        socket_backlog: int = 16,
        tls: Optional[ssl.SSLContext] = None,
        reuse_address: Optional[bool] = None,
        reuse_port: Optional[bool] = None,
    ) -> AbstractSocket:
        """
        :arg socket_backlog: The maximum number of sockets that can
        be inside the queue before they are accepted. Only applicable in
        certain implementation.
        """
        self_ = cls()
        self_._socket_backlog = socket_backlog

        loop = asyncio.get_running_loop()
        srv = await loop.create_server(
            self_._accept_socket,
            host=host,
            port=port,
            family=family,
            flags=flags,
            backlog=backlog,
            ssl=tls,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
        )

        self_._set_server(srv)
        return self_

    async def accept(self) -> AbstractSocket:
        if not self._srv:
            raise OSError("This socket is not listened.")

        if not self._srv.is_serving():
            raise OSError("Socket has closed.")

        async with self._accept_lock:
            while not self._pending_sockets:
                if not self._srv.is_serving():
                    raise OSError("Socket has closed.")

                self._socket_ready.clear()
                await self._socket_ready.wait()

            sock = self._pending_sockets.popleft()
            assert (
                sock._proto is not None
            ), "Listened socket cannot be add to this queue."
            await sock._proto._connected.wait()
            return sock

    def sockname(self) -> Optional[_SOCKET_INFO]:
        """
        Return the socket's local address.

        For listened sockets, it will return the first address.
        """
        if self._srv:
            try:
                return self.bound_socknames()[0]

            except IndexError:
                return None

        assert self._proto, "Socket can either be listened or has a protocol."
        return self._proto._transport.get_extra_info(  # type: ignore
            "sockname"
        )

    def bound_socknames(self) -> List[_SOCKET_INFO]:
        """
        Return all the local names.

        Depending on the I/O library, sometimes the 'Socket' will be able to
        listen to multiple sockets. This method can be used to return all the
        socknames it is bound to.
        """
        if not self._srv:
            raise RuntimeError(
                "You can only use this method on listened sockets."
            )

        if not self._srv.sockets:
            return []

        return [
            sock.getsockname()
            for sock in self._srv.sockets
            if sock.getsockname()
        ]

    def peername(self) -> Optional[_SOCKET_INFO]:
        """
        Return the remote address the socket is connected to.
        """
        if not self._proto:
            return None

        return self._proto._transport.get_extra_info(  # type: ignore
            "sockname"
        )

    def tls_ctx(self) -> Optional[ssl.SSLContext]:
        """
        Return the tls context (if any).
        """
        if not self._proto:
            return None

        return self._proto._transport.get_extra_info(  # type: ignore
            "sslcontext"
        )

    def tls_obj(self) -> Optional[ssl.SSLObject]:
        """
        Return an instance of the `ssl.SSLObject` (if any).
        """
        raise NotImplementedError


class Task(AbstractTask[_T]):
    __slots__ = ("_tsk",)

    def __init__(self, tsk: "asyncio.Task[_T]") -> None:
        self._tsk = tsk

    async def cancel(self, wait: bool = False) -> None:
        self._tsk.cancel()

        if wait:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await self._tsk

    def cancelled(self) -> bool:
        return self._tsk.cancelled()


class AsyncIo(AbstractIo):
    def create_lock(self) -> asyncio.Lock:
        return asyncio.Lock()

    def create_event(self) -> asyncio.Event:
        return asyncio.Event()

    async def create_task(self, coro: Coroutine[Any, Any, _T]) -> Task[_T]:
        return Task(asyncio.create_task(coro))

    Socket = Socket

    CancelledError = asyncio.CancelledError

    # async def shield(self, tsk: Awaitable[_T]) -> _T:
    #     return await asyncio.shield(tsk)


io = AsyncIo()
