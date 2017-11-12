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

from typing import Tuple

import magichttp
import urllib.parse
import asyncio


async def get_page(url: str) -> Tuple[magichttp.HttpResponseInitial, bytes]:
    parsed_url = urllib.parse.urlparse(url)

    req_initial = magichttp.HttpRequestInitial(
        method=magichttp.HttpRequestMethod.Get,
        uri=parsed_url.path.encode(),
        authority=parsed_url.netloc.encode(),
        version=magichttp.HttpVersion.V1_1,
        scheme=parsed_url.scheme.encode()
    )

    _, protocol = await asyncio.get_event_loop().create_connection(
        magichttp.HttpClientProtocol,
        host=parsed_url.hostname,
        port=parsed_url.port or 80)

    ip, port, *_ = protocol.transport.get_extra_info("peername")

    print(f"Connected to: {ip}:{port}")

    writer = await protocol.write_request(req_initial)
    print(f"Request Sent: {writer.initial}")

    await writer.finish()
    print(f"Request Body: b''")

    reader = await writer.read_response()
    print(f"Response Received: {reader.initial}")

    try:
        body = await reader.read()

    except magichttp.HttpStreamFinishedError:
        body = b""

    print(f"Body Received: {body}")
    print("Stream Finished.")

    await protocol.close()
    print("Connection lost.")

    return reader.initial, body


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(get_page("http://localhost:8080/"))
