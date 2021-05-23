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

from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Coroutine,
    Generic,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)
import abc
import socket
import ssl

from typing_extensions import Protocol

_T = TypeVar("_T")

_SOCKET_INFO = Union[Tuple[str, int, int, int], Tuple[str, int]]


class AbstractLock(Protocol):
    def __aenter__(self) -> Awaitable[None]:
        raise NotImplementedError

    def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Awaitable[None]:
        raise NotImplementedError

    def locked(self) -> bool:
        raise NotImplementedError


class AbstractEvent(Protocol):
    def is_set(self) -> bool:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    async def wait(self) -> Optional[bool]:
        raise NotImplementedError

    def set(self) -> None:  # noqa: A003
        raise NotImplementedError


class AbstractSocket(abc.ABC):
    """
    Abstract base class of Socket object.
    """

    @abc.abstractmethod
    async def recv(self, n: int) -> bytes:
        """
        Receive some data.

        :arg n: The size hint of data. If it is more performant to return
            more data, it may do so.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def send_all(self, buf: Union[bytes, bytearray, memoryview]) -> None:
        """
        Send all of the bytes.
        """
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    async def connect(
        cls,
        host: str,
        port: int,
        *,
        tls: Optional[ssl.SSLContext] = None,
        family: int = 0,
        proto: int = 0,
        flags: int = 0,
        server_hostname: Optional[str] = None,
    ) -> "AbstractSocket":
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    async def bind_listen(
        cls,
        host: str,
        port: int,
        *,
        family: int = socket.AF_UNSPEC,
        flags: int = socket.AI_PASSIVE,
        backlog: int = 100,
        socket_backlog: int = 100,
        tls: Optional[ssl.SSLContext] = None,
        reuse_address: Optional[bool] = None,
        reuse_port: Optional[bool] = None,
    ) -> "AbstractSocket":
        """
        :arg socket_backlog: The maximum number of sockets that can
        be inside the queue before they are accepted. Only applicable in
        certain implementation.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def accept(self) -> "AbstractSocket":
        raise NotImplementedError

    @abc.abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def sockname(self) -> Optional[_SOCKET_INFO]:
        """
        Return the socket's local address.

        For listened sockets, it will return the first address.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def bound_socknames(self) -> List[_SOCKET_INFO]:
        """
        Return all the local names.

        Depending on the I/O library, sometimes the 'Socket' will be able to
        listen to multiple sockets. This method can be used to return all the
        socknames it is bound to.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def peername(self) -> Optional[_SOCKET_INFO]:
        """
        Return the remote address the socket is connected to.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def tls_ctx(self) -> Optional[ssl.SSLContext]:
        """
        Return the tls context (if any).
        """
        raise NotImplementedError

    @abc.abstractmethod
    def tls_obj(self) -> Optional[Union[ssl.SSLObject, ssl.SSLSocket]]:
        """
        Return an instance of the `ssl.SSLObject` or `ssl.SSLSocket` (if any).
        """
        raise NotImplementedError


class AbstractTask(Generic[_T]):
    @abc.abstractmethod
    async def cancel(self, wait: bool = False) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def cancelled(self) -> bool:
        raise NotImplementedError


class AbstractIo(abc.ABC):
    """
    Bridge of I/O Library
    """

    @abc.abstractmethod
    def create_lock(self) -> AbstractLock:
        raise NotImplementedError

    @abc.abstractmethod
    def create_event(self) -> AbstractEvent:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def Socket(self) -> Type[AbstractSocket]:  # noqa: N802
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def CancelledError(self) -> Type[BaseException]:  # noqa: N802
        raise NotImplementedError

    @abc.abstractmethod
    async def create_task(
        self, coro: Coroutine[Any, Any, _T]
    ) -> AbstractTask[_T]:
        raise NotImplementedError

    # @abc.abstractmethod
    # async def shield(self, tsk: Awaitable[_T]) -> _T:
    #     raise NotImplementedError


__all__ = [
    "AbstractIo",
    "AbstractTask",
    "AbstractSocket",
    "AbstractEvent",
    "AbstractLock",
]
