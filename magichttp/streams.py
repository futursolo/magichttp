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

from . import initials
from . import impls
from . import exceptions

import abc
import asyncio

__all__ = [
    "HttpRequestReader", "HttpRequestWriter", "HttpResponseReader",
    "HttpResponseWriter"]


class BaseHttpStreamReader(abc.ABC):
    def __init__(self, impl: "impls.BaseHttpImpl") -> None:
        self._impl = impl

        self._protocol = self._impl._protocol

        self._buf = bytearray()

        self._exc: Optional[Exception] = None

        self._finished = False

        self._read_lock = asyncio.Lock()

        self._waiting_for_data_fur: Optional["asyncio.Future[None]"] = None

    def buflen(self) -> int:
        """
        Return the length of the internal buffer.
        """
        return len(self._buf)

    def _data_arrived(self) -> None:
        if self._waiting_for_data_fur is not None:
            if not self._waiting_for_data_fur.done():
                self._waiting_for_data_fur.set_result(None)

            self._waiting_for_data_fur = None

    def _buf_is_full(self) -> bool:
        return self.buflen() > self._protocol._STREAM_BUFFER_LIMIT

    @abc.abstractmethod
    def _resume_reading(self) -> None:
        raise NotImplementedError

    async def _wait_for_data(self) -> None:
        if self._finished:
            if self._exc:
                raise self._exc

            raise exceptions.HttpStreamFinishedError

        self._resume_reading()

        if self._waiting_for_data_fur is None:
            self._waiting_for_data_fur = asyncio.Future()

        await self._waiting_for_data_fur

    def _append_data(self, data: bytes) -> bool:
        if not data:
            return False

        self._buf += data

        self._data_arrived()

        return self._buf_is_full()

    def _append_end(self) -> None:
        self._finished = True

        self._data_arrived()

    def _append_exc(self, exc: Exception) -> None:
        if self._exc is not None:
            return

        self._exc = exc
        self._finished = True

        self._data_arrived()

    async def read(self, n: int=-1, exactly: bool=False) -> bytes:
        """
        Read at most n bytes data or if exactly is `True`,
        read exactly n bytes data. If the end reached before
        the buffer has the length of data the you want, it will
        raise an `asyncio.IncompleteReadError`.

        When finished() is True, this method will raise a
        :class:`exceptions.HttpStreamFinishedError`.
        """
        if n == 0:
            return b""

        async with self._read_lock:
            if exactly:
                if n < 0:
                    raise ValueError(
                        "You MUST sepcify the length of the data "
                        "if exactly is True.")

                while self.buflen() < n:
                    if self._finished:
                        if self.buflen() > 0:
                            partial = bytes(self._buf)
                            self._buf.clear()  # type: ignore

                            raise asyncio.IncompleteReadError(
                                partial, expected=n) from self._exc

                        else:
                            if self._exc:
                                raise self._exc

                            raise exceptions.HttpStreamFinishedError

                    await self._wait_for_data()

            elif n < 0:
                while not self._finished:
                    if self._buf_is_full():
                        raise asyncio.LimitOverrunError(
                            "The buffer is full "
                            "before the stream reaches the end.",
                            self.buflen())

                    await self._wait_for_data()

            elif self.buflen() == 0:
                await self._wait_for_data()

            if self.finished():
                if self._exc:
                    raise self._exc

                raise exceptions.HttpStreamFinishedError

            if n < 0 or self.buflen() <= n:
                data = bytes(self._buf)
                self._buf.clear()  # type: ignore

                return data

            data = bytes(self._buf[0:n])
            del self._buf[0:n]

            return data

    async def read_until(
        self, separator: bytes=b"\n",
            *, keep_separator: bool=True) -> bytes:
        """
        Read until the separator has been found.

        When buffer limit has been reached, and the separator is not found,
        this method will raise an `asyncio.LimitOverrunError`.
        Similarly, if the eof reached before found the separator it will raise
        an `asyncio.IncompleteReadError`.

        When finished() is True, this method will raise a
        :class:`exceptions.HttpStreamFinishedError`.
        """
        async with self._read_lock:
            while True:
                separator_pos = self._buf.find(separator)

                if separator_pos == -1:
                    if self._finished:
                        if self.buflen() > 0:
                            partial = bytes(self._buf)
                            self._buf.clear()  # type: ignore

                            raise asyncio.IncompleteReadError(
                                partial, expected=None) from self._exc

                        else:
                            if self._exc:
                                raise self._exc

                            raise exceptions.HttpStreamFinishedError

                    if self._buf_is_full():
                        raise asyncio.LimitOverrunError(
                            "The buffer limit has been reached "
                            "before a separator can be found.", self.buflen())

                    else:
                        await self._wait_for_data()

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

    def finished(self) -> bool:
        """
        Return True if the reader reached the end of the Request or Response.
        """
        return self.buflen() == 0 and self._finished

    @abc.abstractmethod
    async def abort(self) -> None:
        """
        Abort the reader without waiting for the end.
        """
        raise NotImplementedError


class BaseHttpStreamWriter(abc.ABC):
    def __init__(self, impl: "impls.BaseHttpImpl") -> None:
        self._impl = impl

        self._protocol = self._impl._protocol

        self._buf = bytearray()

        self._exc: Optional[Exception] = None

        self._finished = False

        self._flush_lock = asyncio.Lock()

    def _append_exc(self, exc: Exception) -> None:
        if self._exc is not None:
            return

        self._finished = True
        self._exc = exc

    def buflen(self) -> int:
        """
        Return the length of the internal buffer.
        """
        return len(self._buf)

    def write(self, data: bytes) -> None:
        """
        Write the data.
        """
        if self._exc:
            raise self._exc

        if self._finished:
            raise exceptions.HttpStreamFinishedError("Write after finished.")

        self._buf += data

    async def flush(self) -> None:
        """
        Give the writer a chance to flush the pending data
        out of the internal buffer.
        """
        async with self._flush_lock:
            if self._exc:
                raise self._exc

            if self._finished:
                return

            if self.buflen() == 0:
                return

            data = bytes(self._buf)
            self._buf.clear()  # type: ignore

            try:
                await self._impl.flush_data(self, data)

            except Exception as e:
                self._append_exc(e)

                raise

    async def finish(self) -> None:
        """
        Finish the Request or Response.
        """
        async with self._flush_lock:
            if self._exc:
                raise self._exc

            if self._finished:
                return

            self._finished = True

            if self.buflen() == 0:
                return

            data = bytes(self._buf)
            self._buf.clear()  # type: ignore

            try:
                await self._impl.flush_data(self, data, last_chunk=True)

            except Exception as e:
                self._append_exc(e)

                raise

    def finished(self) -> bool:
        """
        Return `True` if the Request or Response is finished or
        the writer has been aborted.
        """
        return self._finished

    @abc.abstractmethod
    async def abort(self) -> None:
        """
        Abort the writer without draining out all the pending buffer.
        """
        raise NotImplementedError


class HttpRequestReader(BaseHttpStreamReader):
    def __init__(
        self, impl: "impls.BaseHttpServerImpl",
            req_initial: initials.HttpRequestInitial) -> None:
        super().__init__(impl)

        self._initial = req_initial

        self._writer: Optional["HttpResponseWriter"] = None

    def _resume_reading(self) -> None:
        assert isinstance(self._impl, impls.BaseHttpServerImpl)

        self._impl.resume_reading(self)

    @property
    def initial(self) -> initials.HttpRequestInitial:
        return self._initial

    @property
    def writer(self) -> "HttpResponseWriter":
        if self._writer is None:
            raise AttributeError("The writer is not ready.")

        return self._writer

    async def write_response(
        self, res_initial: initials.HttpResponseInitial) -> \
            "HttpResponseWriter":
        assert isinstance(self._impl, impls.BaseHttpServerImpl)

        self._writer = await self._impl.write_response(self, res_initial)

        return self._writer

    async def abort(self) -> None:
        assert isinstance(self._impl, impls.BaseHttpServerImpl)

        await self._impl.abort_request(self)


class HttpRequestWriter(BaseHttpStreamWriter):
    def __init__(
        self, impl: "impls.BaseHttpClientImpl",
            req_initial: initials.HttpRequestInitial) -> None:
        super().__init__(impl)

        self._initial = req_initial

        self._reader: Optional["HttpResponseReader"] = None

    @property
    def initial(self) -> initials.HttpRequestInitial:
        return self._initial

    @property
    def reader(self) -> "HttpResponseReader":
        if self._reader is None:
            raise AttributeError("The reader is not ready.")

        return self._reader

    async def read_response(self) -> "HttpResponseReader":
        assert isinstance(self._impl, impls.BaseHttpClientImpl)

        self._reader = await self._impl.read_response(self)

        return self._reader

    async def abort(self) -> None:
        assert isinstance(self._impl, impls.BaseHttpClientImpl)

        await self._impl.abort_request(self)


class HttpResponseReader(BaseHttpStreamReader):
    def __init__(
        self, impl: "impls.BaseHttpClientImpl",
        res_initial: initials.HttpResponseInitial,
            req_writer: HttpRequestWriter) -> None:
        super().__init__(impl)

        self._initial = res_initial
        self._writer = req_writer

    def _resume_reading(self) -> None:
        assert isinstance(self._impl, impls.BaseHttpClientImpl)

        self._impl.resume_reading(self._writer)

    @property
    def initial(self) -> initials.HttpResponseInitial:
        return self._initial

    @property
    def writer(self) -> HttpRequestWriter:
        return self._writer

    async def abort(self) -> None:
        assert isinstance(self._impl, impls.BaseHttpClientImpl)

        await self._impl.abort_request(self._writer)


class HttpResponseWriter(BaseHttpStreamWriter):
    def __init__(
        self, impl: "impls.BaseHttpServerImpl",
            res_initial: initials.HttpResponseInitial,
            req_reader: Optional[HttpRequestReader]) -> None:
        super().__init__(impl)

        self._initial = res_initial
        self._reader = req_reader

    @property
    def initial(self) -> initials.HttpResponseInitial:
        return self._initial

    @property
    def reader(self) -> HttpRequestReader:
        if self._reader is None:
            raise AttributeError(
                "HttpRequestReader is unavailable due to an "
                "Error during reading.")

        return self._reader

    async def abort(self) -> None:
        assert isinstance(self._impl, impls.BaseHttpServerImpl)

        await self._impl.abort_request(self._reader)
