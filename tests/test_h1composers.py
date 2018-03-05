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

from magichttp.h1composers import compose_request_initial, \
    compose_response_initial, compose_chunked_body
from magichttp import HttpRequestMethod, HttpVersion, __version__, \
    HttpRequestInitial, HttpStatusCode

import magicdict


class ComposeRequestInitialTestCase:
    def test_simple_request(self):
        req, req_bytes = compose_request_initial(
            method=HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            authority=None,
            scheme=None,
            headers=None)

        assert req.version == HttpVersion.V1_1
        assert req.uri == b"/"
        assert not hasattr(req, "authority")
        assert not hasattr(req, "scheme")
        assert req.headers == {
            b"user-agent": b"magichttp/%s" % __version__.encode(),
            b"accept": b"*/*",
            b"connection": b"Keep-Alive"}

        assert req_bytes == (
            b"GET / HTTP/1.1\r\n" +
            b"User-Agent: magichttp/%s\r\n" % __version__.encode() +
            b"Accept: */*\r\nConnection: Keep-Alive\r\n\r\n")

    def test_http_10_request(self):
        req, req_bytes = compose_request_initial(
            method=HttpRequestMethod.GET,
            version=HttpVersion.V1_0,
            uri=b"/",
            authority=b"localhost",
            scheme=b"http",
            headers=None)

        assert req.version == HttpVersion.V1_0
        assert req.uri == b"/"
        assert req.authority == b"localhost"
        assert req.scheme == b"http"
        assert req.headers == {
            b"user-agent": b"magichttp/%s" % __version__.encode(),
            b"accept": b"*/*",
            b"connection": b"Close",
            b"host": b"localhost",
            b"x-scheme": b"http"}

        assert req_bytes == (
            b"GET / HTTP/1.0\r\n" +
            b"User-Agent: magichttp/%s\r\n" % __version__.encode() +
            b"Accept: */*\r\nConnection: Close\r\n" +
            b"Host: localhost\r\nX-Scheme: http\r\n\r\n")


class ComposeResponseInitialTestCase:
    def test_simple_response(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"http",
            headers=magicdict.TolerantMagicDict(),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            b"server": b"magichttp/%s" % __version__.encode(),
            b"connection": b"Close",
            b"transfer-encoding": b"Chunked"}

        assert res_bytes == (
            b"HTTP/1.1 200 OK\r\n" +
            b"Server: magichttp/%s\r\n" % __version__.encode() +
            b"Connection: Close\r\n" +
            b"Transfer-Encoding: Chunked\r\n\r\n")

    def test_bad_request(self):
        res, res_bytes = compose_response_initial(
            HttpStatusCode.BAD_REQUEST, headers=None, req_initial=None)

        assert res.status_code == 400
        assert res.headers == {
            b"server": b"magichttp/%s" % __version__.encode(),
            b"connection": b"Close",
            b"transfer-encoding": b"Chunked"}

        assert res_bytes == (
            b"HTTP/1.1 400 Bad Request\r\n" +
            b"Server: magichttp/%s\r\n" % __version__.encode() +
            b"Connection: Close\r\n" +
            b"Transfer-Encoding: Chunked\r\n\r\n")

    def test_http_10(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_0,
            uri=b"/",
            scheme=b"http",
            headers=magicdict.TolerantMagicDict(),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            b"server": b"magichttp/%s" % __version__.encode(),
            b"connection": b"Close"}

        assert res_bytes == (
            b"HTTP/1.0 200 OK\r\n" +
            b"Server: magichttp/%s\r\n" % __version__.encode() +
            b"Connection: Close\r\n\r\n")

    def test_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"http",
            headers=magicdict.TolerantMagicDict(
                [(b"connection", b"Keep-Alive")]),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            b"server": b"magichttp/%s" % __version__.encode(),
            b"connection": b"Keep-Alive",
            b"transfer-encoding": b"Chunked"}

        assert res_bytes == (
            b"HTTP/1.1 200 OK\r\n" +
            b"Server: magichttp/%s\r\n" % __version__.encode() +
            b"Connection: Keep-Alive\r\n" +
            b"Transfer-Encoding: Chunked\r\n\r\n")

    def test_no_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"http",
            headers=magicdict.TolerantMagicDict(
                [(b"connection", b"Close")]),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            b"server": b"magichttp/%s" % __version__.encode(),
            b"connection": b"Close",
            b"transfer-encoding": b"Chunked"}

        assert res_bytes == (
            b"HTTP/1.1 200 OK\r\n" +
            b"Server: magichttp/%s\r\n" % __version__.encode() +
            b"Connection: Close\r\n" +
            b"Transfer-Encoding: Chunked\r\n\r\n")

    def test_204_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"http",
            headers=magicdict.TolerantMagicDict(
                [(b"connection", b"Keep-Alive")]),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.NO_CONTENT, headers=None, req_initial=req)

        assert res.status_code == 204
        assert res.headers == {
            b"server": b"magichttp/%s" % __version__.encode(),
            b"connection": b"Keep-Alive"}

        assert res_bytes == (
            b"HTTP/1.1 204 No Content\r\n" +
            b"Server: magichttp/%s\r\n" % __version__.encode() +
            b"Connection: Keep-Alive\r\n\r\n")

    def test_304_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"http",
            headers=magicdict.TolerantMagicDict(
                [(b"connection", b"Keep-Alive")]),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.NOT_MODIFIED, headers=None, req_initial=req)

        assert res.status_code == 304
        assert res.headers == {
            b"server": b"magichttp/%s" % __version__.encode(),
            b"connection": b"Keep-Alive"}

        assert res_bytes == (
            b"HTTP/1.1 304 Not Modified\r\n" +
            b"Server: magichttp/%s\r\n" % __version__.encode() +
            b"Connection: Keep-Alive\r\n\r\n")

    def test_head_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.HEAD,
            version=HttpVersion.V1_1,
            uri=b"/",
            scheme=b"http",
            headers=magicdict.TolerantMagicDict(
                [(b"connection", b"Keep-Alive")]),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            b"server": b"magichttp/%s" % __version__.encode(),
            b"connection": b"Keep-Alive"}

        assert res_bytes == (
            b"HTTP/1.1 200 OK\r\n" +
            b"Server: magichttp/%s\r\n" % __version__.encode() +
            b"Connection: Keep-Alive\r\n\r\n")


class ComposeChunkedBodyTestCase:
    def test_normal_chunk(self):
        assert compose_chunked_body(b"a") == b"1\r\na\r\n"

    def test_empty_chunk(self):
        assert compose_chunked_body(b"") == b""

    def test_normal_last_chunk(self):
        assert compose_chunked_body(b"a", finished=True) == \
            b"1\r\na\r\n0\r\n\r\n"

    def test_empty_last_chunk(self):
        assert compose_chunked_body(b"", finished=True) == b"0\r\n\r\n"
