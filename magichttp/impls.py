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
from . import h1parser
from . import h1composer

import typing
import asyncio
import abc
import functools
import enum


class _ReadState(enum.IntEnum):
    Reading = 1
    Paused = 0
    Finished = -1  # EOF.


class BaseHttpImpl(abc.ABC):
    def __init__(
        self, *, protocol: "protocols.BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        self._protocol = protocol
        self._transport = transport

        self._loop = asyncio.get_event_loop()

        self._read_state = _ReadState.Reading
        self._read_state_changed: "asyncio.Future[_ReadState]" = \
            asyncio.Future()

        self._eof_written = asyncio.Event()

        self._conn_closing = asyncio.Event()
        self._conn_closed = asyncio.Event()

    def _set_read_state(self, new_read_state: _ReadState) -> None:
        if self._read_state == new_read_state:
            return

        if self._read_state == _ReadState.Finished:
            raise RuntimeError(
                "You Cannot Recover State from A Finished Transport.")

        self._read_state = new_read_state

        if self._read_state == _ReadState.Reading:
            self._transport.resume_reading()

        elif self._read_state == _ReadState.Paused:
            self._transport.pause_reading()

        self._read_state_changed.set_result(self._read_state)
        self._read_state_changed = asyncio.Future()

    async def _wait_read_state(self, state_needed: _ReadState) -> None:
        if self._read_state == state_needed:
            return

        while ((await self._read_state_changed) != state_needed):
            pass

    def _close_conn(self) -> None:
        self._write_eof()

        if not self._transport.is_closing():
            self._transport.close()

    def _write_eof(self) -> None:
        if self._eof_written.is_set():
            return

        if self._transport.can_write_eof():
            self._transport.write_eof()

        self._eof_written.set()
        self._conn_closing.set()

        if self._read_state == _ReadState.Finished:
            self._close_conn()

    @abc.abstractmethod
    async def flush_data(
        self, writer: "streams.BaseHttpStreamWriter", data: bytes,
            last_chunk: bool=False) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def data_received(self, data: Optional[bytes]=None) -> None:
        raise NotImplementedError

    def eof_received(self) -> None:
        self._set_read_state(_ReadState.Finished)
        self._conn_closing.set()

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        self._set_read_state(_ReadState.Finished)
        self._conn_closing.set()
        self._conn_closed.set()

    async def close(self) -> None:
        self._conn_closing.set()

        await self._conn_closed.wait()


class BaseHttpServerImpl(BaseHttpImpl):
    def resume_reading(self, req_reader: "streams.HttpRequestReader") -> None:
        pass

    @abc.abstractmethod
    async def read_request(self) -> "streams.HttpRequestReader":
        raise NotImplementedError

    @abc.abstractmethod
    async def write_response(
        self, req_reader: Optional["streams.HttpRequestReader"],
        res_initial: initials.HttpResponseInitial) -> \
            "streams.HttpResponseWriter":
        raise NotImplementedError

    @abc.abstractmethod
    async def abort_request(
            self, req_stream: Optional["streams.HttpRequestReader"]) -> None:
        raise NotImplementedError


class BaseHttpClientImpl(BaseHttpImpl):
    def resume_reading(self, req_writer: "streams.HttpRequestWriter") -> None:
        pass

    @abc.abstractmethod
    async def read_response(
        self, req_writer: "streams.HttpRequestWriter") -> \
            "streams.HttpResponseReader":
        raise NotImplementedError

    @abc.abstractmethod
    async def write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            "streams.HttpRequestWriter":
        raise NotImplementedError

    @abc.abstractmethod
    async def abort_request(
            self, req_stream: "streams.HttpRequestWriter") -> None:
        raise NotImplementedError


class BaseH1Impl(BaseHttpImpl):
    def __init__(
        self, *, protocol: "protocols.BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        super().__init__(protocol=protocol, transport=transport)

        self._using_https = self._transport.get_extra_info(
            "sslcontext") is None

        self._buf = bytearray()

        self._parser: h1parser.H1Parser = h1parser.H1Parser(
            self._buf, self._using_https)
        self._composer: h1composer.H1Composer = h1composer.H1Composer(
            self._using_https)

        self._init_lock = asyncio.Lock()

        self._read_exc: Optional[Exception] = None
        self._write_exc: Optional[Exception] = None

        self._stream_read_finished = False
        self._stream_write_finished = False

    def _set_read_exc(self, exc: Exception) -> None:
        if self._read_exc is not None:
            return

        self._conn_closing.set()

        self._read_exc = exc

    def _set_write_exc(self, exc: Exception) -> None:
        if self._write_exc is not None:
            return

        self._conn_closing.set()

        self._write_exc = exc

    def _set_exc(self, exc: Exception) -> None:
        self._set_read_exc(exc)
        self._set_write_exc(exc)

    def _try_raise_read_exc(self) -> None:
        if self._read_exc is not None:
            raise self._read_exc

        if self._conn_closed.is_set():
            raise exceptions.HttpConnectionClosedError

        if self._conn_closing.is_set():
            raise exceptions.HttpConnectionClosingError

    def _try_raise_write_exc(self) -> None:
        if self._write_exc is not None:
            raise self._write_exc

        if self._conn_closed.is_set():
            raise exceptions.HttpConnectionClosedError

        if self._eof_written.is_set():
            raise exceptions.HttpConnectionClosingError

    def _try_raise_any_exc(self) -> None:
        self._try_raise_read_exc()
        self._try_raise_write_exc()

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        super().connection_lost(exc)

        if exc is not None:
            final_exc = exceptions.HttpConnectionClosedError()
            final_exc.__cause__ = exc

            self._set_exc(final_exc)


class H1ServerImpl(BaseH1Impl, BaseHttpServerImpl):
    def __init__(
        self, *, protocol: "protocols.BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        super().__init__(protocol=protocol, transport=transport)

        self._reader: Optional["streams.HttpRequestReader"] = None
        self._writer: Optional["streams.HttpResponseWriter"] = None

        self._reader_fur: \
            "asyncio.Future[streams.HttpRequestReader]" = asyncio.Future()

    def _set_read_exc(self, exc: Exception) -> None:
        if not self._reader_fur.done():
            self._reader_fur.set_exception(exc)

        if self._reader is not None:
            self._reader._append_exc(exc)

        super()._set_read_exc(exc)

    def _set_write_exc(self, exc: Exception) -> None:
        if self._writer is not None:
            self._writer._append_exc(exc)

        super()._set_write_exc(exc)

    def _maybe_finished(self) -> None:
        if not (self._stream_read_finished and self._stream_write_finished):
            return

        self._reader = None
        self._writer = None

        if self._conn_closing.is_set():
            self._close_conn()

        else:
            self._stream_read_finished = False
            self._stream_write_finished = False

            self.data_received()

    def resume_reading(self, req_reader: "streams.HttpRequestReader") -> None:
        if self._reader is not req_reader:
            raise ValueError("Reader Mismatch.")

        if self._read_state == _ReadState.Paused:
            self._try_raise_read_exc()
            self._set_read_state(_ReadState.Reading)

    async def read_request(self) -> "streams.HttpRequestReader":
        async def _write_response(
            res_initial: initials.HttpResponseInitial) -> \
                streams.HttpResponseWriter:
            return await self.write_response(None, res_initial)

        async with self._init_lock:
            try:
                self._try_raise_read_exc()

                reader = await self._reader_fur
                self._reader_fur = asyncio.Future()

                self.data_received()

                return reader

            except exceptions.MalformedHttpInitial as e:
                if self._writer is None and not self._eof_written.is_set():
                    raise exceptions.MalformedHttpInitial(
                        write_response_fn=_write_response) from e

                raise

            except exceptions.MalformedHttpMessage as e:
                if self._writer is None and not self._eof_written.is_set():
                    raise exceptions.MalformedHttpMessage(
                        write_response_fn=_write_response) from e

                raise

            except exceptions.IncomingInitialTooLarge as e:
                if self._writer is None and not self._eof_written.is_set():
                    raise exceptions.IncomingInitialTooLarge(
                        write_response_fn=_write_response) from e

                raise

            except exceptions.IncomingEntityTooLarge as e:
                if self._writer is None and not self._eof_written.is_set():
                    raise exceptions.IncomingEntityTooLarge(
                        write_response_fn=_write_response) from e

                raise

            except exceptions.HttpStreamAbortedError as e:
                raise exceptions.HttpConnectionClosedError from e

    async def write_response(
        self, req_reader: Optional["streams.HttpRequestReader"],
        res_initial: initials.HttpResponseInitial) -> \
            "streams.HttpResponseWriter":
        if req_reader is None:
            if self._read_exc is None:
                raise ValueError(
                    "You MUST provide the request reader "
                    "when there's no error during reading.")

        elif self._reader is not req_reader:
            raise ValueError("Reader Mismatch.")

        if self._writer is not None:
            raise RuntimeError("A Writer has been created.")

        self._try_raise_write_exc()

        refined_initial, res_bytes = self._composer.compose_response(
            res_initial,
            req_initial=req_reader.initial if req_reader else None)

        self._transport.write(res_bytes)

        await self._protocol._flush()

        self._writer = streams.HttpResponseWriter(
            impl=self,
            res_initial=refined_initial,
            req_reader=self._reader)

        return self._writer

    async def flush_data(
        self, writer: "streams.BaseHttpStreamWriter", data: bytes,
            last_chunk: bool=False) -> None:
        if self._writer is not writer:
            raise ValueError("Writer Mismatch.")

        self._try_raise_write_exc()

        body_chunk = self._composer.compose_body(data, last_chunk=last_chunk)
        self._transport.write(body_chunk)

        await self._protocol._flush()

        if last_chunk:
            self._stream_write_finished = True
            self._maybe_finished()

    async def abort_request(
            self, req_stream: Optional["streams.HttpRequestReader"]) -> None:
        if req_stream is None:
            if self._read_exc is None:
                raise ValueError(
                    "You MUST provide request reader if there's "
                    "no error during reading.")

        elif req_stream is not self._reader:
            raise ValueError("Reader Mismatch.")

        self._set_exc(exceptions.HttpStreamAbortedError())

        self._close_conn()

    def data_received(self, data: Optional[bytes]=None) -> None:
        if data:
            self._buf.extend(data)

        if self._reader_fur.done():
            return

        if self._reader is None:
            if len(self._buf) == 0 and self._conn_closing.is_set():
                return

            req_initial = self._parser.parse_request()

            if req_initial is None:
                if len(self._buf) > self._protocol._INITIAL_BUFFER_LIMIT:
                    self._set_read_state(_ReadState.Paused)
                    self._set_read_exc(exceptions.IncomingInitialTooLarge())

                    # Read Finished.

                return

            self._reader = streams.HttpRequestReader(
                impl=self, req_initial=req_initial)
            self._reader_fur.set_result(self._reader)

            return

        while True:
            body_parts = self._parser.parse_body()

            if body_parts is None:
                self._reader._append_end()

                self._stream_read_finished = True
                self._maybe_finished()

                break  # Finished.

            elif len(body_parts) == 0:
                if len(self._buf) > self._protocol._STREAM_BUFFER_LIMIT:
                    self._set_read_state(_ReadState.Paused)
                    self._set_read_exc(exceptions.IncomingEntityTooLarge())

                break  # Not Finished.

            elif self._reader._append_data(body_parts):
                self._set_read_state(_ReadState.Paused)

    async def close(self) -> None:
        if len(self._buf) == 0 and (self._reader and self._writer) is None:
            self._close_conn()

        await super().close()

    def eof_received(self) -> None:
        super().eof_received()

        if not self._reader_fur.done():
            self._reader_fur.set_exception(
                exceptions.HttpConnectionClosingError)

    def connection_lost(self, exc: Optional[BaseException]=None) -> None:
        super().connection_lost(exc)

        if not self._reader_fur.done():
            self._reader_fur.set_exception(
                exceptions.HttpConnectionClosedError)


class H1ClientImpl(BaseH1Impl, BaseHttpClientImpl):
    def __init__(
        self, *, protocol: "protocols.BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        super().__init__(protocol=protocol, transport=transport)

        self._writer: Optional[streams.HttpRequestWriter] = None
        self._reader: Optional[streams.HttpResponseReader] = None

        self._reader_fur: "asyncio.Future[streams.HttpResponseReader]" = \
            asyncio.Future()

        self._read_finished = asyncio.Event()
        self._read_finished.set()

    def _set_read_exc(self, exc: Exception) -> None:
        if not self._reader_fur.done():
            self._reader_fur.set_exception(exc)

        if self._reader is not None:
            self._reader._append_exc(exc)

        super()._set_read_exc(exc)

    def _set_write_exc(self, exc: Exception) -> None:
        if self._writer is not None:
            self._writer._append_exc(exc)

        super()._set_write_exc(exc)

    def _maybe_finished(self) -> None:
        if not (self._stream_read_finished and self._stream_write_finished):
            return

        self._reader = None
        self._writer = None

        if self._conn_closing.is_set():
            self._close_conn()

        else:
            self._stream_read_finished = False
            self._stream_write_finished = False

            self._read_finished.set()

    def resume_reading(self, req_writer: "streams.HttpRequestWriter") -> None:
        if self._writer is not req_writer:
            raise ValueError("Writer Mismatch.")

        if self._read_state == _ReadState.Paused:
            self._try_raise_read_exc()
            self._set_read_state(_ReadState.Reading)

    async def write_request(
        self, req_initial: initials.HttpRequestInitial) -> \
            "streams.HttpRequestWriter":
        async with self._init_lock:
            self._try_raise_write_exc()

            await self._read_finished.wait()

            self._try_raise_write_exc()

            refined_initial, req_bytes = self._composer.compose_request(
                req_initial)

            self._transport.write(req_bytes)

            await self._protocol._flush()

            self._writer = streams.HttpRequestWriter(
                impl=self, req_initial=refined_initial)

            self._read_finished.clear()

            return self._writer

    async def flush_data(
        self, writer: "streams.BaseHttpStreamWriter", data: bytes,
            last_chunk: bool=False) -> None:
        if self._writer is not writer:
            raise ValueError("Writer Mismatch.")

        self._try_raise_write_exc()

        body_chunk = self._composer.compose_body(data, last_chunk=last_chunk)
        self._transport.write(body_chunk)

        await self._protocol._flush()

        if last_chunk:
            self._stream_write_finished = True
            self._maybe_finished()

    async def read_response(
        self, req_writer: "streams.HttpRequestWriter") -> \
            "streams.HttpResponseReader":
        if req_writer is not self._writer:
            raise ValueError("Writer Mismatch.")

        if self._reader is not None:
            raise ValueError("A reader has been created.")

        self._try_raise_read_exc()

        reader = await self._reader_fur
        self._reader_fur = asyncio.Future()

        self.data_received()

        return reader

    async def abort_request(
            self, req_stream: "streams.HttpRequestWriter") -> None:
        if req_stream is not self._writer:
            raise ValueError("Writer Mismatch.")

        self._set_exc(exceptions.HttpStreamAbortedError())

        self._close_conn()

    def data_received(self, data: Optional[bytes]=None) -> None:
        if data:
            self._buf.extend(data)

        if self._reader_fur.done():
            return

        if self._reader is None:
            assert self._writer is not None
            res_initial = self._parser.parse_response(
                self._writer.initial)

            if res_initial is None:
                if len(self._buf) > self._protocol._INITIAL_BUFFER_LIMIT:
                    self._set_read_state(_ReadState.Paused)
                    self._set_read_exc(exceptions.IncomingInitialTooLarge())

                    self._close_conn()

                    # Read Finished.

                return

            self._reader = streams.HttpResponseReader(
                impl=self, res_initial=res_initial,
                req_writer=self._writer)

            self._reader_fur.set_result(self._reader)

            return

        while True:
            body_parts = self._parser.parse_body()

            if body_parts is None:
                self._reader._append_end()

                self._stream_read_finished = True
                self._maybe_finished()

                break  # Finished.

            elif len(body_parts) == 0:
                if len(self._buf) > self._protocol._STREAM_BUFFER_LIMIT:
                    self._set_read_state(_ReadState.Paused)
                    self._set_read_exc(exceptions.IncomingEntityTooLarge())

                    self._close_conn()

                break  # Not Finished.

            elif self._reader._append_data(body_parts):
                self._set_read_state(_ReadState.Paused)

    async def close(self) -> None:
        if len(self._buf) == 0 and (self._reader and self._writer) is None:
            self._close_conn()

        await super().close()

    def eof_received(self) -> None:
        super().eof_received()

        if not self._reader_fur.done():
            self._reader_fur.set_exception(
                exceptions.HttpConnectionClosingError)

    def connection_lost(self, exc: Optional[BaseException]=None) -> None:
        super().connection_lost(exc)

        if not self._reader_fur.done():
            self._reader_fur.set_exception(
                exceptions.HttpConnectionClosedError)
