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

from typing import Any, Dict, List, Optional, Type, Union
import asyncio
import contextlib
import pathlib
import socket
import traceback
import uuid

import magicdict

import magichttp


def get_version_str() -> str:
    return f"magichttp/{magichttp.__version__}"


def get_version_bytes() -> bytes:
    return get_version_str().encode()


def assert_initial(
    buf: Union[bytes, bytearray],
    first_line: bytes,
    *header_lines: bytes,
) -> None:
    buf_initial = buf.split(b"\r\n\r\n")[0]
    buf_parts = buf_initial.split(b"\r\n")

    assert buf_parts.pop(0) == first_line

    assert len(buf_parts) == len(set(buf_parts))
    assert len(buf_parts) == len(header_lines)

    for line in header_lines:
        line = line % {b"self_ver_bytes": get_version_bytes()}  # noqa: S001
        assert line in buf_parts


_REQ_INITIAL = magichttp.HttpRequestInitial(
    magichttp.HttpRequestMethod.GET,
    uri="/",
    headers=magicdict.FrozenTolerantMagicDict(),
    scheme="https",
    version=magichttp.HttpVersion.V1_1,
    authority="www.example.com",
)

_RES_INITIAL = magichttp.HttpResponseInitial(
    magichttp.HttpStatusCode.OK,
    version=magichttp.HttpVersion.V1_1,
    headers=magicdict.FrozenTolerantMagicDict(),
)


class MockedTransport(asyncio.Transport):
    def __init__(self) -> None:
        self._paused = False
        self._closing = False
        self._data_chunks: List[bytes] = []
        self._extra_info: Dict[str, Any] = {}

    def _pop_stored_data(self) -> bytes:
        data = b"".join(self._data_chunks)
        self._data_chunks.clear()

        return data

    def pause_reading(self) -> None:
        assert self._paused is False

        self._paused = True

    def resume_reading(self) -> None:
        assert self._paused is True

        self._paused = False

    def close(self) -> None:
        self._closing = True

    def is_closing(self) -> bool:
        return self._closing

    def write(self, data: bytes) -> None:
        self._data_chunks.append(data)

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return self._extra_info.get(name)


class ReaderDelegateMock(
    magichttp.readers.HttpRequestReaderDelegate,
    magichttp.readers.HttpResponseReaderDelegate,
):
    def __init__(self) -> None:
        self.paused = False
        self.aborted = False
        self.writer_mock: Any = None

    def pause_reading(self) -> None:
        self.paused = True

    def resume_reading(self) -> None:
        self.paused = False

    def abort(self) -> None:
        self.aborted = True

    def write_response(self, *args: Any, **kwargs: Any) -> Any:
        self.writer_mock = object()
        return self.writer_mock


class WriterDelegateMock(
    magichttp.writers.HttpRequestWriterDelegate,
    magichttp.writers.HttpResponseWriterDelegate,
):
    def __init__(self) -> None:
        self.write_called = False
        self.data_pieces: List[bytes] = []
        self.finished = False

        self.flush_event = asyncio.Event()

        self.aborted = False

        self.reader_mock: Optional[magichttp.HttpResponseReader] = None

        self._exc: Optional[Exception] = None

    def write_data(self, data: bytes, finished: bool = False) -> None:
        self.write_called = True
        self.data_pieces.append(data)
        self.finished = finished

        if self._exc:
            raise self._exc

    async def flush_buf(self) -> None:
        await self.flush_event.wait()

        if self._exc:
            raise self._exc

    def abort(self) -> None:
        self.aborted = True

    async def read_response(self) -> magichttp.HttpResponseReader:
        if self.reader_mock is None:
            self.reader_mock = magichttp.HttpResponseReader(
                ReaderDelegateMock(),
                initial=_RES_INITIAL,
                writer=magichttp.HttpRequestWriter(self, initial=_REQ_INITIAL),
            )

        return self.reader_mock


class _SkeletonProtocol(asyncio.Protocol):
    def __init__(self, srv: "MockedServer") -> None:
        self._srv = srv

        self._mock_proto = self._srv.mock_proto_cls()
        self._srv.mock_protos.append(self._mock_proto)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.Transport)
        print("Connection made.")

        self._mock_proto.connection_made(transport)

    def data_received(self, data: bytes) -> None:
        print(f"Data received: {data!r}.")

        self._mock_proto.data_received(data)

    def eof_received(self) -> Optional[bool]:
        print("Eof received.")

        return self._mock_proto.eof_received()

    def connection_lost(self, exc: Optional[Exception]) -> None:
        print("Connection lost.")
        if exc:
            traceback.print_exception(exc.__class__, exc, exc.__traceback__)

        self._mock_proto.connection_lost(exc)


class BaseMockProtocol(asyncio.Protocol):
    def __init__(self) -> None:
        self.transport: Optional[asyncio.Transport] = None
        self.data_chunks: List[bytes] = []
        self.eof = False
        self.exc: Optional[Exception] = None
        self.conn_lost = False

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.Transport)
        self.transport = transport

    def data_received(self, data: bytes) -> None:
        self.data_chunks.append(data)

    def eof_received(self) -> Optional[bool]:
        self.eof = True
        return True

    def connection_lost(self, exc: Optional[Exception]) -> None:
        self.exc = exc
        self.conn_lost = True

    def assert_initial(
        self,
        first_line: bytes,
        *header_lines: bytes,
        buf: Optional[Union[bytes, bytearray]] = None,
    ) -> None:
        if buf is None:
            buf = b"".join(self.data_chunks)

        buf_initial = buf.split(b"\r\n\r\n")[0]
        buf_parts = buf_initial.split(b"\r\n")

        assert buf_parts.pop(0) == first_line

        assert len(buf_parts) == len(set(buf_parts))
        assert len(buf_parts) == len(header_lines)

        for line in header_lines:
            line = line % {  # noqa: S001
                b"self_ver_bytes": get_version_bytes()
            }

            assert line in buf_parts


class MockedServer:
    """
    A test helper that controls the servers.
    """

    @staticmethod
    def avail_tcp_port() -> int:
        with contextlib.closing(socket.socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]  # type: ignore

    def __init__(self) -> None:
        self._srv: Optional[asyncio.AbstractServer] = None

        self.mock_proto_cls: Type[BaseMockProtocol] = BaseMockProtocol
        self.mock_protos: List[BaseMockProtocol] = []

        self.port = self.avail_tcp_port()

    async def __aenter__(self) -> "MockedServer":
        loop = asyncio.get_event_loop()

        self._srv = await loop.create_server(
            lambda: _SkeletonProtocol(self), host="localhost", port=self.port
        )

        return self

    async def __aexit__(self, exc: Optional[Exception] = None) -> None:
        if self._srv:
            self._srv.close()
            await self._srv.wait_closed()

    def select_proto(self) -> BaseMockProtocol:
        """Selects the first non-empty protocol."""

        for proto in self.mock_protos:
            if b"".join(proto.data_chunks):
                return proto

        raise RuntimeError("There's no available protocol.")


class MockedUnixServer(MockedServer):
    """
    Same as MockedServer but using a unix socket.
    """

    def __init__(self) -> None:
        super().__init__()

        self.path = pathlib.Path("/tmp") / f"{str(uuid.uuid4())}.sock"

    async def __aenter__(self) -> "MockedUnixServer":
        loop = asyncio.get_event_loop()

        self._srv = await loop.create_unix_server(
            lambda: _SkeletonProtocol(self), str(self.path)
        )

        return self

    async def __aexit__(self, exc: Optional[Exception] = None) -> None:
        if self._srv:
            self._srv.close()
            await self._srv.wait_closed()

    def select_proto(self) -> BaseMockProtocol:
        """Selects the first non-empty protocol."""

        for proto in self.mock_protos:
            if b"".join(proto.data_chunks):
                return proto

        raise RuntimeError("There's no available protocol.")
