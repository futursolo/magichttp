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

from magichttp.h1parsers import UnparsableHttpMessage, \
     parse_request_initial, parse_response_initial, \
     discover_request_body_length, \
     BODY_IS_CHUNKED, discover_response_body_length, BODY_IS_ENDLESS, \
     is_chunked_body, InvalidTransferEncoding, InvalidContentLength, \
     parse_chunk_length, InvalidChunkLength
from magichttp import HttpVersion, HttpRequestMethod, HttpRequestInitial, \
    HttpResponseInitial, HttpStatusCode

import pytest
import magicdict


class H1IsChunkedBodyTestCase:
    def test_chunked(self):
        assert is_chunked_body(b"Chunked") is True

    def test_identity(self):
        assert is_chunked_body(b"Identity") is False

    def test_malformed_transfer_encodings(self):
        with pytest.raises(InvalidTransferEncoding):
            is_chunked_body(b"Identity; Chunked")

        with pytest.raises(InvalidTransferEncoding):
            is_chunked_body(b"Chunked; Gzip")


class H1ParseRequestInitialTestCase:
    def test_simple_request(self):
        buf = bytearray(b"G")

        assert parse_request_initial(buf) is None

        buf += b"ET / HTTP/1.1\r"

        assert parse_request_initial(buf) is None

        buf += b"\n\r\n"

        req = parse_request_initial(buf)

        assert req is not None

        assert req.headers == {}
        assert req.version == HttpVersion.V1_1
        assert req.uri == b"/"
        assert req.method == HttpRequestMethod.GET
        assert not hasattr(req, "authority")
        assert not hasattr(req, "scheme")

    def test_simple_post_request(self):
        buf = bytearray(
            b"POST / HTTP/1.1\r\nContent-Length: 20\r\n"
            b"Host: localhost\r\nTransfer-Encoding: Identity\r\n"
            b"X-Scheme: HTTP\r\n\r\n")

        req = parse_request_initial(buf)

        assert req is not None

        assert req.headers[b"content-length"] == b"20"
        assert req.version == HttpVersion.V1_1
        assert req.uri == b"/"
        assert req.method == HttpRequestMethod.POST
        assert req.authority == b"localhost"
        assert req.scheme.lower() == b"http"

    def test_malformed_requests(self):
        with pytest.raises(UnparsableHttpMessage):
            parse_request_initial(bytearray(b"GET / HTTP/3.0\r\n\r\n"))

        with pytest.raises(UnparsableHttpMessage):
            parse_request_initial(
                bytearray(b"GET / HTTP/1.1\r\nContent-Length\r\n\r\n"))


class H1ParseResponseInitialTestCase:
    def test_simple_response(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"https",
            headers=magicdict.FrozenTolerantMagicDict(),
            authority=None)

        buf = bytearray(b"HTTP/1.1 200 OK\r\n\r")

        assert parse_response_initial(buf, req_initial=req) is None

        buf += b"\n"

        res = parse_response_initial(buf, req_initial=req)

        assert res is not None

        assert res.headers == {}
        assert res.status_code == HttpStatusCode.OK
        assert res.version == HttpVersion.V1_1

    def test_malformed_responses(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"https",
            headers=magicdict.FrozenTolerantMagicDict(),
            authority=None)

        with pytest.raises(UnparsableHttpMessage):
            parse_response_initial(
                bytearray(b"HTTP/1.1 ???200 Not OK\r\n\r\n"), req_initial=req)

        with pytest.raises(UnparsableHttpMessage):
            parse_response_initial(
                bytearray(b"HTTP/1.1 200 OK\r\nb\r\n\r\n"), req_initial=req)


class H1DiscoverRequestBodyLengthTestCase:
    def test_upgrade_request(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=None,
            headers=magicdict.FrozenTolerantMagicDict(
                [(b"connection", b"Upgrade"), (b"content-length", b"20")]),
            authority=None)

        assert discover_request_body_length(req) == BODY_IS_ENDLESS

    def test_request_chunked(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=None,
            headers=magicdict.FrozenTolerantMagicDict(
                [(b"content-length", b"20"),
                 (b"transfer-encoding", b"Chunked")]),
            authority=None)

        assert discover_request_body_length(req) == BODY_IS_CHUNKED

    def test_request_content_length(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=None,
            headers=magicdict.FrozenTolerantMagicDict(
                [(b"content-length", b"20")]),
            authority=None)

        assert discover_request_body_length(req) == 20

    def test_request_malformed_content_length(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=None,
            headers=magicdict.FrozenTolerantMagicDict(
                [(b"content-length", b"4e21")]),
            authority=None)

        with pytest.raises(InvalidContentLength):
            discover_request_body_length(req)

    def test_request_no_body(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=None,
            headers=magicdict.FrozenTolerantMagicDict(),
            authority=None)

        assert discover_request_body_length(req) == 0


class H1DiscoverResponseBodyLengthTestCase:
    def test_upgrade_response(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"https",
            headers=magicdict.FrozenTolerantMagicDict(
                [(b"Connection", "Upgrade")]),
            authority=None)

        res = HttpResponseInitial(
            HttpStatusCode.SWITCHING_PROTOCOLS,
            version=HttpVersion.V1_1,
            headers=magicdict.FrozenTolerantMagicDict(
                [(b"connection", b"Upgrade")]))

        assert discover_response_body_length(
            res, req_initial=req) == BODY_IS_ENDLESS

    def test_head_request(self):
        req = HttpRequestInitial(
            HttpRequestMethod.HEAD,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"https",
            headers=magicdict.FrozenTolerantMagicDict(),
            authority=None)

        res = HttpResponseInitial(
            HttpStatusCode.OK,
            version=HttpVersion.V1_1,
            headers=magicdict.FrozenTolerantMagicDict(
                [(b"content-length", b"20")]))

        assert discover_response_body_length(res, req_initial=req) == 0

    def test_no_content(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"https",
            headers=magicdict.FrozenTolerantMagicDict(),
            authority=None)

        res = HttpResponseInitial(
            HttpStatusCode.NO_CONTENT,
            version=HttpVersion.V1_1,
            headers=magicdict.FrozenTolerantMagicDict())

        assert discover_response_body_length(res, req_initial=req) == 0

    def test_response_chunked(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=None,
            headers=magicdict.FrozenTolerantMagicDict(),
            authority=None)

        res = HttpResponseInitial(
            HttpStatusCode.OK,
            version=HttpVersion.V1_1,
            headers=magicdict.FrozenTolerantMagicDict(
                [(b"transfer-encoding", b"Chunked")]))

        assert discover_response_body_length(
            res, req_initial=req) == BODY_IS_CHUNKED

    def test_response_endless(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"https",
            headers=magicdict.FrozenTolerantMagicDict(),
            authority=None)

        res = HttpResponseInitial(
            HttpStatusCode.OK,
            version=HttpVersion.V1_1,
            headers=magicdict.FrozenTolerantMagicDict())

        assert discover_response_body_length(
            res, req_initial=req) == BODY_IS_ENDLESS

    def test_response_content_length(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=None,
            headers=magicdict.FrozenTolerantMagicDict(),
            authority=None)

        res = HttpResponseInitial(
            HttpStatusCode.OK,
            version=HttpVersion.V1_1,
            headers=magicdict.FrozenTolerantMagicDict(
                [(b"content-length", b"20")]))

        assert discover_response_body_length(res, req_initial=req) == 20


class H1ParseChunkLengthTestCase:
    def test_valid_chunk_length(self):
        buf = bytearray(b"5\r")

        assert parse_chunk_length(buf) is None

        buf += b"\nASDFG\r\n"

        assert parse_chunk_length(buf) == 5
        assert buf == b"ASDFG\r\n"

    def test_valid_last_chunk(self):
        buf = bytearray(b"0\r\n\r\n")

        assert parse_chunk_length(buf) == 0
        assert buf == b"\r\n"

    def test_malformed_chunk_lengths(self):
        buf = bytearray(b"G\r\n1234567890ABCDEFG\r\n")

        with pytest.raises(InvalidChunkLength):
            assert parse_chunk_length(buf) == 17
