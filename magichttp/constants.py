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

import enum

__all__ = ["HttpVersion", "HttpRequestMethod"]


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
