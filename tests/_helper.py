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

import asyncio


class TestHelper:
    def __init__(self):
        self.loop = asyncio.get_event_loop()

        self.loop.set_debug(True)

    def run_async_test(self, coro_fn):
        async def test_coro(_self, *args, **kwargs):
            await asyncio.wait_for(
                coro_fn(_self, *args, **kwargs), timeout=10)

        def wrapper(_self, *args, **kwargs):
            self.loop.run_until_complete(test_coro(_self, *args, **kwargs))

        return wrapper
