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

from typing import List, Optional

import asyncio
import magichttp
import weakref

import traceback


class _EchoServerProtocol(magichttp.HttpServerProtocol):
    def __init__(self) -> None:
        super().__init__()

        self.conn_made_fur: "asyncio.Future[None]" = asyncio.Future()

    def connection_made(  # type: ignore
            self, transport: asyncio.Transport) -> None:
        super().connection_made(transport)

        if not self.conn_made_fur.done():
            self.conn_made_fur.set_result(None)

    def connection_lost(self, exc: Optional[BaseException]=None) -> None:
        super().connection_lost(exc)

        if not self.conn_made_fur.done():
            e = ConnectionError()
            if exc:
                e.__cause__ = exc
            self.conn_made_fur.set_exception(e)


class EchoHttpServer:
    def __init__(self) -> None:
        self._protocols: "weakref.WeakSet[_EchoServerProtocol]" = \
            weakref.WeakSet()

        self._loop = asyncio.get_event_loop()

        self._srv: Optional[asyncio.AbstractServer] = None

        self._tsks: "weakref.WeakSet[asyncio.Task[None]]" = \
            weakref.WeakSet()

    async def listen(self, port: int, *, host: str="localhost") -> None:
        assert self._srv is None

        self._srv = await self._loop.create_server(
            self._create_protocol, port=port, host=host)

    def _create_protocol(self) -> _EchoServerProtocol:
        protocol = _EchoServerProtocol()
        self._protocols.add(protocol)

        self._tsks.add(
            self._loop.create_task(self._read_requests(protocol)))

        return protocol

    async def _write_echo(
            self, req_reader: magichttp.HttpRequestReader) -> None:
        print(f"New Request: {req_reader.initial}")
        try:
            body = await req_reader.read()

        except magichttp.HttpStreamFinishedError:
            body = b""
        print(f"Request Body: {body}")

        res_initial = magichttp.HttpResponseInitial(
            200, headers={b"Content-Type": b"text/plain"})

        writer = await req_reader.write_response(res_initial)
        print(f"Response Sent: {writer.initial}")

        writer.write(b"Got it!")
        print(f"Response Body: b'Got it!'")

        await writer.finish()
        print(f"Stream Finished.")

    async def _read_requests(self, protocol: _EchoServerProtocol) -> None:
        await protocol.conn_made_fur

        ip, port, *_ = protocol.transport.get_extra_info("peername")
        print(f"New Connection: {ip}:{port}")

        try:
            async for req_reader in protocol:
                await self._write_echo(req_reader)

        except asyncio.CancelledError:
            raise

        except Exception:
            traceback.print_exc()

            await protocol.close()

        finally:
            print("Connection lost.")

    async def close(self) -> None:
        if self._srv is None:
            return

        self._srv.close()

        if self._protocols:
            await asyncio.wait(
                [protocol.close() for protocol in self._protocols])

        await asyncio.sleep(0)

        if self._tsks:
            for tsk in self._tsks:
                if not tsk.done():
                    tsk.cancel()

            await asyncio.wait(list(self._tsks))

        await self._srv.wait_closed()

        self._srv = None


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    srv = EchoHttpServer()

    loop.run_until_complete(srv.listen(8080))

    @loop.call_soon
    def _print_welcome_msg() -> None:
        print("Echo Server is now listening to localhost:8080.")

    try:
        loop.run_forever()

    except KeyboardInterrupt:
        loop.run_until_complete(srv.close())

        print("Server Shutdown.")