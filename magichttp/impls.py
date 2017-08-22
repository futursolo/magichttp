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

from typing import Any, Optional, Generic, TypeVar, Union

from . import protocols
from . import initials
from . import streams
from . import exceptions
from . import h1connection

import typing
import asyncio
import abc
import functools
import enum


class BaseHttpImpl(abc.ABC):
    def __init__(
        self, *, protocol: "protocols.BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        self._protocol = protocol
        self._transport = transport

        self._paused = False

        self._loop = asyncio.get_event_loop()

    def _pause_reading(self) -> None:
        if self._paused:
            return

        self._transport.pause_reading()
        self._paused = True

    def _resume_reading(self) -> None:
        if not self._paused:
            return

        self._transport.resume_reading()
        self._paused = False

    @abc.abstractmethod  # Server-side Only.
    async def _read_request(self) -> "streams.HttpRequestReader":
        raise NotImplementedError

    @abc.abstractmethod  # Client-side Only.
    async def _read_response(
        self, req_writer: "streams.HttpRequestWriter") -> \
            "streams.HttpResponseReader":
        raise NotImplementedError

    async def read_request(self) -> "streams.HttpRequestReader":
        assert isinstance(self._protocol, protocols.HttpServerProtocol)
        return await self._read_request()

    @abc.abstractmethod  # Client-side Only.
    async def _write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            "streams.HttpRequestWriter":
        raise NotImplementedError

    @abc.abstractmethod  # Server-side Only.
    async def _write_response(
        self, req_reader: "streams.HttpRequestReader",
        res_initial: initials.HttpResponseInitial) -> \
            "streams.HttpResponseWriter":
        raise NotImplementedError

    async def write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            "streams.HttpRequestWriter":
        assert isinstance(self._protocol, protocols.HttpClientProtocol)
        return await self._write_request(req_initial)

    @abc.abstractmethod
    async def _flush_data(
        self, writer: "streams.BaseHttpStreamWriter", data: bytes,
            last_chunk: bool=False) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def _abort_request(
        self, req_stream: Union[
            "streams.HttpRequestReader", "streams.HttpRequestWriter"]) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def data_received(self, data: bytes) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def eof_received(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def connection_lost(self, exc: Optional[BaseException]) -> None:
        raise NotImplementedError


class H1Impl(BaseHttpImpl):
    def __init__(
        self, *, protocol: "protocols.BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        super().__init__(protocol=protocol, transport=transport)

        self._parser: Optional[h1connection.H1InitialParser] = None
        self._composer: Optional[h1connection.H1InitialComposer] = None

        self._incoming_buf = bytearray()

        self._exc: Optional[Exception] = None

    def reset(self) -> None:
        self._parser: Optional[h1connection.H1InitialParser] = None
        self._composer: Optional[h1connection.H1InitialComposer] = None

    async def _read_request(self) -> "streams.HttpRequestReader":
        raise NotImplementedError

    async def _read_response(
        self, req_writer: "streams.HttpRequestWriter") -> \
            "streams.HttpResponseReader":
        raise NotImplementedError

    async def _write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            "streams.HttpRequestWriter":
        raise NotImplementedError

    async def _write_response(
        self, req_reader: "streams.HttpRequestReader",
        res_initial: initials.HttpResponseInitial) -> \
            "streams.HttpResponseWriter":
        raise NotImplementedError

    async def _flush_data(
        self, writer: "streams.BaseHttpStreamWriter", data: bytes,
            last_chunk: bool=False) -> None:
        raise NotImplementedError

    async def _abort_request(
        self, req_stream: Union[
            "streams.HttpRequestReader", "streams.HttpRequestWriter"]) -> None:
        raise NotImplementedError

    def data_received(self, data: bytes) -> None:
        self._incoming_buf.extend(data)

        if len(self._incoming_buf) > self._protocol._INITIAL_BUFFER_LIMIT:
            self._pause_reading()

    def eof_received(self) -> None:
        raise NotImplementedError

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        raise NotImplementedError
