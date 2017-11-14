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

from typing import Optional, Union, Iterable, Tuple, Mapping, Any

import magicdict
import enum
import collections
import http

__all__ = [
    "HttpVersion", "HttpRequestMethod",
    "HttpRequestInitial", "HttpResponseInitial"]

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class HttpVersion(enum.Enum):
    V1_0 = b"HTTP/1.0"
    V1_1 = b"HTTP/1.1"


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


def _refine_headers(
    headers: Optional[_HeaderType]) -> \
        magicdict.FrozenTolerantMagicDict[bytes, bytes]:
    if headers is None:
        return magicdict.FrozenTolerantMagicDict()

    elif isinstance(headers, magicdict.FrozenTolerantMagicDict):
        return headers

    else:
        return magicdict.FrozenTolerantMagicDict(headers)


class HttpRequestInitial:
    __slots__ = (
        "_method", "_version", "_uri", "_headers", "_authority", "_scheme")

    def __init__(  # TODO: Remove Optionals.
        self, method: HttpRequestMethod, *,
        uri: bytes, authority: Optional[bytes]=None,
        version: Optional[HttpVersion]=None,
        scheme: Optional[bytes]=None,
            headers: Optional[_HeaderType]=None) -> None:
        self._method = method
        self._version = version
        self._uri = uri

        self._headers = _refine_headers(headers)

        self._authority = authority
        self._scheme = scheme

    @property
    def method(self) -> HttpRequestMethod:
        return self._method

    @property
    def version(self) -> Optional[HttpVersion]:
        return self._version

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

    @property
    def headers(self) -> magicdict.FrozenTolerantMagicDict[bytes, bytes]:
        return self._headers

    def __repr__(self) -> str:
        parts: "collections.OrderedDict[str, str]" = collections.OrderedDict([
            ("method", repr(self._method)),
            ("uri", repr(self._uri)),
        ])

        if self._version is not None:
            parts["version"] = repr(self._version)

        if self._scheme is not None:
            parts["scheme"] = repr(self._scheme)

        parts["headers"] = self._headers

        args_repr = ", ".join([f"{k}={v}" for k, v in parts.items()])

        return f"{self.__class__.__name__}({args_repr})"

    def __str__(self) -> str:
        return repr(self)


class HttpResponseInitial:
    __slots__ = ("_status_code", "_version", "_headers")

    def __init__(
        self, status_code: Union[int, http.HTTPStatus], *,  # TODO: Remove int.
        version: Optional[HttpVersion]=None,  # TODO: Remove Optionals.
            headers: Optional[_HeaderType]=None) -> None:
        self._status_code = http.HTTPStatus(status_code)
        self._version = version

        self._headers = _refine_headers(headers)

    @property
    def status_code(self) -> http.HTTPStatus:
        return self._status_code

    @property
    def version(self) -> Optional[HttpVersion]:
        return self._version

    @property
    def headers(self) -> magicdict.FrozenTolerantMagicDict[bytes, bytes]:
        return self._headers

    def __repr__(self) -> str:
        parts: "collections.OrderedDict[str, str]" = collections.OrderedDict([
            ("status_code", repr(self._status_code))
        ])

        if self._version is not None:
            parts["version"] = repr(self._version)

        parts["headers"] = self._headers

        args_repr = ", ".join([f"{k}={v}" for k, v in parts.items()])

        return f"{self.__class__.__name__}({args_repr})"

    def __str__(self) -> str:
        return repr(self)
