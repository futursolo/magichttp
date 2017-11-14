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

from typing import AsyncIterator, Optional, Any, Union, Mapping, Iterable, \
    Tuple

from . import streams
from . import initials
from . import impls
from . import exceptions

import asyncio
import abc
import typing

if typing.TYPE_CHECKING:
    from . import constants
    from . import readers
    from . import writers

__all__ = ["HttpServerProtocol", "HttpClientProtocol"]

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class BaseHttpProtocolDelegate(abc.ABC):
    @abc.abstractmethod
    def __init__(
        self, protocol: "BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def data_received(self, data: bytes) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def eof_received(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def finished(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    async def wait_finished(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def abort(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def connection_lost(self, exc: Optional[BaseException]) -> None:
        raise NotImplementedError


class BaseHttpProtocol(asyncio.Protocol, abc.ABC):
    _STREAM_BUFFER_LIMIT = 4 * 1024 * 1024  # 4M
    _INITIAL_BUFFER_LIMIT = 64 * 1024  # 64K

    def __init__(self) -> None:
        super().__init__()

        self._loop = asyncio.get_event_loop()

        self._drained_event = asyncio.Event()
        self._drained_event.set()

        self._impl: Optional[impls.BaseHttpImpl] = None

        self._open_after_eof = True

        self._transport: Optional[asyncio.Transport] = None

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        self._open_after_eof = transport.get_extra_info("sslcontext") is None

        self._transport = transport

    @property
    def transport(self) -> asyncio.Transport:
        assert self._transport is not None

        return self._transport

    def pause_writing(self) -> None:
        if not self._drained_event.is_set():
            return

        self._drained_event.clear()

    def resume_writing(self) -> None:
        if self._drained_event.is_set():
            return

        self._drained_event.set()

    async def _flush(self) -> None:
        if self._drained_event.is_set():
            return

        await self._drained_event.wait()

    def data_received(self, data: bytes) -> None:
        assert self._impl is not None

        self._impl.data_received(data)

    def eof_received(self) -> bool:
        assert self._impl is not None

        self._impl.eof_received()

        return self._open_after_eof

    async def close(self) -> None:
        assert self._impl is not None

        await self._impl.close()

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        if self._impl is not None:
            self._impl.connection_lost(exc)


class HttpServerProtocolDelegate(BaseHttpProtocolDelegate):
    @abc.abstractmethod
    def __init__(
        self, protocol: "HttpServerProtocol",
            transport: asyncio.Transport) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def read_request(self) -> "readers.HttpRequestReader":
        raise NotImplementedError


class HttpServerProtocol(
        BaseHttpProtocol, AsyncIterator["streams.HttpRequestReader"]):
    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        self._impl = impls.H1ServerImpl(protocol=self, transport=transport)

        super().connection_made(transport)

    def __aiter__(self) -> AsyncIterator["streams.HttpRequestReader"]:
        return self

    async def __anext__(self) -> "streams.HttpRequestReader":
        assert isinstance(self._impl, impls.BaseHttpServerImpl)

        try:
            return await self._impl.read_request()

        except (
                exceptions.HttpConnectionClosingError,
                exceptions.HttpConnectionClosedError) as e:
            raise StopAsyncIteration from e


class HttpClientProtocolDelegate(BaseHttpProtocolDelegate):
    @abc.abstractmethod
    def __init__(
        self, protocol: "HttpServerProtocol",
            transport: asyncio.Transport) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: bytes, authority: Optional[bytes],
        version: "constants.HttpVersion",
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> "writers.HttpRequestWriter":
        raise NotImplementedError


class HttpClientProtocol(BaseHttpProtocol):
    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        self._impl = impls.H1ClientImpl(protocol=self, transport=transport)

        super().connection_made(transport)

    async def write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            "streams.HttpRequestWriter":
        assert isinstance(self._impl, impls.BaseHttpClientImpl)

        return await self._impl.write_request(req_initial)
