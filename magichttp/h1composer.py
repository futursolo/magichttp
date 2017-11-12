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

from typing import Optional, Tuple, Mapping

from . import initials
from . import exceptions
from . import httputils
from . import _version

import http
import magicdict

__all__ = ["H1Composer"]

_SELF_IDENTIFIER = f"magichttp/{_version.__version__}".encode()


class H1Composer:
    def __init__(self, using_https: bool=False) -> None:
        self._using_chunked_body: Optional[bool] = None

        self._using_https = using_https

    def _determine_if_chunked_body_is_used(
            self, transfer_encoding_bytes: bytes) -> None:
        transfer_encoding_list = list(
            httputils.parse_semicolon_header(transfer_encoding_bytes))

        last_transfer_encoding = transfer_encoding_list[-1]

        if b"identity" in transfer_encoding_list:
            if len(transfer_encoding_list) > 1:
                raise exceptions.MalformedHttpInitial(
                    "Identity is not the only transfer encoding.")

        elif b"chunked" in transfer_encoding_list:
            if last_transfer_encoding != b"chunked":
                raise exceptions.MalformedHttpInitial(
                    "Chunked transfer encoding found, "
                    "but not at last.")

            else:
                self._using_chunked_body = True

        else:
            self._using_chunked_body = False

    def _generate_initial_bytes(
        self, *first_line_args: bytes,
            headers: Optional[Mapping[bytes, bytes]]=None) -> bytes:
        buf = [b" ".join(first_line_args)]

        if headers:
            for key, value in headers.items():
                buf.append(b"%s: %s" % (key, value))

        buf.append(b"")
        buf.append(b"")

        return b"\r\n".join(buf)

    def compose_request(
        self, req_initial: initials.HttpRequestInitial) -> Tuple[
            initials.HttpRequestInitial, bytes]:
        assert self._using_chunked_body is None

        if req_initial.version is None:
            version = initials.HttpVersion.V1_1

        else:
            version = req_initial.version

        refined_req_headers: \
            magicdict.TolerantMagicDict[bytes, bytes] = \
            magicdict.TolerantMagicDict(req_initial.headers)

        refined_req_headers.setdefault(b"user-agent", _SELF_IDENTIFIER)

        refined_req_headers.setdefault(b"accept", b"*/*")

        if b"connection" not in req_initial.headers.keys():
            if version == initials.HttpVersion.V1_1:
                refined_req_headers[b"connection"] = b"Keep-Alive"

            else:
                refined_req_headers[b"connection"] = b"Close"

        if b"transfer-encoding" in req_initial.headers.keys():
            self._determine_if_chunked_body_is_used(
                req_initial.headers[b"transfer-encoding"])

        if self._using_chunked_body is None:
            refined_req_headers.setdefault(b"content-length", b"0")
            self._using_chunked_body = False

        if req_initial.authority is not None and \
                b"host" not in req_initial.headers.keys():
            refined_req_headers[b"host"] = req_initial.authority

        refined_req_initial = initials.HttpRequestInitial(
            req_initial.method,
            version=version,
            uri=req_initial.uri,
            authority=req_initial.authority,
            scheme=req_initial.scheme or (
                b"https" if self._using_https else b"http"),
            headers=refined_req_headers)

        return (refined_req_initial, self._generate_initial_bytes(
            req_initial.method.value,
            req_initial.uri,
            version.value,
            headers=refined_req_initial.headers))

    def compose_response(
        self, res_initial: initials.HttpResponseInitial, *,
        req_initial: Optional[initials.HttpRequestInitial]=None) -> Tuple[
            initials.HttpResponseInitial, bytes]:
        assert self._using_chunked_body is None

        if res_initial.version is None:
            if req_initial is None:
                if res_initial.status_code < 400:
                    raise exceptions.HttpRequestInitialRequired(
                        "req_initial is required for "
                        "a status code less than 400.")

                else:
                    version = initials.HttpVersion.V1_1

            else:
                assert req_initial.version is not None
                version = req_initial.version

        else:
            version = res_initial.version

        refined_res_headers: \
            magicdict.TolerantMagicDict[bytes, bytes] = \
            magicdict.TolerantMagicDict(res_initial.headers)

        refined_res_headers.setdefault(b"server", _SELF_IDENTIFIER)

        if res_initial.status_code >= 400:
            refined_res_headers[b"connection"] = b"Close"

        elif b"connection" not in res_initial.headers.keys():
            if version == initials.HttpVersion.V1_1:
                if req_initial is not None and \
                        b"connection" in req_initial.headers.keys():
                    if req_initial.headers[
                            b"connection"].lower() == b"keep-alive":
                        refined_res_headers[b"connection"] = b"Keep-Alive"

                    else:
                        refined_res_headers[b"connection"] = b"Close"

                else:
                    refined_res_headers[b"connection"] = b"Keep-Alive"

            else:
                refined_res_headers[b"connection"] = b"Close"

        if b"transfer-encoding" in res_initial.headers.keys():
            self._determine_if_chunked_body_is_used(
                res_initial.headers.headers[b"transfer-encoding"])

        elif b"content-length" in res_initial.headers.keys():
            self._using_chunked_body = False

        elif version == initials.HttpVersion.V1_1:
            refined_res_headers[b"transfer-encoding"] = b"Chunked"
            self._using_chunked_body = True

        else:
            refined_res_headers[b"connection"] = b"Close"
            self._using_chunked_body = False

        refined_res_initial = initials.HttpResponseInitial(
            res_initial.status_code, version=version,
            headers=refined_res_headers)
        return (refined_res_initial, self._generate_initial_bytes(
                version.value,
                str(res_initial.status_code).encode(),
                http.HTTPStatus(res_initial.status_code).phrase.encode(),
                headers=refined_res_initial.headers))

    def compose_body(
        self, data_chunk: bytes, *,
            last_chunk: bool=False) -> Optional[bytes]:
        assert self._using_chunked_body is not None

        if self._using_chunked_body:
            if len(data_chunk) > 0:
                chunk_len = f"{len(data_chunk):x}".encode()

                if last_chunk:
                    self._using_chunked_body = None

                    return b"%s\r\n%s\r\n0\r\n\r\n" % (chunk_len, data_chunk)

                else:
                    return b"%s\r\n%s\r\n" % (chunk_len, data_chunk)

            elif last_chunk:
                self._using_chunked_body = None

                return b"0\r\n\r\n"

            else:
                return b""

        if last_chunk:
            self._using_chunked_body = None

        return data_chunk
