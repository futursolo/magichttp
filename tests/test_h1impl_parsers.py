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

import magicdict
import pytest

from magichttp import (
    HttpRequestInitial,
    HttpRequestMethod,
    HttpResponseInitial,
    HttpStatusCode,
    HttpVersion,
)
from magichttp.h1impl.parsers import (
    BODY_IS_CHUNKED,
    BODY_IS_ENDLESS,
    InvalidChunkLength,
    InvalidContentLength,
    InvalidTransferEncoding,
    UnparsableHttpMessage,
    discover_request_body_length,
    discover_response_body_length,
    is_chunked_body,
    parse_chunk_length,
    parse_request_initial,
    parse_response_initial,
)


def test_chunked() -> None:
    assert is_chunked_body("Chunked") is True


def test_identity() -> None:
    assert is_chunked_body("Identity") is False


def test_malformed_transfer_encodings() -> None:
    with pytest.raises(InvalidTransferEncoding):
        is_chunked_body("Identity; Chunked")

    with pytest.raises(InvalidTransferEncoding):
        is_chunked_body("Chunked; Gzip")


def test_simple_request() -> None:
    buf = bytearray(b"G")

    assert parse_request_initial(buf) is None

    buf += b"ET / HTTP/1.1\r"

    assert parse_request_initial(buf) is None

    buf += b"\n\r\n"

    req = parse_request_initial(buf)

    assert req is not None

    assert req.headers == {}
    assert req.version == HttpVersion.V1_1
    assert req.uri == "/"
    assert req.method == HttpRequestMethod.GET
    assert not hasattr(req, "authority")
    assert not hasattr(req, "scheme")


def test_simple_post_request() -> None:
    buf = bytearray(
        b"POST / HTTP/1.1\r\nContent-Length: 20\r\n"
        b"Host: localhost\r\nTransfer-Encoding: Identity\r\n"
        b"X-Scheme: HTTP\r\n\r\n"
    )

    req = parse_request_initial(buf)

    assert req is not None

    assert req.headers["content-length"] == "20"
    assert req.version == HttpVersion.V1_1
    assert req.uri == "/"
    assert req.method == HttpRequestMethod.POST
    assert req.authority == "localhost"
    assert req.scheme.lower() == "http"


def test_malformed_requests() -> None:
    with pytest.raises(UnparsableHttpMessage):
        parse_request_initial(bytearray(b"GET / HTTP/3.0\r\n\r\n"))

    with pytest.raises(UnparsableHttpMessage):
        parse_request_initial(
            bytearray(b"GET / HTTP/1.1\r\nContent-Length\r\n\r\n")
        )


def test_simple_response() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="https",
        headers=magicdict.FrozenTolerantMagicDict(),
        authority=None,
    )

    buf = bytearray(b"HTTP/1.1 200 OK\r\n\r")

    assert parse_response_initial(buf, req_initial=req) is None

    buf += b"\n"

    res = parse_response_initial(buf, req_initial=req)

    assert res is not None

    assert res.headers == {}
    assert res.status_code == HttpStatusCode.OK
    assert res.version == HttpVersion.V1_1


def test_malformed_responses() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="https",
        headers=magicdict.FrozenTolerantMagicDict(),
        authority=None,
    )

    with pytest.raises(UnparsableHttpMessage):
        parse_response_initial(
            bytearray(b"HTTP/1.1 ???200 Not OK\r\n\r\n"), req_initial=req
        )

    with pytest.raises(UnparsableHttpMessage):
        parse_response_initial(
            bytearray(b"HTTP/1.1 200 OK\r\nb\r\n\r\n"), req_initial=req
        )


def test_upgrade_request() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme=None,
        headers=magicdict.FrozenTolerantMagicDict(
            [
                ("connection", "Upgrade"),
                ("upgrade", "My-Super-Proto"),
                ("content-length", "20"),
            ]
        ),
        authority=None,
    )

    assert discover_request_body_length(req) == BODY_IS_ENDLESS


def test_request_chunked() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme=None,
        headers=magicdict.FrozenTolerantMagicDict(
            [("content-length", "20"), ("transfer-encoding", "Chunked")]
        ),
        authority=None,
    )

    assert discover_request_body_length(req) == BODY_IS_CHUNKED


def test_request_content_length() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme=None,
        headers=magicdict.FrozenTolerantMagicDict([("content-length", "20")]),
        authority=None,
    )

    assert discover_request_body_length(req) == 20


def test_request_malformed_content_length() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme=None,
        headers=magicdict.FrozenTolerantMagicDict(
            [("content-length", "4e21")]
        ),
        authority=None,
    )

    with pytest.raises(InvalidContentLength):
        discover_request_body_length(req)


def test_request_no_body() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme=None,
        headers=magicdict.FrozenTolerantMagicDict(),
        authority=None,
    )

    assert discover_request_body_length(req) == 0


def test_upgrade_response() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="https",
        headers=magicdict.FrozenTolerantMagicDict([("Connection", "Upgrade")]),
        authority=None,
    )

    res = HttpResponseInitial(
        HttpStatusCode.SWITCHING_PROTOCOLS,
        version=HttpVersion.V1_1,
        headers=magicdict.FrozenTolerantMagicDict([("connection", "Upgrade")]),
    )

    assert (
        discover_response_body_length(res, req_initial=req) == BODY_IS_ENDLESS
    )


def test_head_request() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.HEAD,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="https",
        headers=magicdict.FrozenTolerantMagicDict(),
        authority=None,
    )

    res = HttpResponseInitial(
        HttpStatusCode.OK,
        version=HttpVersion.V1_1,
        headers=magicdict.FrozenTolerantMagicDict([("content-length", "20")]),
    )

    assert discover_response_body_length(res, req_initial=req) == 0


def test_no_content() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="https",
        headers=magicdict.FrozenTolerantMagicDict(),
        authority=None,
    )

    res = HttpResponseInitial(
        HttpStatusCode.NO_CONTENT,
        version=HttpVersion.V1_1,
        headers=magicdict.FrozenTolerantMagicDict(),
    )

    assert discover_response_body_length(res, req_initial=req) == 0


def test_response_chunked() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme=None,
        headers=magicdict.FrozenTolerantMagicDict(),
        authority=None,
    )

    res = HttpResponseInitial(
        HttpStatusCode.OK,
        version=HttpVersion.V1_1,
        headers=magicdict.FrozenTolerantMagicDict(
            [("transfer-encoding", "Chunked")]
        ),
    )

    assert (
        discover_response_body_length(res, req_initial=req) == BODY_IS_CHUNKED
    )


def test_response_endless() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="https",
        headers=magicdict.FrozenTolerantMagicDict(),
        authority=None,
    )

    res = HttpResponseInitial(
        HttpStatusCode.OK,
        version=HttpVersion.V1_1,
        headers=magicdict.FrozenTolerantMagicDict(),
    )

    assert (
        discover_response_body_length(res, req_initial=req) == BODY_IS_ENDLESS
    )


def test_response_content_length() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme=None,
        headers=magicdict.FrozenTolerantMagicDict(),
        authority=None,
    )

    res = HttpResponseInitial(
        HttpStatusCode.OK,
        version=HttpVersion.V1_1,
        headers=magicdict.FrozenTolerantMagicDict([("content-length", "20")]),
    )

    assert discover_response_body_length(res, req_initial=req) == 20


def test_valid_chunk_length() -> None:
    buf = bytearray(b"5\r")

    assert parse_chunk_length(buf) is None

    buf += b"\nASDFG\r\n"

    assert parse_chunk_length(buf) == 5
    assert buf == b"ASDFG\r\n"


def test_valid_last_chunk() -> None:
    buf = bytearray(b"0\r\n\r\n")

    assert parse_chunk_length(buf) == 0
    assert buf == b"\r\n"


def test_malformed_chunk_lengths() -> None:
    buf = bytearray(b"G\r\n1234567890ABCDEFG\r\n")

    with pytest.raises(InvalidChunkLength):
        assert parse_chunk_length(buf) == 17
