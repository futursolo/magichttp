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

from typing import Optional, List, Tuple, Union

from . import initials
from . import constants

import abc
import http
import magicdict

_CHUNKED_BODY = -1
_ENDLESS_BODY = -2

_CHUNK_NOT_STARTED = -1
_LAST_CHUNK = -2


class InvalidTransferEncoding(ValueError):
    pass


class InvalidContentLength(ValueError):
    pass


class InvalidHeader(ValueError):
    pass


class UnparsableHttpMessage(ValueError):
    pass


class IncompleteHttpMessage(ValueError):
    pass


def is_chunked_body(te_header_bytes: bytes) -> bool:
    te_header_pieces = [
        i.strip().lower() for i in te_header_bytes.split(b";")
        if i]

    last_piece = te_header_pieces.pop(-1)

    if (b"identity" == last_piece and te_header_pieces) or \
            b"identity" in te_header_pieces:
        raise InvalidTransferEncoding(
            "Identity is not the only transfer encoding.")

    if b"chunked" in te_header_pieces:
        raise InvalidTransferEncoding(
            "Chunked transfer encoding found, but not at last.")

    return last_piece == b"chunked"


def parse_content_length(cl_header_bytes: bytes) -> int:
    try:
        cl_header_str = cl_header_bytes.decode("latin-1")

        if not cl_header_str.isdecimal():
            raise ValueError("This is not a valid Decimal Number.")

        return int(cl_header_str)

    except (ValueError, UnicodeDecodeError) as e:
        raise InvalidContentLength(
            "The value of Content-Length is not valid.") from e


def parse_headers(header_lines: List[bytes]) -> \
        magicdict.FrozenTolerantMagicDict[bytes, bytes]:
    headers: List[Tuple[bytes, bytes]] = []

    try:
        for line in header_lines:
            name, value = line.split(b":", 1)

            headers.append((name.strip(), value.strip()))

    except ValueError as e:
        raise InvalidHeader("Unable to unpack the current header.") from e

    return magicdict.FrozenTolerantMagicDict(headers)


class BaseH1Parser(abc.ABC):
    __slots__ = (
        "_buf", "_searched_len", "_body_len_left",
        "_body_chunk_len_left", "_body_chunk_crlf_dropped", "_finished",
        "_incompleted_body", "buf_ended", "_exc")

    def __init__(self, buf: bytearray) -> None:
        self._buf = buf
        self.buf_ended = False

        self._searched_len = 0

        self._body_len_left: Optional[int] = None
        # None means the initial is not ready,
        # a non-negative integer represents the body length left,
        # -1 means the body is chunked,
        # and -2 means the body is endless(Read until connection EOF).

        self._body_chunk_len_left = _CHUNK_NOT_STARTED
        self._body_chunk_crlf_dropped = True

        self._finished = False

        self._exc: Optional[
            Union[UnparsableHttpMessage, IncompleteHttpMessage]] = None

    def _split_initial(self) -> Optional[List[bytes]]:
        pos = self._buf.find(b"\r\n\r\n", self._searched_len)

        if pos == -1:
            searched_len = len(self._buf) - 3
            if searched_len < 0:
                self._searched_len = 0

            else:
                self._searched_len = searched_len

            return None

        self._searched_len = 0

        initial_buf = bytes(self._buf[0:pos])
        del self._buf[0:pos + 4]

        return initial_buf.split(b"\r\n")

    def _parse_chunked_body(self) -> Optional[bytes]:
        def try_drop_crlf() -> None:
            if self._body_chunk_crlf_dropped:
                return

            if self._body_chunk_len_left > 0:
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

            len_bytes = len_bytes.split(b";", 1)[0].strip()

            try:
                len_str = len_bytes.decode("latin-1")
                self._body_chunk_len_left = int(len_str, 16)

            except (UnicodeDecodeError, ValueError) as e:
                raise UnparsableHttpMessage(
                    "Failed to decode Chunk Length") from e

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
            return b""

        if not self._buf:
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

        return current_chunk

    def parse_body(self) -> Optional[bytes]:
        assert self._body_len_left is not None, \
            "You should parse the initial first."

        if self._finished:
            return None

        if self._exc:
            raise

        try:
            if self._body_len_left == 0:
                self._finished = True

                return None

            if self._body_len_left == _ENDLESS_BODY:
                current_chunk = bytes(self._buf)
                self._buf.clear()  # type: ignore

                if self.buf_ended:
                    self._finished = True

            elif self._body_len_left == _CHUNKED_BODY:
                maybe_current_chunk = self._parse_chunked_body()
                if maybe_current_chunk is None:
                    self._finished = True

                    return None

                else:
                    current_chunk = maybe_current_chunk

                    if self.buf_ended and not current_chunk:
                        raise IncompleteHttpMessage(
                            "The buffer ended before the last chunk "
                            "has been found.")

            elif self._body_len_left >= len(self._buf):
                current_chunk = bytes(self._buf)
                self._body_len_left -= len(current_chunk)
                self._buf.clear()  # type: ignore

            else:
                current_chunk = bytes(self._buf[0:self._body_len_left])
                self._body_len_left = 0
                del self._buf[0:self._body_len_left]

            if self.buf_ended and not current_chunk and \
                    self._body_len_left > 0:
                raise IncompleteHttpMessage(
                    "Buffer ended before the body length can be reached.")

            return current_chunk

        except (UnparsableHttpMessage, IncompleteHttpMessage) as e:
            self._exc = e

            raise


class H1RequestParser(BaseH1Parser):
    def _discover_body_length(
            self, initial: initials.HttpRequestInitial) -> None:
        if initial.headers.get_first(
                b"connection", b"").strip().lower() == b"upgrade":
            self._body_len_left = _ENDLESS_BODY

            return

        try:
            if b"transfer-encoding" in initial.headers.keys():
                if is_chunked_body(initial.headers[b"transfer-encoding"]):
                    self._body_len_left = _CHUNKED_BODY

                    return

            if b"content-length" in initial.headers.keys():
                self._body_len_left = parse_content_length(
                    initial.headers[b"content-length"])

                return

        except InvalidTransferEncoding as e:
            raise UnparsableHttpMessage("Transfer Encoding is invalid.") from e

        except InvalidContentLength as e:
            raise UnparsableHttpMessage("Content Length is invalid.") from e

        self._body_len_left = 0

    def parse_request(self) -> Optional[initials.HttpRequestInitial]:
        assert self._body_len_left is None, "Parsers are not reusable."

        if self._exc:
            raise self._exc

        try:
            initial_lines = self._split_initial()

            if initial_lines is None:
                if self.buf_ended:
                    raise IncompleteHttpMessage(
                        "Buffer ended before an initial can be found.")

                return None

            try:
                first_line = initial_lines.pop(0)

                method_buf, path, version_buf = first_line.split(b" ")

                method = constants.HttpRequestMethod(
                    method_buf.upper().strip())
                version = constants.HttpVersion(version_buf.upper().strip())

            except (IndexError, ValueError) as e:
                raise UnparsableHttpMessage(
                    "Unable to unpack the first line of the initial.") from e

            try:
                headers = parse_headers(initial_lines)

            except InvalidHeader as e:
                raise UnparsableHttpMessage("Unable to parse headers.") from e

            initial = initials.HttpRequestInitial(
                method,
                version=version,
                uri=path,
                authority=headers.get(b"host", None),
                scheme=headers.get_first(b"x-scheme", None),
                headers=headers)

            self._discover_body_length(initial)

            return initial

        except (UnparsableHttpMessage, IncompleteHttpMessage) as e:
            self._exc = e

            raise


class H1ResponseParser(BaseH1Parser):
    def _discover_body_length(
        self, req_initial: initials.HttpRequestInitial,
            initial: initials.HttpResponseInitial) -> None:
        if initial.headers.get_first(
                b"connection", b"").strip().lower() == b"upgrade":
            self._body_len_left = _ENDLESS_BODY

            return

        # HEAD Requests, and 204/304 Responses have no body.
        if req_initial.method == constants.HttpRequestMethod.Head:
            self._body_len_left = 0

            return

        if initial.status_code in (204, 304):
            self._body_len_left = 0

            return

        try:
            if b"transfer-encoding" in initial.headers.keys():
                if is_chunked_body(initial.headers[b"transfer-encoding"]):
                    self._body_len_left = _CHUNKED_BODY

                    return

            if b"content-length" not in initial.headers.keys():
                self._body_len_left = _ENDLESS_BODY
                # Read until close.

                return

            self._body_len_left = parse_content_length(
                initial.headers[b"content-length"])

        except InvalidTransferEncoding as e:
            raise UnparsableHttpMessage("Transfer Encoding is invalid.") from e

        except InvalidContentLength as e:
            raise UnparsableHttpMessage("Content Length is invalid.") from e

    def parse_response(
        self, req_initial: initials.HttpRequestInitial) -> Optional[
            initials.HttpResponseInitial]:
        assert self._body_len_left is None, "Parsers are not reusable."

        if self._exc:
            raise self._exc

        try:
            initial_lines = self._split_initial()

            if initial_lines is None:
                if self.buf_ended:
                    raise IncompleteHttpMessage(
                        "Buffer ended before an initial can be found.")

                return None

            try:
                first_line = initial_lines.pop(0)

                version_buf, status_code_buf, *status_text = \
                    first_line.split(b" ")

                status_code_str = status_code_buf.decode()

                if not status_code_str.isdecimal():
                    raise ValueError("Status Code MUST be decimal.")

                status_code = http.HTTPStatus(int(status_code_str))
                version = constants.HttpVersion(version_buf)

            except (IndexError, ValueError) as e:
                raise UnparsableHttpMessage(
                    "Unable to unpack the first line of the initial.") from e

            try:
                headers = parse_headers(initial_lines)

            except InvalidHeader as e:
                raise UnparsableHttpMessage("Unable to parse headers.") from e

            initial = initials.HttpResponseInitial(
                status_code, version=version, headers=headers)

            self._discover_body_length(req_initial, initial)

            return initial

        except (UnparsableHttpMessage, IncompleteHttpMessage) as e:
            self._exc = e

            raise
