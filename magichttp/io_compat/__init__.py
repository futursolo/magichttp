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

import sniffio

from .abc import AbstractIo, AbstractTask
from .asyncio import AsyncIo


def get_io() -> AbstractIo:
    io_name = sniffio.current_async_library()

    if io_name == "asyncio":
        return AsyncIo()

    elif io_name == "curio":
        raise NotImplementedError

    elif io_name == "trio":
        raise NotImplementedError

    else:
        raise RuntimeError(f"Unsupported IO: {io_name}")


__all__ = ["AsyncIo", "AbstractIo", "AbstractTask"]
