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

import enum
import http

__all__ = ["HttpVersion", "HttpRequestMethod", "HttpStatusCode"]


class HttpVersion(enum.Enum):
    V1_0 = b"HTTP/1.0"
    V1_1 = b"HTTP/1.1"


class HttpRequestMethod(enum.Enum):
    GET = b"GET"
    POST = b"POST"
    PUT = b"PUT"
    DELETE = b"DELETE"
    HEAD = b"HEAD"
    OPTIONS = b"OPTIONS"
    CONNECT = b"CONNECT"
    TRACE = b"TRACE"
    PATCH = b"PATCH"


HttpStatusCode = http.HTTPStatus
