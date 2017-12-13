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

from magichttp.h1composers import H1RequestComposer, H1ResponseComposer

from magichttp import HttpRequestMethod, HttpVersion, __version__


class H1RequestComposerTestCase:
    def test_init(self):
        composer = H1RequestComposer()

    def test_simple_request(self):
        composer = H1RequestComposer()

        req, req_bytes = composer.compose_request(
            method=HttpRequestMethod.Get,
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

        assert composer.compose_body(b"", finished=True) == b""


class H1ResponseComposerTestCase:
    def test_init(self):
        composer = H1ResponseComposer()
