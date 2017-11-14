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

from typing import Optional, Union, Mapping, Tuple, Iterable

from . import readers
from . import writers
from . import protocols

import typing
import abc

if typing.TYPE_CHECKING:
    from . import constants
    from . import protocols

    import http
    import asyncio

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class BaseH1StreamManager(
    readers.BaseHttpStreamReaderDelegate,
        writers.BaseHttpStreamWriterDelegate):
    @abc.abstractmethod
    async def fetch_data(self) -> bytes:
        raise NotImplementedError

    @abc.abstractmethod
    def write_data(self, data: bytes) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def flush_buf(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def finish_writing(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def wait_finished(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def abort(self) -> None:
        raise NotImplementedError


class BaseH1Impl(protocols.BaseHttpProtocolDelegate):
    @abc.abstractmethod
    def __init__(
        self, protocol: "protocols.BaseHttpProtocol",
            transport: "asyncio.Transport") -> None:
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


class H1ServerStreamManager(
    BaseH1StreamManager,
    readers.HttpRequestReaderDelegate,
        writers.HttpResponseWriterDelegate):
    @abc.abstractmethod
    def write_response(
        self, status_code: http.HTTPStatus, *,
        version: "constants.HttpVersion",
        headers: Optional[_HeaderType]
            ) -> "writers.HttpResponseWriter":
        raise NotImplementedError


class H1ServerImpl(BaseH1Impl, protocols.HttpServerProtocolDelegate):
    @abc.abstractmethod
    def __init__(
        self, protocol: "protocols.HttpServerProtocol",
            transport: "asyncio.Transport") -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def read_request(self) -> "readers.HttpRequestReader":
        raise NotImplementedError


class H1ClientStreamManager(
    BaseH1StreamManager,
    writers.HttpRequestWriterDelegate,
        readers.HttpResponseReaderDelegate):
    @abc.abstractmethod
    async def read_response(self) -> "readers.HttpResponseReader":
        raise NotImplementedError


class H1ClientImpl(BaseH1Impl, protocols.HttpClientProtocolDelegate):
    @abc.abstractmethod
    def __init__(
        self, protocol: "protocols.HttpClientProtocol",
            transport: "asyncio.Transport") -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: bytes, authority: Optional[bytes],
        version: "constants.HttpVersion",
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> "writers.HttpRequestWriter":
        raise NotImplementedError
