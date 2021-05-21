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

from typing import Generator
import asyncio

import helpers
import pytest


@pytest.fixture
def mocked_server(
    event_loop: asyncio.AbstractEventLoop,
) -> Generator[helpers.MockedServer, None, None]:
    async def create_mocked_server() -> helpers.MockedServer:
        srv = helpers.MockedServer()
        return await srv.__aenter__()

    async def close_mocked_server(srv: helpers.MockedServer) -> None:
        await srv.__aexit__()

    srv = event_loop.run_until_complete(create_mocked_server())

    yield srv

    event_loop.run_until_complete(close_mocked_server(srv))


@pytest.fixture
def mocked_unix_server(
    event_loop: asyncio.AbstractEventLoop,
) -> Generator[helpers.MockedUnixServer, None, None]:
    async def create_mocked_server() -> helpers.MockedUnixServer:
        srv = helpers.MockedUnixServer()
        return await srv.__aenter__()

    async def close_mocked_server(srv: helpers.MockedUnixServer) -> None:
        await srv.__aexit__()

    srv = event_loop.run_until_complete(create_mocked_server())

    yield srv

    event_loop.run_until_complete(close_mocked_server(srv))
