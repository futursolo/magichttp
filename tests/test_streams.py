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
import pytest

from magichttp import (
    MaxBufferLengthReachedError,
    ReadAbortedError,
    ReadFinishedError,
    ReadUnsatisfiableError,
    SeparatorNotFoundError,
)
from magichttp.streams import TcpStream

_BIG_SIZE = 1024 * 1024


@pytest.mark.asyncio
async def test_tcp_stream_connect_read(
    mocked_server: helpers.MockedServer,
) -> None:
    stream = await TcpStream.connect("localhost", port=mocked_server.port)

    send_data = os.urandom(_BIG_SIZE)
    stream.write(send_data)
    stream.finish()

    proto = await mocked_server.await_proto()
    assert proto.transport

    while True:
        await stream._io.sleep(0.01)
        if len(b"".join(proto.data_chunks)) == _BIG_SIZE:
            break

    assert await stream.read(0) == b""
    assert send_data == b"".join(proto.data_chunks)

    recv_data = os.urandom(_BIG_SIZE)
    assert proto.transport is not None
    proto.transport.write(recv_data)
    proto.transport.close()

    buf = bytearray()

    with pytest.raises(MaxBufferLengthReachedError):
        await stream.read()

    with pytest.raises(ReadFinishedError):
        while True:
            chunk = await stream.read(4096)
            assert len(chunk) <= 4096
            buf.extend(chunk)

    assert recv_data == buf

    await stream.close()


@pytest.mark.asyncio
async def test_empty_read(
    mocked_server: helpers.MockedServer,
) -> None:
    async with TcpStream.connect(
        "localhost", port=mocked_server.port
    ) as stream:
        stream.write(b"something")

        proto = await mocked_server.await_proto()
        assert proto.transport
        proto.transport.close()

        with pytest.raises(ReadFinishedError):
            await stream.read()


@pytest.mark.asyncio
async def test_read_end_unsatisfiable(
    mocked_server: helpers.MockedServer,
) -> None:
    async with TcpStream.connect(
        "localhost", port=mocked_server.port
    ) as stream:
        stream.write(b"something")

        proto = await mocked_server.await_proto()
        assert proto.transport

        proto.transport.write(os.urandom(3))
        proto.transport.close()
        tsk = await stream._io.create_task(stream.read(5, exactly=True))

        await stream._io.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        proto.transport.write_eof()

        with pytest.raises(ReadUnsatisfiableError):
            await tsk


@pytest.mark.asyncio
async def test_read_less(
    mocked_server: helpers.MockedServer,
) -> None:
    async with TcpStream.connect(
        "localhost", port=mocked_server.port
    ) as stream:
        stream.write(b"something")
        data = os.urandom(3)
        proto = await mocked_server.await_proto()
        assert proto.transport
        proto.transport.write(data)
        proto.transport.close()

        assert await stream.read(5) == data
        # while not 100% impossible, but very unlikely that socket is going
        # to return less than 3bytes in 1 go.


@pytest.mark.asyncio
async def test_read_more(
    mocked_server: helpers.MockedServer,
) -> None:
    async with TcpStream.connect(
        "localhost", port=mocked_server.port
    ) as stream:
        stream.write(b"something")
        data = os.urandom(6)
        proto = await mocked_server.await_proto()
        assert proto.transport
        proto.transport.write(data)
        proto.transport.close()

        assert await stream.read(5) == data[:5]
        # while not 100% impossible, but very unlikely that socket is going
        # to return less than 5bytes in 1 go.


@pytest.mark.asyncio
async def test_read_exactly(
    mocked_server: helpers.MockedServer,
) -> None:
    async with TcpStream.connect(
        "localhost", port=mocked_server.port
    ) as stream:
        tsk = await stream._io.create_task(stream.read(5, exactly=True))
        proto = await mocked_server.await_proto(allow_empty=True)
        assert proto.transport

        await stream._io.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        data1 = os.urandom(3)
        proto.transport.write(data1)

        await stream._io.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        data2 = os.urandom(3)
        proto.transport.write(data2)

        assert await tsk == data1 + data2[:2]


@pytest.mark.asyncio
async def test_read_till_end(
    mocked_server: helpers.MockedServer,
) -> None:
    async with TcpStream.connect(
        "localhost", port=mocked_server.port
    ) as stream:
        data_chunks = []

        tsk = asyncio.create_task(stream.read())

        proto = await mocked_server.await_proto(allow_empty=True)
        assert proto.transport

        for _ in range(0, 5):
            await stream._io.sleep(0)

            with pytest.raises(asyncio.InvalidStateError):
                tsk.result()

            data = os.urandom(5)
            data_chunks.append(data)
            proto.transport.write(data)

        proto.transport.close()

        assert await tsk == b"".join(data_chunks)


@pytest.mark.asyncio
async def test_max_buf_len(
    mocked_server: helpers.MockedServer,
) -> None:
    async with TcpStream.connect(
        "localhost", port=mocked_server.port
    ) as stream:
        proto = await mocked_server.await_proto(allow_empty=True)
        assert proto.transport

        assert stream.max_buf_len == 64 * 1024
        # Default size is 64 K.
        data = bytearray()

        tsk = await stream._io.create_task(stream.read())

        i = 0
        while len(data) <= stream.max_buf_len:
            with pytest.raises(asyncio.InvalidStateError):
                tsk.result()

            assert stream.reading()

            chunk = os.urandom(1024)

            data += chunk
            proto.transport.write(chunk)
            await stream._io.sleep(0)

            i += 1

        for _i in range(0, 100):  # no good way to tell when this will happen?
            await asyncio.sleep(0.01)

            if stream.reading() is False:
                break

        assert stream.reading() is False

        with pytest.raises(MaxBufferLengthReachedError):
            await tsk

        stream.max_buf_len = 128 * 1024  # 128K

        await stream._io.sleep(0)

        assert stream.reading() is True

        proto.transport.write_eof()

        assert await stream.read() == data


@pytest.mark.asyncio
async def test_read_until(
    mocked_server: helpers.MockedServer,
) -> None:
    async with TcpStream.connect(
        "localhost", port=mocked_server.port
    ) as stream:
        proto = await mocked_server.await_proto(allow_empty=True)
        assert proto.transport
        stream.max_buf_len = 4 * 1024  # 4K

        data = bytearray()

        tsk = asyncio.create_task(stream.read_until())

        while len(data) <= stream.max_buf_len:
            await stream._io.sleep(0)

            with pytest.raises(asyncio.InvalidStateError):
                tsk.result()

            assert stream.reading()

            chunk = b"0" * 1024

            data += chunk
            proto.transport.write(chunk)

        for _i in range(0, 100):  # no good way to tell when this will happen?
            await asyncio.sleep(0.01)

            if stream.reading() is False:
                break

        assert stream.reading() is False

        with pytest.raises(MaxBufferLengthReachedError):
            await tsk

        stream.max_buf_len = 5 * 1024  # 5K

        data += b"\n"
        proto.transport.write(b"\n")

        assert await stream.read_until() == data

        data2 = b"00000"

        tsk = asyncio.create_task(stream.read_until(keep_separator=False))

        await stream._io.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        proto.transport.write(data2)

        await stream._io.sleep(0)

        with pytest.raises(asyncio.InvalidStateError):
            tsk.result()

        proto.transport.write(b"\n")

        assert await tsk == data2

        proto.transport.write(data2)
        proto.transport.write_eof()

        with pytest.raises(SeparatorNotFoundError):
            await stream.read_until()


@pytest.mark.asyncio
async def test_abort(
    mocked_server: helpers.MockedServer,
) -> None:
    stream = await TcpStream.connect("localhost", port=mocked_server.port)
    proto = await mocked_server.await_proto(allow_empty=True)
    assert proto.transport

    assert stream._BaseStreamReader__exc is None  # type: ignore

    await stream.abort()
    assert stream.closed() is True

    with pytest.raises(ReadAbortedError):
        await stream.read()
