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

from typing import Union, Mapping, Iterable, Tuple, Optional

import abc
import asyncio
import typing
import contextlib
import http

if typing.TYPE_CHECKING:
    from . import initials
    from . import writers

__all__ = [
    "HttpStreamReadFinishedError",
    "HttpStreamAbortedError",
    "HttpStreamMaxBufferLengthReachedError",
    "HttpStreamReadUnsatisfiableError",
    "HttpStreamSeparatorNotFoundError",
    "HttpStreamReceivedDataMalformedError",

    "BaseHttpStreamReaderDelegate"
    "BaseHttpStreamReader",

    "HttpRequestReaderDelegate",
    "HttpRequestReader",

    "HttpResponseReaderDelegate",
    "HttpResponseReader"]

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class HttpStreamReadFinishedError(EOFError):
    """
    Raised when the end of the stream is reached.
    """
    pass


class HttpStreamReadAbortedError(Exception):
    """
    Raised when the stream is aborted before reaching the end.
    """
    pass


class HttpStreamMaxBufferLengthReachedError(Exception):
    """
    Raised when the max length of the stream buffer is reached before
    the desired condition can be found.
    """
    pass


class HttpStreamReadUnsatisfiableError(Exception):
    """
    Raised when the end of the stream is reached before
    the desired condition can be satisfied.
    """
    pass


class HttpStreamSeparatorNotFoundError(HttpStreamReadUnsatisfiableError):
    """
    Raised when the end of the stream is reached before
    the requested separator can be found.
    """
    pass


class HttpStreamReceivedDataMalformedError(Exception):
    """
    Raised when the received data is unable to be parsed as http messages.
    """
    pass


class BaseHttpStreamReaderDelegate(abc.ABC):
    @abc.abstractmethod
    async def fetch_data(self) -> bytes:
        raise NotImplementedError

    @abc.abstractmethod
    def abort(self) -> None:
        raise NotImplementedError


class BaseHttpStreamReader(abc.ABC):
    def __init__(
            self, __delegate: BaseHttpStreamReaderDelegate) -> None:
        self._delegate = __delegate
        self._max_buf_len = 4 * 1024 * 1024  # 4M

        self._buf = bytearray()

        self._read_lock = asyncio.Lock()

        self._finished = asyncio.Event()
        self._exc: Optional[BaseException] = None

        self._max_buf_len_changed: "asyncio.Future[None]" = asyncio.Future()

    @property
    def max_buf_len(self) -> int:
        return self._max_buf_len

    @max_buf_len.setter
    def max_buf_len(self, new_max_buf_len: int) -> None:
        self._max_buf_len = new_max_buf_len

        if not self._max_buf_len_changed.done():
            self._max_buf_len_changed.set_result(None)
            self._max_buf_len_changed = asyncio.Future()

    def buf_len(self) -> int:
        return len(self._buf)

    async def _fill_buf(self) -> None:
        if self._finished.is_set():
            if self._exc is not None:
                raise self._exc

            raise HttpStreamReadFinishedError

        if self._max_buf_len_changed.done():
            self._max_buf_len_changed = asyncio.Future()

        fetch_data_coro = self._delegate.fetch_data()

        try:
            done, pending = await asyncio.wait(  # type: ignore
                [fetch_data_coro, self._max_buf_len_changed],
                return_when=asyncio.FIRST_COMPLETED)

            if self._max_buf_len_changed in done:
                fetch_data_coro.cancel()  # type: ignore

                with contextlib.suppress(asyncio.CancelledError):
                    await fetch_data_coro

                return

            self._buf = fetch_data_coro.result()  # type: ignore

        except asyncio.CancelledError:
            fetch_data_coro.cancel()  # type: ignore

            with contextlib.suppress(asyncio.CancelledError):
                await fetch_data_coro

            raise

        except HttpStreamReadFinishedError:
            self._finished.set()

            raise

        except Exception as e:
            if self._exc is None:
                self._exc = e
            self._finished.set()

            raise

    async def read(self, n: int=-1, exactly: bool=False) -> bytes:
        """
        Read at most n bytes data or if exactly is `True`,
        read exactly n bytes data. If the end has been reached before
        the buffer has the length of data asked, it will
        raise an :class:`HttpStreamReadUnsatisfiableError`.

        When :func:`.finished()` is `True`, this method will raise any errors
        occurred during the read or an :class:`HttpStreamReadFinishedError`.
        """
        if n == 0:
            return b""

        async with self._read_lock:
            if self.finished():
                if self._exc:
                    raise self._exc

                raise HttpStreamReadFinishedError

            if exactly:
                if n < 0:
                    raise ValueError(
                        "You MUST sepcify the length of the data "
                        "if exactly is True.")

                while self.buf_len() < n:
                    try:
                        await self._fill_buf()

                    except asyncio.CancelledError:
                        raise

                    except Exception as e:
                        raise HttpStreamReadUnsatisfiableError from e

            elif n < 0:
                while True:
                    if self.buf_len() > self.max_buf_len:
                        raise HttpStreamMaxBufferLengthReachedError

                    try:
                        await self._fill_buf()

                    except asyncio.CancelledError:
                        raise

                    except Exception:
                        data = bytes(self._buf)
                        self._buf.clear()  # type: ignore

                        return data

            elif self.buf_len() == 0:
                await self._fill_buf()

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
        an :class:`HttpStreamMaxBufferSizeReachedError`.
        Similarly, if the end has been reached before found the separator
        it will raise an `HttpStreamSeparatorNotFoundError`.

        When :func:`.finished()` is `True`, this method will raise any errors
        occurred during the read or an :class:`HttpStreamReadFinishedError`.
        """
        async with self._read_lock:
            if self.finished():
                if self._exc:
                    raise self._exc

                raise HttpStreamReadFinishedError

            start_pos = 0

            while True:
                separator_pos = self._buf.find(separator, start_pos)

                if separator_pos == -1:
                    if self.buf_len() > self.max_buf_len:
                        raise HttpStreamMaxBufferLengthReachedError

                    else:
                        try:
                            await self._fill_buf()

                        except Exception as e:
                            if self.buf_len() > 0:
                                raise HttpStreamSeparatorNotFoundError from e

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

    async def wait_finished(self) -> None:
        await self._finished.wait()

    def finished(self) -> bool:
        """
        Return True if the reader reached the end of the Request or Response.
        """
        return self.buf_len() == 0 and self._finished.is_set()

    @abc.abstractmethod
    def abort(self) -> None:
        """
        Abort the reader without waiting for the end.
        """
        self._delegate.abort()


class HttpRequestReaderDelegate(BaseHttpStreamReaderDelegate):
    @abc.abstractmethod
    def write_response(
        self, status_code: http.HTTPStatus, *,
        version: Optional["initials.HttpVersion"],
        headers: _HeaderType
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
        version: Optional["initials.HttpVersion"]=None,
        headers: Optional[_HeaderType]=None
            ) -> "writers.HttpResponseWriter":
        self._writer = self.__delegate.write_response(
            http.HTTPStatus(status_code),
            version=version,
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
