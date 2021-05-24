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

from types import TracebackType
from typing import (
    Any,
    AsyncContextManager,
    AsyncGenerator,
    Awaitable,
    Generator,
    Generic,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)
import contextlib
import socket
import ssl

from .. import io_compat
from . import base

_SOCKET_INFO = Union[Tuple[str, int, int, int], Tuple[str, int]]

_TStream = TypeVar("_TStream", bound="SocketStream", covariant=True)


class SocketConnector(
    Awaitable[_TStream], AsyncContextManager[_TStream], Generic[_TStream]
):
    def __init__(self) -> None:
        self._stream: Optional[_TStream] = None
        self._await_lock = io_compat.get_io().create_lock()

    async def _create_stream(self) -> _TStream:
        raise NotImplementedError

    def __await__(self) -> Generator[Any, None, _TStream]:
        async def impl() -> _TStream:
            async with self._await_lock:
                if self._stream is None:
                    self._stream = await self._create_stream()
                return self._stream

        return impl().__await__()

    async def __aenter__(self) -> _TStream:
        stream = await self
        return await stream.__aenter__()

    async def __aexit__(
        self,
        exc_cls: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if self._stream is not None:
            await self._stream.__aexit__(exc_cls, exc, tb)


class SocketStream(
    base.BaseStreamReader,
    base.BaseStreamWriter,
    AsyncContextManager["SocketStream"],
):
    def __init__(self, sock: io_compat.AbstractSocket) -> None:
        self._sock = sock
        base.BaseStreamReader.__init__(self)
        base.BaseStreamWriter.__init__(self)

        self._close_lock = self._io.create_lock()
        self._closed = False

    async def _read_data(self) -> bytes:
        try:
            data = await self._sock.recv(self.max_buf_len)
            return data

        except Exception:
            with contextlib.suppress(Exception):
                await self._sock.close()

            raise

    async def _abort_stream(self) -> None:
        await self._sock.close()

    async def _write_data(self, data: bytes) -> None:
        try:
            await self._sock.send_all(data)

        except Exception:
            with contextlib.suppress(Exception):
                await self._sock.close()

            with contextlib.suppress(Exception):
                self.finish()

            raise

    async def _finish_writing(self) -> None:
        # Currently does nothing. But ideally should do
        # socket.shutdown(socket.SHUTDOWN_WR) on non-tls sockets.
        pass

    async def close(self) -> None:
        """
        Close the socket.
        """
        async with self._close_lock:
            if not self._closed:

                self._closed = True
                await self._sock.close()

                with contextlib.suppress(Exception):
                    self.finish()

            await self._wait_read_loop()
            await self._wait_write_loop()

    def closed(self) -> bool:
        """
        Return `True` if the socket has been closed.
        """
        return self._closed

    def local_addr(self) -> Optional[_SOCKET_INFO]:
        """
        Return socket's local address.
        """
        return self._sock.sockname()

    def peer_addr(self) -> Optional[_SOCKET_INFO]:
        """
        Return socket's peer address.
        """
        return self._sock.peername()

    async def abort(self) -> None:
        await base.BaseStreamReader.abort(self)
        await base.BaseStreamWriter.abort(self)

    async def __aenter__(self: _TStream) -> _TStream:
        return self

    async def __aexit__(
        self,
        exc_cls: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()


class TcpStream(SocketStream):
    @classmethod
    def connect(
        cls,
        host: str,
        port: int,
        *,
        tls: Optional[ssl.SSLContext] = None,
        family: int = 0,
        proto: int = 0,
        flags: int = 0,
        server_hostname: Optional[str] = None,
    ) -> "TcpConnector":
        return TcpConnector(
            cls,
            host,
            port,
            tls=tls,
            family=family,
            proto=proto,
            flags=flags,
            server_hostname=server_hostname,
        )


class TcpConnector(SocketConnector[TcpStream]):
    def __init__(
        self,
        stream_cls: Type[_TStream],
        host: str,
        port: int,
        *,
        tls: Optional[ssl.SSLContext] = None,
        family: int = 0,
        proto: int = 0,
        flags: int = 0,
        server_hostname: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._stream_cls = stream_cls
        self._host = host
        self._port = port
        self._tls = tls
        self._family = family
        self._proto = proto
        self._flags = flags
        self._server_hostname = server_hostname

    async def _create_stream(self) -> TcpStream:
        io = io_compat.get_io()

        sock = await io.Socket.connect(
            self._host,
            self._port,
            tls=self._tls,
            family=self._family,
            proto=self._proto,
            flags=self._flags,
            server_hostname=self._server_hostname,
        )
        stream = TcpStream(sock)
        await stream._start_read_loop()
        await stream._start_write_loop()
        return stream


class TcpListener:  # noqa: SIM119
    def __init__(self, sock: io_compat.AbstractSocket) -> None:
        self._sock = sock

    @classmethod
    async def bind(
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
    ) -> "TcpListener":
        io = io_compat.get_io()

        sock = await io.Socket.bind_listen(
            host,
            port,
            family=family,
            flags=flags,
            backlog=backlog,
            socket_backlog=socket_backlog,
            tls=tls,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
        )

        return TcpListener(sock)

    async def accept(self) -> TcpStream:
        stream = TcpStream(await self._sock.accept())

        await stream._start_read_loop()

        return stream

    @contextlib.asynccontextmanager
    async def incoming(self) -> AsyncGenerator[TcpStream, None]:
        while True:
            yield await self.accept()

    def local_addrs(self) -> List[_SOCKET_INFO]:
        """
        Return a list of all listened addresses.
        """
        return self._sock.bound_socknames()
