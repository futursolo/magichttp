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

from typing import Optional, Union, Mapping, Iterable, Tuple

from . import stream_mgrs

from .. import protocols
from .. import readers
from .. import writers

import abc
import asyncio
import typing

if typing.TYPE_CHECKING:
    from .. import constants  # noqa: F401

_HeaderType = Union[
    Mapping[str, str],
    Iterable[Tuple[str, str]]]


class BaseH1Impl(protocols.BaseHttpProtocolDelegate):
    def __init__(
            self, protocol: protocols.BaseHttpProtocol) -> None:
        self._protocol = protocol
        self._transport = protocol.transport

        self._buf = bytearray()

        self._reading_paused = False

    def _pause_reading(self) -> None:
        if self._reading_paused:
            return

        self._transport.pause_reading()

        self._reading_paused = True

    def _resume_reading(self) -> None:
        if not self._reading_paused:
            return

        self._transport.resume_reading()

        self._reading_paused = False

    @property
    @abc.abstractmethod
    def _stream(self) -> stream_mgrs.BaseH1StreamManager:  # pragma: no cover
        raise NotImplementedError

    def data_received(self, data: bytes) -> None:
        self._buf += data

        self._stream._data_appended()

    def eof_received(self) -> None:
        if not self._stream._finished():
            self._stream._eof_received()

        else:
            self._transport.close()

    def close(self) -> None:
        if not self._stream._finished():
            self._stream._mark_as_last_stream()

        else:
            self._transport.close()

    @abc.abstractmethod
    def _set_abort_error(
        self,
            __cause: Optional[BaseException]) -> None:  # pragma: no cover
        raise NotImplementedError

    def abort(self) -> None:
        self._set_abort_error(None)

        self._transport.close()

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        if exc:
            self._set_abort_error(exc)

        else:
            self._stream._connection_lost(None)


class H1ServerImpl(BaseH1Impl, protocols.HttpServerProtocolDelegate):
    def __init__(
        self, protocol: protocols.HttpServerProtocol,
            max_initial_size: int) -> None:
        super().__init__(protocol)

        self._max_initial_size = max_initial_size

        self._exc: Optional[readers.ReadAbortedError] = None

        self.__stream = stream_mgrs.H1ServerStreamManager(
            self, self._buf, max_initial_size)

        self._read_request_lock = asyncio.Lock()
        self._request_read = False

    @property
    def _stream(self) -> stream_mgrs.H1ServerStreamManager:
        return self.__stream

    async def read_request(self) -> readers.HttpRequestReader:
        async with self._read_request_lock:
            if self._request_read:
                await self._stream._wait_finished()

                if self._transport.is_closing():
                    if self._exc:
                        raise self._exc

                    raise readers.ReadFinishedError

                self._resume_reading()

                self.__stream = stream_mgrs.H1ServerStreamManager(
                    self, self._buf, self._max_initial_size)
                self._request_read = False

            reader = await self._stream._read_request()
            self._request_read = True

            return reader

    def _set_abort_error(self, __cause: Optional[BaseException]) -> None:
        if self._exc is not None:
            return

        if __cause:
            self._exc = readers.ReadAbortedError(
                "Read aborted due to socket error.")
            self._exc.__cause__ = __cause

        else:
            self._exc = readers.ReadAbortedError("Read aborted by user.")

        self._stream._set_abort_error(__cause)


class H1ClientImpl(BaseH1Impl, protocols.HttpClientProtocolDelegate):
    def __init__(
        self, protocol: protocols.HttpClientProtocol, max_initial_size: int,
            http_version: "constants.HttpVersion") -> None:
        super().__init__(protocol)

        self._http_version = http_version
        self._max_initial_size = max_initial_size

        self._exc: Optional[writers.WriteAbortedError] = None

        self.__stream = stream_mgrs.H1ClientStreamManager(
            self, self._buf, max_initial_size, http_version)

        self._write_request_lock = asyncio.Lock()
        self._request_written = False

    @property
    def _stream(self) -> stream_mgrs.H1ClientStreamManager:
        return self.__stream

    async def write_request(
        self, method: "constants.HttpRequestMethod", *,
        uri: str, authority: Optional[str],
        scheme: Optional[str],
            headers: Optional[_HeaderType]) -> writers.HttpRequestWriter:
        async with self._write_request_lock:
            if self._request_written:
                await self._stream._wait_finished()

                if self._transport.is_closing():
                    if self._exc:
                        raise self._exc

                    raise writers.WriteAfterFinishedError

                self.__stream = stream_mgrs.H1ClientStreamManager(
                    self, self._buf, self._max_initial_size,
                    self._http_version)
                self._request_written = False

            writer = self._stream._write_request(
                method, uri=uri, authority=authority, scheme=scheme,
                headers=headers)
            self._request_written = True

            self._resume_reading()

            return writer

    def _set_abort_error(self, __cause: Optional[BaseException]) -> None:
        if self._exc is not None:
            return

        if __cause:
            self._exc = writers.WriteAbortedError(
                "Write aborted due to socket error.")
            self._exc.__cause__ = __cause

        else:
            self._exc = writers.WriteAbortedError("Write aborted by user.")

        self._stream._set_abort_error(__cause)
