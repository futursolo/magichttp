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

from typing import Optional, Union, Iterable, Tuple, Mapping

import magicdict
import enum

__all__ = ["HttpRequestMethod", "HttpRequestInitial", "HttpResponseInitial"]

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class HttpRequestMethod(enum.Enum):
    Get = b"GET"
    Post = b"POST"
    Put = b"PUT"
    Delete = b"DELETE"
    Head = b"HEAD"
    Options = b"OPTIONS"
    Connect = b"CONNECT"
    Trace = b"TRACE"
    Patch = b"PATCH"


class HttpRequestInitial:
    def __init__(
        self, *, method: HttpRequestMethod,
        uri: bytes, authority: Optional[bytes]=None,
        scheme: Optional[bytes]=None,
            headers: Optional[_HeaderType]=None) -> None:
        self._method = method
        self._uri = uri

        if headers is None:
            self._headers: magicdict.FrozenTolerantMagicDict[bytes, bytes] = \
                magicdict.FrozenTolerantMagicDict()

        elif isinstance(headers, magicdict.FrozenTolerantMagicDict):
            self._headers = headers

        else:
            self._headers: magicdict.FrozenTolerantMagicDict[bytes, bytes] = \
                magicdict.FrozenTolerantMagicDict(headers)

        self._authority = authority
        self._scheme = scheme

    @property
    def headers(self) -> magicdict.FrozenTolerantMagicDict[bytes, bytes]:
        return self._headers

    @property
    def method(self) -> HttpRequestMethod:
        return self._method

    @property
    def uri(self) -> bytes:
        return self._uri

    @property
    def authority(self) -> bytes:
        if self._authority is None:
            raise AttributeError("Authority is not set.")

        return self._authority

    @property
    def scheme(self) -> bytes:
        if self._scheme is None:
            raise AttributeError("Scheme is not set.")

        return self._scheme


class HttpResponseInitial:
    def __init__(
        self, *, status_code: int,
            headers: Optional[_HeaderType]=None) -> None:
        self._status_code = status_code

        if headers is None:
            self._headers: magicdict.FrozenTolerantMagicDict[bytes, bytes] = \
                magicdict.FrozenTolerantMagicDict()

        elif isinstance(headers, magicdict.FrozenTolerantMagicDict):
            self._headers = self._headers

        else:
            self._headers: magicdict.FrozenTolerantMagicDict[bytes, bytes] = \
                magicdict.FrozenTolerantMagicDict(headers)

    @property
    def headers(self) -> magicdict.FrozenTolerantMagicDict[bytes, bytes]:
        return self._headers

    @property
    def status_code(self) -> int:
        return self._status_code
