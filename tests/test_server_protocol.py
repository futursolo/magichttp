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
    HttpServerProtocol,
    HttpStatusCode,
    ReadAbortedError,
    ReadFinishedError,
    ReceivedDataMalformedError,
    RequestInitialMalformedError,
    RequestInitialTooLargeError,
    WriteAbortedError,
)


def test_init() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()
    protocol.connection_made(transport_mock)
    transport_mock._closing = True
    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_simple_request() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()
    protocol.connection_made(transport_mock)

    async def aiter_requests() -> None:
        count = 0
        async for reader in protocol:
            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(HttpStatusCode.OK)
            writer.finish()

            count += 1

        assert count == 1

    tsk = asyncio.create_task(aiter_requests())

    await asyncio.sleep(0)
    assert not tsk.done()

    protocol.data_received(b"GET / HTTP/1.1\r\nConnection: Close\r\n\r\n")

    await tsk

    assert protocol.eof_received() is True

    assert transport_mock._closing is True
    protocol.connection_lost(None)

    data = transport_mock._pop_stored_data()

    helpers.assert_initial(
        data,
        b"HTTP/1.1 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Close",
        b"Transfer-Encoding: Chunked",
    )

    assert data.split(b"\r\n\r\n", 1)[1] == b"0\r\n\r\n"


@pytest.mark.asyncio
async def test_simple_request_10() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()
    protocol.connection_made(transport_mock)

    async def aiter_requests() -> None:
        count = 0
        async for reader in protocol:
            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(HttpStatusCode.OK)
            writer.finish()

            count += 1

        assert count == 1

    tsk = asyncio.create_task(aiter_requests())

    await asyncio.sleep(0)
    assert not tsk.done()

    protocol.data_received(b"GET / HTTP/1.0\r\n\r\n")

    await tsk

    assert protocol.eof_received() is True

    assert transport_mock._closing is True
    protocol.connection_lost(None)

    helpers.assert_initial(
        transport_mock._pop_stored_data(),
        b"HTTP/1.0 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Close",
    )


@pytest.mark.asyncio
async def test_chunked_request() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()
    protocol.connection_made(transport_mock)

    async def aiter_requests() -> None:
        count = 0
        async for reader in protocol:
            assert await reader.read(9, exactly=True) == b"123456789"

            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(HttpStatusCode.OK)
            writer.finish()

            count += 1

        assert count == 1

    tsk = asyncio.create_task(aiter_requests())

    await asyncio.sleep(0)
    assert not tsk.done()

    protocol.data_received(
        b"GET / HTTP/1.1\r\nTransfer-Encoding: Chunked\r\n"
        b"Connection: Close\r\n\r\n"
        b"5\r\n12345\r\n4\r\n6789\r\n0\r\n\r\n"
    )

    await tsk

    assert protocol.eof_received() is True

    assert transport_mock._closing is True
    protocol.connection_lost(None)

    data = transport_mock._pop_stored_data()

    helpers.assert_initial(
        data,
        b"HTTP/1.1 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Close",
        b"Transfer-Encoding: Chunked",
    )

    assert data.split(b"\r\n\r\n", 1)[1] == b"0\r\n\r\n"


@pytest.mark.asyncio
async def test_simple_response_with_chunked_body() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()
    protocol.connection_made(transport_mock)

    data = os.urandom(20)

    async def aiter_requests() -> None:
        count = 0
        async for reader in protocol:
            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(HttpStatusCode.OK)
            writer.finish(data)

            count += 1

        assert count == 1

    tsk = asyncio.create_task(aiter_requests())

    await asyncio.sleep(0)
    assert not tsk.done()

    protocol.data_received(b"GET / HTTP/1.1\r\nConnection: Close\r\n\r\n")

    await tsk

    assert protocol.eof_received() is True

    assert transport_mock._closing is True
    protocol.connection_lost(None)

    final_data = transport_mock._pop_stored_data()

    helpers.assert_initial(
        final_data,
        b"HTTP/1.1 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Close",
        b"Transfer-Encoding: Chunked",
    )

    assert (
        final_data.split(b"\r\n\r\n", 1)[1]
        == b"14\r\n" + data + b"\r\n0\r\n\r\n"
    )


@pytest.mark.asyncio
async def test_simple_response_with_content_length() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()
    protocol.connection_made(transport_mock)

    data = os.urandom(20)

    async def aiter_requests() -> None:
        count = 0
        async for reader in protocol:
            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(
                HttpStatusCode.OK, headers={"content-length": "20"}
            )
            writer.finish(data)

            count += 1

        assert count == 1

    tsk = asyncio.create_task(aiter_requests())

    await asyncio.sleep(0)
    assert not tsk.done()

    protocol.data_received(b"GET / HTTP/1.1\r\nConnection: Close\r\n\r\n")

    await tsk

    assert protocol.eof_received() is True

    assert transport_mock._closing is True
    protocol.connection_lost(None)

    final_data = transport_mock._pop_stored_data()

    helpers.assert_initial(
        final_data,
        b"HTTP/1.1 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Close",
        b"Content-Length: 20",
    )

    assert final_data.split(b"\r\n\r\n", 1)[1] == data


@pytest.mark.asyncio
async def test_keep_alive() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\n\r\n" b"GET / HTTP/1.1\r\n\r\n")

    async def aiter_requests() -> None:
        count = 0

        async for reader in protocol:
            assert reader.initial.uri == "/"
            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(HttpStatusCode.NO_CONTENT)

            helpers.assert_initial(
                transport_mock._pop_stored_data(),
                b"HTTP/1.1 204 No Content",
                b"Server: %(self_ver_bytes)s",
            )

            writer.finish()

            assert b"".join(transport_mock._data_chunks) == b""

            count += 1

        assert count == 2

    tsk = asyncio.create_task(aiter_requests())

    await asyncio.sleep(0)
    if tsk.done():
        raise RuntimeError(tsk.result())

    assert protocol.eof_received() is True

    await tsk

    transport_mock._closing = True
    protocol.connection_lost(None)

    with pytest.raises(StopAsyncIteration):
        await protocol.__aiter__().__anext__()


@pytest.mark.asyncio
async def test_keep_alive_10() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"GET / HTTP/1.0\r\nConnection: Keep-Alive\r\n\r\n"
        b"GET / HTTP/1.0\r\nConnection: Keep-Alive\r\n\r\n"
    )

    async def aiter_requests() -> None:
        count = 0

        async for reader in protocol:
            assert reader.initial.uri == "/"
            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(HttpStatusCode.NO_CONTENT)

            helpers.assert_initial(
                transport_mock._pop_stored_data(),
                b"HTTP/1.0 204 No Content",
                b"Connection: Keep-Alive",
                b"Server: %(self_ver_bytes)s",
            )

            writer.finish()

            assert b"".join(transport_mock._data_chunks) == b""

            count += 1

        assert count == 2

    tsk = asyncio.create_task(aiter_requests())

    await asyncio.sleep(0)
    if tsk.done():
        raise RuntimeError(tsk.result())

    assert protocol.eof_received() is True

    await tsk

    transport_mock._closing = True
    protocol.connection_lost(None)

    with pytest.raises(StopAsyncIteration):
        await protocol.__aiter__().__anext__()


@pytest.mark.asyncio
async def test_response_with_endless_body() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.0\r\n\r\n")

    async for reader in protocol:
        with pytest.raises(ReadFinishedError):
            await reader.read()

        writer = reader.write_response(HttpStatusCode.OK)

        helpers.assert_initial(
            transport_mock._pop_stored_data(),
            b"HTTP/1.0 200 OK",
            b"Server: %(self_ver_bytes)s",
            b"Connection: Close",
        )

        for _ in range(0, 5):
            data = os.urandom(1024)
            writer.write(data)
            assert b"".join(transport_mock._data_chunks) == data
            transport_mock._data_chunks.clear()

        writer.finish()
        assert b"".join(transport_mock._data_chunks) == b""

    assert protocol.eof_received() is True

    assert transport_mock._closing is True

    protocol.connection_lost(None)


@pytest.mark.asyncio
async def test_upgrade() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"GET / HTTP/1.1\r\nConnection: Upgrade\r\n"
        b"Upgrade: WebSocket\r\n\r\n"
    )

    count = 0
    async for reader in protocol:
        count += 1

        assert reader.initial.headers["connection"] == "Upgrade"
        assert reader.initial.headers["upgrade"] == "WebSocket"

        writer = reader.write_response(
            HttpStatusCode.SWITCHING_PROTOCOLS,
            headers={"Connection": "Upgrade", "Upgrade": "WebSocket"},
        )

        helpers.assert_initial(
            transport_mock._pop_stored_data(),
            b"HTTP/1.1 101 Switching Protocols",
            b"Server: %(self_ver_bytes)s",
            b"Upgrade: WebSocket",
            b"Connection: Upgrade",
        )

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

        transport_mock.close()
        protocol.connection_lost(None)

    assert count == 1


@pytest.mark.asyncio
async def test_close_after_finished() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n\r\n")

    count = 0

    async for reader in protocol:
        count += 1

        with pytest.raises(ReadFinishedError):
            await reader.read()

        writer = reader.write_response(
            HttpStatusCode.NO_CONTENT, headers={"connection": "Keep-Alive"}
        )

        writer.finish()

        helpers.assert_initial(
            transport_mock._pop_stored_data(),
            b"HTTP/1.1 204 No Content",
            b"Server: %(self_ver_bytes)s",
            b"Connection: Keep-Alive",
        )

        protocol.close()

        assert transport_mock._closing is True

        assert protocol.eof_received() is True
        protocol.connection_lost(None)

    assert count == 1


@pytest.mark.asyncio
async def test_close_before_finished() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n\r\n")

    async def wait_closed() -> None:
        await protocol.wait_closed()

    count = 0

    async for reader in protocol:
        count += 1

        protocol.close()

        tsk = asyncio.create_task(wait_closed())
        await asyncio.sleep(0)

        assert tsk.done() is False

        assert transport_mock._closing is False

        with pytest.raises(ReadFinishedError):
            await reader.read()

        writer = reader.write_response(
            HttpStatusCode.NO_CONTENT, headers={"connection": "Keep-Alive"}
        )

        writer.finish()

        helpers.assert_initial(
            transport_mock._pop_stored_data(),
            b"HTTP/1.1 204 No Content",
            b"Server: %(self_ver_bytes)s",
            b"Connection: Keep-Alive",
        )

    assert count == 1

    assert transport_mock._closing is True

    assert protocol.eof_received() is True

    assert tsk.done() is False
    protocol.connection_lost(None)

    await tsk


@pytest.mark.asyncio
async def test_request_initial_too_large() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(os.urandom(5 * 1024 * 1024))

    with pytest.raises(RequestInitialTooLargeError) as exc_info:
        await protocol.__anext__()

    writer = exc_info.value.write_response()
    writer.finish(b"12345")

    assert transport_mock._closing is True
    protocol.connection_lost(None)

    data = transport_mock._pop_stored_data()

    helpers.assert_initial(
        data,
        b"HTTP/1.1 431 Request Header Fields Too Large",
        b"Server: %(self_ver_bytes)s",
        b"Transfer-Encoding: Chunked",
        b"Connection: Close",
    )

    assert data.split(b"\r\n\r\n", 1)[1] == b"5\r\n12345\r\n0\r\n\r\n"


@pytest.mark.asyncio
async def test_request_initial_malformed() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"HTTP/1.1\r\n\r\n")

    with pytest.raises(RequestInitialMalformedError) as exc_info:
        await protocol.__anext__()

    writer = exc_info.value.write_response()
    writer.finish(b"12345")

    assert transport_mock._closing is True
    protocol.connection_lost(None)

    data = transport_mock._pop_stored_data()

    helpers.assert_initial(
        data,
        b"HTTP/1.1 400 Bad Request",
        b"Server: %(self_ver_bytes)s",
        b"Transfer-Encoding: Chunked",
        b"Connection: Close",
    )

    assert data.split(b"\r\n\r\n", 1)[1] == b"5\r\n12345\r\n0\r\n\r\n"


@pytest.mark.asyncio
async def test_request_chunk_len_too_long() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n"
        b"Transfer-Encoding: Chunked\r\n\r\n"
    )

    async for reader in protocol:
        assert reader.initial.headers["transfer-encoding"] == "Chunked"

        protocol.data_received(b"0" * 5 * 1024 * 1024)

        with pytest.raises(EntityTooLargeError):
            await reader.read()

        writer = reader.write_response(HttpStatusCode.REQUEST_ENTITY_TOO_LARGE)
        writer.finish()

        assert transport_mock._closing is True
        protocol.connection_lost(None)

    data = transport_mock._pop_stored_data()

    helpers.assert_initial(
        data,
        b"HTTP/1.1 413 Request Entity Too Large",
        b"Server: %(self_ver_bytes)s",
        b"Transfer-Encoding: Chunked",
        b"Connection: Close",
    )

    assert data.split(b"\r\n\r\n", 1)[1] == b"0\r\n\r\n"


@pytest.mark.asyncio
async def test_request_chunk_len_malformed() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(
        b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n"
        b"Transfer-Encoding: Chunked\r\n\r\n"
    )

    async for reader in protocol:
        assert reader.initial.headers["transfer-encoding"] == "Chunked"

        protocol.data_received(b"ABCDEFGH\r\n")

        with pytest.raises(ReceivedDataMalformedError):
            await reader.read()

        writer = reader.write_response(HttpStatusCode.BAD_REQUEST)
        writer.finish()

        assert transport_mock._closing is True
        protocol.connection_lost(None)

    data = transport_mock._pop_stored_data()

    helpers.assert_initial(
        data,
        b"HTTP/1.1 400 Bad Request",
        b"Server: %(self_ver_bytes)s",
        b"Transfer-Encoding: Chunked",
        b"Connection: Close",
    )

    assert data.split(b"\r\n\r\n", 1)[1] == b"0\r\n\r\n"


@pytest.mark.asyncio
async def test_remote_abort_1() -> None:
    """
    HttpServerProtocol.connection_made() -x-> \
    HttpServerProtocol.__anext__() -> \
    HttpRequestReader.read() -> \
    HttpRequestReader.write_response() -> \
    [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
    HttpResponseWriter.finish()
    """
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)

    protocol.connection_lost(None)
    assert transport_mock._closing is True

    with pytest.raises(StopAsyncIteration):
        await protocol.__anext__()


@pytest.mark.asyncio
async def test_remote_abort_2() -> None:
    """
    HttpServerProtocol.connection_made() -> \
    HttpServerProtocol.__anext__() -x-> \
    HttpRequestReader.read() -> \
    HttpRequestReader.write_response() -> \
    [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
    HttpResponseWriter.finish()
    """
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\nContent-Length: 20\r\n\r\n")

    async for reader in protocol:
        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(ReadAbortedError):
            await reader.read()

        with pytest.raises(WriteAbortedError):
            reader.write_response(HttpStatusCode.BAD_REQUEST)


@pytest.mark.asyncio
async def test_remote_abort_3() -> None:
    """
    HttpServerProtocol.connection_made() -> \
    HttpServerProtocol.__anext__() -> \
    HttpRequestReader.read() -x-> \
    HttpRequestReader.write_response() -> \
    [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
    HttpResponseWriter.finish()
    """
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

    async for reader in protocol:
        with pytest.raises(ReadFinishedError):
            await reader.read()

        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(WriteAbortedError):
            reader.write_response(HttpStatusCode.BAD_REQUEST)


@pytest.mark.asyncio
async def test_remote_abort_4() -> None:
    """
    HttpServerProtocol.connection_made() -> \
    HttpServerProtocol.__anext__() -> \
    HttpRequestReader.read() -> \
    HttpRequestReader.write_response() -x-> \
    [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
    HttpResponseWriter.finish()
    """
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

    async for reader in protocol:
        with pytest.raises(ReadFinishedError):
            await reader.read()

        writer = reader.write_response(HttpStatusCode.OK)

        writer.write(b"12345")

        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(WriteAbortedError):
            writer.write(b"12345")

        with pytest.raises(WriteAbortedError):
            await writer.flush()


@pytest.mark.asyncio
async def test_remote_abort_5() -> None:
    """
    HttpServerProtocol.connection_made() -> \
    HttpServerProtocol.__anext__() -> \
    HttpRequestReader.read() -> \
    HttpRequestReader.write_response() -> \
    [HttpResponseWriter.write(), HttpResponseWriter.flush()] -x-> \
    HttpResponseWriter.finish()
    """
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

    async for reader in protocol:
        with pytest.raises(ReadFinishedError):
            await reader.read()

        writer = reader.write_response(HttpStatusCode.OK)

        writer.write(b"12345")
        await writer.flush()

        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(WriteAbortedError):
            writer.finish()


@pytest.mark.asyncio
async def test_local_abort_1() -> None:
    """
    HttpServerProtocol.__anext__() -x-> \
    HttpRequestReader.read() -> \
    HttpRequestReader.write_response() -> \
    [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
    HttpResponseWriter.finish()
    """
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\nContent-Length: 20\r\n\r\n")

    async for reader in protocol:
        reader.abort()
        assert transport_mock._closing is True
        protocol.connection_lost(None)

        with pytest.raises(ReadAbortedError):
            await reader.read()

        with pytest.raises(WriteAbortedError):
            reader.write_response(HttpStatusCode.BAD_REQUEST)


@pytest.mark.asyncio
async def test_local_abort_2() -> None:
    """
    HttpServerProtocol.__anext__() -> \
    HttpRequestReader.read() -x-> \
    HttpRequestReader.write_response() -> \
    [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
    HttpResponseWriter.finish()
    """
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

    async for reader in protocol:
        with pytest.raises(ReadFinishedError):
            await reader.read()

        reader.abort()
        assert transport_mock._closing is True
        protocol.connection_lost(None)

        with pytest.raises(WriteAbortedError):
            reader.write_response(HttpStatusCode.BAD_REQUEST)


@pytest.mark.asyncio
async def test_local_abort_3() -> None:
    """
    HttpServerProtocol.__anext__() -> \
    HttpRequestReader.read() -> \
    HttpRequestReader.write_response() -x-> \
    [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
    HttpResponseWriter.finish()
    """
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

    async for reader in protocol:
        with pytest.raises(ReadFinishedError):
            await reader.read()

        writer = reader.write_response(HttpStatusCode.OK)

        writer.write(b"12345")

        reader.abort()
        assert transport_mock._closing is True
        protocol.connection_lost(None)

        with pytest.raises(WriteAbortedError):
            writer.write(b"12345")

        with pytest.raises(WriteAbortedError):
            await writer.flush()


@pytest.mark.asyncio
async def test_local_abort_4() -> None:
    """
    HttpServerProtocol.__anext__() -> \
    HttpRequestReader.read() -> \
    HttpRequestReader.write_response() -> \
    [HttpResponseWriter.write(), HttpResponseWriter.flush()] -x-> \
    HttpResponseWriter.finish()
    """
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()

    protocol.connection_made(transport_mock)
    protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

    async for reader in protocol:
        with pytest.raises(ReadFinishedError):
            await reader.read()

        writer = reader.write_response(HttpStatusCode.OK)

        writer.write(b"12345")
        await writer.flush()

        reader.abort()
        assert transport_mock._closing is True
        protocol.connection_lost(None)

        with pytest.raises(WriteAbortedError):
            writer.finish()


@pytest.mark.asyncio
async def test_http11_100continue_request() -> None:
    protocol = HttpServerProtocol()
    transport_mock = helpers.MockedTransport()
    protocol.connection_made(transport_mock)

    async def aiter_requests() -> None:
        count = 0
        async for reader in protocol:
            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(HttpStatusCode.OK)
            writer.finish()

            count += 1

        assert count == 1

    tsk = asyncio.create_task(aiter_requests())

    await asyncio.sleep(0)
    assert not tsk.done()

    protocol.data_received(
        b"GET / HTTP/1.1\r\nExpect: 100-continue\r\n"
        b"Connection: Close\r\n\r\n"
    )

    await tsk

    assert protocol.eof_received() is True

    assert transport_mock._closing is True
    protocol.connection_lost(None)

    data = transport_mock._pop_stored_data()

    data_continue, data = data.split(b"\r\n\r\n", 1)

    helpers.assert_initial(data_continue, b"HTTP/1.1 100 Continue")

    helpers.assert_initial(
        data,
        b"HTTP/1.1 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Close",
        b"Transfer-Encoding: Chunked",
    )

    assert data.split(b"\r\n\r\n", 1)[1] == b"0\r\n\r\n"
