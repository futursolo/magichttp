#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2021 Kaede Hoshikawa
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

from typing import Any, Iterable, Mapping, Optional, Tuple, Union
import typing

from . import constants

if typing.TYPE_CHECKING:
    from . import readers, writers

_HeaderType = Union[Mapping[str, str], Iterable[Tuple[str, str]]]


class BaseReadException(Exception):
    """
    The base class of all read exceptions.
    """

    pass


class BaseWriteException(Exception):
    """
    The base class of all write exceptions.
    """

    pass


class EntityTooLargeError(BaseReadException):
    """
    The incoming entity is too large.
    """

    pass


class RequestInitialTooLargeError(EntityTooLargeError):
    """
    The incoming request initial is too large.
    """

    def __init__(
        self, __delegate: "readers.HttpRequestReaderDelegate", *args: Any
    ) -> None:
        super().__init__(*args)

        self._delegate = __delegate

    def write_response(
        self,
        status_code: Union[
            int, constants.HttpStatusCode
        ] = constants.HttpStatusCode.REQUEST_HEADER_FIELDS_TOO_LARGE,
        *,
        headers: Optional[_HeaderType] = None,
    ) -> "writers.HttpResponseWriter":
        """
        When this exception is raised on the server side, this method is used
        to send a error response instead of
        :method:`BaseHttpStreamReader.write_response()`.
        """
        return self._delegate.write_response(
            constants.HttpStatusCode(status_code), headers=headers
        )


class ReadFinishedError(EOFError, BaseReadException):
    """
    Raised when the end of the stream is reached.
    """

    pass


class ReadAbortedError(BaseReadException):
    """
    Raised when the stream is aborted before reaching the end.
    """

    pass


class MaxBufferLengthReachedError(BaseReadException):
    """
    Raised when the max length of the stream buffer is reached before
    the desired condition can be satisfied.
    """

    pass


class ReadUnsatisfiableError(BaseReadException):
    """
    Raised when the end of the stream is reached before
    the desired condition can be satisfied.
    """

    pass


class SeparatorNotFoundError(ReadUnsatisfiableError):
    """
    Raised when the end of the stream is reached before
    the requested separator can be found.
    """

    pass


class ReceivedDataMalformedError(BaseReadException):
    """
    Raised when the received data is unable to be parsed as an http message.
    """

    pass


class RequestInitialMalformedError(ReceivedDataMalformedError):
    """
    The request initial is malformed.
    """

    def __init__(
        self, __delegate: "readers.HttpRequestReaderDelegate", *args: Any
    ) -> None:
        super().__init__(*args)

        self._delegate = __delegate

    def write_response(
        self,
        status_code: Union[
            int, constants.HttpStatusCode
        ] = constants.HttpStatusCode.BAD_REQUEST,
        *,
        headers: Optional[_HeaderType] = None,
    ) -> "writers.HttpResponseWriter":
        """
        When this exception is raised on the server side, this method is used
        to send a error response instead of
        :method:`BaseHttpStreamReader.write_response()`.
        """
        return self._delegate.write_response(
            constants.HttpStatusCode(status_code), headers=headers
        )


class WriteAfterFinishedError(EOFError, BaseWriteException):
    """
    Raised when :method:`BaseHttpStreamWriter.write()` or
    :method:`BaseHttpStreamWriter.finish()`is called after
    the stream is finished.
    """

    pass


class WriteAbortedError(BaseWriteException):
    """
    Raised when the stream is aborted before writing the end.
    """

    pass


__all__ = [
    "BaseReadException",
    "EntityTooLargeError",
    "RequestInitialTooLargeError",
    "ReadFinishedError",
    "ReadAbortedError",
    "MaxBufferLengthReachedError",
    "ReadUnsatisfiableError",
    "SeparatorNotFoundError",
    "ReceivedDataMalformedError",
    "RequestInitialMalformedError",
    "BaseWriteException",
    "WriteAfterFinishedError",
    "WriteAbortedError",
]
