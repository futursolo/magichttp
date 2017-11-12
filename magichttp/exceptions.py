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

from typing import Callable, Awaitable, Optional

import typing

if typing.TYPE_CHECKING:
    from . import initials
    from . import streams

__all__ = [
    "HttpStreamFinishedError",
    "HttpConnectionClosingError",
    "HttpConnectionClosedError",
    "HttpStreamAbortedError",
    "MalformedHttpMessage",
    "MalformedHttpInitial",
    "IncomingEntityTooLarge",
    "IncomingInitialTooLarge",
    "HttpRequestInitialRequired"]


class HttpStreamFinishedError(EOFError):
    """
    Read or write the stream after it is finished.
    """
    pass


class HttpConnectionClosingError(EOFError):
    """
    Read or write after the EOF is written or received.
    """
    pass


class HttpConnectionClosedError(HttpConnectionClosingError, ConnectionError):
    """
    Read or write the stream after the connection it it attached to is closed.
    """
    pass


class HttpStreamAbortedError(HttpStreamFinishedError):
    """
    Read or write the stream after the stream is aborted.
    """
    pass


class MalformedHttpMessage(ValueError):
    """
    The HTTP Message is malformed.
    """
    def __init__(
            self, *args: str, write_response_fn: Optional[Callable[
            ["initials.HttpResponseInitial"],
            Awaitable["streams.HttpResponseWriter"]]]=None) -> None:
        self._write_response_fn = write_response_fn

        final_args = args or (self.__doc__,)

        super().__init__(*final_args)

    @property
    def write_response(self) -> Callable[
            ["initials.HttpResponseInitial"],
            Awaitable["streams.HttpResponseWriter"]]:
        if self._write_response_fn is None:
            raise AttributeError("This is not available.")

        return self._write_response_fn


class MalformedHttpInitial(MalformedHttpMessage):
    """
    The Initial of a HTTP Message is malformed.
    """
    pass


class IncomingEntityTooLarge(ValueError):
    """
    The size of the Request is too large for the server to process.

    The Server should respond the request with an
    HTTP 413(Request Entity Too Large) status.
    """
    def __init__(
            self, *args: str, write_response_fn: Optional[Callable[
            ["initials.HttpResponseInitial"],
            Awaitable["streams.HttpResponseWriter"]]]=None) -> None:
        self._write_response_fn = write_response_fn

        final_args = args or (self.__doc__,)

        super().__init__(*final_args)

    @property
    def write_response(self) -> Callable[
            ["initials.HttpResponseInitial"],
            Awaitable["streams.HttpResponseWriter"]]:
        if self._write_response_fn is None:
            raise AttributeError("This is not available.")

        return self._write_response_fn


class IncomingInitialTooLarge(IncomingEntityTooLarge):
    """
    Similar to IncomingEntityTooLarge exception; however, more specifically,
    the initial is too large.

    The Server should respond with HTTP 431(Request Header Fields Too Large) or
    with HTTP 413(Request Entity Too Large).
    """
    pass


class HttpRequestInitialRequired(ValueError):
    """
    The Request Initial is required under this situation.
    """
    pass
