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

import magicdict


class H1InitialParser:
    def __init__(self, buf: bytearray, is_https: bool=False) -> None:
        self._buf = buf

        self._searched_len = 0

        self._is_https = is_https

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

    def parse_request(self) -> Optional[initials.HttpRequestInitial]:
        initial_lines = self._split_initial()

        if initial_lines is None:
            return None

        try:
            first_line = initial_lines.pop(0)

            method_buf, path, version_buf = first_line.split(b" ")

            method = initials.HttpRequestMethod(method_buf.strip())

        except (IndexError, ValueError) as e:
            raise exceptions.MalformedHttpInitial(
                "Unable to unpack the first line of the initial.") from e

        headers = self._parse_headers(initial_lines)

        return initials.HttpRequestInitial(
            method=method,
            uri=path,
            authority=headers[b"host"],
            scheme=b"https" if self._is_https else b"http",
            headers=headers)

    def parse_response(self) -> Optional[initials.HttpResponseInitial]:
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

        except (IndexError, ValueError) as e:
            raise exceptions.MalformedHttpInitial(
                "Unable to unpack the first line of the initial.") from e

        headers = self._parse_headers(initial_lines)

        return initials.HttpResponseInitial(
            status_code=status_code, headers=headers)


class H1InitialComposer:
    pass
