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

from typing import Tuple, Optional

import magichttp
import urllib.parse
import asyncio


class _EchoClientProtocol(magichttp.HttpClientProtocol):
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


async def get_page(url: str) -> Tuple[magichttp.HttpResponseInitial, bytes]:
    parsed_url = urllib.parse.urlparse(url)

    _, protocol = await asyncio.get_event_loop().create_connection(
        _EchoClientProtocol,
        host=parsed_url.hostname,
        port=parsed_url.port or 80)

    await protocol.conn_made_fur

    ip, port, *_ = protocol.transport.get_extra_info("peername")

    print(f"Connected to: {ip}:{port}")

    writer = await protocol.write_request(
        magichttp.HttpRequestMethod.Get,
        uri=parsed_url.path.encode(),
        authority=parsed_url.netloc.encode(),
        scheme=parsed_url.scheme.encode())

    print(f"Request Sent: {writer.initial}")

    writer.finish()
    print(f"Request Body: b''")

    reader = await writer.read_response()
    print(f"Response Received: {reader.initial}")

    try:
        body = await reader.read()

    except magichttp.HttpStreamFinishedError:
        body = b""

    print(f"Body Received: {body}")
    print("Stream Finished.")

    protocol.close()

    await protocol.wait_closed()
    print("Connection lost.")

    return reader.initial, body


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(get_page("http://localhost:8080/"))
