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

from . import initials
from . import impls

import abc
import asyncio


class BaseHttpStreamReader(abc.ABC):
    def __init__(self, impl: "impls.BaseHttpImpl") -> None:
        self._impl = impl

        self._protocol = self._impl._protocol

        self._buffer = bytearray()

        self._finished = False

        self._read_lock = asyncio.Lock()

    def buflen(self) -> int:
        """
        Return the length of the internal buffer.
        """
        return len(self._buffer)

    def _append_data(self, data: bytes) -> bool:
        self._buffer += data
        return self.buflen() > self._protocol._STREAM_BUFFER_LIMIT

    def _append_end(self) -> None:
        self._finished = True

    async def read(self, n: int=-1, exactly: bool=False) -> bytes:
        """
        Read at most n bytes data or if exactly is `True`,
        read exactly n bytes data. If the eof reached before
        the buffer has the exact same number of data the you want, if will
        raise an `asyncio.IncompleteReadError`.

        When finished() is True, this method will raise a
        :class:`exceptions.StreamEOFError`.
        """
        raise NotImplementedError

    async def read_until(
        self, separator: bytes=b"\n",
            *, keep_separator: bool=True) -> bytes:
        """
        Read until the separator has been found.

        When limit(if any) has been reached, and the separator is not found,
        this method will raise an `asyncio.LimitOverrunError`.
        Similarly, if the eof reached before found the separator it will raise
        an `asyncio.IncompleteReadError`.

        When at_eof() is True, this method will raise a
        :class:`exceptions.StreamEOFError`.
        """
        raise NotImplementedError

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

        self._buffer = bytearray()

        self._finished = False

        self._flush_lock = asyncio.Lock()

    def buflen(self) -> int:
        """
        Return the length of the internal buffer.
        """
        return len(self._buffer)

    def write(self, data: bytes) -> None:
        """
        Write the data.
        """
        assert not self._finished, "Write after finished."
        self._buffer += data

    async def flush(self) -> None:
        """
        Give the writer a chance to flush the pending data
        out of the internal buffer.
        """
        async with self._flush_lock:
            if self._finished:
                return

            if self.buflen() == 0:
                return

            data = bytes(self._buffer)
            self._buffer.clear()  # type: ignore

            await self._impl._flush_data(self, data)

    async def finish(self) -> None:
        """
        Finish the Request or Response.
        """
        async with self._flush_lock:
            if self._finished:
                return

            self._finished = True

            if self.buflen() == 0:
                return

            data = bytes(self._buffer)
            self._buffer.clear()  # type: ignore

            await self._impl._flush_data(self, data, last_chunk=True)

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
        self, impl: "impls.BaseHttpImpl",
            req_initial: initials.HttpRequestInitial) -> None:
        super().__init__(impl)

        self._req_initial = req_initial

    @property
    def initial(self) -> initials.HttpRequestInitial:
        return self._req_initial

    @property
    def res_writer(self) -> "HttpResponseWriter":
        raise NotImplementedError

    async def write_response(
        self, res_initial: initials.HttpResponseInitial) -> \
            "HttpResponseWriter":
        raise NotImplementedError

    async def abort(self) -> None:
        await self._impl._abort_request(self)


class HttpRequestWriter(BaseHttpStreamWriter):
    def __init__(
        self, impl: "impls.BaseHttpImpl",
            req_initial: initials.HttpRequestInitial) -> None:
        super().__init__(impl)

        self._req_initial = req_initial

    @property
    def initial(self) -> initials.HttpRequestInitial:
        return self._req_initial

    @property
    def res_reader(self) -> "HttpResponseReader":
        raise NotImplementedError

    async def read_response(self) -> "HttpResponseReader":
        raise NotImplementedError

    async def abort(self) -> None:
        await self._impl._abort_request(self)


class HttpResponseReader(BaseHttpStreamReader):
    def __init__(
        self, impl: "impls.BaseHttpImpl",
        res_initial: initials.HttpResponseInitial,
            req_writer: HttpRequestWriter) -> None:
        super().__init__(impl)

        self._res_initial = res_initial
        self._req_writer = req_writer

    @property
    def initial(self) -> initials.HttpResponseInitial:
        return self._res_initial

    @property
    def req_writer(self) -> HttpRequestWriter:
        return self._req_writer

    async def abort(self) -> None:
        await self._impl._abort_request(self.req_writer)


class HttpResponseWriter(BaseHttpStreamWriter):
    def __init__(
        self, impl: "impls.BaseHttpImpl",
            res_initial: initials.HttpResponseInitial,
            req_reader: HttpRequestReader) -> None:
        super().__init__(impl)

        self._res_initial = res_initial
        self._req_reader = req_reader

    @property
    def initial(self) -> initials.HttpResponseInitial:
        return self._res_initial

    @property
    def req_reader(self) -> HttpRequestReader:
        return self._req_reader

    async def abort(self) -> None:
        await self._impl._abort_request(self.req_reader)
