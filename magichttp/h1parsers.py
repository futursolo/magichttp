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

from typing import Optional, List, Tuple

from . import initials
from . import constants

import magicdict

BODY_IS_CHUNKED = -1
BODY_IS_ENDLESS = -2


class UnparsableHttpMessage(ValueError):
    pass


class InvalidHeader(UnparsableHttpMessage):
    pass


class InvalidTransferEncoding(InvalidHeader):
    pass


class InvalidContentLength(InvalidHeader):
    pass


class InvalidChunkLength(InvalidHeader):
    pass


def is_chunked_body(te_header_bytes: bytes) -> bool:
    te_header_pieces = [
        i.strip().lower() for i in te_header_bytes.split(b";") if i]

    last_piece = te_header_pieces.pop(-1)

    if (b"identity" == last_piece and te_header_pieces) or \
            b"identity" in te_header_pieces:
        raise InvalidTransferEncoding(
            "Identity is not the only transfer encoding.")

    if b"chunked" in te_header_pieces:
        raise InvalidTransferEncoding(
            "Chunked transfer encoding found, but not at last.")

    return last_piece == b"chunked"


def _parse_content_length_header(cl_header_bytes: bytes) -> int:
    try:
        return int(cl_header_bytes, 10)

    except ValueError as e:
        raise InvalidContentLength(
            "The value of Content-Length is not valid.") from e


def _split_initial_lines(buf: bytearray) -> Optional[List[bytes]]:
    pos = buf.find(b"\r\n\r\n")

    if pos == -1:
        return None

    initial_buf = bytes(buf[:pos])
    del buf[:pos + 4]

    return initial_buf.split(b"\r\n")


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


def parse_request_initial(
        buf: bytearray) -> Optional[initials.HttpRequestInitial]:
    initial_lines = _split_initial_lines(buf)

    if initial_lines is None:
        return None

    try:
        method_buf, path_buf, version_buf = initial_lines.pop(0).split(b" ")

        headers = parse_headers(initial_lines)

        return initials.HttpRequestInitial(
            constants.HttpRequestMethod(method_buf.upper().strip()),
            version=constants.HttpVersion(version_buf.upper().strip()),
            uri=path_buf,
            authority=headers.get(b"host", None),
            scheme=headers.get_first(b"x-scheme", None),
            headers=headers)

    except InvalidHeader:
        raise

    except (IndexError, ValueError) as e:
        raise UnparsableHttpMessage(
            "Unable to unpack the first line of the initial.") from e


def parse_response_initial(
    buf: bytearray, req_initial: initials.HttpRequestInitial) -> Optional[
        initials.HttpResponseInitial]:
    initial_lines = _split_initial_lines(buf)

    if initial_lines is None:
        return None

    try:
        version_buf, status_code_buf, *status_text = \
            initial_lines.pop(0).split(b" ")

        return initials.HttpResponseInitial(
            constants.HttpStatusCode(int(status_code_buf, 10)),
            version=constants.HttpVersion(version_buf),
            headers=parse_headers(initial_lines))

    except InvalidHeader:
        raise

    except (IndexError, ValueError) as e:
        raise UnparsableHttpMessage(
            "Unable to unpack the first line of the initial.") from e


def discover_request_body_length(initial: initials.HttpRequestInitial) -> int:
    if b"upgrade" in [s.strip() for s in initial.headers.get_first(
            b"connection", b"").lower().split(b",")]:
        return BODY_IS_ENDLESS

    if b"transfer-encoding" in initial.headers:
        if is_chunked_body(initial.headers[b"transfer-encoding"]):
            return BODY_IS_CHUNKED

    if b"content-length" in initial.headers:
        return _parse_content_length_header(initial.headers[b"content-length"])

    return 0


def discover_response_body_length(
    initial: initials.HttpResponseInitial, *,
        req_initial: initials.HttpRequestInitial) -> int:
    if initial.status_code == constants.HttpStatusCode.SWITCHING_PROTOCOLS:
        return BODY_IS_ENDLESS

    # HEAD Requests, and 204/304 Responses have no body.
    if req_initial.method == constants.HttpRequestMethod.HEAD or \
            initial.status_code in (204, 304):
        return 0

    if b"transfer-encoding" in initial.headers:
        if is_chunked_body(initial.headers[b"transfer-encoding"]):
            return BODY_IS_CHUNKED

    if b"content-length" not in initial.headers:
        # Read until close.
        return BODY_IS_ENDLESS

    return _parse_content_length_header(initial.headers[b"content-length"])


def parse_chunk_length(buf: bytearray) -> Optional[int]:
    pos = buf.find(b"\r\n")

    if pos == -1:
        return None

    len_buf = buf[:pos]
    del buf[:pos + 2]

    len_buf = len_buf.split(b";", 1)[0].strip()

    try:
        return int(len_buf, 16)

    except ValueError as e:
        raise InvalidChunkLength("Failed to decode Chunk Length") from e
