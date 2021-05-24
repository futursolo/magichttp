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

from collections import deque
from typing import Deque, Optional
import abc
import contextlib

from .. import exceptions, io_compat
from ._abc import AbstractStreamReader, AbstractStreamWriter


class BaseStreamReader(AbstractStreamReader):
    """
    A base class of buffered stream readers.
    """

    def __init__(
        self, max_buf_len: int = 64 * 1024  # Default buffer size is 64K
    ) -> None:
        self.__buf: Deque[bytes] = deque()
        self.__buf_len = 0

        self.__should_read = self._io.create_event()
        self.__should_read.set()
        self.__data_ready = self._io.create_event()

        self.__read_lock = self._io.create_lock()

        self.__end_received = False
        self.__exc: Optional[Exception] = None

        self.__max_buf_len = max_buf_len

        self.__read_loop: Optional[io_compat.AbstractTask[None]] = None

    @abc.abstractmethod
    async def _read_data(self) -> bytes:
        """
        Read some data.

        This method should return some data or raise EOFError if there's no
        data.

        It should also raise any exceptions raised by the socket.

        Readers should implement this method to.

        If the underlying requires a "sizehint", the recommended size is the
        :code:`BaseStreamReader.max_buf_len`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def _abort_stream(self) -> None:
        """
        Abort the stream.

        This method should abort the stream immediately.

        When this method is called. self._read_data should not be awaiting /
        already cancelled.
        """
        raise NotImplementedError

    async def _read_until_end(self) -> None:
        """
        The read loop.

        This task will read until an EOFError is received unless aborted
        (cancelled).
        """
        while True:
            try:
                await self.__should_read.wait()

                data = await self._read_data()
                self.__buf_len += len(data)
                self.__buf.append(data)

                if len(self) > self.max_buf_len:
                    self.__should_read.clear()

            except self._io.CancelledError:
                if self.__exc is None:
                    self.__exc = exceptions.ReadAbortedError(
                        "Read loop is cancelled."
                    )
                self.__should_read.clear()

                await self._abort_stream()

                raise

            except EOFError:
                self.__end_received = True
                self.__should_read.clear()
                return

            except Exception as e:
                self.__exc = e
                self.__should_read.clear()
                return

            finally:
                self.__data_ready.set()

    async def _start_read_loop(self) -> None:
        """
        Start the read loop.

        This method should be called as soon as the reader becomes readable.

        You can only call this method once.
        """
        if self.__read_loop is not None:
            raise RuntimeError("Read loop has been spawned.")

        self.__read_loop = await self._io.create_task(self._read_until_end())

    async def _wait_read_loop(self) -> None:
        with contextlib.suppress(BaseException):
            if not self.__read_loop:
                raise RuntimeError("Read loop is not spawned.")

            await self.__read_loop

    def __len__(self) -> int:
        return self.__buf_len

    @property
    def max_buf_len(self) -> int:
        """
        Return the current maximum buffer length.
        """
        return self.__max_buf_len

    @max_buf_len.setter
    def max_buf_len(self, max_buf_len: int) -> None:
        """
        Set a new current maximum buffer length.
        """
        self.__max_buf_len = max_buf_len
        if self.__buf_len <= self.__max_buf_len:
            self.__should_read.set()

    def _raise_exc_if_finished(self) -> None:
        if not self.end_reached():
            return

        if self.__exc:
            raise self.__exc

        raise exceptions.ReadFinishedError

    def _raise_exc_if_end_appended(self) -> None:
        if self.__exc:
            raise self.__exc

        if not self.__end_received:
            return

        raise exceptions.ReadFinishedError

    def _maybe_continue_reading(self) -> None:
        if (
            len(self) < self.max_buf_len
            and not self.__end_received
            and not self.__exc
        ):
            self.__should_read.set()

    async def read(self, n: int = -1, exactly: bool = False) -> bytes:
        async with self.__read_lock:
            self._raise_exc_if_finished()

            if n == 0:
                return b""

            if exactly:
                if n < 0:  # pragma: no cover
                    raise ValueError(
                        "You MUST sepcify the length of the data "
                        "if exactly is True."
                    )

                if n > self.max_buf_len:  # pragma: no cover
                    raise ValueError(
                        "The length provided cannot be larger "
                        "than the max buffer length."
                    )

                while len(self) < n:
                    try:
                        self._raise_exc_if_end_appended()

                        self.__data_ready.clear()
                        await self.__data_ready.wait()

                    except self._io.CancelledError:  # pragma: no cover
                        raise

                    except Exception as e:
                        raise exceptions.ReadUnsatisfiableError from e

            elif n < 0:
                while True:
                    if len(self) > self.max_buf_len:
                        raise exceptions.MaxBufferLengthReachedError

                    try:
                        self._raise_exc_if_end_appended()

                        self.__data_ready.clear()
                        await self.__data_ready.wait()

                    except self._io.CancelledError:  # pragma: no cover
                        raise

                    except Exception:
                        if self.__buf:
                            data = b"".join(self.__buf)
                            self.__buf = deque()
                            self.__buf_len = 0

                            # Shouldn't be able to continue reading anyways,
                            # Calling to be consistent.
                            self._maybe_continue_reading()
                            return data

                        raise

            elif len(self) == 0:
                self._raise_exc_if_end_appended()

                self.__data_ready.clear()
                await self.__data_ready.wait()

            self._raise_exc_if_finished()

            data = self.__buf.popleft()

            if exactly:
                while len(data) < n:  # Should have enough data by now
                    data += self.__buf.popleft()

            if len(data) <= n:
                self.__buf_len -= len(data)
                self._maybe_continue_reading()
                return data

            else:
                self.__buf_len -= n
                self.__buf.appendleft(data[n:])
                self._maybe_continue_reading()
                return data[:n]

    async def read_until(
        self, separator: bytes = b"\n", *, keep_separator: bool = True
    ) -> bytes:
        async with self.__read_lock:
            self._raise_exc_if_finished()

            start_pos = 0

            while True:
                data = b"".join(self.__buf)
                self.__buf = deque()

                separator_pos = data.find(separator, start_pos)

                if separator_pos != -1:
                    break

                self.__buf.appendleft(data)

                if len(self) > self.max_buf_len:
                    raise exceptions.MaxBufferLengthReachedError

                try:
                    self._raise_exc_if_end_appended()

                    self.__data_ready.clear()
                    await self.__data_ready.wait()

                except self._io.CancelledError:  # pragma: no cover
                    raise

                except Exception as e:
                    if len(self) > 0:
                        raise exceptions.SeparatorNotFoundError from e

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

            self.__buf.appendleft(data[full_pos:])
            self.__buf_len -= full_pos

            self._maybe_continue_reading()
            return data[:data_pos]

    def reading(self) -> bool:
        return self.__should_read.is_set()

    def end_reached(self) -> bool:
        return (
            self.__end_received
            or self.__exc is not None
            and self.__buf_len == 0
        )

    async def abort(self) -> None:
        if self.__read_loop:
            if self.__read_loop.cancelled():
                return

            await self.__read_loop.cancel(wait=True)


class BaseStreamWriter(AbstractStreamWriter):
    """
    A base class of stream writers.
    """

    def __init__(self) -> None:
        self.__buf: Deque[bytes] = deque()

        self.__should_write = self._io.create_event()
        self.__data_flushed = self._io.create_event()
        self.__data_flushed.set()

        self.__finished = False

        self.__write_loop: Optional[io_compat.AbstractTask[None]] = None
        self.__exc: Optional[Exception] = None

    @abc.abstractmethod
    async def _write_data(self, data: bytes) -> None:
        """
        Write some data.

        This method should wait until data is flushed if necessary.

        This should be equivalent to :code:`socket.sendall`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def _finish_writing(self) -> None:
        """
        Called when there will not be any data coming.

        This should write an EOF or call :code:`sock.shutdown(SHUT_WR)` if
        applicable.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def _abort_stream(self) -> None:
        """
        Abort the stream.

        This method should abort the stream immediately.

        When this method is called. self._write_data should not be awaiting /
        already cancelled.
        """
        raise NotImplementedError

    async def _write_until_finish(self) -> None:
        """
        The write loop.

        This task will write until finish unless aborted
        (cancelled).
        """
        while True:
            try:
                if not self.__buf:
                    self.__should_write.clear()
                    await self.__should_write.wait()

                self.__data_flushed.clear()
                if self.__buf:
                    data = self.__buf.popleft()
                    await self._write_data(data)

                if self.__finished:
                    await self._finish_writing()
                    self.__should_write.clear()
                    return

            except self._io.CancelledError:
                self.__exc = exceptions.WriteAbortedError(
                    "Write loop is cancelled."
                )
                await self._abort_stream()

            finally:
                self.__data_flushed.set()

    async def _start_write_loop(self) -> None:
        """
        Start the write loop.

        This method should be called as soon as the writer becomes writable.

        You can only call this method once.
        """
        if self.__write_loop is not None:
            raise RuntimeError("Write loop has been spawned.")

        self.__write_loop = await self._io.create_task(
            self._write_until_finish()
        )

    async def _wait_write_loop(self) -> None:
        with contextlib.suppress(BaseException):
            if not self.__write_loop:
                raise RuntimeError("Write loop is not spawned.")

            await self.__write_loop

    def write(self, data: bytes) -> None:
        if self.__exc:
            raise self.__exc

        if self.__finished:
            raise exceptions.ReadFinishedError("Writing is finished.")

        self.__buf.append(data)
        self.__should_write.set()

    def finish(self) -> None:
        if self.__exc:
            raise self.__exc

        self.__should_write.set()
        self.__finished = True

    async def flush(self) -> None:
        await self.__data_flushed.wait()
        if self.__exc:
            raise self.__exc

    def writing(self) -> bool:
        """
        Return `True` if the writer is writing.
        """
        return self.__should_write.is_set()

    def finished(self) -> bool:
        """
        Return `True` if writing has finished.
        """
        return self.__finished or self.__exc is not None

    async def abort(self) -> None:
        """
        Abort the writer without flushing the internal buffer.

        This also aborts the corresponding reader (if applicable).
        """
        if self.__write_loop:
            if self.__write_loop.cancelled():
                return

            await self.__write_loop.cancel(wait=True)
