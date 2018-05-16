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

from typing import Generic, TypeVar, Optional, Union, Mapping, Iterable, Tuple

from . import parsers
from . import composers

from .. import readers
from .. import writers
from .. import constants

import asyncio
import typing
import abc
import contextlib

if typing.TYPE_CHECKING:
    from . import impls  # noqa: F401

_T = TypeVar("_T")

_HeaderType = Union[
    Mapping[str, str],
    Iterable[Tuple[str, str]]]

_LAST_CHUNK = -1


class _ReaderFuture(asyncio.Future, Generic[_T]):
    __slots__ = ()

    def set_exception(  # type: ignore
            self, __exc: readers.BaseReadException) -> None:
        super().set_exception(__exc)

    def exception(self) -> Optional[readers.BaseReadException]:  # type: ignore
        return super().exception()  # type: ignore

    def cancel(self) -> bool:  # pragma: no cover
        raise NotImplementedError("You cannot cancel this future.")

    def result(self) -> _T:
        return super().result()  # type: ignore

    async def safe_await(self) -> _T:
        return await asyncio.shield(self)


class BaseH1StreamManager(
    readers.BaseHttpStreamReaderDelegate,
        writers.BaseHttpStreamWriterDelegate):
    def __init__(
        self, __impl: "impls.BaseH1Impl", buf: bytearray,
            max_initial_size: int) -> None:
        self._impl = __impl
        self._buf = buf
        self._protocol = self._impl._protocol
        self._transport = self._protocol.transport

        self._max_initial_size = max_initial_size

        self._body_len: Optional[int] = None
        self._current_chunk_len: Optional[int] = None
        self._current_chunk_crlf_dropped = True
        self._read_exc: Optional[readers.BaseReadException] = None

        self._writer_ready = asyncio.Event()
        self._write_chunked_body: Optional[bool] = None
        self._write_finished = False
        self._write_exc: Optional[writers.BaseWriteException] = None

        self._last_stream: Optional[bool] = None

    def pause_reading(self) -> None:
        if self._finished():
            return

        self._impl._pause_reading()

    def resume_reading(self) -> None:
        if self._finished():
            return

        self._impl._resume_reading()

    @property
    @abc.abstractmethod
    def _reader_fur(self) -> _ReaderFuture[
            readers.BaseHttpStreamReader]:  # pragma: no cover
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def _writer(self) -> Optional[
            writers.BaseHttpStreamWriter]:  # pragma: no cover
        raise NotImplementedError

    @abc.abstractmethod
    def _try_parse_initial(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def _try_parse_chunked_body(self) -> None:
        reader = self._reader_fur.result()

        while True:
            if self._current_chunk_len is None or \
                    self._current_chunk_len == _LAST_CHUNK:
                if self._current_chunk_crlf_dropped is False:
                    if len(self._buf) < 2:
                        return

                    del self._buf[:2]

                    self._current_chunk_crlf_dropped = True

                    if self._current_chunk_len == _LAST_CHUNK:
                        reader._append_end(None)

                        self._maybe_cleanup()

                        return

                self._current_chunk_len = parsers.parse_chunk_length(
                    self._buf)

                if self._current_chunk_len is None:
                    if len(self._buf) > self._max_initial_size:
                        self._set_read_exception(readers.EntityTooLargeError(
                            "Chunk size cannot be found "
                            "before the initial size has been reached,"))

                    return

                self._current_chunk_crlf_dropped = False

                if self._current_chunk_len == 0:
                    self._current_chunk_len = _LAST_CHUNK

                    continue

            data = self._buf[:self._current_chunk_len]
            del self._buf[:self._current_chunk_len]

            self._current_chunk_len -= len(data)

            reader._append_data(data)

            if self._current_chunk_len > 0:
                return

            self._current_chunk_len = None

    def _try_parse_body(self) -> None:
        assert self._body_len is not None
        reader = self._reader_fur.result()

        if self._body_len == parsers.BODY_IS_ENDLESS:
            reader._append_data(self._buf)
            self._buf.clear()

            return

        if self._body_len == parsers.BODY_IS_CHUNKED:
            self._try_parse_chunked_body()

            return

        data = self._buf[:self._body_len]
        del self._buf[:self._body_len]

        self._body_len -= len(data)

        reader._append_data(data)

        if self._body_len == 0:
            reader._append_end(None)

            self._maybe_cleanup()

    def _data_appended(self) -> None:
        if self._read_finished():
            return

        try:
            if not self._reader_fur.done():
                self._try_parse_initial()

            if self._reader_fur.done() and \
                    self._reader_fur.exception() is None:
                self._try_parse_body()

        except parsers.UnparsableHttpMessage as e:
            exc = readers.ReceivedDataMalformedError()
            exc.__cause__ = e

            self._set_read_exception(exc)

    def _eof_received(self) -> None:
        if self._read_finished():
            return

        if self._body_len == parsers.BODY_IS_ENDLESS:
            reader = self._reader_fur.result()
            reader._append_end(None)

            self._maybe_cleanup()

            return

        self._set_read_exception(readers.ReadAbortedError(
            "Eof received before the end is found."))

    def _read_finished(self) -> bool:
        if not self._reader_fur.done():
            return False

        if self._reader_fur.exception() is not None:
            return True

        return self._reader_fur.result().end_appended()

    def _finished(self) -> bool:
        return self._read_finished() and self._write_finished

    async def _wait_finished(self) -> None:
        with contextlib.suppress(readers.BaseReadException):
            reader = await self._reader_fur.safe_await()
            await reader.wait_end()

        await self._writer_ready.wait()

        if self._writer:
            await self._writer.wait_finished()

    @abc.abstractmethod
    def _is_last_stream(self) -> Optional[bool]:  # pragma: no cover
        raise NotImplementedError

    def _mark_as_last_stream(self) -> None:
        self._last_stream = True

    def write_data(self, data: bytes, finished: bool=False) -> None:
        if self._write_finished:
            if self._write_exc:
                raise self._write_exc

            raise writers.WriteAfterFinishedError

        if self._write_chunked_body is None:
            raise RuntimeError(
                "Please write the initial before writing its body.")

        if self._write_chunked_body:
            data = composers.compose_chunked_body(data, finished=finished)

        try:
            self._transport.write(data)

        except Exception as e:
            exc = writers.WriteAbortedError()
            exc.__cause__ = e

            self._set_write_exception(exc)

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

    def _maybe_cleanup(self) -> None:
        if self._is_last_stream() is True:
            self._transport.close()

    def abort(self) -> None:
        if self._finished():
            return

        self._impl.abort()

    def _set_read_exception(self, exc: readers.BaseReadException) -> None:
        if self._read_finished():
            return

        self._read_exc = exc

        if not self._reader_fur.done():
            self._reader_fur.set_exception(exc)

        else:
            self._reader_fur.result()._append_end(exc)

        self._maybe_cleanup()

    def _set_write_exception(self, exc: writers.BaseWriteException) -> None:
        if self._write_finished:
            return

        self._write_exc = exc

        self._writer_ready.set()
        self._write_finished = True

        self._maybe_cleanup()

    def _set_abort_error(self, __cause: Optional[BaseException]) -> None:
        if self._finished():
            return

        if __cause:
            read_exc = readers.ReadAbortedError(
                "Read aborted due to socket error.")
            read_exc.__cause__ = __cause

            write_exc = writers.WriteAbortedError(
                "Write aborted due to socket error.")
            write_exc.__cause__ = __cause

        else:
            read_exc = readers.ReadAbortedError("Read aborted by user.")
            write_exc = writers.WriteAbortedError("Write aborted by user.")

        self._set_read_exception(read_exc)
        self._set_write_exception(write_exc)

    def _connection_lost(self, exc: Optional[BaseException]) -> None:
        if self._finished():
            return

        if exc:
            self._set_abort_error(exc)

            return

        self._eof_received()
        self._set_write_exception(
            writers.WriteAbortedError("Connnection closed."))


class H1ClientStreamManager(
    BaseH1StreamManager, writers.HttpRequestWriterDelegate,
        readers.HttpResponseReaderDelegate):
    def __init__(
        self, __impl: "impls.H1ClientImpl", buf: bytearray,
        max_initial_size: int,
            http_version: "constants.HttpVersion") -> None:
        self._http_version = http_version

        self.__reader_fur: _ReaderFuture[readers.HttpResponseReader] = \
            _ReaderFuture()

        self.__writer: Optional[writers.HttpRequestWriter] = None

        super().__init__(__impl, buf, max_initial_size)

    @property
    def _reader_fur(  # type: ignore
            self) -> _ReaderFuture[readers.HttpResponseReader]:
        return self.__reader_fur

    @property
    def _writer(self) -> Optional[writers.HttpRequestWriter]:
        return self.__writer

    def _try_parse_initial(self) -> None:
        if self._writer is None:
            return

        initial = parsers.parse_response_initial(
            self._buf, self._writer.initial)

        if initial is None:
            if len(self._buf) > self._max_initial_size:
                self.pause_reading()

                exc = readers.EntityTooLargeError()
                self._set_read_exception(exc)

            return

        self._body_len = parsers.discover_response_body_length(
            initial, req_initial=self._writer.initial)

        reader = readers.HttpResponseReader(
            self, initial=initial, writer=self._writer)
        self._reader_fur.set_result(reader)

    def _write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: str, authority: Optional[str],
        scheme: Optional[str],
            headers: Optional[_HeaderType]) -> writers.HttpRequestWriter:
        if self._writer is not None:
            raise RuntimeError("You cannot write request twice.")

        if self._write_exc:
            raise self._write_exc

        initial, initial_bytes = \
            composers.compose_request_initial(
                method=method, uri=uri, authority=authority,
                version=self._http_version,
                scheme=scheme, headers=headers)

        try:
            if "transfer-encoding" not in initial.headers.keys():
                self._write_chunked_body = False

            else:
                self._write_chunked_body = parsers.is_chunked_body(
                    initial.headers["transfer-encoding"])

            self._transport.write(initial_bytes)

        except Exception as e:
            exc = writers.WriteAbortedError()
            exc.__cause__ = e
            self._set_write_exception(exc)

            raise exc

        writer = writers.HttpRequestWriter(
            self, initial=initial)

        self.__writer = writer
        self._writer_ready.set()

        self._data_appended()

        return writer

    async def read_response(self) -> "readers.HttpResponseReader":
        return await self._reader_fur.safe_await()

    def _is_last_stream(self) -> Optional[bool]:
        if not self._finished():
            return None

        if self._last_stream is None:
            if self._reader_fur.exception() is not None or \
                    self._read_exc is not None:
                self._last_stream = True

            elif self._writer is None or self._write_exc is not None:
                self._last_stream = True

            else:
                reader = self._reader_fur.result()

                if reader.initial.status_code >= 400:
                    self._last_stream = True

                elif self._body_len == parsers.BODY_IS_ENDLESS:
                    self._last_stream = True

                else:
                    remote_conn_header = reader.initial.headers.get(
                        "connection", "").lower()

                    local_conn_header = self._writer.initial.headers.get(
                        "connection", "").lower()

                    if reader.initial.version == constants.HttpVersion.V1_1:
                        if "close" not in (
                                remote_conn_header, local_conn_header):
                            self._last_stream = False

                        else:
                            self._last_stream = True

                    else:
                        if "keep-alive" not in (
                                remote_conn_header, local_conn_header):
                            self._last_stream = False

                        else:
                            self._last_stream = True

        return self._last_stream


class H1ServerStreamManager(
    BaseH1StreamManager, readers.HttpRequestReaderDelegate,
        writers.HttpResponseWriterDelegate):
    def __init__(
        self, __impl: "impls.H1ServerImpl", buf: bytearray,
            max_initial_size: int) -> None:
        self.__reader_fur: _ReaderFuture[readers.HttpRequestReader] = \
            _ReaderFuture()

        self.__writer: Optional[writers.HttpResponseWriter] = None

        super().__init__(__impl, buf, max_initial_size)

        self._data_appended()

    @property
    def _reader_fur(  # type: ignore
            self) -> _ReaderFuture[readers.HttpRequestReader]:
        return self.__reader_fur

    @property
    def _writer(self) -> Optional[writers.HttpResponseWriter]:
        return self.__writer

    def _try_parse_initial(self) -> None:
        initial = parsers.parse_request_initial(self._buf)

        if initial is None:
            if len(self._buf) > self._max_initial_size:
                self.pause_reading()

                self._set_read_exception(readers.EntityTooLargeError())

            return

        self._body_len = parsers.discover_request_body_length(initial)

        reader = readers.HttpRequestReader(self, initial=initial)
        self._reader_fur.set_result(reader)

    async def _read_request(self) -> readers.HttpRequestReader:
        try:
            return await self._reader_fur.safe_await()

        except readers.EntityTooLargeError as e:
            raise readers.RequestInitialTooLargeError(self) from e

        except readers.ReceivedDataMalformedError as e:
            raise readers.RequestInitialMalformedError(self) from e

    def write_response(
        self, status_code: "constants.HttpStatusCode", *,
        headers: Optional[_HeaderType]
            ) -> writers.HttpResponseWriter:
        if self._writer is not None:
            raise RuntimeError("You cannot write response twice.")

        if self._write_exc:
            raise self._write_exc

        maybe_reader = self._reader_fur.result() \
            if self._reader_fur.exception() is None else None

        maybe_req_initial = \
            maybe_reader.initial if maybe_reader is not None else None

        initial, initial_bytes = \
            composers.compose_response_initial(
                status_code=status_code, headers=headers,
                req_initial=maybe_req_initial)

        try:
            if "transfer-encoding" not in initial.headers.keys():
                self._write_chunked_body = False

            else:
                self._write_chunked_body = parsers.is_chunked_body(
                    initial.headers["transfer-encoding"])

            self._transport.write(initial_bytes)

        except Exception as e:
            exc = writers.WriteAbortedError()
            exc.__cause__ = e
            self._set_write_exception(exc)

            raise exc

        writer = writers.HttpResponseWriter(
            self, initial=initial, reader=maybe_reader)

        self.__writer = writer
        self._writer_ready.set()

        return writer

    def _is_last_stream(self) -> Optional[bool]:
        if not self._finished():
            return None

        if self._last_stream is None:
            if self._reader_fur.exception() is not None or \
                    self._read_exc is not None:
                self._last_stream = True

            elif self._writer is None or self._write_exc is not None:
                self._last_stream = True

            elif self._writer.initial.status_code >= 400:
                self._last_stream = True

            else:
                reader = self._reader_fur.result()

                remote_conn_header = reader.initial.headers.get(
                    "connection", "").lower()

                local_conn_header = self._writer.initial.headers.get(
                    "connection", "").lower()

                if "close" not in (remote_conn_header, local_conn_header):
                    self._last_stream = False

                else:
                    self._last_stream = True

        return self._last_stream
