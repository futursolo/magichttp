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

from typing import Union, Mapping, Iterable, Tuple, Optional, Any

from . import constants

import abc
import asyncio
import typing

if typing.TYPE_CHECKING:  # pragma: no cover
    from . import initials  # noqa: F401
    from . import writers  # noqa: F401

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
    The base class of all read exceptions.
    """
    pass


class EntityTooLargeError(BaseReadException):
    """
    The incoming entity is too large.
    """
    pass


class RequestInitialTooLargeError(EntityTooLargeError):
    """
    The incoming request initial is too large.
    """
    def __init__(
            self, __delegate: "HttpRequestReaderDelegate", *args: Any) -> None:
        super().__init__(*args)

        self._delegate = __delegate

    def write_response(
        self, status_code: Union[
            int, constants.HttpStatusCode
        ]=constants.HttpStatusCode.REQUEST_HEADER_FIELDS_TOO_LARGE, *,
        headers: Optional[_HeaderType]=None
            ) -> "writers.HttpResponseWriter":
        """
        When this exception is raised on the server side, this method is used
        to send a error response instead of
        :method:`BaseHttpStreamReader.write_response()`.
        """
        return self._delegate.write_response(
            constants.HttpStatusCode(status_code),
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
    Raised when the received data is unable to be parsed as an http message.
    """
    pass


class RequestInitialMalformedError(ReceivedDataMalformedError):
    """
    The request initial is malformed.
    """
    def __init__(
            self, __delegate: "HttpRequestReaderDelegate", *args: Any) -> None:
        super().__init__(*args)

        self._delegate = __delegate

    def write_response(
        self, status_code: Union[
            int, constants.HttpStatusCode
        ]=constants.HttpStatusCode.BAD_REQUEST, *,
        headers: Optional[_HeaderType]=None
            ) -> "writers.HttpResponseWriter":
        """
        When this exception is raised on the server side, this method is used
        to send a error response instead of
        :method:`BaseHttpStreamReader.write_response()`.
        """
        return self._delegate.write_response(
            constants.HttpStatusCode(status_code),
            headers=headers)


class BaseHttpStreamReaderDelegate(abc.ABC):  # pragma: no cover
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
    """
    The Base class of :class:`HttpRequestReader`
    and :class:`HttpResponseReader`.
    """
    __slots__ = (
        "_delegate", "_max_buf_len", "_buf",
        "_wait_for_data_fur", "_read_lock", "_end_appended", "_exc")

    def __init__(
            self, __delegate: BaseHttpStreamReaderDelegate) -> None:
        self._delegate = __delegate
        self._max_buf_len = 4 * 1024 * 1024  # 4M

        self._buf = bytearray()
        self._wait_for_data_fur: Optional["asyncio.Future[None]"] = None

        self._read_lock = asyncio.Lock()

        self._end_appended = asyncio.Event()
        self._exc: Optional[BaseReadException] = None

    def _append_data(self, data: Union[bytes, bytearray, memoryview]) -> None:
        assert not self._end_appended.is_set(), "Append data after ended."

        if not data:  # pragma: no cover
            return

        self._buf += data  # type: ignore

        if len(self) >= self.max_buf_len:
            self._delegate.pause_reading()

        if self._wait_for_data_fur is not None and \
                not self._wait_for_data_fur.done():
            self._wait_for_data_fur.set_result(None)

    def _append_end(self, exc: Optional[BaseReadException]) -> None:
        if self._end_appended.is_set():  # pragma: no cover
            return

        if exc:
            self._exc = exc

        self._end_appended.set()

        if self._wait_for_data_fur is not None and \
                not self._wait_for_data_fur.done():
            self._wait_for_data_fur.set_result(None)

    def _raise_exc_if_finished(self) -> None:
        if not self.finished():
            return

        if self._exc:
            raise self._exc

        raise ReadFinishedError

    def _raise_exc_if_end_appended(self) -> None:
        if not self._end_appended.is_set():
            return

        if self._exc:
            raise self._exc

        raise ReadFinishedError

    async def _wait_for_data(self) -> None:
        self._raise_exc_if_end_appended()

        self._delegate.resume_reading()

        self._wait_for_data_fur = asyncio.Future()
        try:
            await self._wait_for_data_fur

            self._raise_exc_if_end_appended()

        except asyncio.CancelledError:  # pragma: no cover
            raise

        finally:
            self._wait_for_data_fur = None

    @property
    def max_buf_len(self) -> int:
        """
        Return the current maximum buffer length.
        """
        return self._max_buf_len

    @max_buf_len.setter
    def max_buf_len(self, new_max_buf_len: int) -> None:
        """
        Replace the current maximum buffer length with the one provided.
        """
        assert not self.busy(), \
            "You cannot set max buffer length when the reader is busy."

        self._max_buf_len = new_max_buf_len

    def __len__(self) -> int:
        return len(self._buf)

    async def read(self, n: int=-1, exactly: bool=False) -> bytes:
        """
        Read at most n bytes data or if exactly is `True`,
        read exactly n bytes data. If the end has been reached before
        the buffer has the length of data asked, it will
        raise a :class:`ReadUnsatisfiableError`.

        When :method:`.finished()` is `True`, this method will raise any errors
        occurred during the read or a :class:`ReadFinishedError`.
        """
        async with self._read_lock:
            self._raise_exc_if_finished()

            if n == 0:
                return b""

            if exactly:
                if n < 0:  # pragma: no cover
                    raise ValueError(
                        "You MUST sepcify the length of the data "
                        "if exactly is True.")

                if n > self.max_buf_len:  # pragma: no cover
                    raise ValueError(
                        "The length provided cannot be larger "
                        "than the max buffer length.")

                while len(self) < n:
                    try:
                        await self._wait_for_data()

                    except asyncio.CancelledError:  # pragma: no cover
                        raise

                    except Exception as e:
                        raise ReadUnsatisfiableError from e

            elif n < 0:
                while True:
                    if len(self) > self.max_buf_len:
                        raise MaxBufferLengthReachedError

                    try:
                        await self._wait_for_data()

                    except asyncio.CancelledError:  # pragma: no cover
                        raise

                    except Exception:
                        data = bytes(self._buf)
                        self._buf.clear()

                        return data

            elif len(self) == 0:
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
        a :class:`MaxBufferLengthReachedError`.
        Similarly, if the end has been reached before found the separator
        it will raise a :class:`SeparatorNotFoundError`.

        When :method:`.finished()` is `True`, this method will raise any errors
        occurred during the read or a :class:`ReadFinishedError`.
        """
        async with self._read_lock:
            self._raise_exc_if_finished()

            start_pos = 0

            while True:
                separator_pos = self._buf.find(separator, start_pos)

                if separator_pos != -1:
                    break

                if len(self) > self.max_buf_len:
                    raise MaxBufferLengthReachedError

                try:
                    await self._wait_for_data()

                except asyncio.CancelledError:  # pragma: no cover
                    raise

                except Exception as e:
                    if len(self) > 0:
                        raise SeparatorNotFoundError from e

                    else:
                        raise

                new_start_pos = len(self) - len(separator)

                if new_start_pos > 0:
                    start_pos = new_start_pos

            full_pos = separator_pos + len(separator)

            if keep_separator:
                data_pos = full_pos

            else:
                data_pos = separator_pos

            data = bytes(self._buf[0:data_pos])
            del self._buf[0:full_pos]

            return data

    def busy(self) -> bool:
        """
        Return `True` if the reader is reading.
        """
        return self._read_lock.locked()

    async def wait_end(self) -> None:
        """
        Wait until the end has been appended.
        """
        await self._end_appended.wait()

    def end_appended(self) -> bool:
        return self._end_appended.is_set()

    def finished(self) -> bool:
        """
        Return `True` if the reader reached the end of the Request or Response.
        """
        return len(self) == 0 and self._end_appended.is_set()

    def abort(self) -> None:
        """
        Abort the reader without waiting for the end.
        """
        self._delegate.abort()


class HttpRequestReaderDelegate(
        BaseHttpStreamReaderDelegate):  # pragma: no cover
    @abc.abstractmethod
    def write_response(
        self, status_code: constants.HttpStatusCode, *,
        headers: Optional[_HeaderType]
            ) -> "writers.HttpResponseWriter":
        raise NotImplementedError


class HttpRequestReader(BaseHttpStreamReader):
    """
    The Reader for reading http requests.
    """
    __slots__ = ("__delegate", "_initial", "_writer")

    def __init__(
        self, __delegate: HttpRequestReaderDelegate, *,
            initial: "initials.HttpRequestInitial") -> None:
        super().__init__(__delegate)
        self.__delegate = __delegate

        self._initial = initial

        self._writer: Optional["writers.HttpResponseWriter"] = None

    @property
    def initial(self) -> "initials.HttpRequestInitial":
        """
        The request initial.
        """
        return self._initial

    @property
    def writer(self) -> "writers.HttpResponseWriter":
        """
        This property can be used to access the corresponding
        :class:`writers.HttpResponseWriter` if it has been created using
        :method:`.write_response()` or it will raise an
        :class:`AttributeError`.
        """
        if self._writer is None:
            raise AttributeError("The writer is not ready.")

        return self._writer

    def write_response(
        self, status_code: Union[int, constants.HttpStatusCode], *,
        headers: Optional[_HeaderType]=None
            ) -> "writers.HttpResponseWriter":
        """
        Write a response to the client.
        """
        self._writer = self.__delegate.write_response(
            constants.HttpStatusCode(status_code),
            headers=headers)

        return self._writer


class HttpResponseReaderDelegate(BaseHttpStreamReaderDelegate):
    pass


class HttpResponseReader(BaseHttpStreamReader):
    """
    The Reader for reading http responses.
    """
    __slots__ = ("_initial", "_writer")

    def __init__(
        self, __delegate: HttpResponseReaderDelegate, *,
        initial: "initials.HttpResponseInitial",
            writer: "writers.HttpRequestWriter") -> None:
        super().__init__(__delegate)

        self._initial = initial

        self._writer = writer

    @property
    def initial(self) -> "initials.HttpResponseInitial":
        """
        The response initial.
        """
        return self._initial

    @property
    def writer(self) -> "writers.HttpRequestWriter":
        """
        This property can be used to access the corresponding
        :class:`writers.HttpRequestWriter`.
        """
        return self._writer
