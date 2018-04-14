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

from typing import Optional, Mapping, Union, Iterable, Tuple

from . import initials
from . import constants
from . import _version

import magicdict

_SELF_IDENTIFIER = f"magichttp/{_version.__version__}"

_HeaderType = Union[
    Mapping[str, str],
    Iterable[Tuple[str, str]]]


def _compose_initial_bytes(
        *first_line_args: str, headers: Mapping[str, str]) -> bytes:
    buf = [" ".join(first_line_args), "\r\n"]

    for key, value in headers.items():
        buf.append("%s: %s\r\n" % (key.title(), value))

    buf.append("\r\n")

    return "".join(buf).encode("latin-1")


def compose_request_initial(
    method: constants.HttpRequestMethod, *,
    uri: str, authority: Optional[str],
    version: constants.HttpVersion,
    scheme: Optional[str],
    headers: Optional[_HeaderType]
        ) -> Tuple[initials.HttpRequestInitial, bytes]:
    refined_headers: magicdict.TolerantMagicDict[str, str] = \
        magicdict.TolerantMagicDict(headers or {})

    refined_headers.setdefault("user-agent", _SELF_IDENTIFIER)
    refined_headers.setdefault("accept", "*/*")

    if "connection" not in refined_headers.keys():
        if version == constants.HttpVersion.V1_1:
            refined_headers["connection"] = "Keep-Alive"

        else:
            refined_headers["connection"] = "Close"

    if authority is not None:
        refined_headers.setdefault("host", authority)

    if scheme is not None:
        refined_headers.setdefault("x-scheme", scheme)

    refined_initial = initials.HttpRequestInitial(
        method,
        version=version,
        uri=uri,
        authority=authority,
        scheme=scheme,
        headers=magicdict.FrozenTolerantMagicDict(refined_headers))

    return (refined_initial, _compose_initial_bytes(
        method.value, uri, version.value,
        headers=refined_initial.headers))


def compose_response_initial(
        status_code: constants.HttpStatusCode, *,
        headers: Optional[_HeaderType],
        req_initial: Optional[initials.HttpRequestInitial]
            ) -> Tuple[initials.HttpResponseInitial, bytes]:
    if req_initial is None:
        assert status_code >= 400, \
            ("req_initial is required for "
             "a status code less than 400.")

        version = constants.HttpVersion.V1_1

    else:
        version = req_initial.version

    refined_headers: magicdict.TolerantMagicDict[str, str] = \
        magicdict.TolerantMagicDict(headers or {})

    refined_headers.setdefault("server", _SELF_IDENTIFIER)

    if status_code >= 400:
        refined_headers["connection"] = "Close"

    elif "connection" not in refined_headers.keys():
        if version != constants.HttpVersion.V1_1:
            refined_headers["connection"] = "Close"

        elif req_initial is None or \
                "connection" not in req_initial.headers.keys():
            refined_headers["connection"] = "Close"

        elif req_initial.headers["connection"].lower() != "keep-alive":
            refined_headers["connection"] = "Close"

        else:
            refined_headers["connection"] = "Keep-Alive"

    if req_initial is None or \
        (req_initial.method != constants.HttpRequestMethod.HEAD and
            status_code not in (
                constants.HttpStatusCode.NO_CONTENT,
                constants.HttpStatusCode.NOT_MODIFIED,
                constants.HttpStatusCode.SWITCHING_PROTOCOLS) and
            "transfer-encoding" not in refined_headers.keys() and
            "content-length" not in refined_headers.keys()):
        if version == constants.HttpVersion.V1_1:
            refined_headers["transfer-encoding"] = "Chunked"

        else:
            refined_headers["connection"] = "Close"

    refined_initial = initials.HttpResponseInitial(

        status_code, version=version,
        headers=magicdict.FrozenTolerantMagicDict(refined_headers))

    return (refined_initial, _compose_initial_bytes(
            version.value,
            str(status_code.value),
            status_code.phrase,
            headers=refined_initial.headers))


def compose_chunked_body(
        data: bytes, finished: bool=False) -> bytes:
    if data:
        data_len = f"{len(data):x}".encode("utf-8")

        if finished:
            return b"%s\r\n%s\r\n0\r\n\r\n" % (data_len, data)

        else:
            return b"%s\r\n%s\r\n" % (data_len, data)

    elif finished:
        return b"0\r\n\r\n"

    else:
        return b""
