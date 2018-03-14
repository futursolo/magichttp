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

from magichttp import HttpClientProtocol, HttpRequestMethod, \
    WriteAfterFinishedError, ReadFinishedError, __version__, \
    HttpServerProtocol, EntityTooLargeError, ReceivedDataMalformedError, \
    WriteAbortedError, ReadAbortedError, HttpStatusCode, \
    RequestInitialTooLargeError, RequestInitialMalformedError

from _helper import TestHelper

import pytest
import os
import asyncio


helper = TestHelper()


class TransportMock:
    def __init__(self):
        self._paused = False
        self._closing = False
        self._data_chunks = []
        self._extra_info = {}

    def pause_reading(self):
        assert self._paused is False

        self._paused = True

    def resume_reading(self):
        assert self._paused is True

        self._paused = False

    def close(self):
        self._closing = True

    def is_closing(self):
        return self._closing

    def write(self, data):
        self._data_chunks.append(data)

    def get_extra_info(self, name):
        return self._extra_info.get(name)


class HttpClientProtocolTestCase:
    def test_init(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()
        protocol.connection_made(transport_mock)
        transport_mock._closing = True
        protocol.connection_lost(None)

    @helper.run_async_test
    async def test_simple_request(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(b"HTTP/1.1 200 OK\r\n\r\n")

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")

        assert b"".join(transport_mock._data_chunks) == \
            (b"GET / HTTP/1.1\r\nUser-Agent: magichttp/%s\r\n"
             b"Accept: */*\r\nConnection: Keep-Alive\r\n\r\n") % \
            __version__.encode()
        transport_mock._data_chunks.clear()

        assert protocol.eof_received() is True

        writer.finish()

        assert b"".join(transport_mock._data_chunks) == b""

        with pytest.raises(WriteAfterFinishedError):
            writer.write(b"1")

        protocol.connection_lost(None)

        reader = await writer.read_response()

        with pytest.raises(ReadFinishedError):
            await reader.read()

        assert reader.initial.status_code == 200
        assert reader.initial.headers == {}

    @helper.run_async_test
    async def test_keep_alive(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"HTTP/1.1 204 NO CONTENT\r\nConnection: Keep-Alive\r\n\r\n"
            b"HTTP/1.1 204 NO CONTENT\r\nConnection: Keep-Alive\r\n\r\n")

        for _ in range(0, 2):
            writer = await protocol.write_request(
                HttpRequestMethod.GET, uri=b"/",
                headers={b"content-length": b"5"})

            assert b"".join(transport_mock._data_chunks) == \
                (b"GET / HTTP/1.1\r\nContent-Length: 5\r\n"
                 b"User-Agent: magichttp/%s\r\n"
                 b"Accept: */*\r\nConnection: Keep-Alive\r\n\r\n") % \
                __version__.encode()
            transport_mock._data_chunks.clear()

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
            assert reader.initial.headers == {b"connection": b"Keep-Alive"}

        assert protocol.eof_received() is True
        protocol.connection_lost(None)

        with pytest.raises(WriteAfterFinishedError):
            await protocol.write_request(HttpRequestMethod.GET)

    @helper.run_async_test
    async def test_response_with_body(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n12345")

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")
        writer.finish()

        reader = await writer.read_response()
        assert await reader.read() == b"12345"

        assert reader.initial.status_code == 200
        assert reader.initial.headers == {b"content-length": b"5"}

        assert protocol.eof_received() is True
        protocol.connection_lost(None)

    @helper.run_async_test
    async def test_response_with_endless_body(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(b"HTTP/1.0 200 OK\r\n\r\n")

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")
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

    @helper.run_async_test
    async def test_upgrade(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"HTTP/1.0 101 Switching Protocol\r\n"
            b"Connection: Upgrade\r\nUpgrade: WebSocket\r\n\r\n")

        writer = await protocol.write_request(
            HttpRequestMethod.GET, uri=b"/", headers={
                b"connection": b"Upgrade", b"Upgrade": b"WebSocket"})

        assert b"".join(transport_mock._data_chunks) == \
            (b"GET / HTTP/1.1\r\nConnection: Upgrade\r\n"
             b"Upgrade: WebSocket\r\nUser-Agent: magichttp/%s\r\n"
             b"Accept: */*\r\n\r\n") % \
            __version__.encode()
        transport_mock._data_chunks.clear()

        reader = await writer.read_response()

        for i in range(0, 5):
            for j in range(0, 5):
                data = os.urandom(1024)
                protocol.data_received(data)
                assert await reader.read(4096) == data

            for k in range(0, 5):
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

    @helper.run_async_test
    async def test_response_with_chunked_body(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n")

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")
        writer.finish()

        reader = await writer.read_response()

        assert reader.initial.headers[b"transfer-encoding"] == b"Chunked"

        data = os.urandom(5)

        async def read_data():
            assert await reader.read(5, exactly=True) == data

        tsk = helper.loop.create_task(read_data())

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

    @helper.run_async_test
    async def test_flush_pause_and_resume(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(b"HTTP/1.0 200 OK\r\n\r\n")

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")

        reader = await writer.read_response()

        data = os.urandom(5 * 1024 * 1024)  # 5M

        assert transport_mock._paused is False

        protocol.data_received(data)

        assert transport_mock._paused is True

        assert await reader.read(6 * 1024 * 1024) == data
        data = os.urandom(1)

        async def read_data():
            assert await reader.read() == data

        tsk = helper.loop.create_task(read_data())
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

        writer.write(data[:4 * 1024])
        protocol.pause_writing()
        protocol.pause_writing()

        async def flush_data():
            await writer.flush()

        tsk = helper.loop.create_task(flush_data())
        await asyncio.sleep(0)

        assert tsk.done() is False

        writer.write(data[4 * 1024:])
        writer.finish()
        assert b"".join(transport_mock._data_chunks) == data

        await asyncio.sleep(0)
        assert tsk.done() is False

        protocol.resume_writing()
        protocol.resume_writing()
        await tsk

        assert transport_mock._closing is True

        protocol.connection_lost(None)

    @helper.run_async_test
    async def test_close_after_finished(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"HTTP/1.1 204 NO CONTENT\r\nConnection: Keep-Alive\r\n\r\n")

        writer = await protocol.write_request(
            HttpRequestMethod.GET, uri=b"/",
            headers={b"content-length": b"5"})

        assert b"".join(transport_mock._data_chunks) == \
            (b"GET / HTTP/1.1\r\nContent-Length: 5\r\n"
             b"User-Agent: magichttp/%s\r\n"
             b"Accept: */*\r\nConnection: Keep-Alive\r\n\r\n") % \
            __version__.encode()
        transport_mock._data_chunks.clear()

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
        assert reader.initial.headers == {b"connection": b"Keep-Alive"}

        protocol.close()

        assert transport_mock._closing is True

        assert protocol.eof_received() is True
        protocol.connection_lost(None)

    @helper.run_async_test
    async def test_close_before_finished(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"HTTP/1.1 204 NO CONTENT\r\nConnection: Keep-Alive\r\n\r\n")

        writer = await protocol.write_request(
            HttpRequestMethod.GET, uri=b"/",
            headers={b"content-length": b"5"})

        protocol.close()

        async def wait_closed():
            await protocol.wait_closed()

        tsk = helper.loop.create_task(wait_closed())
        await asyncio.sleep(0)

        assert tsk.done() is False

        assert transport_mock._closing is False

        assert b"".join(transport_mock._data_chunks) == \
            (b"GET / HTTP/1.1\r\nContent-Length: 5\r\n"
             b"User-Agent: magichttp/%s\r\n"
             b"Accept: */*\r\nConnection: Keep-Alive\r\n\r\n") % \
            __version__.encode()
        transport_mock._data_chunks.clear()

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
        assert reader.initial.headers == {b"connection": b"Keep-Alive"}

        assert transport_mock._closing is True

        assert protocol.eof_received() is True

        assert tsk.done() is False
        protocol.connection_lost(None)

        await tsk

    @helper.run_async_test
    async def test_response_initial_too_large(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(os.urandom(5 * 1024 * 1024))

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")
        writer.finish()

        with pytest.raises(EntityTooLargeError):
            await writer.read_response()

        assert transport_mock._closing is True
        protocol.connection_lost(None)

    @helper.run_async_test
    async def test_response_initial_malformed(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(b"HTTP/1.2 204 NO CONTENT\r\n\r\n")

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")
        writer.finish()

        with pytest.raises(ReceivedDataMalformedError):
            await writer.read_response()

        assert transport_mock._closing is True
        protocol.connection_lost(None)

    @helper.run_async_test
    async def test_response_chunk_len_too_long(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n")

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")
        writer.finish()

        reader = await writer.read_response()

        assert reader.initial.headers[b"transfer-encoding"] == b"Chunked"

        protocol.data_received(b"0" * 5 * 1024 * 1024)
        with pytest.raises(EntityTooLargeError):
            await reader.read()

        assert transport_mock._closing is True
        protocol.connection_lost(None)

    @helper.run_async_test
    async def test_response_chunk_len_malformed(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n")

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")
        writer.finish()

        reader = await writer.read_response()

        assert reader.initial.headers[b"transfer-encoding"] == b"Chunked"

        protocol.data_received(b"ABCDEFGH\r\n")
        with pytest.raises(ReceivedDataMalformedError):
            await reader.read()

        assert transport_mock._closing is True
        protocol.connection_lost(None)

    @helper.run_async_test
    async def test_remote_abort_1(self):
        """
        HttpClientProtocol.connection_made() -x-> \
        HttpClientProtocol.write_request() -> \
        [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
        HttpRequestWriter.finish() -> \
        HttpRequestWriter.read_response() -> \
        HttpResponseReader.read()
        """
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(WriteAbortedError):
            await protocol.write_request(HttpRequestMethod.GET)

    @helper.run_async_test
    async def test_remote_abort_2(self):
        """
        HttpClientProtocol.connection_made() -> \
        HttpClientProtocol.write_request() -x-> \
        [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
        HttpRequestWriter.finish() -> \
        HttpRequestWriter.read_response() -> \
        HttpResponseReader.read()
        """
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")

        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(WriteAbortedError):
            await writer.flush()

        with pytest.raises(WriteAbortedError):
            writer.finish()

        with pytest.raises(ReadAbortedError):
            await writer.read_response()

    @helper.run_async_test
    async def test_remote_abort_3(self):
        """
        HttpClientProtocol.connection_made() -> \
        HttpClientProtocol.write_request() -> \
        [HttpRequestWriter.write(), HttpRequestWriter.flush()] -x-> \
        HttpRequestWriter.finish() -> \
        HttpRequestWriter.read_response() -> \
        HttpResponseReader.read()
        """
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        writer = await protocol.write_request(
            HttpRequestMethod.POST, uri=b"/", headers={b"content-type": b"1"})

        writer.write(os.urandom(1))
        await writer.flush()

        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(WriteAbortedError):
            writer.finish()

        with pytest.raises(ReadAbortedError):
            await writer.read_response()

    @helper.run_async_test
    async def test_remote_abort_4(self):
        """
        HttpClientProtocol.connection_made() -> \
        HttpClientProtocol.write_request() -> \
        [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
        HttpRequestWriter.finish() -x-> \
        HttpRequestWriter.read_response() -> \
        HttpResponseReader.read()
        """
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        writer = await protocol.write_request(
            HttpRequestMethod.POST, uri=b"/", headers={b"content-type": b"1"})

        writer.write(os.urandom(1))
        await writer.flush()
        writer.finish()

        protocol.data_received(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r")

        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(ReadAbortedError):
            await writer.read_response()

    @helper.run_async_test
    async def test_remote_abort_5(self):
        """
        HttpClientProtocol.connection_made() -> \
        HttpClientProtocol.write_request() -> \
        [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
        HttpRequestWriter.finish() -> \
        HttpRequestWriter.read_response() -x-> \
        HttpResponseReader.read()
        """
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        writer = await protocol.write_request(
            HttpRequestMethod.POST, uri=b"/", headers={b"content-type": b"1"})

        writer.write(os.urandom(1))
        await writer.flush()
        writer.finish()

        protocol.data_received(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n")

        reader = await writer.read_response()

        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(ReadAbortedError):
            await reader.read()

    @helper.run_async_test
    async def test_local_abort_1(self):
        """
        HttpClientProtocol.write_request() -x-> \
        [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
        HttpRequestWriter.finish() -> \
        HttpRequestWriter.read_response() -> \
        HttpResponseReader.read()
        """
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")

        writer.abort()
        assert transport_mock._closing is True

        with pytest.raises(WriteAbortedError):
            await writer.flush()

        with pytest.raises(WriteAbortedError):
            writer.finish()

        with pytest.raises(ReadAbortedError):
            await writer.read_response()

    @helper.run_async_test
    async def test_local_abort_2(self):
        """
        HttpClientProtocol.write_request() -> \
        [HttpRequestWriter.write(), HttpRequestWriter.flush()] -x-> \
        HttpRequestWriter.finish() -> \
        HttpRequestWriter.read_response() -> \
        HttpResponseReader.read()
        """
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        writer = await protocol.write_request(
            HttpRequestMethod.POST, uri=b"/", headers={b"content-type": b"1"})

        writer.write(os.urandom(1))
        await writer.flush()

        writer.abort()
        assert transport_mock._closing is True

        with pytest.raises(WriteAbortedError):
            writer.finish()

        with pytest.raises(ReadAbortedError):
            await writer.read_response()

    @helper.run_async_test
    async def test_local_abort_3(self):
        """
        HttpClientProtocol.write_request() -> \
        [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
        HttpRequestWriter.finish() -x-> \
        HttpRequestWriter.read_response() -> \
        HttpResponseReader.read()
        """
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        writer = await protocol.write_request(
            HttpRequestMethod.POST, uri=b"/", headers={b"content-type": b"1"})

        writer.write(os.urandom(1))
        await writer.flush()
        writer.finish()

        protocol.data_received(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r")

        writer.abort()
        assert transport_mock._closing is True

        with pytest.raises(ReadAbortedError):
            await writer.read_response()

    @helper.run_async_test
    async def test_local_abort_4(self):
        """
        HttpClientProtocol.write_request() -> \
        [HttpRequestWriter.write(), HttpRequestWriter.flush()] -> \
        HttpRequestWriter.finish() -> \
        HttpRequestWriter.read_response() -x-> \
        HttpResponseReader.read()
        """
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        writer = await protocol.write_request(
            HttpRequestMethod.POST, uri=b"/", headers={b"content-type": b"1"})

        writer.write(os.urandom(1))
        await writer.flush()
        writer.finish()

        protocol.data_received(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: Chunked\r\n\r\n")

        reader = await writer.read_response()

        writer.abort()
        assert transport_mock._closing is True

        with pytest.raises(ReadAbortedError):
            await reader.read()

    @helper.run_async_test
    async def test_endless_response_cutoff(self):
        protocol = HttpClientProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(b"HTTP/1.0 200 OK\r\n\r\n")

        writer = await protocol.write_request(HttpRequestMethod.GET, uri=b"/")
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


class HttpServerProtocolTestCase:
    def test_init(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()
        protocol.connection_made(transport_mock)
        transport_mock._closing = True
        protocol.connection_lost(None)

    @helper.run_async_test
    async def test_simple_request(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()
        protocol.connection_made(transport_mock)

        async def aiter_requests():
            count = 0
            async for reader in protocol:
                with pytest.raises(ReadFinishedError):
                    await reader.read()

                writer = reader.write_response(HttpStatusCode.OK)
                writer.finish()

                count += 1

            assert count == 1

        tsk = helper.loop.create_task(aiter_requests())

        await asyncio.sleep(0)
        assert not tsk.done()

        protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

        await tsk

        assert protocol.eof_received() is True

        assert transport_mock._closing is True
        protocol.connection_lost(None)

        assert b"".join(transport_mock._data_chunks) == \
            (b"HTTP/1.1 200 OK\r\n"
             b"Server: magichttp/%s\r\n"
             b"Connection: Close\r\n"
             b"Transfer-Encoding: Chunked\r\n\r\n0\r\n\r\n") % \
            __version__.encode()

    @helper.run_async_test
    async def test_simple_request_10(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()
        protocol.connection_made(transport_mock)

        async def aiter_requests():
            count = 0
            async for reader in protocol:
                with pytest.raises(ReadFinishedError):
                    await reader.read()

                writer = reader.write_response(HttpStatusCode.OK)
                writer.finish()

                count += 1

            assert count == 1

        tsk = helper.loop.create_task(aiter_requests())

        await asyncio.sleep(0)
        assert not tsk.done()

        protocol.data_received(b"GET / HTTP/1.0\r\n\r\n")

        await tsk

        assert protocol.eof_received() is True

        assert transport_mock._closing is True
        protocol.connection_lost(None)

        assert b"".join(transport_mock._data_chunks) == \
            (b"HTTP/1.0 200 OK\r\n"
             b"Server: magichttp/%s\r\n"
             b"Connection: Close\r\n\r\n") % \
            __version__.encode()

    @helper.run_async_test
    async def test_chunked_request(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()
        protocol.connection_made(transport_mock)

        async def aiter_requests():
            count = 0
            async for reader in protocol:
                await reader.read(9, exactly=True) == b"123456789"

                with pytest.raises(ReadFinishedError):
                    await reader.read()

                writer = reader.write_response(HttpStatusCode.OK)
                writer.finish()

                count += 1

            assert count == 1

        tsk = helper.loop.create_task(aiter_requests())

        await asyncio.sleep(0)
        assert not tsk.done()

        protocol.data_received(
            b"GET / HTTP/1.1\r\nTransfer-Encoding: Chunked\r\n\r\n"
            b"5\r\n12345\r\n4\r\n6789\r\n0\r\n\r\n")

        await tsk

        assert protocol.eof_received() is True

        assert transport_mock._closing is True
        protocol.connection_lost(None)

        assert b"".join(transport_mock._data_chunks) == \
            (b"HTTP/1.1 200 OK\r\n"
             b"Server: magichttp/%s\r\n"
             b"Connection: Close\r\n"
             b"Transfer-Encoding: Chunked\r\n\r\n0\r\n\r\n") % \
            __version__.encode()

    @helper.run_async_test
    async def test_simple_response_with_chunked_body(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()
        protocol.connection_made(transport_mock)

        data = os.urandom(20)

        async def aiter_requests():
            count = 0
            async for reader in protocol:
                with pytest.raises(ReadFinishedError):
                    await reader.read()

                writer = reader.write_response(
                    HttpStatusCode.OK)
                writer.finish(data)

                count += 1

            assert count == 1

        tsk = helper.loop.create_task(aiter_requests())

        await asyncio.sleep(0)
        assert not tsk.done()

        protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

        await tsk

        assert protocol.eof_received() is True

        assert transport_mock._closing is True
        protocol.connection_lost(None)

        assert b"".join(transport_mock._data_chunks) == \
            (b"HTTP/1.1 200 OK\r\n"
             b"Server: magichttp/%s\r\n"
             b"Connection: Close\r\n"
             b"Transfer-Encoding: Chunked\r\n\r\n14\r\n") % \
            __version__.encode() + data + b"\r\n0\r\n\r\n"

    @helper.run_async_test
    async def test_simple_response_with_content_length(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()
        protocol.connection_made(transport_mock)

        data = os.urandom(20)

        async def aiter_requests():
            count = 0
            async for reader in protocol:
                with pytest.raises(ReadFinishedError):
                    await reader.read()

                writer = reader.write_response(
                    HttpStatusCode.OK, headers={b"content-length": b"20"})
                writer.finish(data)

                count += 1

            assert count == 1

        tsk = helper.loop.create_task(aiter_requests())

        await asyncio.sleep(0)
        assert not tsk.done()

        protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

        await tsk

        assert protocol.eof_received() is True

        assert transport_mock._closing is True
        protocol.connection_lost(None)

        assert b"".join(transport_mock._data_chunks) == \
            (b"HTTP/1.1 200 OK\r\n"
             b"Content-Length: 20\r\n"
             b"Server: magichttp/%s\r\n"
             b"Connection: Close\r\n\r\n") % \
            __version__.encode() + data

    @helper.run_async_test
    async def test_keep_alive(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n\r\n"
            b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n\r\n")

        async def aiter_requests():
            count = 0

            async for reader in protocol:
                assert reader.initial.uri == b"/"
                assert reader.initial.headers[b"connection"] == b"Keep-Alive"
                with pytest.raises(ReadFinishedError):
                    await reader.read()

                writer = reader.write_response(HttpStatusCode.NO_CONTENT)

                assert b"".join(transport_mock._data_chunks) == \
                    (b"HTTP/1.1 204 No Content\r\n"
                     b"Server: magichttp/%s\r\n"
                     b"Connection: Keep-Alive\r\n\r\n") % \
                    __version__.encode()
                transport_mock._data_chunks.clear()

                writer.finish()

                assert b"".join(transport_mock._data_chunks) == b""

                count += 1

            assert count == 2

        tsk = helper.loop.create_task(aiter_requests())

        await asyncio.sleep(0)
        assert not tsk.done()

        assert protocol.eof_received() is True

        await tsk

        transport_mock._closing = True
        protocol.connection_lost(None)

        with pytest.raises(StopAsyncIteration):
            await protocol.__aiter__().__anext__()

    @helper.run_async_test
    async def test_response_with_endless_body(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(b"GET / HTTP/1.0\r\n\r\n")

        async for reader in protocol:
            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(HttpStatusCode.OK)

            assert b"".join(transport_mock._data_chunks) == \
                (b"HTTP/1.0 200 OK\r\n"
                 b"Server: magichttp/%s\r\n"
                 b"Connection: Close\r\n\r\n") % \
                __version__.encode()
            transport_mock._data_chunks.clear()

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

    @helper.run_async_test
    async def test_upgrade(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"GET / HTTP/1.1\r\nConnection: Upgrade\r\n"
            b"Upgrade: WebSocket\r\n\r\n")

        count = 0
        async for reader in protocol:
            count += 1

            assert reader.initial.headers[b"connection"] == b"Upgrade"
            assert reader.initial.headers[b"upgrade"] == b"WebSocket"

            writer = reader.write_response(
                HttpStatusCode.SWITCHING_PROTOCOLS,
                headers={b"Connection": b"Upgrade", b"Upgrade": b"WebSocket"})

            assert b"".join(transport_mock._data_chunks) == \
                (b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\n"
                 b"Upgrade: WebSocket\r\n"
                 b"Server: magichttp/%s\r\n\r\n") % __version__.encode()
            transport_mock._data_chunks.clear()

            for i in range(0, 5):
                for j in range(0, 5):
                    data = os.urandom(1024)
                    protocol.data_received(data)
                    assert await reader.read(4096) == data

                for k in range(0, 5):
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

        assert count == 1

    @helper.run_async_test
    async def test_close_after_finished(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n\r\n")

        count = 0

        async for reader in protocol:
            count += 1

            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(
                HttpStatusCode.NO_CONTENT,
                headers={b"connection": b"Keep-Alive"})

            writer.finish()

            assert b"".join(transport_mock._data_chunks) == \
                (b"HTTP/1.1 204 No Content\r\n"
                 b"Connection: Keep-Alive\r\n"
                 b"Server: magichttp/%s\r\n\r\n") % \
                __version__.encode()
            transport_mock._data_chunks.clear()

            protocol.close()

            assert transport_mock._closing is True

            assert protocol.eof_received() is True
            protocol.connection_lost(None)

        assert count == 1

    @helper.run_async_test
    async def test_close_before_finished(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n\r\n")

        async def wait_closed():
            await protocol.wait_closed()

        count = 0

        async for reader in protocol:
            count += 1

            protocol.close()

            tsk = helper.loop.create_task(wait_closed())
            await asyncio.sleep(0)

            assert tsk.done() is False

            assert transport_mock._closing is False

            with pytest.raises(ReadFinishedError):
                await reader.read()

            writer = reader.write_response(
                HttpStatusCode.NO_CONTENT,
                headers={b"connection": b"Keep-Alive"})

            writer.finish()

            assert b"".join(transport_mock._data_chunks) == \
                (b"HTTP/1.1 204 No Content\r\n"
                 b"Connection: Keep-Alive\r\n"
                 b"Server: magichttp/%s\r\n\r\n") % \
                __version__.encode()
            transport_mock._data_chunks.clear()

        assert count == 1

        assert transport_mock._closing is True

        assert protocol.eof_received() is True

        assert tsk.done() is False
        protocol.connection_lost(None)

        await tsk

    @helper.run_async_test
    async def test_request_initial_too_large(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(os.urandom(5 * 1024 * 1024))

        with pytest.raises(RequestInitialTooLargeError) as exc_info:
            await protocol.__anext__()

        writer = exc_info.value.write_response()
        writer.finish(b"12345")

        assert transport_mock._closing is True
        protocol.connection_lost(None)

        assert b"".join(transport_mock._data_chunks) == \
            (b"HTTP/1.1 431 Request Header Fields Too Large\r\n"
             b"Server: magichttp/%s\r\n"
             b"Connection: Close\r\n"
             b"Transfer-Encoding: Chunked\r\n\r\n") % \
            __version__.encode() + b"5\r\n12345\r\n0\r\n\r\n"
        transport_mock._data_chunks.clear()

    @helper.run_async_test
    async def test_request_initial_malformed(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(b"HTTP/1.1\r\n\r\n")

        with pytest.raises(RequestInitialMalformedError) as exc_info:
            await protocol.__anext__()

        writer = exc_info.value.write_response()
        writer.finish(b"12345")

        assert transport_mock._closing is True
        protocol.connection_lost(None)

        assert b"".join(transport_mock._data_chunks) == \
            (b"HTTP/1.1 400 Bad Request\r\n"
             b"Server: magichttp/%s\r\n"
             b"Connection: Close\r\n"
             b"Transfer-Encoding: Chunked\r\n\r\n") % \
            __version__.encode() + b"5\r\n12345\r\n0\r\n\r\n"
        transport_mock._data_chunks.clear()

    @helper.run_async_test
    async def test_request_chunk_len_too_long(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n"
            b"Transfer-Encoding: Chunked\r\n\r\n")

        async for reader in protocol:
            assert reader.initial.headers[b"transfer-encoding"] == b"Chunked"

            protocol.data_received(b"0" * 5 * 1024 * 1024)

            with pytest.raises(EntityTooLargeError):
                await reader.read()

            writer = reader.write_response(
                HttpStatusCode.REQUEST_ENTITY_TOO_LARGE)
            writer.finish()

            assert transport_mock._closing is True
            protocol.connection_lost(None)

        assert b"".join(transport_mock._data_chunks) == \
            (b"HTTP/1.1 413 Request Entity Too Large\r\n"
             b"Server: magichttp/%s\r\n"
             b"Connection: Close\r\n"
             b"Transfer-Encoding: Chunked\r\n\r\n") % \
            __version__.encode() + b"0\r\n\r\n"
        transport_mock._data_chunks.clear()

    @helper.run_async_test
    async def test_request_chunk_len_malformed(self):
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(
            b"GET / HTTP/1.1\r\nConnection: Keep-Alive\r\n"
            b"Transfer-Encoding: Chunked\r\n\r\n")

        async for reader in protocol:
            assert reader.initial.headers[b"transfer-encoding"] == b"Chunked"

            protocol.data_received(b"ABCDEFGH\r\n")

            with pytest.raises(ReceivedDataMalformedError):
                await reader.read()

            writer = reader.write_response(
                HttpStatusCode.BAD_REQUEST)
            writer.finish()

            assert transport_mock._closing is True
            protocol.connection_lost(None)

        assert b"".join(transport_mock._data_chunks) == \
            (b"HTTP/1.1 400 Bad Request\r\n"
             b"Server: magichttp/%s\r\n"
             b"Connection: Close\r\n"
             b"Transfer-Encoding: Chunked\r\n\r\n") % \
            __version__.encode() + b"0\r\n\r\n"
        transport_mock._data_chunks.clear()

    @helper.run_async_test
    async def test_remote_abort_1(self):
        """
        HttpServerProtocol.connection_made() -x-> \
        HttpServerProtocol.__anext__() -> \
        HttpRequestReader.read() -> \
        HttpRequestReader.write_response() -> \
        [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
        HttpResponseWriter.finish()
        """
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)

        protocol.connection_lost(None)
        assert transport_mock._closing is True

        with pytest.raises(StopAsyncIteration):
            await protocol.__anext__()

    @helper.run_async_test
    async def test_remote_abort_2(self):
        """
        HttpServerProtocol.connection_made() -> \
        HttpServerProtocol.__anext__() -x-> \
        HttpRequestReader.read() -> \
        HttpRequestReader.write_response() -> \
        [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
        HttpResponseWriter.finish()
        """
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(b"GET / HTTP/1.1\r\nContent-Length: 20\r\n\r\n")

        async for reader in protocol:
            protocol.connection_lost(None)
            assert transport_mock._closing is True

            with pytest.raises(ReadAbortedError):
                await reader.read()

            with pytest.raises(WriteAbortedError):
                reader.write_response(HttpStatusCode.BAD_REQUEST)

    @helper.run_async_test
    async def test_remote_abort_3(self):
        """
        HttpServerProtocol.connection_made() -> \
        HttpServerProtocol.__anext__() -> \
        HttpRequestReader.read() -x-> \
        HttpRequestReader.write_response() -> \
        [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
        HttpResponseWriter.finish()
        """
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

        protocol.connection_made(transport_mock)
        protocol.data_received(b"GET / HTTP/1.1\r\n\r\n")

        async for reader in protocol:
            with pytest.raises(ReadFinishedError):
                await reader.read()

            protocol.connection_lost(None)
            assert transport_mock._closing is True

            with pytest.raises(WriteAbortedError):
                reader.write_response(HttpStatusCode.BAD_REQUEST)

    @helper.run_async_test
    async def test_remote_abort_4(self):
        """
        HttpServerProtocol.connection_made() -> \
        HttpServerProtocol.__anext__() -> \
        HttpRequestReader.read() -> \
        HttpRequestReader.write_response() -x-> \
        [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
        HttpResponseWriter.finish()
        """
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

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

    @helper.run_async_test
    async def test_remote_abort_5(self):
        """
        HttpServerProtocol.connection_made() -> \
        HttpServerProtocol.__anext__() -> \
        HttpRequestReader.read() -> \
        HttpRequestReader.write_response() -> \
        [HttpResponseWriter.write(), HttpResponseWriter.flush()] -x-> \
        HttpResponseWriter.finish()
        """
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

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

    @helper.run_async_test
    async def test_local_abort_1(self):
        """
        HttpServerProtocol.__anext__() -x-> \
        HttpRequestReader.read() -> \
        HttpRequestReader.write_response() -> \
        [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
        HttpResponseWriter.finish()
        """
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

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

    @helper.run_async_test
    async def test_local_abort_2(self):
        """
        HttpServerProtocol.__anext__() -> \
        HttpRequestReader.read() -x-> \
        HttpRequestReader.write_response() -> \
        [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
        HttpResponseWriter.finish()
        """
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

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

    @helper.run_async_test
    async def test_local_abort_3(self):
        """
        HttpServerProtocol.__anext__() -> \
        HttpRequestReader.read() -> \
        HttpRequestReader.write_response() -x-> \
        [HttpResponseWriter.write(), HttpResponseWriter.flush()] -> \
        HttpResponseWriter.finish()
        """
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

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

    @helper.run_async_test
    async def test_local_abort_4(self):
        """
        HttpServerProtocol.__anext__() -> \
        HttpRequestReader.read() -> \
        HttpRequestReader.write_response() -> \
        [HttpResponseWriter.write(), HttpResponseWriter.flush()] -x-> \
        HttpResponseWriter.finish()
        """
        protocol = HttpServerProtocol()
        transport_mock = TransportMock()

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
