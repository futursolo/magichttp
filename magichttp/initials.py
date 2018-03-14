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

from typing import Optional, Union, Iterable, Tuple, Mapping

import typing

if typing.TYPE_CHECKING:  # pragma: no cover
    from . import constants  # noqa: F401

    import magicdict  # noqa: F401

__all__ = [
    "HttpRequestInitial", "HttpResponseInitial"]

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class HttpRequestInitial:
    """
    The reuqest initial.
    """
    __slots__ = (
        "_method", "_version", "_uri", "_headers", "_authority", "_scheme")

    def __init__(
        self, method: "constants.HttpRequestMethod", *,
        uri: bytes, authority: Optional[bytes],
        version: "constants.HttpVersion",
        scheme: Optional[bytes],
        headers: "magicdict.FrozenTolerantMagicDict[bytes, bytes]"
            ) -> None:
        self._method = method
        self._version = version
        self._uri = uri

        self._headers = headers

        self._authority = authority
        self._scheme = scheme

    @property
    def method(self) -> "constants.HttpRequestMethod":
        return self._method

    @property
    def version(self) -> "constants.HttpVersion":
        return self._version

    @property
    def uri(self) -> bytes:
        return self._uri

    @property
    def authority(self) -> bytes:
        if self._authority is None:
            raise AttributeError("Authority is not available.")

        return self._authority

    @property
    def scheme(self) -> bytes:
        if self._scheme is None:
            raise AttributeError("Scheme is not available.")

        return self._scheme

    @property
    def headers(self) -> "magicdict.FrozenTolerantMagicDict[bytes, bytes]":
        return self._headers

    def __repr__(self) -> str:  # pragma: no cover
        parts = [
            ("method", repr(self._method)),
            ("uri", repr(self._uri)),
            ("version", repr(self._version))
        ]

        if self._authority is not None:
            parts.append(("authority", repr(self._authority)))

        if self._scheme is not None:
            parts.append(("scheme", repr(self._scheme)))

        parts.append(("headers", repr(self._headers)))

        args_repr = ", ".join([f"{k}={v}" for k, v in parts])

        return f"{self.__class__.__name__}({args_repr})"

    def __str__(self) -> str:  # pragma: no cover
        return repr(self)


class HttpResponseInitial:
    """
    The response initial.
    """
    __slots__ = ("_status_code", "_version", "_headers")

    def __init__(
        self, status_code: "constants.HttpStatusCode", *,
        version: "constants.HttpVersion",
        headers: "magicdict.FrozenTolerantMagicDict[bytes, bytes]"
            ) -> None:
        self._status_code = status_code
        self._version = version

        self._headers = headers

    @property
    def status_code(self) -> "constants.HttpStatusCode":
        return self._status_code

    @property
    def version(self) -> "constants.HttpVersion":
        return self._version

    @property
    def headers(self) -> "magicdict.FrozenTolerantMagicDict[bytes, bytes]":
        return self._headers

    def __repr__(self) -> str:  # pragma: no cover
        parts = [
            ("status_code", repr(self._status_code)),
            ("version", repr(self._version)),
            ("headers", repr(self._headers))
        ]

        args_repr = ", ".join([f"{k}={v}" for k, v in parts])

        return f"{self.__class__.__name__}({args_repr})"

    def __str__(self) -> str:  # pragma: no cover
        return repr(self)
