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

from typing import Union, Mapping, Iterable, Tuple, Optional, Any

from . import constants

import abc
import asyncio
import typing
import http

if typing.TYPE_CHECKING:
    from . import initials
    from . import writers

__all__ = [
    "EntityTooLargeError",
    "RequestInitialTooLargeError",
    "ReadFinishedError",
    "ReadAbortedError",
    "MaxBufferLengthReachedError",
    "ReadUnsatisfiableError",
    "SeparatorNotFoundError",
    "ReceivedDataMalformedError",
    "RequestInitialMalformedError",

    "BaseHttpStreamReader",
    "HttpRequestReader",
    "HttpResponseReader"]

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class BaseReadException(Exception):
    """
    The base class of all the read exceptions.
    """
    pass


class EntityTooLargeError(BaseReadException):
    """
    The incoming entity is too large.
    """
    pass


class RequestInitialTooLargeError(EntityTooLargeError):
    """
    The incoming initial is too large.
    """
    def __init__(
        self, __delegate: "HttpRequestReaderDelegate",
            *args: Any) -> None:
        super().__init__(*args)

        self._delegate = __delegate

    def write_response(
        self, status_code: Union[
            int, http.HTTPStatus
        ]=http.HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE, *,
        headers: Optional[_HeaderType]=None
            ) -> "writers.HttpResponseWriter":

        return self._delegate.write_response(
            http.HTTPStatus(status_code),
            headers=headers)


class ReadFinishedError(EOFError, BaseReadException):
    """
    Raised when the end of the stream is reached.
    """
    pass


class ReadAbortedError(BaseReadException):
    """
    Raised when the stream is aborted before reaching the end.
    """
    pass


class MaxBufferLengthReachedError(BaseReadException):
    """
    Raised when the max length of the stream buffer is reached before
    the desired condition can be satisfied.
    """
    pass


class ReadUnsatisfiableError(BaseReadException):
    """
    Raised when the end of the stream is reached before
    the desired condition can be satisfied.
    """
    pass


class SeparatorNotFoundError(ReadUnsatisfiableError):
    """
    Raised when the end of the stream is reached before
    the requested separator can be found.
    """
    pass


class ReceivedDataMalformedError(BaseReadException):
    """
    Raised when the received data is unable to be parsed as http messages.
    """
    pass


class RequestInitialMalformedError(ReceivedDataMalformedError):
    """
    The request initial is malformed.
    """
    def __init__(
        self, __delegate: "HttpRequestReaderDelegate",
            *args: Any) -> None:
        super().__init__(*args)

        self._delegate = __delegate

    def write_response(
        self, status_code: Union[
            int, http.HTTPStatus]=http.HTTPStatus.BAD_REQUEST, *,
        headers: Optional[_HeaderType]=None
            ) -> "writers.HttpResponseWriter":

        return self._delegate.write_response(
            http.HTTPStatus(status_code),
            headers=headers)


class BaseHttpStreamReaderDelegate(abc.ABC):
    @abc.abstractmethod
    def pause_reading(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def resume_reading(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def abort(self) -> None:
        raise NotImplementedError


class BaseHttpStreamReader(abc.ABC):
    __slots__ = (
        "_delegate", "__delegate", "_max_buf_len", "_buf",
        "_wait_for_data_fur", "_read_lock", "_end_appended", "_exc",
        "_max_buf_len_changed_fur", "_initial", "_writer")

    def __init__(
            self, __delegate: BaseHttpStreamReaderDelegate) -> None:
        self._delegate = __delegate
        self._max_buf_len = 4 * 1024 * 1024  # 4M

        self._buf = bytearray()
        self._wait_for_data_fur: Optional["asyncio.Future[None]"] = None

        self._read_lock = asyncio.Lock()

        self._end_appended = asyncio.Event()
        self._exc: Optional[BaseReadException] = None

        self._max_buf_len_changed_fur: Optional["asyncio.Future[None]"] = \
            asyncio.Future()

    @property
    def max_buf_len(self) -> int:
        return self._max_buf_len

    @max_buf_len.setter
    def max_buf_len(self, new_max_buf_len: int) -> None:
        self._max_buf_len = new_max_buf_len

        if self._max_buf_len_changed_fur is not None and \
                not self._max_buf_len_changed_fur.done():
            self._max_buf_len_changed_fur.set_result(None)

    def buf_len(self) -> int:
        return len(self._buf)

    def _append_data(self, data: bytes) -> None:
        if not data:
            return

        self._buf += data

        if self.buf_len() >= self.max_buf_len:
            self._delegate.pause_reading()

        if self._wait_for_data_fur is not None and \
                not self._wait_for_data_fur.done():
            self._wait_for_data_fur.set_result(None)

    def _append_end(self, exc: Optional[BaseReadException]) -> None:
        if self._end_appended.is_set():
            return

        self._exc = exc

        self._end_appended.set()

        if self._wait_for_data_fur is not None and \
                not self._wait_for_data_fur.done():
            self._wait_for_data_fur.set_result(None)

    async def _wait_for_data(self) -> None:
        if self._end_appended.is_set():
            if self._exc is not None:
                raise self._exc

            raise ReadFinishedError

        former_buf_len = self.buf_len()

        self._delegate.resume_reading()

        self._max_buf_len_changed_fur = asyncio.Future()
        self._wait_for_data_fur = asyncio.Future()
        try:
            done, pending = await asyncio.wait(
                [self._wait_for_data_fur, self._max_buf_len_changed_fur],
                return_when=asyncio.FIRST_COMPLETED)

            if self._max_buf_len_changed_fur.done():
                return

            if former_buf_len <= self.buf_len():
                # New data has been appended.
                return

            if self._end_appended.is_set():
                if self._exc is not None:
                    raise self._exc

                raise ReadFinishedError

        except asyncio.CancelledError:
            raise

        finally:
            self._max_buf_len_changed_fur = None
            self._wait_for_data_fur = None

    async def read(self, n: int=-1, exactly: bool=False) -> bytes:
        """
        Read at most n bytes data or if exactly is `True`,
        read exactly n bytes data. If the end has been reached before
        the buffer has the length of data asked, it will
        raise an :class:`HttpStreamReadUnsatisfiableError`.

        When :func:`.finished()` is `True`, this method will raise any errors
        occurred during the read or an :class:`ReadFinishedError`.
        """
        if n == 0:
            return b""

        async with self._read_lock:
            if self.finished():
                if self._exc:
                    raise self._exc

                raise ReadFinishedError

            if exactly:
                if n < 0:
                    raise ValueError(
                        "You MUST sepcify the length of the data "
                        "if exactly is True.")

                while self.buf_len() < n:
                    try:
                        await self._wait_for_data()

                    except asyncio.CancelledError:
                        raise

                    except Exception as e:
                        raise ReadUnsatisfiableError from e

            elif n < 0:
                while True:
                    if self.buf_len() > self.max_buf_len:
                        raise MaxBufferLengthReachedError

                    try:
                        await self._wait_for_data()

                    except asyncio.CancelledError:
                        raise

                    except Exception:
                        data = bytes(self._buf)
                        self._buf.clear()  # type: ignore

                        return data

            elif self.buf_len() == 0:
                await self._wait_for_data()

            data = bytes(self._buf[0:n])
            del self._buf[0:n]

            return data

    async def read_until(
        self, separator: bytes=b"\n",
            *, keep_separator: bool=True) -> bytes:
        """
        Read until the separator has been found.

        When the max size of the buffer has been reached,
        and the separator is not found, this method will raise
        an :class:`MaxBufferSizeReachedError`.
        Similarly, if the end has been reached before found the separator
        it will raise an `SeparatorNotFoundError`.

        When :func:`.finished()` is `True`, this method will raise any errors
        occurred during the read or an :class:`ReadFinishedError`.
        """
        async with self._read_lock:
            if self.finished():
                if self._exc:
                    raise self._exc

                raise ReadFinishedError

            start_pos = 0

            while True:
                separator_pos = self._buf.find(separator, start_pos)

                if separator_pos == -1:
                    if self.buf_len() > self.max_buf_len:
                        raise MaxBufferLengthReachedError

                    else:
                        try:
                            await self._wait_for_data()

                        except Exception as e:
                            if self.buf_len() > 0:
                                raise SeparatorNotFoundError from e

                            else:
                                raise

                        new_start_pos = self.buf_len() - len(separator)

                        if new_start_pos > 0:
                            start_pos = new_start_pos

                        continue

                if keep_separator:
                    separator_pos += len(separator)

                data = bytes(self._buf[0:separator_pos])
                del self._buf[0:separator_pos]

                return data

    def busy(self) -> bool:
        """
        Return True if the reader is reading.
        """
        return self._read_lock.locked()

    async def wait_end(self) -> None:
        await self._end_appended.wait()

    def finished(self) -> bool:
        """
        Return True if the reader reached the end of the Request or Response.
        """
        return self.buf_len() == 0 and self._end_appended.is_set()

    def abort(self) -> None:
        """
        Abort the reader without waiting for the end.
        """
        self._delegate.abort()


class HttpRequestReaderDelegate(BaseHttpStreamReaderDelegate):
    @abc.abstractmethod
    def write_response(
        self, status_code: http.HTTPStatus, *,
        headers: Optional[_HeaderType]
            ) -> "writers.HttpResponseWriter":
        raise NotImplementedError


class HttpRequestReader(BaseHttpStreamReader):
    def __init__(
        self, __delegate: HttpRequestReaderDelegate, *,
            initial: "initials.HttpRequestInitial") -> None:
        super().__init__(__delegate)
        self.__delegate = __delegate

        self._initial = initial

        self._writer: Optional["writers.HttpResponseWriter"] = None

    @property
    def initial(self) -> "initials.HttpRequestInitial":
        return self._initial

    @property
    def writer(self) -> "writers.HttpResponseWriter":
        if self._writer is None:
            raise AttributeError("The writer is not ready.")

        return self._writer

    def write_response(
        self, status_code: Union[int, http.HTTPStatus], *,
        headers: Optional[_HeaderType]=None
            ) -> "writers.HttpResponseWriter":

        self._writer = self.__delegate.write_response(
            http.HTTPStatus(status_code),
            headers=headers)

        return self._writer


class HttpResponseReaderDelegate(BaseHttpStreamReaderDelegate):
    pass


class HttpResponseReader(BaseHttpStreamReader):
    def __init__(
        self, __delegate: HttpResponseReaderDelegate, *,
        initial: "initials.HttpResponseInitial",
            writer: "writers.HttpRequestWriter") -> None:
        self._delegate: HttpResponseReaderDelegate
        super().__init__(__delegate)

        self._initial = initial

        self._writer = writer

    @property
    def initial(self) -> "initials.HttpResponseInitial":
        return self._initial

    @property
    def writer(self) -> "writers.HttpRequestWriter":
        return self._writer
