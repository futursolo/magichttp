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

from magichttp.h1impl.composers import compose_request_initial, \
    compose_response_initial, compose_chunked_body
from magichttp import HttpRequestMethod, HttpVersion, \
    HttpRequestInitial, HttpStatusCode

from test_helper import TestHelper

import magicdict

helper = TestHelper()


class ComposeRequestInitialTestCase:
    def test_simple_request(self):
        req, req_bytes = compose_request_initial(
            method=HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri="/",
            authority=None,
            scheme=None,
            headers=None)

        assert req.version == HttpVersion.V1_1
        assert req.uri == "/"
        assert not hasattr(req, "authority")
        assert not hasattr(req, "scheme")
        assert req.headers == {
            "user-agent": helper.get_version_str(),
            "accept": "*/*"}

        helper.assert_initial_bytes(
            req_bytes,
            b"GET / HTTP/1.1",
            b"User-Agent: %(self_ver_bytes)s",
            b"Accept: */*")

    def test_http_10_request(self):
        req, req_bytes = compose_request_initial(
            method=HttpRequestMethod.GET,
            version=HttpVersion.V1_0,
            uri="/",
            authority="localhost",
            scheme="http",
            headers=None)

        assert req.version == HttpVersion.V1_0
        assert req.uri == "/"
        assert req.authority == "localhost"
        assert req.scheme == "http"
        assert req.headers == {
            "user-agent": helper.get_version_str(),
            "connection": "Keep-Alive",
            "accept": "*/*",
            "host": "localhost"}

        helper.assert_initial_bytes(
            req_bytes,
            b"GET / HTTP/1.0",
            b"User-Agent: %(self_ver_bytes)s",
            b"Accept: */*",
            b"Connection: Keep-Alive",
            b"Host: localhost")


class ComposeResponseInitialTestCase:
    def test_simple_response(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri="/",
            scheme="http",
            headers=magicdict.TolerantMagicDict(),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            "server": helper.get_version_str(),
            "transfer-encoding": "Chunked"}

        helper.assert_initial_bytes(
            res_bytes,
            b"HTTP/1.1 200 OK",
            b"Server: %(self_ver_bytes)s",
            b"Transfer-Encoding: Chunked")

    def test_bad_request(self):
        res, res_bytes = compose_response_initial(
            HttpStatusCode.BAD_REQUEST, headers=None, req_initial=None)

        assert res.status_code == 400
        assert res.headers == {
            "server": helper.get_version_str(),
            "connection": "Close",
            "transfer-encoding": "Chunked"}

        helper.assert_initial_bytes(
            res_bytes,
            b"HTTP/1.1 400 Bad Request",
            b"Server: %(self_ver_bytes)s",
            b"Connection: Close",
            b"Transfer-Encoding: Chunked")

    def test_http_10(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_0,
            uri="/",
            scheme="http",
            headers=magicdict.TolerantMagicDict(),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            "server": helper.get_version_str(),
            "connection": "Close"}

        helper.assert_initial_bytes(
            res_bytes,
            b"HTTP/1.0 200 OK",
            b"Server: %(self_ver_bytes)s",
            b"Connection: Close")

    def test_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri="/",
            scheme="http",
            headers=magicdict.TolerantMagicDict(),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            "server": helper.get_version_str(),
            "transfer-encoding": "Chunked"}

        helper.assert_initial_bytes(
            res_bytes,
            b"HTTP/1.1 200 OK",
            b"Server: %(self_ver_bytes)s",
            b"Transfer-Encoding: Chunked")

    def test_http_10_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_0,
            uri="/",
            scheme="http",
            headers=magicdict.TolerantMagicDict(
                [("connection", "Keep-Alive")]),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers={"content-length": "0"},
            req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            "content-length": "0",
            "server": helper.get_version_str(),
            "connection": "Keep-Alive"}

        helper.assert_initial_bytes(
            res_bytes,
            b"HTTP/1.0 200 OK",
            b"Server: %(self_ver_bytes)s",
            b"Connection: Keep-Alive",
            b"Content-Length: 0")

    def test_no_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri="/",
            scheme="http",
            headers=magicdict.TolerantMagicDict(
                [("connection", "Close")]),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            "server": helper.get_version_str(),
            "connection": "Close",
            "transfer-encoding": "Chunked"}

        helper.assert_initial_bytes(
            res_bytes,
            b"HTTP/1.1 200 OK",
            b"Server: %(self_ver_bytes)s",
            b"Connection: Close",
            b"Transfer-Encoding: Chunked")

    def test_204_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri="/",
            scheme="http",
            headers=magicdict.TolerantMagicDict(),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.NO_CONTENT, headers=None, req_initial=req)

        assert res.status_code == 204
        assert res.headers == {
            "server": helper.get_version_str()}

        helper.assert_initial_bytes(
            res_bytes,
            b"HTTP/1.1 204 No Content",
            b"Server: %(self_ver_bytes)s")

    def test_304_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.GET,
            version=HttpVersion.V1_1,
            uri="/",
            scheme="http",
            headers=magicdict.TolerantMagicDict(),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.NOT_MODIFIED, headers=None, req_initial=req)

        assert res.status_code == 304
        assert res.headers == {
            "server": helper.get_version_str()}

        helper.assert_initial_bytes(
            res_bytes,
            b"HTTP/1.1 304 Not Modified",
            b"Server: %(self_ver_bytes)s")

    def test_head_keep_alive(self):
        req = HttpRequestInitial(
            HttpRequestMethod.HEAD,
            version=HttpVersion.V1_1,
            uri="/",
            scheme="http",
            headers=magicdict.TolerantMagicDict(),
            authority=None)

        res, res_bytes = compose_response_initial(
            HttpStatusCode.OK, headers=None, req_initial=req)

        assert res.status_code == 200
        assert res.headers == {
            "server": helper.get_version_str()}

        helper.assert_initial_bytes(
            res_bytes,
            b"HTTP/1.1 200 OK",
            b"Server: %(self_ver_bytes)s")


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
