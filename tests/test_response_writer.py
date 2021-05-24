#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2021 Kaede Hoshikawa
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
import pytest

from magichttp import (
    HttpRequestInitial,
    HttpRequestMethod,
    HttpRequestReader,
    HttpResponseInitial,
    HttpResponseWriter,
    HttpStatusCode,
    HttpVersion,
)

_INITIAL = HttpRequestInitial(
    HttpRequestMethod.GET,
    uri="/",
    headers=magicdict.FrozenTolerantMagicDict(),
    scheme="https",
    version=HttpVersion.V1_1,
    authority="www.example.com",
)

_RES_INITIAL = HttpResponseInitial(
    HttpStatusCode.OK,
    version=HttpVersion.V1_1,
    headers=magicdict.FrozenTolerantMagicDict(),
)


def test_init() -> None:
    HttpResponseWriter(
        helpers.WriterDelegateMock(),
        initial=_RES_INITIAL,
        reader=HttpRequestReader(
            helpers.ReaderDelegateMock(), initial=_INITIAL
        ),
    )


def test_initial() -> None:
    writer = HttpResponseWriter(
        helpers.WriterDelegateMock(),
        initial=_RES_INITIAL,
        reader=HttpRequestReader(
            helpers.ReaderDelegateMock(), initial=_INITIAL
        ),
    )

    assert _RES_INITIAL is writer.initial


def test_reader() -> None:
    reader_mock = HttpRequestReader(
        helpers.ReaderDelegateMock(), initial=_INITIAL
    )

    writer = HttpResponseWriter(
        helpers.WriterDelegateMock(),
        initial=_RES_INITIAL,
        reader=reader_mock,
    )

    assert reader_mock is writer.reader


def test_reader_attr_err() -> None:
    writer = HttpResponseWriter(
        helpers.WriterDelegateMock(), initial=_RES_INITIAL, reader=None
    )

    with pytest.raises(AttributeError):
        writer.reader
