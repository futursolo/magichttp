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
    WriteAfterFinishedError, ReadFinishedError, __version__

from _helper import TestHelper

import pytest


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

        writer = await protocol.write_request(HttpRequestMethod.Get, uri=b"/")

        assert b"".join(transport_mock._data_chunks) == \
            (b"GET / HTTP/1.1\r\nUser-Agent: magichttp/%s\r\n"
             b"Accept: */*\r\nConnection: Keep-Alive\r\n\r\n") % \
                __version__.encode()
        transport_mock._data_chunks.clear()

        assert protocol.eof_received() is True

        writer.write(b"12345")
        writer.finish()

        assert b"".join(transport_mock._data_chunks) == b"12345"

        with pytest.raises(WriteAfterFinishedError):
            writer.write(b"1")

        protocol.connection_lost(None)

        reader = await writer.read_response()

        with pytest.raises(ReadFinishedError):
            await reader.read()

        assert reader.initial.status_code == 200
        assert reader.initial.headers == {}
