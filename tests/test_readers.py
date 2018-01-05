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

from magichttp.readers import HttpRequestReaderDelegate, \
    HttpResponseReaderDelegate
from magichttp import HttpRequestReader, HttpResponseReader


class ReaderDelegateMock(
        HttpRequestReaderDelegate, HttpResponseReaderDelegate):
    def __init__(self):
        self.paused = False
        self.aborted = False
        self.writer_mock = None

    def pause_reading(self):
        self.paused = True

    def resume_reading(self):
        self.paused = False

    def abort(self):
        self.aborted = True

    def write_response(self, res_initial):
        self.writer_mock = object()
        return self.writer_mock


class HttpRequestReaderTestCase:
    def test_init(self):
        reader = HttpRequestReader(object(), initial=object())


class HttpResponseReaderTestCase:
    def test_init(self):
        reader = HttpResponseReader(
            object(), initial=object(), writer=object())
