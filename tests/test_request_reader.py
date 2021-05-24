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

import asyncio
import os

import helpers
import magicdict
import pytest

from magichttp import (
    HttpRequestInitial,
    HttpRequestMethod,
    HttpRequestReader,
    HttpVersion,
    MaxBufferLengthReachedError,
    ReadAbortedError,
    ReadFinishedError,
    ReadUnsatisfiableError,
    SeparatorNotFoundError,
)

_INITIAL = HttpRequestInitial(
    HttpRequestMethod.GET,
    uri="/",
    headers=magicdict.FrozenTolerantMagicDict(),
    scheme="https",
    version=HttpVersion.V1_1,
    authority="www.example.com",
)


def test_init() -> None:
    HttpRequestReader(helpers.ReaderDelegateMock(), initial=_INITIAL)


@pytest.mark.asyncio
async def test_read() -> None:
    reader = HttpRequestReader(helpers.ReaderDelegateMock(), initial=_INITIAL)
    await reader.read(0)


@pytest.mark.asyncio
async def test_read_wait() -> None:
    reader = HttpRequestReader(helpers.ReaderDelegateMock(), initial=_INITIAL)

    tsk = asyncio.create_task(reader.read(5))

    await asyncio.sleep(0)

    with pytest.raises(asyncio.InvalidStateError):
        tsk.result()

    data = os.urandom(5)

    reader._append_data(data)

    assert await tsk == data


@pytest.mark.asyncio
async def test_read_end() -> None:
    reader = HttpRequestReader(helpers.ReaderDelegateMock(), initial=_INITIAL)

    tsk = asyncio.create_task(reader.read(5))
    tsk_wait_end = asyncio.create_task(reader.wait_end())

    await asyncio.sleep(0)

    with pytest.raises(asyncio.InvalidStateError):
        tsk.result()

    with pytest.raises(asyncio.InvalidStateError):
        tsk_wait_end.result()

    reader._append_end(None)

    with pytest.raises(ReadFinishedError):
        await tsk

    await tsk_wait_end


@pytest.mark.asyncio
async def test_read_end_unsatisfiable() -> None:
    reader = HttpRequestReader(helpers.ReaderDelegateMock(), initial=_INITIAL)

    reader._append_data(os.urandom(3))

    tsk = asyncio.create_task(reader.read(5, exactly=True))

    await asyncio.sleep(0)

    with pytest.raises(asyncio.InvalidStateError):
        tsk.result()

    reader._append_end(None)

    with pytest.raises(ReadUnsatisfiableError):
        await tsk


@pytest.mark.asyncio
async def test_read_less() -> None:
    reader = HttpRequestReader(helpers.ReaderDelegateMock(), initial=_INITIAL)

    data = os.urandom(3)

    reader._append_data(data)

    assert await reader.read(5) == data


@pytest.mark.asyncio
async def test_read_more() -> None:
    reader = HttpRequestReader(helpers.ReaderDelegateMock(), initial=_INITIAL)

    data = os.urandom(6)

    reader._append_data(data)

    assert await reader.read(5) == data[:5]


@pytest.mark.asyncio
async def test_read_exactly() -> None:
    reader = HttpRequestReader(helpers.ReaderDelegateMock(), initial=_INITIAL)

    tsk = asyncio.create_task(reader.read(5, exactly=True))

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


@pytest.mark.asyncio
async def test_read_till_end() -> None:
    reader = HttpRequestReader(helpers.ReaderDelegateMock(), initial=_INITIAL)

    data_chunks = []

    tsk = asyncio.create_task(reader.read())

    for _ in range(0, 5):
        await asyncio.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        data = os.urandom(5)
        reader._append_data(data)
        data_chunks.append(data)

    reader._append_end(None)

    assert await tsk == b"".join(data_chunks)


@pytest.mark.asyncio
async def test_max_buf_len() -> None:
    delegate_mock = helpers.ReaderDelegateMock()

    reader = HttpRequestReader(delegate_mock, initial=_INITIAL)

    reader.max_buf_len = 64 * 1024  # 64K

    data = bytearray()

    tsk = asyncio.create_task(reader.read())

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


@pytest.mark.asyncio
async def test_read_until() -> None:
    delegate_mock = helpers.ReaderDelegateMock()

    reader = HttpRequestReader(delegate_mock, initial=_INITIAL)

    reader.max_buf_len = 4 * 1024  # 4K

    data = bytearray()

    tsk = asyncio.create_task(reader.read_until())

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

    data2 = b"00000"

    tsk = asyncio.create_task(reader.read_until(keep_separator=False))

    await asyncio.sleep(0)

    with pytest.raises(asyncio.InvalidStateError):
        tsk.result()

    reader._append_data(data2)

    await asyncio.sleep(0)

    with pytest.raises(asyncio.InvalidStateError):
        tsk.result()

    reader._append_data(b"\n")

    assert await tsk == data2

    reader._append_data(data2)
    reader._append_end(None)

    with pytest.raises(SeparatorNotFoundError):
        await reader.read_until()


@pytest.mark.asyncio
async def test_abort() -> None:
    mock = helpers.ReaderDelegateMock()
    reader = HttpRequestReader(mock, initial=_INITIAL)

    assert mock.aborted is False

    reader.abort()

    assert mock.aborted is True

    reader._append_end(ReadAbortedError())

    with pytest.raises(ReadAbortedError):
        await reader.read()


def test_initial() -> None:
    initial_mock = HttpRequestInitial(
        HttpRequestMethod.GET,
        uri="/",
        headers=magicdict.FrozenTolerantMagicDict(),
        scheme="https",
        version=HttpVersion.V1_1,
        authority="www.example.com",
    )

    reader = HttpRequestReader(
        helpers.ReaderDelegateMock(), initial=initial_mock
    )

    assert initial_mock is reader.initial


def test_write_response() -> None:
    mock = helpers.ReaderDelegateMock()
    reader = HttpRequestReader(mock, initial=_INITIAL)

    with pytest.raises(AttributeError):
        reader.writer

    writer = reader.write_response(204)

    assert writer is mock.writer_mock
    assert reader.writer is writer
