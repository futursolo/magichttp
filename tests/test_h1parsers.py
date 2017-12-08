#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2017 Kaede Hoshikawa
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

from magichttp.h1parsers import H1RequestParser, H1ResponseParser, \
    UnparsableHttpMessage, IncompleteHttpMessage
from magichttp import HttpVersion, HttpRequestMethod

import os
import pytest


class H1RequestParserTestCase:
    def test_init(self):
        parser = H1RequestParser(bytearray(), using_https=False)

    def test_simple_request(self):
        buf = bytearray(b"G")
        parser = H1RequestParser(buf, using_https=False)

        req = parser.parse_request()

        assert req is None

        buf += b"ET / HTTP/1.1\r"

        req = parser.parse_request()

        assert req is None

        buf += b"\n\r\n"

        req = parser.parse_request()

        assert req is not None

        assert req.headers == {}
        assert req.version == HttpVersion.V1_1
        assert req.uri == b"/"
        assert req.method == HttpRequestMethod.Get
        assert not hasattr(req, "authority")
        assert req.scheme == b"http"

        assert parser.parse_body() is None

    def test_simple_request_with_body(self):
        buf = bytearray(
            b"POST / HTTP/1.1\r\nContent-Length: 20\r\n"
            b"Host: localhost\r\nTransfer-Encoding: Identity\r\n\r\n")
        parser = H1RequestParser(buf, using_https=True)

        req = parser.parse_request()

        assert req is not None

        assert req.headers[b"content-length"] == b"20"
        assert req.version == HttpVersion.V1_1
        assert req.uri == b"/"
        assert req.method == HttpRequestMethod.Post
        assert req.authority == b"localhost"
        assert req.scheme == b"https"

        assert parser.parse_body() == b""

        body_part = os.urandom(5)
        buf += body_part

        assert parser.parse_body() == body_part

        assert parser.parse_body() == b""

        body_part = os.urandom(16)
        buf += body_part

        assert parser.parse_body() == body_part[:15]

        assert parser.parse_body() is None

    def test_malformed_request(self):
        buf = bytearray(b"GET / HTTP/3.0\r\n\r\n")

        parser = H1RequestParser(buf, using_https=False)

        with pytest.raises(UnparsableHttpMessage):
            parser.parse_request()

        buf = bytearray(b"GET / HTTP/1.1\r\nContent-Length\r\n\r\n")

        parser = H1RequestParser(buf, using_https=False)

        with pytest.raises(UnparsableHttpMessage):
            parser.parse_request()

        buf = bytearray(b"GET / HTTP/1.1\r\nContent-Length: ABC\r\n\r\n")

        parser = H1RequestParser(buf, using_https=False)

        with pytest.raises(UnparsableHttpMessage):
            parser.parse_request()

        buf = bytearray(
            b"GET / HTTP/1.1\r\nTransfer-Encoding: Identity; Chunked\r\n\r\n")

        parser = H1RequestParser(buf, using_https=False)

        with pytest.raises(UnparsableHttpMessage):
            parser.parse_request()

        buf = bytearray(
            b"GET / HTTP/1.1\r\nTransfer-Encoding: Chunked; Gzip\r\n\r\n")

        parser = H1RequestParser(buf, using_https=False)

        with pytest.raises(UnparsableHttpMessage):
            parser.parse_request()

        buf = bytearray(b"GET / HTTP/1.1\r\n\r")

        parser = H1RequestParser(buf, using_https=False)
        parser.buf_ended = True

        with pytest.raises(IncompleteHttpMessage):
            parser.parse_request()

        buf = bytearray(b"GET / HTTP/1.1\r\nContent-Length:20\r\n\r\n")

        parser = H1RequestParser(buf, using_https=False)
        parser.buf_ended = True

        parser.parse_request()

        with pytest.raises(IncompleteHttpMessage):
            parser.parse_body()

    def test_upgrade_request(self):
        buf = bytearray(
            b"GET / HTTP/1.1\r\n"
            b"Connection: Upgrade\r\n\r\n")
        parser = H1RequestParser(buf, using_https=False)

        req = parser.parse_request()

        assert req is not None

        assert req.headers[b"connection"] == b"Upgrade"

        assert parser.parse_body() == b""

        body_part = os.urandom(5)
        buf += body_part

        assert parser.parse_body() == body_part

        assert parser.parse_body() == b""

        body_part = os.urandom(16)
        buf += body_part

        assert parser.parse_body() == body_part

        assert parser.parse_body() == b""
        assert parser.parse_body() == b""

        body_part = os.urandom(20)
        buf += body_part
        parser.buf_ended = True

        assert parser.parse_body() == body_part

        assert parser.parse_body() is None

    def test_chunked_request(self):
        buf = bytearray(
            b"POST / HTTP/1.1\r\nTransfer-Encoding: Chunked\r\n\r\n")

        parser = H1RequestParser(buf, using_https=False)
        req = parser.parse_request()

        assert req is not None

        assert req.headers[b"transfer-encoding"] == b"Chunked"

        assert parser.parse_body() == b""

        buf += b"4\r\n1234\r\n"

        assert parser.parse_body() == b"1234"

        buf += b"0\r\n\r\n"

        assert parser.parse_body() is None
