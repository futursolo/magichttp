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
    EntityTooLargeError,
    HttpClientProtocol,
    HttpRequestMethod,
    ReadAbortedError,
    ReadFinishedError,
    ReceivedDataMalformedError,
    WriteAbortedError,
    WriteAfterFinishedError,
)


def test_init() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()
    protocol.connection_made(transport_mock)
    transport_mock._closing = True
    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_simple_request() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"HTTP/1.1 200 OK\r\n\r\n")

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")

    helpers.assert_initial(
        transport_mock._pop_stored_data(),
        b"GET / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Accept: */*",
    )

    assert protocol.eof_received() is True

    writer.finish()

    assert transport_mock._pop_stored_data() == b""

    with pytest.raises(WriteAfterFinishedError):
        writer.write(b"1")

    protocol.connection_lost(None)

    reader = await writer.read_response()

    with pytest.raises(ReadFinishedError):
        await reader.read()

    assert reader.initial.status_code == 200
    assert reader.initial.headers == {}


@pytest.mark.asyncio
async def test_keep_alive() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"HTTP/1.1 204 NO CONTENT\r\n\r\n" b"HTTP/1.1 204 NO CONTENT\r\n\r\n"
    )

    for _ in range(0, 2):
        writer = await protocol.write_request(
            HttpRequestMethod.GET, uri="/", headers={"content-length": "5"}
        )

        helpers.assert_initial(
            transport_mock._pop_stored_data(),
            b"GET / HTTP/1.1",
            b"Content-Length: 5",
            b"User-Agent: %(self_ver_bytes)s",
            b"Accept: */*",
        )

        writer.write(b"12345")
        await writer.flush()
        writer.finish()
        await writer.flush()

        assert transport_mock._pop_stored_data() == b"12345"
        transport_mock._data_chunks.clear()

        reader = await writer.read_response()

        with pytest.raises(ReadFinishedError):
            await reader.read()

        assert reader.initial.status_code == 204
        assert reader.initial.headers == {}

    assert protocol.eof_received() is True
    protocol.connection_lost(None)

    with pytest.raises(WriteAfterFinishedError):
        await protocol.write_request(HttpRequestMethod.GET)


@pytest.mark.asyncio
async def test_response_with_body() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n12345"
    )

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")
    writer.finish()

    reader = await writer.read_response()
    assert await reader.read() == b"12345"

    assert reader.initial.status_code == 200
    assert reader.initial.headers == {"content-length": "5"}

    assert protocol.eof_received() is True
    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_response_with_endless_body() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"HTTP/1.0 200 OK\r\n\r\n")

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")
    writer.finish()

    reader = await writer.read_response()

    for _ in range(0, 5):
        data = os.urandom(1024)
        protocol.data_received(data)
        assert await reader.read(4096) == data

    assert protocol.eof_received() is True

    with pytest.raises(ReadFinishedError):
        await reader.read()

    assert transport_mock._closing is True

    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_upgrade() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"HTTP/1.0 101 Switching Protocol\r\n"
        b"Connection: Upgrade\r\nUpgrade: WebSocket\r\n\r\n"
    )

    writer = await protocol.write_request(
        HttpRequestMethod.GET,
        uri="/",
        headers={"connection": "Upgrade", "Upgrade": "WebSocket"},
    )

    helpers.assert_initial(
        transport_mock._pop_stored_data(),
        b"GET / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Connection: Upgrade",
        b"Upgrade: WebSocket",
    )

    reader = await writer.read_response()

    for _i in range(0, 5):
        for _j in range(0, 5):
            data = os.urandom(1024)
            protocol.data_received(data)
            assert await reader.read(4096) == data

        for _k in range(0, 5):
            data = os.urandom(1024)
            writer.write(data)
            assert b"".join(transport_mock._data_chunks) == data
            transport_mock._data_chunks.clear()

    writer.finish()

    assert protocol.eof_received() is True

    with pytest.raises(ReadFinishedError):
        await reader.read()

    assert transport_mock._closing is True

    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_response_with_chunked_body() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n"
    )

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")
    writer.finish()

    reader = await writer.read_response()

    assert reader.initial.headers["transfer-encoding"] == "Chunked"

    data = os.urandom(5)

    async def read_data() -> None:
        assert await reader.read(5, exactly=True) == data

    tsk = asyncio.create_task(read_data())

    await asyncio.sleep(0)
    assert tsk.done() is False

    protocol.data_received(b"5\r")

    await asyncio.sleep(0)
    assert tsk.done() is False

    protocol.data_received(b"\n" + data[:3])

    await asyncio.sleep(0)
    assert tsk.done() is False

    protocol.data_received(data[3:] + b"\r")

    await tsk

    protocol.data_received(b"\n0\r\n\r\n")

    with pytest.raises(ReadFinishedError):
        await reader.read()

    assert protocol.eof_received() is True
    assert transport_mock._closing is True

    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_flush_pause_and_resume() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"HTTP/1.0 200 OK\r\n\r\n")

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")

    reader = await writer.read_response()

    data = os.urandom(5 * 1024 * 1024)  # 5M

    assert transport_mock._paused is False

    protocol.data_received(data)

    assert transport_mock._paused is True

    assert await reader.read(6 * 1024 * 1024) == data
    data = os.urandom(1)

    async def read_data():
        assert await reader.read() == data

    tsk = asyncio.create_task(read_data())
    await asyncio.sleep(0)

    assert transport_mock._paused is False
    assert transport_mock._closing is False

    protocol.data_received(data)
    assert protocol.eof_received() is True

    await tsk

    with pytest.raises(ReadFinishedError):
        await reader.read()

    data = os.urandom(5 * 1024)  # 5K
    transport_mock._data_chunks.clear()

    writer.write(data[: 4 * 1024])
    protocol.pause_writing()
    protocol.pause_writing()

    async def flush_data():
        await writer.flush()

    tsk = asyncio.create_task(flush_data())
    await asyncio.sleep(0)

    assert tsk.done() is False

    writer.write(data[4 * 1024 :])
    writer.finish()
    assert b"".join(transport_mock._data_chunks) == data

    await asyncio.sleep(0)
    assert tsk.done() is False

    protocol.resume_writing()
    protocol.resume_writing()
    await tsk

    assert transport_mock._closing is True

    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_close_after_finished() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"HTTP/1.1 204 NO CONTENT\r\n\r\n")

    writer = await protocol.write_request(
        HttpRequestMethod.GET, uri="/", headers={"content-length": "5"}
    )

    helpers.assert_initial(
        transport_mock._pop_stored_data(),
        b"GET / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Accept: */*",
        b"Content-Length: 5",
    )

    writer.write(b"12345")
    await writer.flush()
    writer.finish()
    await writer.flush()

    assert b"".join(transport_mock._data_chunks) == b"12345"
    transport_mock._data_chunks.clear()

    reader = await writer.read_response()

    with pytest.raises(ReadFinishedError):
        await reader.read()

    assert reader.initial.status_code == 204
    assert reader.initial.headers == {}

    protocol.close()

    assert transport_mock._closing is True

    assert protocol.eof_received() is True
    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_close_before_finished() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"HTTP/1.1 204 NO CONTENT\r\n\r\n")

    writer = await protocol.write_request(
        HttpRequestMethod.GET, uri="/", headers={"content-length": "5"}
    )

    protocol.close()

    async def wait_closed() -> None:
        await protocol.wait_closed()

    tsk = asyncio.create_task(wait_closed())
    await asyncio.sleep(0)

    assert tsk.done() is False

    assert transport_mock._closing is False

    helpers.assert_initial(
        transport_mock._pop_stored_data(),
        b"GET / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Accept: */*",
        b"Content-Length: 5",
    )

    writer.write(b"12345")
    await writer.flush()
    writer.finish()
    await writer.flush()

    assert b"".join(transport_mock._data_chunks) == b"12345"
    transport_mock._data_chunks.clear()

    reader = await writer.read_response()

    with pytest.raises(ReadFinishedError):
        await reader.read()

    assert reader.initial.status_code == 204
    assert reader.initial.headers == {}

    assert transport_mock._closing is True

    assert protocol.eof_received() is True

    assert tsk.done() is False
    protocol.connection_lost(None)

    await tsk


@pytest.mark.asyncio
async def test_response_initial_too_large() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(os.urandom(5 * 1024 * 1024))

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")
    writer.finish()

    with pytest.raises(EntityTooLargeError):
        await writer.read_response()

    assert transport_mock._closing is True
    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_response_initial_malformed() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"HTTP/1.2 204 NO CONTENT\r\n\r\n")

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")
    writer.finish()

    with pytest.raises(ReceivedDataMalformedError):
        await writer.read_response()

    assert transport_mock._closing is True
    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_response_chunk_len_too_long() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n"
    )

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")
    writer.finish()

    reader = await writer.read_response()

    assert reader.initial.headers["transfer-encoding"] == "Chunked"

    protocol.data_received(b"0" * 5 * 1024 * 1024)
    with pytest.raises(EntityTooLargeError):
        await reader.read()

    assert transport_mock._closing is True
    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_response_chunk_len_malformed() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n"
    )

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")
    writer.finish()

    reader = await writer.read_response()

    assert reader.initial.headers["transfer-encoding"] == "Chunked"

    protocol.data_received(b"ABCDEFGH\r\n")
    with pytest.raises(ReceivedDataMalformedError):
        await reader.read()

    assert transport_mock._closing is True
    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_remote_abort_1() -> None:
    """
    HttpClientProtocol.connection_made() -x-> \
    HttpClientProtocol.write_request() -> \
    [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
    HttpRequestWriter.finish() -> \
    HttpRequestWriter.read_response() -> \
    HttpResponseReader.read()
    """
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    protocol.connection_lost(None)
    assert transport_mock._closing is True

    with pytest.raises(WriteAbortedError):
        await protocol.write_request(HttpRequestMethod.GET)


@pytest.mark.asyncio
async def test_remote_abort_2() -> None:
    """
    HttpClientProtocol.connection_made() -> \
    HttpClientProtocol.write_request() -x-> \
    [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
    HttpRequestWriter.finish() -> \
    HttpRequestWriter.read_response() -> \
    HttpResponseReader.read()
    """
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")

    protocol.connection_lost(None)
    assert transport_mock._closing is True

    with pytest.raises(WriteAbortedError):
        await writer.flush()

    with pytest.raises(WriteAbortedError):
        writer.finish()

    with pytest.raises(ReadAbortedError):
        await writer.read_response()


@pytest.mark.asyncio
async def test_remote_abort_3() -> None:
    """
    HttpClientProtocol.connection_made() -> \
    HttpClientProtocol.write_request() -> \
    [HttpRequestWriter.write(), HttpRequestWriter.flush()] -x-> \
    HttpRequestWriter.finish() -> \
    HttpRequestWriter.read_response() -> \
    HttpResponseReader.read()
    """
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    writer = await protocol.write_request(
        HttpRequestMethod.POST, uri="/", headers={"content-type": "1"}
    )

    writer.write(os.urandom(1))
    await writer.flush()

    protocol.connection_lost(None)
    assert transport_mock._closing is True

    with pytest.raises(WriteAbortedError):
        writer.finish()

    with pytest.raises(ReadAbortedError):
        await writer.read_response()


@pytest.mark.asyncio
async def test_remote_abort_4() -> None:
    """
    HttpClientProtocol.connection_made() -> \
    HttpClientProtocol.write_request() -> \
    [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
    HttpRequestWriter.finish() -x-> \
    HttpRequestWriter.read_response() -> \
    HttpResponseReader.read()
    """
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    writer = await protocol.write_request(
        HttpRequestMethod.POST, uri="/", headers={"content-type": "1"}
    )

    writer.write(os.urandom(1))
    await writer.flush()
    writer.finish()

    protocol.data_received(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r"
    )

    protocol.connection_lost(None)
    assert transport_mock._closing is True

    with pytest.raises(ReadAbortedError):
        await writer.read_response()


@pytest.mark.asyncio
async def test_remote_abort_5() -> None:
    """
    HttpClientProtocol.connection_made() -> \
    HttpClientProtocol.write_request() -> \
    [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
    HttpRequestWriter.finish() -> \
    HttpRequestWriter.read_response() -x-> \
    HttpResponseReader.read()
    """
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    writer = await protocol.write_request(
        HttpRequestMethod.POST, uri="/", headers={"content-type": "1"}
    )

    writer.write(os.urandom(1))
    await writer.flush()
    writer.finish()

    protocol.data_received(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n"
    )

    reader = await writer.read_response()

    protocol.connection_lost(None)
    assert transport_mock._closing is True

    with pytest.raises(ReadAbortedError):
        await reader.read()


@pytest.mark.asyncio
async def test_local_abort_1() -> None:
    """
    HttpClientProtocol.write_request() -x-> \
    [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
    HttpRequestWriter.finish() -> \
    HttpRequestWriter.read_response() -> \
    HttpResponseReader.read()
    """
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")

    writer.abort()
    assert transport_mock._closing is True

    with pytest.raises(WriteAbortedError):
        await writer.flush()

    with pytest.raises(WriteAbortedError):
        writer.finish()

    with pytest.raises(ReadAbortedError):
        await writer.read_response()


@pytest.mark.asyncio
async def test_local_abort_2() -> None:
    """
    HttpClientProtocol.write_request() -> \
    [HttpRequestWriter.write(), HttpRequestWriter.flush()] -x-> \
    HttpRequestWriter.finish() -> \
    HttpRequestWriter.read_response() -> \
    HttpResponseReader.read()
    """
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    writer = await protocol.write_request(
        HttpRequestMethod.POST, uri="/", headers={"content-type": "1"}
    )

    writer.write(os.urandom(1))
    await writer.flush()

    writer.abort()
    assert transport_mock._closing is True

    with pytest.raises(WriteAbortedError):
        writer.finish()

    with pytest.raises(ReadAbortedError):
        await writer.read_response()


@pytest.mark.asyncio
async def test_local_abort_3() -> None:
    """
    HttpClientProtocol.write_request() -> \
    [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
    HttpRequestWriter.finish() -x-> \
    HttpRequestWriter.read_response() -> \
    HttpResponseReader.read()
    """
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    writer = await protocol.write_request(
        HttpRequestMethod.POST, uri="/", headers={"content-type": "1"}
    )

    writer.write(os.urandom(1))
    await writer.flush()
    writer.finish()

    protocol.data_received(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r"
    )

    writer.abort()
    assert transport_mock._closing is True

    with pytest.raises(ReadAbortedError):
        await writer.read_response()


@pytest.mark.asyncio
async def test_local_abort_4() -> None:
    """
    HttpClientProtocol.write_request() -> \
    [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
    HttpRequestWriter.finish() -> \
    HttpRequestWriter.read_response() -x-> \
    HttpResponseReader.read()
    """
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    writer = await protocol.write_request(
        HttpRequestMethod.POST, uri="/", headers={"content-type": "1"}
    )

    writer.write(os.urandom(1))
    await writer.flush()
    writer.finish()

    protocol.data_received(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n"
    )

    reader = await writer.read_response()

    writer.abort()
    assert transport_mock._closing is True

    with pytest.raises(ReadAbortedError):
        await reader.read()


@pytest.mark.asyncio
async def test_endless_response_cutoff() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"HTTP/1.0 200 OK\r\n\r\n")

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")
    writer.finish()

    reader = await writer.read_response()

    for _ in range(0, 5):
        data = os.urandom(1024)
        protocol.data_received(data)
        assert await reader.read(4096) == data

    transport_mock._closing = True

    protocol.connection_lost(OSError())

    with pytest.raises(ReadAbortedError):
        await reader.read()


@pytest.mark.asyncio
async def test_http11_100continue_response() -> None:
    protocol = HttpClientProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"HTTP/1.1 100 Continue\r\n\r\n"
        b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n12345"
    )

    writer = await protocol.write_request(HttpRequestMethod.GET, uri="/")
    writer.finish()

    reader = await writer.read_response()
    assert await reader.read() == b"12345"

    assert reader.initial.status_code == 200
    assert reader.initial.headers == {"content-length": "5"}

    assert protocol.eof_received() is True
    protocol.connection_lost(None)
