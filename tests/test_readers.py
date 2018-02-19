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

from magichttp.readers import HttpRequestReaderDelegate, \
    HttpResponseReaderDelegate
from magichttp import HttpRequestReader, HttpResponseReader, \
    ReadFinishedError, ReadUnsatisfiableError, MaxBufferLengthReachedError, \
    SeparatorNotFoundError, ReadAbortedError

from _helper import TestHelper

import pytest
import asyncio
import os


helper = TestHelper()


class ReaderDelegateMock(
        HttpRequestReaderDelegate, HttpResponseReaderDelegate):
    def __init__(self):
        self.paused = False
        self.aborted = False
        self.writer_mock = None

    def pause_reading(self):
        self.paused = True

    def resume_reading(self):
        self.paused = False

    def abort(self):
        self.aborted = True

    def write_response(self, *args, **kwargs):
        self.writer_mock = object()
        return self.writer_mock


class HttpRequestReaderTestCase:
    def test_init(self):
        HttpRequestReader(object(), initial=object())

    @helper.run_async_test
    async def test_read(self):
        reader = HttpRequestReader(ReaderDelegateMock(), initial=object())
        await reader.read(0)

    @helper.run_async_test
    async def test_read_wait(self):
        reader = HttpRequestReader(ReaderDelegateMock(), initial=object())

        tsk = helper.loop.create_task(reader.read(5))

        await asyncio.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        data = os.urandom(5)

        reader._append_data(data)

        assert await tsk == data

    @helper.run_async_test
    async def test_read_end(self):
        reader = HttpRequestReader(ReaderDelegateMock(), initial=object())

        tsk = helper.loop.create_task(reader.read(5))
        tsk_wait_end = helper.loop.create_task(reader.wait_end())

        await asyncio.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        with pytest.raises(asyncio.InvalidStateError):
            tsk_wait_end.result()

        reader._append_end(None)

        with pytest.raises(ReadFinishedError):
            await tsk

        await tsk_wait_end

    @helper.run_async_test
    async def test_read_end_unsatisfiable(self):
        reader = HttpRequestReader(ReaderDelegateMock(), initial=object())

        reader._append_data(os.urandom(3))

        tsk = helper.loop.create_task(reader.read(5, exactly=True))

        await asyncio.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        reader._append_end(None)

        with pytest.raises(ReadUnsatisfiableError):
            await tsk

    @helper.run_async_test
    async def test_read_less(self):
        reader = HttpRequestReader(ReaderDelegateMock(), initial=object())

        data = os.urandom(3)

        reader._append_data(data)

        assert await reader.read(5) == data

    @helper.run_async_test
    async def test_read_more(self):
        reader = HttpRequestReader(ReaderDelegateMock(), initial=object())

        data = os.urandom(6)

        reader._append_data(data)

        assert await reader.read(5) == data[:5]

    @helper.run_async_test
    async def test_read_exactly(self):
        reader = HttpRequestReader(ReaderDelegateMock(), initial=object())

        tsk = helper.loop.create_task(reader.read(5, exactly=True))

        await asyncio.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        data1 = os.urandom(3)

        reader._append_data(data1)

        await asyncio.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        data2 = os.urandom(3)

        reader._append_data(data2)

        assert await tsk == data1 + data2[:2]

    @helper.run_async_test
    async def test_read_till_end(self):
        reader = HttpRequestReader(ReaderDelegateMock(), initial=object())

        data_chunks = []

        tsk = helper.loop.create_task(reader.read())

        for _ in range(0, 5):
            await asyncio.sleep(0)

            with pytest.raises(asyncio.InvalidStateError):
                tsk.result()

            data = os.urandom(5)
            reader._append_data(data)
            data_chunks.append(data)

        reader._append_end(None)

        assert await tsk == b"".join(data_chunks)

    @helper.run_async_test
    async def test_max_buf_len(self):
        delegate_mock = ReaderDelegateMock()

        reader = HttpRequestReader(delegate_mock, initial=object())

        reader.max_buf_len = 64 * 1024  # 64K

        data = bytearray()

        tsk = helper.loop.create_task(reader.read())

        while len(data) <= reader.max_buf_len:
            await asyncio.sleep(0)

            with pytest.raises(asyncio.InvalidStateError):
                tsk.result()

            assert delegate_mock.paused is False

            chunk = os.urandom(1024)

            data += chunk

            reader._append_data(chunk)

        assert delegate_mock.paused is True

        with pytest.raises(MaxBufferLengthReachedError):
            await tsk

        reader.max_buf_len = 128 * 1024  # 128K

        reader._append_end(None)

        assert await reader.read() == data

    @helper.run_async_test
    async def test_read_until(self):
        delegate_mock = ReaderDelegateMock()

        reader = HttpRequestReader(delegate_mock, initial=object())

        reader.max_buf_len = 4 * 1024  # 4K

        data = bytearray()

        tsk = helper.loop.create_task(reader.read_until())

        while len(data) <= reader.max_buf_len:
            await asyncio.sleep(0)

            with pytest.raises(asyncio.InvalidStateError):
                tsk.result()

            assert delegate_mock.paused is False

            chunk = b"0" * 1024

            data += chunk

            reader._append_data(chunk)

        assert delegate_mock.paused is True

        with pytest.raises(MaxBufferLengthReachedError):
            await tsk

        reader.max_buf_len = 5 * 1024  # 5K

        data += b"\n"
        reader._append_data(b"\n")

        assert await reader.read_until() == data

        data = b"00000"

        tsk = helper.loop.create_task(reader.read_until(keep_separator=False))

        await asyncio.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        reader._append_data(data)

        await asyncio.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        reader._append_data(b"\n")

        assert await tsk == data

        reader._append_data(data)
        reader._append_end(None)

        with pytest.raises(SeparatorNotFoundError):
            await reader.read_until()

    @helper.run_async_test
    async def test_abort(self):
        mock = ReaderDelegateMock()
        reader = HttpRequestReader(mock, initial=object())

        assert mock.aborted is False

        reader.abort()

        assert mock.aborted is True

        reader._append_end(ReadAbortedError())

        with pytest.raises(ReadAbortedError):
            await reader.read()

    def test_initial(self):
        initial_mock = object()

        reader = HttpRequestReader(object(), initial=initial_mock)

        assert initial_mock is reader.initial

    def test_write_response(self):
        mock = ReaderDelegateMock()
        reader = HttpRequestReader(mock, initial=object())

        with pytest.raises(AttributeError):
            reader.writer

        writer = reader.write_response(204)

        assert writer is mock.writer_mock
        assert reader.writer is writer


class HttpResponseReaderTestCase:
    def test_init(self):
        HttpResponseReader(
            object(), initial=object(), writer=object())

    def test_initial(self):
        initial_mock = object()

        reader = HttpResponseReader(
            object(), initial=initial_mock, writer=object())

        assert initial_mock is reader.initial

    def test_writer(self):
        writer_mock = object()

        reader = HttpResponseReader(
            object(), writer=writer_mock, initial=object())

        assert writer_mock is reader.writer
