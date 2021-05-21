#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2020 Kaede Hoshikawa
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

import asyncio
import os
import time

import helpers
import magicdict
import pytest

from magichttp import (
    HttpRequestInitial,
    HttpRequestMethod,
    HttpRequestWriter,
    HttpResponseInitial,
    HttpStatusCode,
    HttpVersion,
    WriteAbortedError,
    WriteAfterFinishedError,
)

_INITIAL = HttpRequestInitial(
    HttpRequestMethod.GET,
    uri="/",
    headers=magicdict.FrozenTolerantMagicDict(),
    scheme="https",
    version=HttpVersion.V1_1,
    authority="www.example.com",
)

_RES_INITIAL = HttpResponseInitial(
    HttpStatusCode.OK,
    version=HttpVersion.V1_1,
    headers=magicdict.FrozenTolerantMagicDict(),
)


def test_init() -> None:
    HttpRequestWriter(helpers.WriterDelegateMock(), initial=_INITIAL)


def test_write() -> None:
    mock = helpers.WriterDelegateMock()
    writer = HttpRequestWriter(mock, initial=_INITIAL)

    writer.write(b"")
    assert mock.write_called is False

    data = os.urandom(5)

    writer.write(data)
    assert mock.write_called is True
    assert mock.data_pieces == [data]

    writer.finish()
    with pytest.raises(WriteAfterFinishedError):
        writer.write(os.urandom(1))


def test_write_err() -> None:
    mock = helpers.WriterDelegateMock()
    writer = HttpRequestWriter(mock, initial=_INITIAL)

    mock._exc = WriteAbortedError()

    with pytest.raises(WriteAbortedError):
        writer.write(os.urandom(1))

    with pytest.raises(WriteAbortedError):
        writer.write(os.urandom(1))


@pytest.mark.asyncio
async def test_flush_err() -> None:
    mock = helpers.WriterDelegateMock()
    writer = HttpRequestWriter(mock, initial=_INITIAL)

    mock.flush_event.set()

    mock._exc = WriteAbortedError()

    with pytest.raises(WriteAbortedError):
        await writer.flush()

    with pytest.raises(WriteAbortedError):
        await writer.flush()


@pytest.mark.asyncio
async def test_finish() -> None:
    mock = helpers.WriterDelegateMock()
    writer = HttpRequestWriter(mock, initial=_INITIAL)

    assert writer.finished() is False

    finish_time = -1.0
    tsk_running = asyncio.Event()

    async def _wait_finish_task() -> None:
        nonlocal finish_time

        tsk_running.set()
        await writer.wait_finished()
        finish_time = time.time()

    tsk = asyncio.create_task(_wait_finish_task())

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


def test_finish_err() -> None:
    mock = helpers.WriterDelegateMock()
    writer = HttpRequestWriter(mock, initial=_INITIAL)

    mock._exc = WriteAbortedError()

    with pytest.raises(WriteAbortedError):
        writer.finish()

    with pytest.raises(WriteAbortedError):
        writer.finish()


@pytest.mark.asyncio
async def test_flush() -> None:
    mock = helpers.WriterDelegateMock()
    writer = HttpRequestWriter(mock, initial=_INITIAL)

    flush_time = -1.0
    tsk_running = asyncio.Event()

    async def _flush_task() -> None:
        nonlocal flush_time

        tsk_running.set()
        await writer.flush()
        flush_time = time.time()

    tsk = asyncio.create_task(_flush_task())

    await tsk_running.wait()

    mock.flush_event.set()
    event_time = time.time()

    await tsk

    assert event_time < flush_time


def test_abort() -> None:
    mock = helpers.WriterDelegateMock()
    writer = HttpRequestWriter(mock, initial=_INITIAL)

    assert mock.aborted is False

    writer.abort()

    assert mock.aborted is True


def test_initial() -> None:
    writer = HttpRequestWriter(helpers.WriterDelegateMock(), initial=_INITIAL)

    assert _INITIAL is writer.initial


@pytest.mark.asyncio
async def test_read_response() -> None:
    mock = helpers.WriterDelegateMock()
    writer = HttpRequestWriter(mock, initial=_INITIAL)

    with pytest.raises(AttributeError):
        writer.reader

    reader = await writer.read_response()

    assert reader is mock.reader_mock
    assert writer.reader is reader
