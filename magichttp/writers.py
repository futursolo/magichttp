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

from typing import Optional

import abc
import asyncio
import typing

if typing.TYPE_CHECKING:
    from . import initials
    from . import readers


class HttpStreamWriteAfterFinishedError(EOFError):
    """
    Raised when :func:`BaseHttpStreamWriter.write()` is called after
    the stream is finished.
    """
    pass


class HttpStreamWriteAbortedError(Exception):
    """
    Raised when the stream is aborted before writing the end.
    """
    pass


class BaseHttpStreamWriterDelegate(abc.ABC):
    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def flush(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def finish(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def abort(self) -> None:
        raise NotImplementedError


class BaseHttpStreamWriter(abc.ABC):
    def __init__(self, __delegate: BaseHttpStreamWriterDelegate) -> None:
        self._delegate = __delegate
        self._max_buf_len = 4 * 1024 * 1024  # 4M

        self._buf = bytearray()

        self._flush_lock = asyncio.Lock()

        self._finished = asyncio.Event()
        self._exc: Optional[BaseException] = None

        self._max_buf_len_changed: "asyncio.Future[None]" = asyncio.Future()

    def buf_len(self) -> int:
        """
        Return the length of the internal buffer.
        """
        return len(self._buf)

    @property
    def max_buf_len(self) -> int:
        return self._max_buf_len

    @max_buf_len.setter
    def max_buf_len(self, new_max_buf_len: int) -> None:
        self._max_buf_len = new_max_buf_len

        if not self._max_buf_len_changed.done():
            self._max_buf_len_changed.set_result(None)
            self._max_buf_len_changed = asyncio.Future()

    def _empty_buf(self) -> None:
        if self.buf_len() >= 0:
            data = bytes(self._buf)
            self._buf.clear()  # type: ignore

            try:
                self._delegate.write(data)

            except Exception as e:
                self._finished.set()
                if self._exc is None:
                    self._exc = e

                raise

    def write(self, data: bytes) -> None:
        """
        Write the data.
        """
        if self.finished():
            if self._exc:
                raise self._exc

            raise HttpStreamWriteAfterFinishedError

        self._buf += data

        if self.buf_len() > self.max_buf_len:
            self._empty_buf()

    async def flush(self) -> None:
        """
        Give the writer a chance to flush the pending data
        out of the internal buffer.
        """
        async with self._flush_lock:
            if self.finished():
                if self._exc:
                    raise self._exc

                return

            self._empty_buf()

            try:
                await self._delegate.flush()

            except asyncio.CancelledError:
                raise

            except Exception as e:
                self._finished.set()
                if self._exc is None:
                    self._exc = e

                raise

    def finish(self) -> None:
        """
        Finish the stream.
        """
        if self.finished():
            if self._exc:
                raise self._exc

            return

        self._finished.set()

        try:
            self._empty_buf()
            self._delegate.finish()

        except Exception as e:
            if self._exc is None:
                self._exc = e

            raise

    def finished(self) -> bool:
        """
        Return `True` if the Request or Response is finished or
        the writer has been aborted.
        """
        return self._finished.is_set()

    async def wait_finished(self) -> None:
        await self._finished.wait()

    def abort(self) -> None:
        """
        Abort the writer without draining out all the pending buffer.
        """
        self._delegate.abort()


class HttpRequestWriterDelegate(BaseHttpStreamWriterDelegate):
    @abc.abstractmethod
    async def read_response(self) -> "readers.HttpResponseReader":
        raise NotImplementedError


class HttpRequestWriter(BaseHttpStreamWriter):
    def __init__(
        self, __delegate: HttpRequestWriterDelegate, *,
            initial: "initials.HttpRequestInitial") -> None:
        super().__init__(__delegate)
        self.__delegate = __delegate

        self._initial = initial

        self._reader: Optional["readers.HttpResponseReader"] = None

    @property
    def initial(self) -> "initials.HttpRequestInitial":
        return self._initial

    @property
    def reader(self) -> "readers.HttpResponseReader":
        if self._reader is None:
            raise AttributeError("The reader is not ready.")

        return self._reader

    async def read_response(self) -> "readers.HttpResponseReader":
        self._reader = await self.__delegate.read_response()

        return self._reader


class HttpResponseWriterDelegate(BaseHttpStreamWriterDelegate):
    pass


class HttpResponseWriter(BaseHttpStreamWriter):
    def __init__(
        self, __delegate: HttpResponseWriterDelegate, *,
            initial: "initials.HttpResponseInitial",
            reader: Optional["readers.HttpRequestReader"]) -> None:
        super().__init__(__delegate)

        self._initial = initial

        self._reader = reader

    @property
    def initial(self) -> "initials.HttpResponseInitial":
        return self._initial

    @property
    def reader(self) -> "readers.HttpRequestReader":
        if self._reader is None:
            raise AttributeError(
                "HttpRequestReader is unavailable due to an "
                "Error during reading.")

        return self._reader
