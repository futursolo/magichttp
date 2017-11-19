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
    @abc.abstractmethod
    def __init__(self, __impl: "BaseH1Impl", *, buf: bytearray) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def resume_reading(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def pause_reading(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def _data_arrived(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def _eof_arrived(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def write_data(self, data: bytes, finished: bool=False) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def flush_buf(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def finished(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    async def wait_finished(self) -> None:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def _last_stream(self) -> Optional[bool]:
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
    BaseH1StreamManager, readers.HttpRequestReaderDelegate,
        writers.HttpResponseWriterDelegate):
    def __init__(self, __impl: "H1ServerImpl", buf: bytearray) -> None:
        self._impl = __impl

        self._conn_exc: Optional[BaseException] = None

        self._buf = buf
        self._transport = self._impl._transport
        self._protocol = self._impl._protocol

        self._max_initial_size = self._protocol._INITIAL_BUFFER_LIMIT

        self._parser = h1parsers.H1RequestParser(
            self._buf, using_https=self._impl._using_https)
        self._composer = h1composers.H1ResponseComposer(
            self._impl._using_https)

        self._reader: Optional[readers.HttpRequestReader] = None
        self._reader_ready = asyncio.Event()
        self._read_exc: Optional[BaseException] = None
        self._read_ended = False
        self._reader_returned = False

        self._response_initial_bytes: Optional[bytes] = None

        self._writer: Optional[writers.HttpResponseWriter] = None
        self._writer_ready = asyncio.Event()
        self._write_finished = False

        self._aborted = False

        self._marked_as_last_stream = False

        self._data_arrived()

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

    def _data_arrived(self, *, buf_ended: bool=False) -> None:
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

            self._reader = readers.HttpRequestReader(self, initial=initial)
            self._reader_ready.set()

        try:
            while True:
                data = self._parser.parse_body()

                if data is None:
                    self._reader._append_end(None)
                    self._read_ended = True

                    self._maybe_cleanup()

                    break

                if not data:
                    if len(self._buf) > self._max_initial_size:
                        self._read_exc = \
                            readers.HttpStreamReceivedDataMalformedError()
                        self._reader._append_end(exc=self._read_exc)
                        self._read_ended = True

                        self._maybe_cleanup()

                    break

                self._reader._append_data(data)

        except h1parsers.IncompletedHttpBody as e:
            self._read_exc = readers.HttpStreamReadAbortedError()
            self._read_exc.__cause__ = e
            self._reader._append_end(self._read_exc)
            self._read_ended = True

            self._maybe_cleanup()

    def _eof_arrived(self) -> None:
        if self._read_ended:
            return

        self._parser.buf_ended = True

        self._data_arrived()

    def _conn_lost(self, exc: Optional[BaseException]) -> None:
        """
        Prevent Any Reading or Writing after this.
        """
        if self._conn_exc is None:
            self._conn_exc = exc

        if self.finished():
            return

        self._eof_arrived()

        if not self._write_finished:
            self.abort()

    def _mark_as_last_stream(self) -> None:
        self._marked_as_last_stream = True

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

    def resume_reading(self) -> None:
        if self._read_ended:
            return

        self._transport.resume_reading()

    def pause_reading(self) -> None:
        if self._read_ended:
            return

        self._transport.pause_reading()

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
        self, status_code: http.HTTPStatus, *,
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

        self._writer = writers.HttpResponseWriter(
            self, initial=initial, reader=self._reader)

        self._writer_ready.set()
        return self._writer

    def write_data(self, data: bytes, finished: bool=False) -> None:
        if self._aborted:
            raise writers.HttpStreamWriteAbortedError from self._conn_exc

        if self._write_finished:
            raise writers.HttpStreamWriteAfterFinishedError

        data = self._composer.compose_body(data, finished=finished)

        if self._response_initial_bytes:
            data = self._response_initial_bytes + data
            self._response_initial_bytes = None

        self._transport.write(data)

        if finished:
            self._write_finished = True
            self._maybe_cleanup()

    async def flush_buf(self) -> None:
        if self._aborted:
            raise writers.HttpStreamWriteAbortedError from self._conn_exc

        if self._write_finished:
            return

        if self._response_initial_bytes:
            data = self._response_initial_bytes
            self._response_initial_bytes = None

            self._transport.write(data)

        await self._protocol._flush()

    def finished(self) -> bool:
        if self._aborted:
            return True

        return self._read_ended and self._write_finished

    async def wait_finished(self) -> None:
        await self._reader_ready.wait()

        if self._reader:
            await self._reader.wait_end()

        await self._writer_ready.wait()

        if self._writer:
            await self._writer.wait_finished()

    def abort(self) -> None:
        self._aborted = True

        self._maybe_cleanup()


class H1ServerImpl(BaseH1Impl, protocols.HttpServerProtocolDelegate):
    def __init__(
        self, protocol: "protocols.HttpServerProtocol",
            transport: "asyncio.Transport") -> None:
        self._protocol = protocol
        self._transport = transport

        self._using_https = transport.get_extra_info("sslcontext") is not None

        self._buf = bytearray()

        self._stream_mgr = H1ServerStreamManager(self, self._buf)
        self._new_stream_mgr_fur: Optional["asyncio.Future[None]"] = None
        self._request_read = False

        self._read_lock = asyncio.Lock()
        self._wait_finished_lock = asyncio.Lock()

        self._closing = False
        self._conn_exc: Optional[BaseException] = None

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

    async def read_request(self) -> "readers.HttpRequestReader":
        async with self._read_lock:
            if self._request_read:
                await self._stream_mgr.wait_finished()

                if self.finished():
                    raise readers.HttpStreamReadFinishedError \
                        from self._conn_exc

                self._stream_mgr = H1ServerStreamManager(self, self._buf)
                self._request_read = False
                if self._new_stream_mgr_fur and \
                        not self._new_stream_mgr_fur.done():
                    self._new_stream_mgr_fur.set_result(None)
                # In case the following await got cancelled.

            request = await self._stream_mgr.read_request()
            self._request_read = True

            return request


class H1ClientStreamManager(
    BaseH1StreamManager, writers.HttpRequestWriterDelegate,
        readers.HttpResponseReaderDelegate):
    @abc.abstractmethod
    def write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: bytes, authority: Optional[bytes],
        version: "constants.HttpVersion",
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> "writers.HttpRequestWriter":
        raise NotImplementedError

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

    @abc.abstractmethod
    def write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: bytes, authority: Optional[bytes],
        version: "constants.HttpVersion",
        scheme: Optional[bytes],
            headers: Optional[_HeaderType]) -> "writers.HttpRequestWriter":
        raise NotImplementedError
