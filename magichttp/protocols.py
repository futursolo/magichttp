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

from typing import AsyncIterator, Optional, Any

from . import streams
from . import initials
from . import impls
from . import exceptions

import asyncio
import abc

__all__ = ["HttpServerProtocol", "HttpClientProtocol"]


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

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        self._open_after_eof = transport.get_extra_info("sslcontext") is None

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


class HttpServerProtocol(
        BaseHttpProtocol, AsyncIterator[streams.HttpRequestReader]):
    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        super().connection_made(transport)

        self._impl = impls.H1ServerImpl(protocol=self, transport=transport)

    def __aiter__(self) -> AsyncIterator[streams.HttpRequestReader]:
        return self

    async def __anext__(self) -> streams.HttpRequestReader:
        assert isinstance(self._impl, impls.BaseHttpServerImpl)

        try:
            return await self._impl.read_request()

        except (
                exceptions.HttpConnectionClosingError,
                exceptions.HttpConnectionClosedError) as e:
            raise StopAsyncIteration from e


class HttpClientProtocol(BaseHttpProtocol):
    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        super().connection_made(transport)

        self._impl = impls.H1ClientImpl(protocol=self, transport=transport)

    async def write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            streams.HttpRequestWriter:
        assert isinstance(self._impl, impls.BaseHttpClientImpl)

        return await self._impl.write_request(req_initial)
