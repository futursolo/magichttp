#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2021 Kaede Hoshikawa
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

import abc

from .. import io_compat


class AbstractStreamReader(io_compat.WithIo):
    """
    The abstract base class of all stream readers.
    """

    @abc.abstractmethod
    def __len__(self) -> int:
        """
        Return length of the internal buffer.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def max_buf_len(self) -> int:
        """
        Return the current maximum buffer length.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def read(self, n: int = -1, exactly: bool = False) -> bytes:
        """
        Read at most n bytes data or if exactly is `True`,
        read exactly n bytes data. If the end has been reached before
        the buffer has the length of data asked, it will
        raise a :class:`ReadUnsatisfiableError`.

        If n is less than 0, it will read until the end of the stream.

        When :method:`.end_reached()` is `True`, this method will raise any
        errors occurred during the read or a
        :class:`exceptions.ReadFinishedError`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def read_until(
        self, separator: bytes = b"\n", *, keep_separator: bool = True
    ) -> bytes:
        """
        Read until the separator has been found.

        When the max size of the buffer has been reached,
        and the separator is not found, this method will raise
        a :class:`MaxBufferLengthReachedError`.
        Similarly, if the end has been reached before found the separator
        it will raise a :class:`SeparatorNotFoundError`.

        When :method:`.end_reached()` is `True`, this method will raise any
        errors occurred during the read or a
        :class:`exceptions.ReadFinishedError`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def reading(self) -> bool:
        """
        Return `True` if the reader is reading.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def end_reached(self) -> bool:
        """
        Return `True` if the reader reached the end of the stream.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def abort(self) -> None:
        """
        Abort the reader without waiting for .

        This also aborts the corresponding writer (if applicable).
        """
        raise NotImplementedError


class AbstractStreamWriter(io_compat.WithIo):
    """
    The abstract base class of all stream writers.
    """

    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        """
        Add data to writer buffer.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def finish(self) -> None:
        """
        Finish writing.

        The behaviour differs depending on the implementation.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def flush(self) -> None:
        """
        Give the writer a chance to flush the pending data
        out of the internal buffer.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def writing(self) -> bool:
        """
        Return `True` if the writer is writing.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def finished(self) -> bool:
        """
        Return `True` if the writing has finished.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def abort(self) -> None:
        """
        Abort the writer without flushing the internal buffer.

        This also aborts the corresponding reader (if applicable).
        """
        raise NotImplementedError
