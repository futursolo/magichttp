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

import typing
import asyncio
import h11
import abc
import functools


class BaseHttpImpl(abc.ABC):
    def __init__(
        self, *, protocol: "protocols.BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        self._protocol = protocol
        self._transport = transport

        self._paused = False

        self._loop = self._protocol._loop

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

    @abc.abstractmethod
    async def _read_request(self) -> streams.HttpRequestReader:
        raise NotImplementedError

    @abc.abstractmethod
    async def _read_response(
        self, req_writer: streams.HttpRequestWriter) -> \
            streams.HttpResponseReader:
        raise NotImplementedError

    async def read_request(self) -> streams.HttpRequestReader:
        assert isinstance(self._protocol, protocols.HttpServerProtocol)
        return await self._read_request()

    @abc.abstractmethod
    async def _write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            streams.HttpRequestWriter:
        raise NotImplementedError

    @abc.abstractmethod
    async def _write_response(
        self, req_reader: streams.HttpRequestReader,
        res_initial: initials.HttpResponseInitial) -> \
            streams.HttpResponseWriter:
        raise NotImplementedError

    async def write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            streams.HttpRequestWriter:
        assert isinstance(self._protocol, protocols.HttpClientProtocol)
        return await self._write_request(req_initial)

    @abc.abstractmethod
    async def _flush_data(
        self, writer: streams.BaseHttpStreamWriter, data: bytes,
            last_chunk: bool=False) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def _abort_request(
        self, req_stream: Union[
            streams.HttpRequestReader, streams.HttpRequestWriter]) -> None:
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


class H11Impl(BaseHttpImpl):
    def __init__(
        self, *, protocol: "protocols.BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        super().__init__(protocol=protocol, transport=transport)

        if isinstance(self._protocol, protocols.HttpServerProtocol):
            self._init_as_server()

        else:
            self._init_as_client()

        self._req_obtain_lock = asyncio.Lock()

        self._conn_exc: Optional[BaseException] = None

        self._closed = False

    def _init_as_server(self) -> None:
        self._h11 = h11.Connection(h11.SERVER)

        self._req_reader_queue: \
            "asyncio.Queue[Optional[streams.HttpRequestReader]]" = \
            asyncio.Queue(loop=self._loop)

        self._reset_as_server()

    def _reset_as_server(self) -> None:
        self._req_reader: Optional[streams.HttpRequestReader] = None
        self._res_writer: Optional[streams.HttpResponseWriter] = None

    def _init_as_client(self) -> None:
        self._h11 = h11.Connection(h11.CLIENT)

        self._reset_as_client()

    def _reset_as_client(self) -> None:
        self._req_writer: Optional[streams.HttpRequestWriter] = None
        self._res_reader: Optional[streams.HttpResponseReader] = None

        self._pause_reading()

    def _translate_to_h11_request(
            self, req_initial: initials.HttpRequestInitial) -> h11.Request:
        raise NotImplementedError

    def _translate_from_h11_request(self, h11_req: h11.Request) -> \
            initials.HttpRequestInitial:
        raise NotImplementedError

    async def _read_request(self) -> streams.HttpRequestReader:
        async with self._req_obtain_lock:
            if self._closed:
                raise exceptions.HttpConnectionClosedError

            reader = await self._req_reader_queue.get()

            if reader is None:
                raise exceptions.HttpConnectionClosedError

            return reader

    async def _read_response(
        self, req_writer: streams.HttpRequestWriter) -> \
            streams.HttpResponseReader:
        raise NotImplementedError

    async def _write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            streams.HttpRequestWriter:
        if self._closed:
            raise exceptions.HttpConnectionClosedError

        h11_req = self._translate_to_h11_request(req_initial)

        self._send_h11_event(h11_req)

        self._req_writer = streams.HttpRequestWriter(self, req_initial)
        self._resume_reading()

        return self._req_writer

    async def _write_response(
        self, req_reader: streams.HttpRequestReader,
        res_initial: initials.HttpResponseInitial) -> \
            streams.HttpResponseWriter:
        raise NotImplementedError

    def _send_h11_event(self, event: Any) -> None:
        raise NotImplementedError

    def _handle_h11_events(self) -> None:
        @functools.singledispatch
        def dispatch_client_event(event: Any) -> None:
            """
            Client Events:

            h11.NEED_DATA
            h11.PAUSED
            h11.InformationalResponse
            h11.Response
            h11.Data
            h11.EndOfMessage
            h11.ConnectionClosed
            """
            raise NotImplementedError

        @dispatch_client_event.register(  # type: ignore
            h11.InformationalResponse)
        def _(event: h11.InformationalResponse) -> None:
            pass

        @dispatch_client_event.register(h11.Response)  # type: ignore
        def _(event: h11.Response) -> None:
            raise NotImplementedError

        @dispatch_client_event.register(h11.Data)  # type: ignore
        def _(event: h11.Data) -> None:
            raise NotImplementedError

        @dispatch_client_event.register(h11.EndOfMessage)  # type: ignore
        def _(event: h11.EndOfMessage) -> None:
            raise NotImplementedError

        @dispatch_client_event.register(h11.ConnectionClosed)  # type: ignore
        def _(event: h11.ConnectionClosed) -> None:
            raise NotImplementedError

        @functools.singledispatch
        def dispatch_server_event(event: Any) -> None:
            """
            Server Events:

            h11.NEED_DATA
            h11.PAUSED
            h11.Request
            h11.Data
            h11.EndOfMessage
            h11.ConnectionClosed
            """
            raise NotImplementedError

        @dispatch_server_event.register(h11.Request)  # type: ignore
        def _(event: h11.Request) -> None:
            req_initial = self._translate_from_h11_request(event)

            self._req_reader = streams.HttpRequestReader(self, req_initial)
            self._req_reader_queue.put_nowait(self._req_reader)

        @dispatch_server_event.register(h11.Data)  # type: ignore
        def _(event: h11.Data) -> None:
            assert self._req_reader is not None
            self._req_reader._append_data(event.data)

        @dispatch_server_event.register(h11.EndOfMessage)  # type: ignore
        def _(event: h11.EndOfMessage) -> None:
            assert self._req_reader is not None
            self._req_reader._append_end()

        @dispatch_server_event.register(h11.ConnectionClosed)  # type: ignore
        def _(event: h11.ConnectionClosed) -> None:
            self._req_reader_queue.put_nowait(None)

            self._closed = True

        if isinstance(self._protocol, protocols.HttpServerProtocol):
            dispatch_event = dispatch_client_event

        else:
            dispatch_event = dispatch_server_event

        while True:
            try:
                event = self._h11.next_event()

            except h11.RemoteProtocolError as e:
                self._conn_exc = e
                self._transport.pause_reading()
                break

            if event is h11.NEED_DATA:
                if self._h11.they_are_waiting_for_100_continue:
                    self._send_h11_event(h11.InformationalResponse(
                        status_code=100, headers=[]))
                break

            if event is h11.PAUSED:
                self._transport.pause_reading()
                break

            dispatch_event(event)

    async def _flush_data(
        self, writer: streams.BaseHttpStreamWriter, data: bytes,
            last_chunk: bool=False) -> None:
        raise NotImplementedError

    async def _abort_request(
        self, req_stream: Union[
            streams.HttpRequestReader, streams.HttpRequestWriter]) -> None:
        raise NotImplementedError

    def data_received(self, data: bytes) -> None:
        if not data:
            return

        self._h11.receive_data(data)
        self._handle_h11_events()

    def eof_received(self) -> None:
        self._h11.receive_data(b"")
        self._handle_h11_events()

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        self._conn_exc = exc

        self._h11.receive_data(b"")
        self._handle_h11_events()
