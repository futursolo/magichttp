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

from magichttp import HttpRequestWriter, HttpResponseWriter
from magichttp.writers import HttpRequestWriterDelegate, \
    HttpResponseWriterDelegate
from magichttp import WriteAfterFinishedError, WriteAbortedError

from _helper import TestHelper

import asyncio
import os
import pytest
import time


helper = TestHelper()


class HttpWriterDelegateMock(
        HttpRequestWriterDelegate, HttpResponseWriterDelegate):
    def __init__(self):
        self.write_called = False
        self.data_pieces = []
        self.finished = False

        self.flush_event = asyncio.Event()

        self.aborted = False

        self.reader_mock = None

        self._exc = None

    def write_data(self, data, finished):
        self.write_called = True
        self.data_pieces.append(data)
        self.finished = finished

        if self._exc:
            raise self._exc

    async def flush_buf(self):
        await self.flush_event.wait()

        if self._exc:
            raise self._exc

    def abort(self):
        self.aborted = True

    async def read_response(self):
        if self.reader_mock is None:
            self.reader_mock = object()

        return self.reader_mock


class HttpRequestWriterTestCase:
    def test_init(self):
        HttpRequestWriter(object(), initial=object())

    def test_write(self):
        mock = HttpWriterDelegateMock()
        writer = HttpRequestWriter(mock, initial=object())

        writer.write(b"")
        assert mock.write_called is False

        data = os.urandom(5)

        writer.write(data)
        assert mock.write_called is True
        assert mock.data_pieces == [data]

        writer.finish()
        with pytest.raises(WriteAfterFinishedError):
            writer.write(os.urandom(1))

    def test_write_err(self):
        mock = HttpWriterDelegateMock()
        writer = HttpRequestWriter(mock, initial=object())

        mock._exc = WriteAbortedError()

        with pytest.raises(WriteAbortedError):
            writer.write(os.urandom(1))

        with pytest.raises(WriteAbortedError):
            writer.write(os.urandom(1))

    @helper.run_async_test
    async def test_flush_err(self):
        mock = HttpWriterDelegateMock()
        writer = HttpRequestWriter(mock, initial=object())

        mock.flush_event.set()

        mock._exc = WriteAbortedError()

        with pytest.raises(WriteAbortedError):
            await writer.flush()

        with pytest.raises(WriteAbortedError):
            await writer.flush()

    @helper.run_async_test
    async def test_finish(self):
        mock = HttpWriterDelegateMock()
        writer = HttpRequestWriter(mock, initial=object())

        assert writer.finished() is False

        finish_time = -1
        tsk_running = asyncio.Event()

        async def _wait_finish_task():
            nonlocal finish_time

            tsk_running.set()
            await writer.wait_finished()
            finish_time = time.time()

        tsk = helper.loop.create_task(_wait_finish_task())

        await tsk_running.wait()

        writer.finish()
        event_time = time.time()

        assert mock.write_called is True
        assert mock.finished is True
        assert mock.data_pieces == [b""]

        with pytest.raises(WriteAfterFinishedError):
            writer.write(os.urandom(1))

        assert writer.finished() is True

        await tsk

        await writer.flush()

        writer.finish()

        with pytest.raises(WriteAfterFinishedError):
            writer.finish(os.urandom(1))

        assert event_time < finish_time

    def test_finish_err(self):
        mock = HttpWriterDelegateMock()
        writer = HttpRequestWriter(mock, initial=object())

        mock._exc = WriteAbortedError()

        with pytest.raises(WriteAbortedError):
            writer.finish()

        with pytest.raises(WriteAbortedError):
            writer.finish()

    @helper.run_async_test
    async def test_flush(self):
        mock = HttpWriterDelegateMock()
        writer = HttpRequestWriter(mock, initial=object())

        flush_time = -1
        tsk_running = asyncio.Event()

        async def _flush_task():
            nonlocal flush_time

            tsk_running.set()
            await writer.flush()
            flush_time = time.time()

        tsk = helper.loop.create_task(_flush_task())

        await tsk_running.wait()

        mock.flush_event.set()
        event_time = time.time()

        await tsk

        assert event_time < flush_time

    def test_abort(self):
        mock = HttpWriterDelegateMock()
        writer = HttpRequestWriter(mock, initial=object())

        assert mock.aborted is False

        writer.abort()

        assert mock.aborted is True

    def test_initial(self):
        initial_mock = object()

        writer = HttpRequestWriter(object(), initial=initial_mock)

        assert initial_mock is writer.initial

    @helper.run_async_test
    async def test_read_response(self):
        mock = HttpWriterDelegateMock()
        writer = HttpRequestWriter(mock, initial=object())

        with pytest.raises(AttributeError):
            writer.reader

        reader = await writer.read_response()

        assert reader is mock.reader_mock
        assert writer.reader is reader


class HttpResponseWriterTestCase:
    def test_init(self):
        HttpResponseWriter(object(), initial=object(), reader=object())

    def test_initial(self):
        initial_mock = object()

        writer = HttpResponseWriter(
            object(), initial=initial_mock, reader=object())

        assert initial_mock is writer.initial

    def test_reader(self):
        reader_mock = object()

        writer = HttpResponseWriter(
            object(), reader=reader_mock, initial=object())

        assert reader_mock is writer.reader

    def test_reader_attr_err(self):
        writer = HttpResponseWriter(
            object(), reader=None, initial=object())

        with pytest.raises(AttributeError):
            writer.reader
