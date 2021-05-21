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

import asyncio
import os

import helpers
import pytest

from magichttp.io_compat.asyncio import Socket

_BIG_SIZE = 1024 * 1024  # 1M


@pytest.mark.asyncio
async def test_connect(mocked_server: helpers.MockedServer) -> None:
    sock = await Socket.connect("localhost", mocked_server.port)

    send_data = os.urandom(_BIG_SIZE)
    tsk = asyncio.create_task(sock.send_all(send_data))

    while True:
        await asyncio.sleep(0.01)
        try:
            proto = mocked_server.select_proto()

        except RuntimeError:
            continue

        if len(b"".join(proto.data_chunks)) == _BIG_SIZE:
            break

    await tsk
    assert send_data == b"".join(proto.data_chunks)

    recv_data = os.urandom(_BIG_SIZE)
    assert proto.transport is not None
    proto.transport.write(recv_data)

    buf = bytearray()
    while len(buf) < _BIG_SIZE:
        buf.extend(await sock.recv())

    assert recv_data == buf

    await sock.close()

    with pytest.raises(EOFError):
        await sock.recv()


@pytest.mark.asyncio
async def test_listen() -> None:
    port = helpers.MockedServer.avail_tcp_port()
    bind_sock = await Socket.bind_listen("localhost", port)

    send_data = os.urandom(_BIG_SIZE)
    recv_data = os.urandom(_BIG_SIZE)

    async def send_write() -> None:
        reader, writer = await asyncio.open_connection("localhost", port)
        writer.write(recv_data)
        writer.write_eof()

        client_buf = bytearray()
        while len(client_buf) < _BIG_SIZE:
            client_buf.extend(await reader.read(_BIG_SIZE))
        assert send_data == client_buf

    tsk = asyncio.create_task(send_write())

    with pytest.raises(OSError):
        await bind_sock.send_all(b"")

    with pytest.raises(OSError):
        await bind_sock.recv()

    sock = await bind_sock.accept()

    buf = bytearray()
    while len(buf) < _BIG_SIZE:
        buf.extend(await sock.recv())
    assert recv_data == buf

    send_data = os.urandom(_BIG_SIZE)
    await sock.send_all(send_data)

    await sock.close()
    await bind_sock.close()
    await tsk
