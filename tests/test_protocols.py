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
    WriteAbortedError, ReadAbortedError

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
