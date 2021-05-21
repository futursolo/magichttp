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

import helpers
import magicdict

from magichttp import (
    HttpRequestInitial,
    HttpRequestMethod,
    HttpStatusCode,
    HttpVersion,
)
from magichttp.h1impl.composers import (
    compose_chunked_body,
    compose_request_initial,
    compose_response_initial,
)


def test_simple_request() -> None:
    req, req_bytes = compose_request_initial(
        method=HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        authority=None,
        scheme=None,
        headers=None,
    )

    assert req.version == HttpVersion.V1_1
    assert req.uri == "/"
    assert not hasattr(req, "authority")
    assert not hasattr(req, "scheme")
    assert req.headers == {
        "user-agent": helpers.get_version_str(),
        "accept": "*/*",
    }

    helpers.assert_initial(
        req_bytes,
        b"GET / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Accept: */*",
    )


def test_http_10_request() -> None:
    req, req_bytes = compose_request_initial(
        method=HttpRequestMethod.GET,
        version=HttpVersion.V1_0,
        uri="/",
        authority="localhost",
        scheme="http",
        headers=None,
    )

    assert req.version == HttpVersion.V1_0
    assert req.uri == "/"
    assert req.authority == "localhost"
    assert req.scheme == "http"
    assert req.headers == {
        "user-agent": helpers.get_version_str(),
        "connection": "Keep-Alive",
        "accept": "*/*",
        "host": "localhost",
    }

    helpers.assert_initial(
        req_bytes,
        b"GET / HTTP/1.0",
        b"User-Agent: %(self_ver_bytes)s",
        b"Accept: */*",
        b"Connection: Keep-Alive",
        b"Host: localhost",
    )


def test_simple_response() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="http",
        headers=magicdict.TolerantMagicDict(),
        authority=None,
    )

    res, res_bytes = compose_response_initial(
        HttpStatusCode.OK, headers=None, req_initial=req
    )

    assert res.status_code == 200
    assert res.headers == {
        "server": helpers.get_version_str(),
        "transfer-encoding": "Chunked",
    }

    helpers.assert_initial(
        res_bytes,
        b"HTTP/1.1 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Transfer-Encoding: Chunked",
    )


def test_bad_request() -> None:
    res, res_bytes = compose_response_initial(
        HttpStatusCode.BAD_REQUEST, headers=None, req_initial=None
    )

    assert res.status_code == 400
    assert res.headers == {
        "server": helpers.get_version_str(),
        "connection": "Close",
        "transfer-encoding": "Chunked",
    }

    helpers.assert_initial(
        res_bytes,
        b"HTTP/1.1 400 Bad Request",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Close",
        b"Transfer-Encoding: Chunked",
    )


def test_http_10() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_0,
        uri="/",
        scheme="http",
        headers=magicdict.TolerantMagicDict(),
        authority=None,
    )

    res, res_bytes = compose_response_initial(
        HttpStatusCode.OK, headers=None, req_initial=req
    )

    assert res.status_code == 200
    assert res.headers == {
        "server": helpers.get_version_str(),
        "connection": "Close",
    }

    helpers.assert_initial(
        res_bytes,
        b"HTTP/1.0 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Close",
    )


def test_keep_alive() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="http",
        headers=magicdict.TolerantMagicDict(),
        authority=None,
    )

    res, res_bytes = compose_response_initial(
        HttpStatusCode.OK, headers=None, req_initial=req
    )

    assert res.status_code == 200
    assert res.headers == {
        "server": helpers.get_version_str(),
        "transfer-encoding": "Chunked",
    }

    helpers.assert_initial(
        res_bytes,
        b"HTTP/1.1 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Transfer-Encoding: Chunked",
    )


def test_http_10_keep_alive() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_0,
        uri="/",
        scheme="http",
        headers=magicdict.TolerantMagicDict([("connection", "Keep-Alive")]),
        authority=None,
    )

    res, res_bytes = compose_response_initial(
        HttpStatusCode.OK, headers={"content-length": "0"}, req_initial=req
    )

    assert res.status_code == 200
    assert res.headers == {
        "content-length": "0",
        "server": helpers.get_version_str(),
        "connection": "Keep-Alive",
    }

    helpers.assert_initial(
        res_bytes,
        b"HTTP/1.0 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Keep-Alive",
        b"Content-Length: 0",
    )


def test_no_keep_alive() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="http",
        headers=magicdict.TolerantMagicDict([("connection", "Close")]),
        authority=None,
    )

    res, res_bytes = compose_response_initial(
        HttpStatusCode.OK, headers=None, req_initial=req
    )

    assert res.status_code == 200
    assert res.headers == {
        "server": helpers.get_version_str(),
        "connection": "Close",
        "transfer-encoding": "Chunked",
    }

    helpers.assert_initial(
        res_bytes,
        b"HTTP/1.1 200 OK",
        b"Server: %(self_ver_bytes)s",
        b"Connection: Close",
        b"Transfer-Encoding: Chunked",
    )


def test_204_keep_alive() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="http",
        headers=magicdict.TolerantMagicDict(),
        authority=None,
    )

    res, res_bytes = compose_response_initial(
        HttpStatusCode.NO_CONTENT, headers=None, req_initial=req
    )

    assert res.status_code == 204
    assert res.headers == {"server": helpers.get_version_str()}

    helpers.assert_initial(
        res_bytes,
        b"HTTP/1.1 204 No Content",
        b"Server: %(self_ver_bytes)s",
    )


def test_304_keep_alive() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.GET,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="http",
        headers=magicdict.TolerantMagicDict(),
        authority=None,
    )

    res, res_bytes = compose_response_initial(
        HttpStatusCode.NOT_MODIFIED, headers=None, req_initial=req
    )

    assert res.status_code == 304
    assert res.headers == {"server": helpers.get_version_str()}

    helpers.assert_initial(
        res_bytes,
        b"HTTP/1.1 304 Not Modified",
        b"Server: %(self_ver_bytes)s",
    )


def test_head_keep_alive() -> None:
    req = HttpRequestInitial(
        HttpRequestMethod.HEAD,
        version=HttpVersion.V1_1,
        uri="/",
        scheme="http",
        headers=magicdict.TolerantMagicDict(),
        authority=None,
    )

    res, res_bytes = compose_response_initial(
        HttpStatusCode.OK, headers=None, req_initial=req
    )

    assert res.status_code == 200
    assert res.headers == {"server": helpers.get_version_str()}

    helpers.assert_initial(
        res_bytes, b"HTTP/1.1 200 OK", b"Server: %(self_ver_bytes)s"
    )


def test_normal_chunk() -> None:
    assert compose_chunked_body(b"a") == b"1\r\na\r\n"


def test_empty_chunk() -> None:
    assert compose_chunked_body(b"") == b""


def test_normal_last_chunk() -> None:
    assert compose_chunked_body(b"a", finished=True) == b"1\r\na\r\n0\r\n\r\n"


def test_empty_last_chunk() -> None:
    assert compose_chunked_body(b"", finished=True) == b"0\r\n\r\n"
