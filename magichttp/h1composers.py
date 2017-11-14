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

from typing import Optional, Mapping, MutableMapping, Union, Iterable, Tuple

from . import httputils
from . import initials
from . import _version

import abc
import magicdict
import collections
import http

__all__ = [
    "IncomposableHttpInitial",

    "BaseH1Composer",
    "H1RequestComposer",
    "H1ResponseComposer"]

_SELF_IDENTIFIER = f"magichttp/{_version.__version__}".encode()

_HeaderType = Union[
    Mapping[bytes, bytes],
    Iterable[Tuple[bytes, bytes]]]


class IncomposableHttpInitial(ValueError):
    pass


class HttpRequestInitialRequiredForComposing(ValueError):
    """
    The Request Initial is required for composing.
    """
    pass


class BaseH1Composer(abc.ABC):
    def __init__(self, using_https: bool=False) -> None:
        self._using_https = using_https

        self._using_chunked_body: Optional[bool] = None

        self._finished = False

    def _decide_body_by_transfer_encoding(
            self, transfer_encoding_bytes: bytes) -> None:
        transfer_encoding_list = list(
            httputils.parse_semicolon_header(transfer_encoding_bytes))

        last_transfer_encoding = transfer_encoding_list[-1]

        if b"identity" in transfer_encoding_list:
            if len(transfer_encoding_list) > 1:
                raise IncomposableHttpInitial(
                    "Identity is not the only transfer encoding.")

        elif b"chunked" in transfer_encoding_list:
            if last_transfer_encoding != b"chunked":
                raise IncomposableHttpInitial(
                    "Chunked transfer encoding found, "
                    "but not at last.")

            else:
                self._using_chunked_body = True

        self._using_chunked_body = False

    def _compose_initial_bytes(
        self, *first_line_args: bytes,
            headers: Optional[Mapping[bytes, bytes]]=None) -> bytes:
        buf = [b" ".join(first_line_args)]

        if headers:
            for key, value in headers.items():
                buf.append(b"%s: %s" % (key, value))

        buf.append(b"")
        buf.append(b"")

        return b"\r\n".join(buf)

    def compose_body(
            self, data: bytes, finished: bool=False) -> Optional[bytes]:
        assert not self._finished, "Composers are not reusable."
        assert self._using_chunked_body is not None, \
            "You should write the initial first."

        if self._using_chunked_body:
            if len(data) > 0:
                data_len = f"{len(data):x}".encode()

                if finished:
                    self._finished = True

                    return b"%s\r\n%s\r\n0\r\n\r\n" % (data_len, data)

                else:
                    return b"%s\r\n%s\r\n" % (data_len, data)

            elif finished:
                self._finished = True

                return b"0\r\n\r\n"

            else:
                return b""

        if finished:
            self._finished = True

        return data


class H1RequestComposer(BaseH1Composer):
    def compose_request(
        self, method: initials.HttpRequestMethod, *,
        uri: bytes, authority: Optional[bytes],
        version: Optional[initials.HttpVersion],
        scheme: Optional[bytes],
        headers: Optional[_HeaderType]
            ) -> Tuple[initials.HttpRequestInitial, bytes]:
        assert self._using_chunked_body is None, "Composers are not reusable."

        if version is None:
            version = initials.HttpVersion.V1_1

        refined_headers: MutableMapping[bytes, bytes]
        if headers:
            refined_headers = magicdict.TolerantMagicDict(headers)

        else:
            refined_headers = collections.OrderedDict()

        refined_headers.setdefault(b"user-agent", _SELF_IDENTIFIER)
        refined_headers.setdefault(b"accept", b"*/*")

        if b"connection" not in refined_headers.keys():
            if version == initials.HttpVersion.V1_1:
                refined_headers[b"connection"] = b"Keep-Alive"

            else:
                refined_headers[b"connection"] = b"Close"

        if b"transfer-encoding" in refined_headers.keys():
            self._decide_body_by_transfer_encoding(
                refined_headers[b"transfer-encoding"])

        else:
            self._using_chunked_body = False

        if authority is not None and b"host" not in refined_headers.keys():
            refined_headers[b"host"] = authority

        refined_initial = initials.HttpRequestInitial(
            method,
            version=version,
            uri=uri,
            authority=authority,
            scheme=scheme or (
                b"https" if self._using_https else b"http"),
            headers=refined_headers)

        return (refined_initial, self._compose_initial_bytes(
            method.value, uri, version.value,
            headers=refined_initial.headers))


class H1ResponseComposer(BaseH1Composer):
    def compose_response(
        self, status_code: int, *,
        version: Optional[initials.HttpVersion]=None,
        headers: Optional[_HeaderType]=None,
        req_initial: initials.HttpRequestInitial
            ) -> Tuple[initials.HttpResponseInitial, bytes]:
        assert self._using_chunked_body is None, "Composers are not reusable."

        if version is None:
            if req_initial is None:
                if status_code < 400:
                    raise HttpRequestInitialRequiredForComposing(
                        "req_initial is required for "
                        "a status code less than 400.")

                else:
                    version = initials.HttpVersion.V1_1

            else:
                assert req_initial.version is not None
                version = req_initial.version

        refined_headers: MutableMapping[bytes, bytes]
        if headers:
            refined_headers = magicdict.TolerantMagicDict(headers)

        else:
            refined_headers = collections.OrderedDict()

        refined_headers.setdefault(b"server", _SELF_IDENTIFIER)

        if status_code >= 400:
            refined_headers[b"connection"] = b"Close"

        elif b"connection" not in refined_headers.keys():
            if version == initials.HttpVersion.V1_1:
                if req_initial is not None and \
                        b"connection" in req_initial.headers.keys():
                    if req_initial.headers[
                            b"connection"].lower() == b"keep-alive":
                        refined_headers[b"connection"] = b"Keep-Alive"

                    else:
                        refined_headers[b"connection"] = b"Close"

                else:
                    refined_headers[b"connection"] = b"Keep-Alive"

            else:
                refined_headers[b"connection"] = b"Close"

        if b"transfer-encoding" in refined_headers.keys():
            self._decide_body_by_transfer_encoding(
                refined_headers[b"transfer-encoding"])

        elif b"content-length" in refined_headers.keys():
            self._using_chunked_body = False

        elif version == initials.HttpVersion.V1_1:
            refined_headers[b"transfer-encoding"] = b"Chunked"
            self._using_chunked_body = True

        else:
            refined_headers[b"connection"] = b"Close"
            self._using_chunked_body = False

        refined_initial = initials.HttpResponseInitial(
            status_code, version=version, headers=refined_headers)

        return (refined_initial, self._compose_initial_bytes(
                version.value,
                str(status_code).encode(),
                http.HTTPStatus(status_code).phrase.encode(),
                headers=refined_initial.headers))
