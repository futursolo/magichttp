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

from typing import AsyncIterator, Optional, Union, Mapping, Iterable, Tuple

from . import h1impls
from . import readers
from . import constants

import asyncio
import abc
import typing

if typing.TYPE_CHECKING:
    from . import writers

__all__ = [
    "BaseHttpProtocolDelegate",
    "BaseHttpProtocol",

    "HttpServerProtocolDelegate",
    "HttpServerProtocol",

    "HttpClientProtocolDelegate",
    "HttpClientProtocol"]

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
    _MAX_INITIAL_SIZE = 64 * 1024  # 64K

    def __init__(self) -> None:
        super().__init__()

        self._drained_event = asyncio.Event()
        self._drained_event.set()

        self._open_after_eof = True

        self._transport: Optional[asyncio.Transport] = None

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        self._open_after_eof = transport.get_extra_info("sslcontext") is None

        self._transport = transport

    @property
    @abc.abstractmethod
    def _delegate(self) -> BaseHttpProtocolDelegate:
        raise NotImplementedError

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
        self._delegate.data_received(data)

    def eof_received(self) -> bool:
        self._delegate.eof_received()

        return self._open_after_eof

    def close(self) -> None:
        self._delegate.close()

    async def wait_closed(self) -> None:
        await self._delegate.wait_finished()

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        if hasattr(self, "_delegate"):
            self._delegate.connection_lost(exc)

        self._drained_event.set()


class HttpServerProtocolDelegate(BaseHttpProtocolDelegate):
    @abc.abstractmethod
    def __init__(
        self, protocol: "HttpServerProtocol",
            transport: asyncio.Transport) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def read_request(self) -> readers.HttpRequestReader:
        raise NotImplementedError


class HttpServerProtocol(
        BaseHttpProtocol, AsyncIterator[readers.HttpRequestReader]):
    def __init__(self) -> None:
        super().__init__()

        self.__delegate: Optional[HttpServerProtocolDelegate] = None

    @property
    def _delegate(self) -> HttpServerProtocolDelegate:
        if self.__delegate is None:
            raise AttributeError("Delegate is not ready.")

        return self.__delegate

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        self.__delegate = h1impls.H1ServerImpl(self, transport)

        super().connection_made(transport)

    def __aiter__(self) -> AsyncIterator[readers.HttpRequestReader]:
        return self

    async def __anext__(self) -> readers.HttpRequestReader:
        try:
            return await self._delegate.read_request()

        except (
                readers.HttpStreamReadFinishedError,
                readers.HttpStreamReadAbortedError) as e:
            raise StopAsyncIteration from e


class HttpClientProtocolDelegate(BaseHttpProtocolDelegate):
    @abc.abstractmethod
    def __init__(
        self, protocol: "HttpClientProtocol",
            transport: asyncio.Transport) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def write_request(
        self, method: constants.HttpRequestMethod, *,
        uri: bytes, authority: Optional[bytes],
        version: constants.HttpVersion,
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> "writers.HttpRequestWriter":
        raise NotImplementedError


class HttpClientProtocol(BaseHttpProtocol):
    def __init__(self) -> None:
        super().__init__()

        self.__delegate: Optional[HttpClientProtocolDelegate] = None

    @property
    def _delegate(self) -> HttpClientProtocolDelegate:
        if self.__delegate is None:
            raise AttributeError("Delegate is not ready.")

        return self.__delegate

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        self.__delegate = h1impls.H1ClientImpl(self, transport)

        super().connection_made(transport)

    async def write_request(
        self, method: constants.HttpRequestMethod, *,
        uri: bytes=b"/", authority: Optional[bytes]=None,
        version: Union[
            bytes, constants.HttpVersion]=constants.HttpVersion.V1_1,
        scheme: Optional[bytes]=None,
        headers: Optional[_HeaderType]=None) -> \
            "writers.HttpRequestWriter":
        return await self._delegate.write_request(
            method, uri=uri, authority=authority,
            version=constants.HttpVersion(version),
            scheme=scheme, headers=headers)
