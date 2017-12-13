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

__all__ = [
    "WriteAfterFinishedError",
    "WriteAbortedError",

    "BaseHttpStreamWriter",
    "HttpRequestWriter",
    "HttpResponseWriter"]


class BaseWriteException(Exception):
    """
    The base class of all the write exceptions.
    """
    pass


class WriteAfterFinishedError(EOFError, BaseWriteException):
    """
    Raised when :func:`BaseHttpStreamWriter.write()` is called after
    the stream is finished.
    """
    pass


class WriteAbortedError(BaseWriteException):
    """
    Raised when the stream is aborted before writing the end.
    """
    pass


class BaseHttpStreamWriterDelegate(abc.ABC):  # pragma: no cover
    @abc.abstractmethod
    def write_data(self, data: bytes, finished: bool=False) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def flush_buf(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def abort(self) -> None:
        raise NotImplementedError


class BaseHttpStreamWriter(abc.ABC):
    __slots__ = (
        "_delegate", "__delegate", "_flush_lock", "_finished", "_exc",
        "_initial", "_reader")

    def __init__(self, __delegate: BaseHttpStreamWriterDelegate) -> None:
        self._delegate = __delegate

        self._flush_lock = asyncio.Lock()

        self._finished = asyncio.Event()
        self._exc: Optional[BaseWriteException] = None

    def write(self, data: bytes) -> None:
        """
        Write the data.
        """
        if self.finished():
            if self._exc:
                raise self._exc

            raise WriteAfterFinishedError

        if not data:
            return

        try:
            self._delegate.write_data(data, finished=False)

        except BaseWriteException as e:
            self._finished.set()
            if self._exc is None:
                self._exc = e

            raise

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

            try:
                await self._delegate.flush_buf()

            except asyncio.CancelledError:
                raise

            except BaseWriteException as e:
                self._finished.set()
                if self._exc is None:
                    self._exc = e

                raise

    def finish(self, data: bytes=b"") -> None:
        """
        Finish the stream.
        """
        if self.finished():
            if self._exc:
                raise self._exc

            if data:
                raise WriteAfterFinishedError

            return

        try:
            self._delegate.write_data(data, finished=True)

        except BaseWriteException as e:
            if self._exc is None:
                self._exc = e

            raise

        finally:
            self._finished.set()

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


class HttpRequestWriterDelegate(
        BaseHttpStreamWriterDelegate):  # pragma: no cover
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
