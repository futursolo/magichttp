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

from typing import Optional, Union, Mapping, Tuple, Iterable

from . import readers
from . import writers
from . import protocols
from . import h1parsers
from . import h1composers

import typing
import abc
import asyncio


if typing.TYPE_CHECKING:  # pragma: no cover
    from . import constants  # noqa: F401

    import http  # noqa: F401

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class BaseH1StreamManager(
    readers.BaseHttpStreamReaderDelegate,
        writers.BaseHttpStreamWriterDelegate):
    def __init__(
        self, __impl: "BaseH1Impl", buf: bytearray,
            max_initial_size: int) -> None:
        self._impl = __impl

        self._buf = buf
        self._protocol = self._impl.protocol
        self._transport = self._protocol.transport

        self._max_initial_size = max_initial_size

        self._reader_ready = asyncio.Event()
        self._read_exc: Optional[readers.BaseReadException] = None
        self._read_ended = False

        self._writer_ready = asyncio.Event()
        self._write_chunked_body: Optional[bool] = None
        self._write_exc: Optional[writers.BaseWriteException] = None
        self._write_finished = False

        self._conn_exc: Optional[BaseException] = None

        self._marked_as_last_stream = False

    def _end_reading(self, exc: Optional[readers.BaseReadException]) -> None:
        if self._read_ended:
            return

        if self._reader:
            self._reader._append_end(exc)

        self._read_exc = exc

        self._reader_ready.set()
        self._read_ended = True

        self._maybe_cleanup()

    def _tear_writing(self, exc: Optional[writers.BaseWriteException]) -> None:
        if self._write_finished:
            return

        self._write_exc = exc

        self._writer_ready.set()
        self._write_finished = True

        self._maybe_cleanup(force_close=True)

    def _maybe_cleanup(self, *, force_close: bool=False) -> None:
        if force_close:
            if not self._read_ended:
                read_exc = readers.ReadAbortedError()

                if self._conn_exc:
                    read_exc.__cause__ = self._conn_exc

                self._end_reading(read_exc)

            if not self._write_finished:
                write_exc = writers.WriteAbortedError()

                if self._conn_exc:
                    write_exc.__cause__ = self._conn_exc

                self._tear_writing(write_exc)

            self._transport.close()

            return

        if not (self._read_ended and self._write_finished):
            return

        if self._last_stream:
            self._transport.close()

    @property
    @abc.abstractmethod
    def _reader(self) -> Optional[readers.BaseHttpStreamReader]:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def _writer(self) -> Optional[writers.BaseHttpStreamWriter]:
        raise NotImplementedError

    @abc.abstractmethod
    def _data_arrived(self) -> None:
        raise NotImplementedError

    def _eof_arrived(self) -> None:
        if self._read_ended:
            return

        # self._parser.buf_ended = True

        self._data_arrived()

        if (self._reader and self._writer) is None and not self._buf:
            self._tear_writing(None)

        else:
            self.abort()

    def _conn_lost(self, exc: Optional[BaseException]) -> None:
        if self._conn_exc is None:
            self._conn_exc = exc

        self._eof_arrived()

        if not self.finished():
            self.abort()

    @property
    @abc.abstractmethod
    def _last_stream(self) -> Optional[bool]:
        raise NotImplementedError

    def _mark_as_last_stream(self) -> None:
        self._marked_as_last_stream = True

        if (self._reader and self._writer) is None:
            self._end_reading(None)
            self._tear_writing(None)

    def resume_reading(self) -> None:
        if self._read_ended:
            return

        self._impl.resume_reading()

    def pause_reading(self) -> None:
        if self._read_ended:
            return

        self._impl.pause_reading()

    def write_data(self, data: bytes, finished: bool=False) -> None:
        assert self._write_chunked_body is not None, \
            "Please write initials before their body."
        if self._write_finished:
            if self._write_exc:
                raise self._write_exc

            raise writers.WriteAfterFinishedError

        if self._write_chunked_body:
            data = h1composers.compose_chunked_body(data, finished=finished)

        try:
            self._transport.write(data)

        except Exception as e:
            exc = writers.WriteAbortedError()
            exc.__cause__ = e
            self._tear_writing(exc)

            raise exc

        if finished:
            self._write_finished = True

            self._maybe_cleanup()

    async def flush_buf(self) -> None:
        if self._write_finished:
            if self._write_exc:
                raise self._write_exc

            return

        await self._protocol._flush()

    async def wait_finished(self) -> None:
        await self._reader_ready.wait()

        if self._reader:
            await self._reader.wait_end()

        await self._writer_ready.wait()

        if self._writer:
            await self._writer.wait_finished()

    def finished(self) -> bool:
        return self._read_ended and self._write_finished

    def abort(self) -> None:
        self._maybe_cleanup(force_close=True)


class BaseH1Impl(protocols.BaseHttpProtocolDelegate):
    def __init__(
        self, protocol: protocols.BaseHttpProtocol,
            max_initial_size: int) -> None:
        self._protocol = protocol
        self._transport = self._protocol.transport
        self._reading_paused = False

        self._max_initial_size = max_initial_size

        self._buf = bytearray()

        self._init_lock = asyncio.Lock()
        self._init_finished = False

        self._wait_finished_lock = asyncio.Lock()

        self._closing = False
        self._conn_exc: Optional[BaseException] = None

        self._new_stream_mgr_fur: Optional["asyncio.Future[None]"] = None

    @property
    def protocol(self) -> protocols.BaseHttpProtocol:
        return self._protocol

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

    def pause_reading(self) -> None:
        if self._reading_paused:
            return

        if self._transport.is_closing():
            return

        self._transport.pause_reading()
        self._reading_paused = True

    def resume_reading(self) -> None:
        if not self._reading_paused:
            return

        self._transport.resume_reading()
        self._reading_paused = False

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
    def __init__(
        self, __impl: "H1ServerImpl", buf: bytearray,
            max_initial_size: int) -> None:
        super().__init__(__impl, buf, max_initial_size)

        self.__reader: Optional[readers.HttpRequestReader] = None
        self.__writer: Optional[writers.HttpResponseWriter] = None

        self._data_arrived()

    @property
    def _reader(self) -> Optional[readers.HttpRequestReader]:
        return self.__reader

    @property
    def _writer(self) -> Optional[writers.HttpResponseWriter]:
        return self.__writer

    def _data_arrived(self) -> None:
        """if self._read_ended:
            return

        exc: readers.BaseReadException
        try:
            if self._reader is None:
                if not self._buf:
                    # if self._parser.buf_ended:
                        # self._end_reading(None)

                    return

                # initial = self._parser.parse_request()

                # if initial is None:
                    # if len(self._buf) > self._max_initial_size:
                        # self.pause_reading()

                        # exc = readers.EntityTooLargeError()
                        # self._end_reading(exc)

                    # return

                # reader = readers.HttpRequestReader(self, initial=initial)

                # self.__reader = reader
                # self._reader_ready.set()

            else:
                # reader = self._reader

            while True:
                # data = self._parser.parse_body()

                if data is None:
                    self._end_reading(None)

                    break

                if not data:
                    if len(self._buf) > self._max_initial_size:
                        exc = readers.ReceivedDataMalformedError()
                        self._end_reading(exc)

                    break

                reader._append_data(data)

        except h1parsers.UnparsableHttpMessage as e:
            exc = readers.ReceivedDataMalformedError()
            exc.__cause__ = e

            self._end_reading(exc)

        except h1parsers.IncompleteHttpMessage as e:
            if self._conn_exc:
                e.__cause__ = self._conn_exc

            exc = readers.ReadAbortedError()
            exc.__cause__ = e

            self._end_reading(exc)"""

    @property
    def _last_stream(self) -> Optional[bool]:
        if not self.finished():
            return None

        if self._marked_as_last_stream:
            return True

        if self._reader is None or self._writer is None:
            return True

        if (self._read_exc or self._write_exc) is not None:
            return True

        if self._writer.initial.status_code >= 400:
            return True

        remote_conn_header = self._reader.initial.headers.get(
            b"connection", b"").lower()

        local_conn_header = self._writer.initial.headers.get(
            b"connection", b"").lower()

        if remote_conn_header == local_conn_header == b"keep-alive":
            return False

        else:
            return True

    async def read_request(self) -> readers.HttpRequestReader:
        await self._reader_ready.wait()

        if self._reader is None:
            if self._read_exc:
                try:
                    raise self._read_exc

                except readers.EntityTooLargeError as e:
                    raise readers.RequestInitialTooLargeError(self) from e

                except readers.ReceivedDataMalformedError as e:
                    raise readers.RequestInitialMalformedError(self) from e

            raise readers.ReadFinishedError

        return self._reader

    def write_response(
        self, status_code: "http.HTTPStatus", *,
        headers: Optional[_HeaderType]
            ) -> writers.HttpResponseWriter:
        if self._writer is not None:
            raise RuntimeError("You cannot write response twice.")

        if self._write_exc:
            raise self._write_exc

        initial, initial_bytes = \
            h1composers.compose_response_initial(
                status_code=status_code, headers=headers,
                req_initial=self._reader.initial if self._reader else None)

        try:
            if b"transfer-encoding" not in initial.headers.keys():
                self._write_chunked_body = False

            else:
                self._write_chunked_body = h1parsers.is_chunked_body(
                    initial.headers[b"transfer-encoding"])

            self._transport.write(initial_bytes)

        except Exception as e:
            exc = writers.WriteAbortedError()
            exc.__cause__ = e
            self._tear_writing(exc)

            raise exc

        writer = writers.HttpResponseWriter(
            self, initial=initial, reader=self._reader)

        self.__writer = writer
        self._writer_ready.set()

        return writer


class H1ServerImpl(BaseH1Impl, protocols.HttpServerProtocolDelegate):
    def __init__(
        self, protocol: protocols.HttpServerProtocol,
            max_initial_size: int) -> None:
        super().__init__(protocol, max_initial_size)

        self.__protocol = protocol

        self.__stream_mgr = H1ServerStreamManager(
            self, self._buf, max_initial_size)

    @property
    def _stream_mgr(self) -> H1ServerStreamManager:
        return self.__stream_mgr

    async def read_request(self) -> readers.HttpRequestReader:
        async with self._init_lock:
            if self._init_finished:
                await self._stream_mgr.wait_finished()

                if self.finished():
                    raise readers.ReadFinishedError from self._conn_exc

                self.resume_reading()

                self.__stream_mgr = H1ServerStreamManager(
                    self, self._buf, self._max_initial_size)
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
    def __init__(
        self, __impl: "H1ClientImpl", buf: bytearray,
        max_initial_size: int,
            http_version: "constants.HttpVersion") -> None:
        super().__init__(__impl, buf, max_initial_size)

        self._http_version = http_version

        self.__writer: Optional[writers.HttpRequestWriter] = None
        self.__reader: Optional[readers.HttpResponseReader] = None

    @property
    def _reader(self) -> Optional[readers.HttpResponseReader]:
        return self.__reader

    @property
    def _writer(self) -> Optional[writers.HttpRequestWriter]:
        return self.__writer

    def _data_arrived(self) -> None:
        """if self._read_ended:
            return

        if self._writer is None:
            if self._parser.buf_ended:
                if self._buf:
                    self._end_reading(readers.ReadAbortedError())

                else:
                    self._end_reading(readers.ReadFinishedError())

            return

        exc: readers.BaseReadException
        try:
            if self._reader is None:
                initial = self._parser.parse_response(self._writer.initial)

                if initial is None:
                    if len(self._buf) > self._max_initial_size:
                        self.pause_reading()

                        exc = readers.EntityTooLargeError()
                        self._end_reading(exc)

                    return

                reader = readers.HttpResponseReader(
                    self, initial=initial, writer=self._writer)

                self.__reader = reader
                self._reader_ready.set()

            else:
                reader = self._reader

            while True:
                data = self._parser.parse_body()

                if data is None:
                    self._end_reading(None)

                    break

                if not data:
                    if len(self._buf) > self._max_initial_size:
                        exc = readers.ReceivedDataMalformedError()
                        self._end_reading(exc)

                    break

                reader._append_data(data)

        except h1parsers.UnparsableHttpMessage as e:
            exc = readers.ReceivedDataMalformedError()
            exc.__cause__ = e

            self._end_reading(exc)

        except h1parsers.IncompleteHttpMessage as e:
            if self._conn_exc:
                e.__cause__ = self._conn_exc

            exc = readers.ReadAbortedError()
            exc.__cause__ = e

            self._end_reading(exc)"""

    @property
    def _last_stream(self) -> Optional[bool]:
        if not self.finished():
            return None

        if self._marked_as_last_stream:
            return True

        if self._reader is None or self._writer is None:
            return True

        if (self._read_exc or self._write_exc) is not None:
            return True

        if self._reader.initial.status_code >= 400:
            return True

        remote_conn_header = self._reader.initial.headers.get(
            b"connection", b"").lower()

        local_conn_header = self._writer.initial.headers.get(
            b"connection", b"").lower()

        if remote_conn_header == local_conn_header == b"keep-alive":
            return False

        else:
            return True

    def write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: bytes, authority: Optional[bytes],
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> writers.HttpRequestWriter:
        if self._writer is not None:
            raise RuntimeError("You cannot write response twice.")

        if self._write_exc:
            raise self._write_exc

        initial, initial_bytes = \
            h1composers.compose_request_initial(
                method=method, uri=uri, authority=authority,
                version=self._http_version,
                scheme=scheme, headers=headers)

        try:
            if b"transfer-encoding" not in initial.headers.keys():
                self._write_chunked_body = False

            else:
                self._write_chunked_body = h1parsers.is_chunked_body(
                    initial.headers[b"transfer-encoding"])

            self._transport.write(initial_bytes)

        except Exception as e:
            exc = writers.WriteAbortedError()
            exc.__cause__ = e
            self._tear_writing(exc)

            raise exc

        writer = writers.HttpRequestWriter(
            self, initial=initial)

        self.__writer = writer
        self._writer_ready.set()

        self._data_arrived()

        return writer

    async def read_response(self) -> readers.HttpResponseReader:
        await self._reader_ready.wait()

        if self._reader is None:
            if self._read_exc:
                raise self._read_exc

            raise readers.ReadFinishedError

        return self._reader


class H1ClientImpl(BaseH1Impl, protocols.HttpClientProtocolDelegate):
    def __init__(
        self, protocol: protocols.HttpClientProtocol,
        max_initial_size: int,
            http_version: "constants.HttpVersion") -> None:
        super().__init__(protocol, max_initial_size)

        self.__protocol = protocol

        self._http_version = http_version

        self.__stream_mgr = H1ClientStreamManager(
            self, self._buf, max_initial_size, http_version)

    @property
    def _stream_mgr(self) -> H1ClientStreamManager:
        return self.__stream_mgr

    async def write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: bytes, authority: Optional[bytes],
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> writers.HttpRequestWriter:
        async with self._init_lock:
            if self._init_finished:
                await self._stream_mgr.wait_finished()

                if self.finished():
                    raise writers.WriteAfterFinishedError from self._conn_exc

                self.__stream_mgr = H1ClientStreamManager(
                    self, self._buf, self._max_initial_size,
                    self._http_version)
                self._init_finished = False
                if self._new_stream_mgr_fur and \
                        not self._new_stream_mgr_fur.done():
                    self._new_stream_mgr_fur.set_result(None)

            writer = self._stream_mgr.write_request(
                method, uri=uri, authority=authority, scheme=scheme,
                headers=headers)
            self._init_finished = True

            self.resume_reading()

            return writer
