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
from . import h1parsers
from . import h1composers

import typing
import abc
import asyncio


if typing.TYPE_CHECKING:
    from . import constants
    from . import protocols

    import http

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class BaseH1StreamManager(
    readers.BaseHttpStreamReaderDelegate,
        writers.BaseHttpStreamWriterDelegate):
    def __init__(self, __impl: "BaseH1Impl", buf: bytearray) -> None:
        self._impl = __impl

        self._conn_exc: Optional[BaseException] = None

        self._buf = buf
        self._transport = self._impl._transport
        self._protocol = self._impl._protocol

        self._max_initial_size = self._protocol._INITIAL_BUFFER_LIMIT

        self._reader_ready = asyncio.Event()
        self._read_exc: Optional[BaseException] = None
        self._read_ended = False
        self._reader_returned = False

        self._pending_initial_bytes: Optional[bytes] = None

        self._writer_ready = asyncio.Event()
        self._write_finished = False

        self._aborted = False

        self._marked_as_last_stream = False

    @abc.abstractmethod
    def _maybe_cleanup(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def _data_arrived(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def _eof_arrived(self) -> None:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def _last_stream(self) -> Optional[bool]:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def _parser(self) -> h1parsers.BaseH1Parser:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def _composer(self) -> h1composers.BaseH1Composer:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def _reader(self) -> Optional[readers.BaseHttpStreamReader]:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def _writer(self) -> Optional[writers.BaseHttpStreamWriter]:
        raise NotImplementedError

    def _conn_lost(self, exc: Optional[BaseException]) -> None:
        if self._conn_exc is None:
            self._conn_exc = exc

        if self.finished():
            return

        self._eof_arrived()

        if not self._write_finished:
            self.abort()

    def _mark_as_last_stream(self) -> None:
        self._marked_as_last_stream = True

    def resume_reading(self) -> None:
        if self._read_ended:
            return

        self._transport.resume_reading()

    def pause_reading(self) -> None:
        if self._read_ended:
            return

        self._transport.pause_reading()

    async def flush_buf(self) -> None:
        if self._aborted:
            raise writers.HttpStreamWriteAbortedError from self._conn_exc

        if self._write_finished:
            return

        if self._pending_initial_bytes:
            data = self._pending_initial_bytes
            self._pending_initial_bytes = None

            self._transport.write(data)

        await self._protocol._flush()

    def finished(self) -> bool:
        if self._aborted:
            return True

        return self._read_ended and self._write_finished

    @abc.abstractmethod
    async def wait_finished(self) -> None:
        raise NotImplementedError

    def abort(self) -> None:
        self._aborted = True

        self._maybe_cleanup()


class BaseH1Impl(protocols.BaseHttpProtocolDelegate):
    def __init__(
        self, protocol: "protocols.BaseHttpProtocol",
            transport: asyncio.Transport) -> None:
        self._protocol = protocol
        self._transport = transport

        self._using_https = transport.get_extra_info("sslcontext") is not None

        self._buf = bytearray()

        self._init_lock = asyncio.Lock()
        self._init_finished = False

        self._wait_finished_lock = asyncio.Lock()

        self._closing = False
        self._conn_exc: Optional[BaseException] = None

        self._new_stream_mgr_fur: Optional["asyncio.Future[None]"] = None

    @property
    @abc.abstractmethod
    def _stream_mgr(self) -> BaseH1StreamManager:
        raise NotImplementedError

    def _set_closing(self) -> None:
        if self._closing:
            return

        self._closing = True

        if self._new_stream_mgr_fur and \
                not self._new_stream_mgr_fur.done():
            self._new_stream_mgr_fur.set_result(None)

    def data_received(self, data: bytes) -> None:
        if not data:
            return

        self._buf += data

        if not self._stream_mgr.finished():
            self._stream_mgr._data_arrived()

    def eof_received(self) -> None:
        if self._closing:
            return

        self._set_closing()

        if not self._stream_mgr.finished():
            self._stream_mgr._eof_arrived()

        else:
            self._transport.close()

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        if self._conn_exc is None:
            self._conn_exc = exc

        self._set_closing()

        if not self._stream_mgr.finished():
            self._stream_mgr._conn_lost(exc)

    def finished(self) -> bool:
        if self._closing:
            return self._stream_mgr.finished()

        if self._stream_mgr._last_stream is True:
            self._set_closing()

            return True

        return False

    async def wait_finished(self) -> None:
        async with self._wait_finished_lock:
            while True:
                await self._stream_mgr.wait_finished()

                if self.finished():
                    return

                if self._new_stream_mgr_fur is None or \
                        self._new_stream_mgr_fur.done():
                    self._new_stream_mgr_fur = asyncio.Future()

                await self._new_stream_mgr_fur

    def close(self) -> None:
        if not self._stream_mgr.finished():
            self._stream_mgr._mark_as_last_stream()

        else:
            self._transport.close()

    def abort(self) -> None:
        if not self._stream_mgr.finished():
            self._stream_mgr.abort()

        else:
            self._transport.close()


class H1ServerStreamManager(
    BaseH1StreamManager, readers.HttpRequestReaderDelegate,
        writers.HttpResponseWriterDelegate):
    def __init__(self, __impl: "H1ServerImpl", buf: bytearray) -> None:
        super().__init__(__impl, buf)

        self.__parser = h1parsers.H1RequestParser(
            self._buf, using_https=self._impl._using_https)
        self.__composer = h1composers.H1ResponseComposer(
            self._impl._using_https)

        self.__reader: Optional[readers.HttpRequestReader] = None
        self.__writer: Optional[writers.HttpResponseWriter] = None

        self._data_arrived()

    @property
    def _parser(self) -> h1parsers.H1RequestParser:
        return self.__parser

    @property
    def _composer(self) -> h1composers.H1ResponseComposer:
        return self.__composer

    @property
    def _reader(self) -> Optional[readers.HttpRequestReader]:
        return self.__reader

    @property
    def _writer(self) -> Optional[writers.HttpResponseWriter]:
        return self.__writer

    def _maybe_cleanup(self) -> None:
        if self._aborted:
            if not self._read_ended:
                if not self._read_exc:
                    self._read_exc = readers.HttpStreamReadAbortedError()

                if self._reader:
                    self._reader._append_end(self._read_exc)

                self._read_ended = True

            self._reader_ready.set()
            self._writer_ready.set()

            self._transport.close()

        elif not (self._read_ended and self._write_finished):
            return

        if self._last_stream:
            self._transport.close()

    def _data_arrived(self) -> None:
        if self._read_ended:
            return

        if self._aborted:
            return

        if self._reader is None:
            if not self._buf:
                return

            initial = self._parser.parse_request()

            if initial is None:
                if len(self._buf) > self._max_initial_size:
                    self.pause_reading()

                    self._read_exc = readers.HttpStreamInitialTooLargeError()
                    self._reader_ready.set()
                    self._read_ended = True

                    self._maybe_cleanup()

                return

            reader = readers.HttpRequestReader(self, initial=initial)

            self.__reader = reader
            self._reader_ready.set()

        else:
            reader = self._reader

        try:
            while True:
                data = self._parser.parse_body()

                if data is None:
                    reader._append_end(None)
                    self._read_ended = True

                    self._maybe_cleanup()

                    break

                if not data:
                    if len(self._buf) > self._max_initial_size:
                        self._read_exc = \
                            readers.HttpStreamReceivedDataMalformedError()
                        reader._append_end(exc=self._read_exc)
                        self._read_ended = True

                        self._maybe_cleanup()

                    break

                reader._append_data(data)

        except h1parsers.IncompletedHttpBody as e:
            self._read_exc = readers.HttpStreamReadAbortedError()
            self._read_exc.__cause__ = e
            reader._append_end(self._read_exc)
            self._read_ended = True

            self._maybe_cleanup()

    def _eof_arrived(self) -> None:
        if self._read_ended:
            return

        self._parser.buf_ended = True

        self._data_arrived()

    @property
    def _last_stream(self) -> Optional[bool]:
        if not self.finished():
            return None

        if self._marked_as_last_stream:
            return True

        if self._reader is None or self._writer is None:
            return True

        return self._writer.initial.headers[
            b"connection"].lower() != b"keep-alive"

    async def read_request(self) -> readers.HttpRequestReader:
        await self._reader_ready.wait()

        if self._reader is None:
            if self._read_exc:
                if self._conn_exc:
                    raise self._read_exc from self._conn_exc

                else:
                    raise self._read_exc

            if self._aborted:
                raise readers.HttpStreamReadAbortedError from self._conn_exc

            raise NotImplementedError("This is not gonna happen.")

        return self._reader

    def write_response(
        self, status_code: "http.HTTPStatus", *,
        version: "constants.HttpVersion",
        headers: Optional[_HeaderType]
            ) -> writers.HttpResponseWriter:
        if self._writer is not None:
            raise writers.HttpStreamWriteDuplicatedError(
                "You cannot write response twice.")

        if self._aborted:
            raise writers.HttpStreamWriteAbortedError from self._conn_exc

        initial, self._response_initial_bytes = \
            self._composer.compose_response(
                status_code=status_code, version=version, headers=headers,
                req_initial=self._reader.initial if self._reader else None)

        writer = writers.HttpResponseWriter(
            self, initial=initial, reader=self._reader)

        self.__writer = writer
        self._writer_ready.set()

        return writer

    def write_data(self, data: bytes, finished: bool=False) -> None:
        if self._aborted:
            raise writers.HttpStreamWriteAbortedError from self._conn_exc

        if self._write_finished:
            raise writers.HttpStreamWriteAfterFinishedError

        data = self._composer.compose_body(data, finished=finished)

        if self._pending_initial_bytes:
            data = self._pending_initial_bytes + data
            self._pending_initial_bytes = None

        self._transport.write(data)

        if finished:
            self._write_finished = True
            self._maybe_cleanup()

    async def wait_finished(self) -> None:
        await self._reader_ready.wait()

        if self._reader:
            await self._reader.wait_end()

        await self._writer_ready.wait()

        if self._writer:
            await self._writer.wait_finished()


class H1ServerImpl(BaseH1Impl, protocols.HttpServerProtocolDelegate):
    def __init__(
        self, protocol: "protocols.HttpServerProtocol",
            transport: asyncio.Transport) -> None:
        self.__stream_mgr = H1ServerStreamManager(self, self._buf)

        super().__init__(protocol, transport)

    @property
    def _stream_mgr(self) -> H1ServerStreamManager:
        return self.__stream_mgr

    async def read_request(self) -> "readers.HttpRequestReader":
        async with self._init_lock:
            if self._init_finished:
                await self._stream_mgr.wait_finished()

                if self.finished():
                    raise readers.HttpStreamReadFinishedError \
                        from self._conn_exc

                self.__stream_mgr = H1ServerStreamManager(self, self._buf)
                self._init_finished = False
                if self._new_stream_mgr_fur and \
                        not self._new_stream_mgr_fur.done():
                    self._new_stream_mgr_fur.set_result(None)

            reader = await self._stream_mgr.read_request()
            self._init_finished = True

            return reader


class H1ClientStreamManager(
    BaseH1StreamManager, writers.HttpRequestWriterDelegate,
        readers.HttpResponseReaderDelegate):
    def __init__(self, __impl: "H1ClientImpl", buf: bytearray) -> None:
        super().__init__(__impl, buf)

        self.__composer = h1composers.H1RequestComposer(
            self._impl._using_https)
        self.__parser = h1parsers.H1ResponseParser(
            self._buf, using_https=self._impl._using_https)

        self.__writer: Optional[writers.HttpRequestWriter] = None
        self.__reader: Optional[readers.HttpResponseReader] = None

        self._data_arrived()

    @property
    def _parser(self) -> h1parsers.H1ResponseParser:
        return self.__parser

    @property
    def _composer(self) -> h1composers.H1RequestComposer:
        return self.__composer

    @property
    def _reader(self) -> Optional[readers.HttpResponseReader]:
        return self.__reader

    @property
    def _writer(self) -> Optional[writers.HttpRequestWriter]:
        return self.__writer

    def _maybe_cleanup(self) -> None:
        if self._aborted:
            if not self._read_ended:
                if not self._read_exc:
                    self._read_exc = readers.HttpStreamReadAbortedError()

                if self._reader:
                    self._reader._append_end(self._read_exc)

                self._read_ended = True

            self._reader_ready.set()
            self._writer_ready.set()

            self._transport.close()

    def _data_arrived(self) -> None:
        if self._read_ended:
            return

        if self._aborted:
            return

        if self._reader is None:
            assert self._writer is not None

            if not self._buf:
                return

            initial = self._parser.parse_response(self._writer.initial)

            if initial is None:
                if len(self._buf) > self._max_initial_size:
                    self.pause_reading()

                    self._read_exc = readers.HttpStreamInitialTooLargeError()
                    self._reader_ready.set()
                    self._read_ended = True

                    self._maybe_cleanup()

                return

            reader = readers.HttpResponseReader(
                self, initial=initial, writer=self._writer)

            self.__reader = reader
            self._reader_ready.set()

        else:
            reader = self._reader

        try:
            while True:
                data = self._parser.parse_body()

                if data is None:
                    reader._append_end(None)
                    self._read_ended = True

                    self._maybe_cleanup()

                    break

                if not data:
                    if len(self._buf) > self._max_initial_size:
                        self._read_exc = \
                            readers.HttpStreamReceivedDataMalformedError()
                        reader._append_end(exc=self._read_exc)
                        self._read_ended = True

                        self._maybe_cleanup()

                    break

                reader._append_data(data)

        except h1parsers.IncompletedHttpBody as e:
            self._read_exc = readers.HttpStreamReadAbortedError()
            self._read_exc.__cause__ = e
            reader._append_end(self._read_exc)
            self._read_ended = True

            self._maybe_cleanup()

    def _eof_arrived(self) -> None:
        if self._read_ended:
            return

        self._parser.buf_ended = True

        self._data_arrived()

    @property
    def _last_stream(self) -> Optional[bool]:
        if not self.finished():
            return None

        if self._marked_as_last_stream:
            return True

        if self._reader is None or self._writer is None:
            return True

        return self._reader.initial.headers[
            b"connection"].lower() != b"keep-alive"

    def write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: bytes, authority: Optional[bytes],
        version: "constants.HttpVersion",
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> "writers.HttpRequestWriter":
        if self._writer is not None:
            raise writers.HttpStreamWriteDuplicatedError(
                "You cannot write response twice.")

        if self._aborted:
            raise writers.HttpStreamWriteAbortedError from self._conn_exc

        initial, self._request_initial_bytes = \
            self._composer.compose_request(
                method=method, uri=uri, authority=authority, version=version,
                scheme=scheme, headers=headers)

        writer = writers.HttpRequestWriter(
            self, initial=initial)

        self.__writer = writer
        self._writer_ready.set()

        return writer

    def write_data(self, data: bytes, finished: bool=False) -> None:
        if self._aborted:
            raise writers.HttpStreamWriteAbortedError from self._conn_exc

        if self._write_finished:
            raise writers.HttpStreamWriteAfterFinishedError

        data = self._composer.compose_body(data, finished=finished)

        if self._pending_initial_bytes:
            data = self._pending_initial_bytes + data
            self._pending_initial_bytes = None

        self._transport.write(data)

        if finished:
            self._write_finished = True
            self._maybe_cleanup()

    async def read_response(self) -> "readers.HttpResponseReader":
        await self._reader_ready.wait()

        if self._reader is None:
            if self._read_exc:
                if self._conn_exc:
                    raise self._read_exc from self._conn_exc

                else:
                    raise self._read_exc

            if self._aborted:
                raise readers.HttpStreamReadAbortedError from self._conn_exc

            raise NotImplementedError("This is not gonna happen.")

        return self._reader

    async def wait_finished(self) -> None:
        await self._writer_ready.wait()

        if self._writer:
            await self._writer.wait_finished()

        await self._reader_ready.wait()

        if self._reader:
            await self._reader.wait_end()


class H1ClientImpl(BaseH1Impl, protocols.HttpClientProtocolDelegate):
    def __init__(
        self, protocol: "protocols.HttpClientProtocol",
            transport: "asyncio.Transport") -> None:
        self.__stream_mgr = H1ClientStreamManager(self, self._buf)

        super().__init__(protocol, transport)

    @property
    def _stream_mgr(self) -> H1ClientStreamManager:
        return self.__stream_mgr

    async def write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: bytes, authority: Optional[bytes],
        version: "constants.HttpVersion",
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> "writers.HttpRequestWriter":
        async with self._init_lock:
            if self._init_finished:
                await self._stream_mgr.wait_finished()

                if self.finished():
                    raise writers.HttpStreamWriteAfterFinishedError \
                        from self._conn_exc

                self.__stream_mgr = H1ClientStreamManager(self, self._buf)
                self._init_finished = False
                if self._new_stream_mgr_fur and \
                        not self._new_stream_mgr_fur.done():
                    self._new_stream_mgr_fur.set_result(None)

            writer = self._stream_mgr.write_request(
                method, uri=uri, authority=authority, version=version,
                scheme=scheme, headers=headers)
            self._init_finished = True

            return writer
