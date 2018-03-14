#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2018 Kaede Hoshikawa
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

if typing.TYPE_CHECKING:  # pragma: no cover
    from . import writers  # noqa: F401

__all__ = [
    "BaseHttpProtocol",
    "HttpServerProtocol",
    "HttpClientProtocol"]

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class BaseHttpProtocolDelegate(abc.ABC):  # pragma: nocover
    @abc.abstractmethod
    def __init__(
            self, protocol: "BaseHttpProtocol", max_initial_size: int) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def data_received(self, data: bytes) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def eof_received(self) -> None:
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
    """
    The base protocol for :class:`HttpServerProtocol` and
    :class:`HttpClientProtocol`.
    """
    __slots__ = ("_drained_event", "_open_after_eof", "_transport")

    _MAX_INITIAL_SIZE = 64 * 1024  # 64K

    def __init__(self) -> None:
        super().__init__()

        self._drained_event = asyncio.Event()
        self._drained_event.set()

        self._open_after_eof = True

        self._transport: Optional[asyncio.Transport] = None

        self._conn_lost = asyncio.Event()

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        self._open_after_eof = transport.get_extra_info("sslcontext") is None

        self._transport = transport

    @property
    @abc.abstractmethod
    def _delegate(self) -> BaseHttpProtocolDelegate:  # pragma: no cover
        raise NotImplementedError

    @property
    def transport(self) -> asyncio.Transport:
        """
        Returns :class:`asyncio.Transport`.
        """
        if self._transport is None:  # pragma: no cover
            raise AttributeError("Transport is not ready.")

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
        """
        Close the connection after current stream is finished.
        """
        self._delegate.close()

    async def wait_closed(self) -> None:
        """
        Wait until :method:`.connection_lost()` is called.
        """
        await self._conn_lost.wait()

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        if hasattr(self, "_delegate"):
            self._delegate.connection_lost(exc)

        self._drained_event.set()

        self._conn_lost.set()


class HttpServerProtocolDelegate(BaseHttpProtocolDelegate):  # pragma: no cover
    @abc.abstractmethod
    def __init__(
        self, protocol: "HttpServerProtocol",
            max_initial_size: int) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def read_request(self) -> readers.HttpRequestReader:
        raise NotImplementedError


class HttpServerProtocol(
        BaseHttpProtocol, AsyncIterator[readers.HttpRequestReader]):
    """
    The http server protocol.
    """
    __slots__ = ("__delegate",)

    def __init__(self) -> None:
        super().__init__()

        self.__delegate: Optional[HttpServerProtocolDelegate] = None

    @property
    def _delegate(self) -> HttpServerProtocolDelegate:
        if self.__delegate is None:  # pragma: no cover
            raise AttributeError("Delegate is not ready.")

        return self.__delegate

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        super().connection_made(transport)

        self.__delegate = h1impls.H1ServerImpl(
            self, self._MAX_INITIAL_SIZE)

    def __aiter__(self) -> AsyncIterator[readers.HttpRequestReader]:
        return self

    async def __anext__(self) -> readers.HttpRequestReader:
        """
        Returns the next Reuqest reader (if any).

        .. code-block:: python3

            async for reader in protocol:
                ...
        """
        try:
            return await self._delegate.read_request()

        except (readers.ReadFinishedError, readers.ReadAbortedError) as e:
            raise StopAsyncIteration from e


class HttpClientProtocolDelegate(BaseHttpProtocolDelegate):  # pragma: no cover
    @abc.abstractmethod
    def __init__(
        self, protocol: "HttpClientProtocol", max_initial_size: int,
            http_version: constants.HttpVersion) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def write_request(
        self, method: constants.HttpRequestMethod, *,
        uri: bytes, authority: Optional[bytes],
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> "writers.HttpRequestWriter":
        raise NotImplementedError


class HttpClientProtocol(BaseHttpProtocol):
    """
    The http client protocol.
    """
    __slots__ = ("__delegate", "_http_version")

    def __init__(
        self, *, http_version:
            constants.HttpVersion=constants.HttpVersion.V1_1) -> None:
        super().__init__()

        self._http_version = http_version

        self.__delegate: Optional[HttpClientProtocolDelegate] = None

    @property
    def _delegate(self) -> HttpClientProtocolDelegate:
        if self.__delegate is None:  # pragma: no cover
            raise AttributeError("Delegate is not ready.")

        return self.__delegate

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        super().connection_made(transport)

        self.__delegate = h1impls.H1ClientImpl(
            self, self._MAX_INITIAL_SIZE, self._http_version)

    async def write_request(
        self, method: constants.HttpRequestMethod, *,
        uri: bytes=b"/", authority: Optional[bytes]=None,
        scheme: Optional[bytes]=None,
        headers: Optional[_HeaderType]=None) -> \
            "writers.HttpRequestWriter":
        """
        Send next request to the server.
        """
        return await self._delegate.write_request(
            method, uri=uri, authority=authority,
            scheme=scheme, headers=headers)
