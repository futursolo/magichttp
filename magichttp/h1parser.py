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

from typing import Optional, List

from . import exceptions
from . import initials
from . import httputils
from . import constants

import magicdict

__all__ = ["H1Parser"]

_CHUNKED_BODY = -1
_ENDLESS_BODY = -2

_CHUNK_NOT_STARTED = -1
_LAST_CHUNK = -2


class H1Parser:
    __slots__ = (
        "_buf", "_searched_len", "_using_https", "_body_len_left",
        "_body_chunk_len_left", "_body_chunk_crlf_dropped")

    def __init__(self, buf: bytearray, using_https: bool=False) -> None:
        self._buf = buf

        self._searched_len = 0

        self._using_https = using_https

        self._body_len_left: Optional[int] = None
        # None means the initial is not ready,
        # a non-negative integer represents the body length left,
        # -1 means the body is chunked,
        # and -2 means the body is endless(Read until connection EOF).

        self._body_chunk_len_left = _CHUNK_NOT_STARTED
        self._body_chunk_crlf_dropped = True

    def _split_initial(self) -> Optional[List[bytes]]:
        pos = self._buf.find(b"\r\n\r\n", self._searched_len)

        if pos == -1:
            self._searched_len = len(self._buf)

            return None

        self._searched_len = 0

        initial_buf = bytes(self._buf[0:pos])
        del self._buf[0:pos + 4]

        return initial_buf.split(b"\r\n")

    def _parse_headers(self, initial_lines: List[bytes]) -> \
            magicdict.FrozenTolerantMagicDict[bytes, bytes]:
        headers: magicdict.TolerantMagicDict[bytes, bytes] = \
            magicdict.TolerantMagicDict()

        for header_line in initial_lines:
            try:
                header_name, header_value = header_line.split(b":", 1)

            except ValueError as e:
                raise exceptions.MalformedHttpInitial(
                    "Unable to pack headers.") from e

            headers.add(header_name.strip().lower(), header_value.strip())

        return headers

    def _determine_by_transfer_encoding(
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
                self._body_len_left = _CHUNKED_BODY
                self._body_chunk_len_left = _CHUNK_NOT_STARTED

    def _determine_content_length_by_header(
            self, content_length_bytes: bytes) -> None:
        try:
            content_length_str = content_length_bytes.decode("latin-1")

            if not content_length_str.isdecimal():
                raise ValueError("This is not a valid Decimal Number.")

            self._body_len_left = int(content_length_str)

        except (ValueError, UnicodeDecodeError) as e:
            raise exceptions.MalformedHttpInitial(
                "The value of Content-Length is not valid.") from e

    def _discover_request_body_len(
            self, req_initial: initials.HttpRequestInitial) -> None:
        assert self._body_len_left is None

        if req_initial.headers.get_first(
                b"connection", b"").strip().lower() == "upgrade":
            self._body_len_left = _ENDLESS_BODY

            return

        if b"transfer-encoding" in req_initial.headers.keys():
            self._determine_by_transfer_encoding(
                req_initial.headers[b"transfer-encoding"])

            if self._body_len_left is not None:
                return

        if b"content-length" not in req_initial.headers.keys():
            self._body_len_left = 0

            return

        self._determine_content_length_by_header(
            req_initial.headers[b"content-length"])

    def _discover_response_body_len(
            self, req_initial: initials.HttpRequestInitial,
            res_initial: initials.HttpResponseInitial) -> None:
        assert self._body_len_left is None

        if res_initial.headers.get_first(
                b"connection", b"").strip().lower() == b"upgrade":
            self._body_len_left = _ENDLESS_BODY

            return

        # HEAD Requests, and 204/304 Responses have no body.
        if req_initial.method == constants.HttpRequestMethod.Head:
            self._body_len_left = 0

            return

        if res_initial.status_code in (204, 304):
            self._body_len_left = 0

            return

        if b"transfer-encoding" in res_initial.headers.keys():
            self._determine_by_transfer_encoding(
                res_initial.headers[b"transfer-encoding"])

            if self._body_len_left is not None:
                return

        if b"content-length" not in res_initial.headers.keys():
            self._body_len_left = _ENDLESS_BODY
            # Read until close.

        self._determine_content_length_by_header(
            res_initial.headers[b"content-length"])

    def parse_request(self) -> Optional[initials.HttpRequestInitial]:
        if self._body_len_left is not None:
            return None  # Waiting for body to finish.

        initial_lines = self._split_initial()

        if initial_lines is None:
            return None

        try:
            first_line = initial_lines.pop(0)

            method_buf, path, version_buf = first_line.split(b" ")

            method = constants.HttpRequestMethod(method_buf.strip())
            version = constants.HttpVersion(version_buf.strip())

        except (IndexError, ValueError) as e:
            raise exceptions.MalformedHttpInitial(
                "Unable to unpack the first line of the initial.") from e

        headers = self._parse_headers(initial_lines)

        req_initial = initials.HttpRequestInitial(
            method,
            version=version,
            uri=path,
            authority=headers.get(b"host", None),
            scheme=b"https" if self._using_https else b"http",
            headers=headers)

        self._discover_request_body_len(req_initial)

        return req_initial

    def parse_response(self, req_initial: initials.HttpRequestInitial) -> \
            Optional[initials.HttpResponseInitial]:
        if self._body_len_left is not None:
            return None  # Waiting for body to finish.

        initial_lines = self._split_initial()

        if initial_lines is None:
            return None

        try:
            first_line = initial_lines.pop(0)

            version_buf, status_code_buf, status_text = first_line.split(b" ")

            status_code_str = status_code_buf.decode()

            if not status_code_str.isdecimal():
                raise ValueError("Status Code MUST be decimal.")

            status_code = int(status_code_str)
            version = constants.HttpVersion(version_buf)

        except (IndexError, ValueError) as e:
            raise exceptions.MalformedHttpInitial(
                "Unable to unpack the first line of the initial.") from e

        headers = self._parse_headers(initial_lines)

        res_initial = initials.HttpResponseInitial(
            status_code, version=version, headers=headers)

        self._discover_response_body_len(req_initial, res_initial)

        return res_initial

    def _parse_chunked_body(
            self, _can_drop_last_crlf: bool=True) -> Optional[bytes]:
        def try_drop_crlf() -> None:
            if self._body_chunk_crlf_dropped:
                return

            if self._body_chunk_len_left > 0:
                return

            if self._body_chunk_len_left == _LAST_CHUNK and \
                    not _can_drop_last_crlf:
                return

            if len(self._buf) < 2:
                return

            del self._buf[0:2]

            if self._body_chunk_len_left != _LAST_CHUNK:
                self._body_chunk_len_left = _CHUNK_NOT_STARTED

            self._body_chunk_crlf_dropped = True

        def try_read_next_chunk_len() -> None:
            try_drop_crlf()

            if self._body_chunk_len_left != _CHUNK_NOT_STARTED:
                return

            pos = self._buf.find(b"\r\n")

            if pos == -1:
                return

            len_bytes = self._buf[0:pos]
            del self._buf[0:pos + 2]

            len_bytes = list(
                httputils.parse_semicolon_header(bytes(len_bytes)).keys())[0]

            try:
                len_str = len_bytes.decode("latin-1")

            except UnicodeDecodeError as e:
                raise exceptions.MalformedHttpMessage(
                    "Unable to decode the chunk length as latin-1.") from e
            try:
                self._body_chunk_len_left = int(len_str, 16)

            except ValueError as e:
                raise exceptions.MalformedHttpMessage(
                    "Chunk length is not a valid hex integer.") from e

            if self._body_chunk_len_left == 0:
                self._body_chunk_len_left = _LAST_CHUNK

            self._body_chunk_crlf_dropped = False

        try_read_next_chunk_len()

        if self._body_chunk_len_left == _CHUNK_NOT_STARTED:
            return b""  # Chunk Length Not Ready.

        if self._body_chunk_len_left == _LAST_CHUNK:
            try_drop_crlf()
            if self._body_chunk_crlf_dropped:
                # Body Finished.
                return None

            else:
                # Last CRLF not dropped.
                return b""

        if self._body_chunk_len_left == 0:
            try_drop_crlf()

            if self._body_chunk_crlf_dropped and len(self._buf) > 0:
                return self._parse_chunked_body(_can_drop_last_crlf=False)

            else:
                return b""

        if len(self._buf) == 0:
            # No more data.
            return b""

        if self._body_chunk_len_left >= len(self._buf):
            current_chunk = bytes(self._buf)
            self._body_chunk_len_left -= len(current_chunk)
            self._buf.clear()  # type: ignore

        else:
            current_chunk = self._buf[0:self._body_chunk_len_left]
            del self._buf[0:self._body_chunk_len_left]
            self._body_chunk_len_left = 0

        if self._body_chunk_len_left == 0:
            try_drop_crlf()

        return current_chunk

    def parse_body(self) -> Optional[bytes]:
        if self._body_len_left is None:
            return None  # Wait the initial to finish.

        if self._body_len_left == 0:
            self._body_len_left = None

            return None

        if self._body_len_left == _ENDLESS_BODY:
            current_chunk = bytes(self._buf)
            self._buf.clear()  # type: ignore

        elif self._body_len_left == _CHUNKED_BODY:
            maybe_current_chunk = self._parse_chunked_body()
            if maybe_current_chunk is None:
                self._body_len_left = None

                return None

            else:
                current_chunk = maybe_current_chunk

        elif self._body_len_left >= len(self._buf):
            current_chunk = bytes(self._buf)
            self._body_len_left -= len(current_chunk)
            self._buf.clear()  # type: ignore

        else:
            current_chunk = bytes(self._buf[0:self._body_len_left])
            self._body_len_left = 0
            del self._buf[0:self._body_len_left]

        return current_chunk
