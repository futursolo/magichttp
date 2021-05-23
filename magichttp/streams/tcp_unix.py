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

from typing import AsyncGenerator, List, Optional, Tuple, Union
import contextlib
import socket
import ssl

from .. import io_compat
from . import base

_SOCKET_INFO = Union[Tuple[str, int, int, int], Tuple[str, int]]


class SocketStream(base.BaseStreamReader, base.BaseStreamWriter):
    def __init__(self, sock: io_compat.AbstractSocket) -> None:
        self._sock = sock
        super().__init__()

        self._close_lock = self._io.create_lock()
        self._closed = False

    async def _read_data(self) -> bytes:
        try:
            return await self._sock.recv(self.max_buf_len)

        except Exception:
            self._closed = True
            raise

    async def _abort_stream(self) -> None:
        async with self._close_lock:
            self._closed = True
            await self._sock.close()

    async def _close_stream(self) -> None:
        async with self._close_lock:
            self._closed = True
            await self._sock.close()

    async def _write_data(self, data: bytes) -> None:
        try:
            await self._sock.send_all(data)

        except Exception:
            self._closed = True
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
            if self._closed:
                return

            self._closed = True
            await self._sock.close()

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


class TcpStream(SocketStream):
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
    ) -> "TcpStream":
        io = io_compat.get_io()

        sock = await io.Socket.connect(
            host,
            port,
            tls=tls,
            family=family,
            proto=proto,
            flags=flags,
            server_hostname=server_hostname,
        )
        stream = cls(sock)
        await stream._start_read_loop()
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
