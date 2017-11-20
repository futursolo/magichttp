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

from typing import Mapping, Optional, Union, Tuple, List, Iterable

import magicdict
import collections.abc

__all__ = ["parse_semicolon_header", "compose_semicolon_header"]


def parse_semicolon_header(
    header_bytes: bytes) -> magicdict.FrozenTolerantMagicDict[
        bytes, Optional[bytes]]:
    header_parts: List[Tuple[bytes, Optional[bytes]]] = []

    for part in header_bytes.split(b";"):
        part = part.strip()

        if not part:
            continue

        name, *maybe_value = part.split(b"=", 1)

        name = name.strip()

        if maybe_value:
            value = maybe_value[0].strip()
            if value.startswith(b'"') and value.endswith(b'"'):
                value = value[1:-1]

            header_parts.append((name, value))

        else:
            header_parts.append((name, None))

    return magicdict.FrozenTolerantMagicDict(header_parts)


def compose_semicolon_header(
    header_parts: Union[
        Mapping[bytes, Optional[bytes]],
        Iterable[Tuple[bytes, Optional[bytes]]]]) -> bytes:
    header_part_lst: List[bytes] = []

    def add_one_part(name: bytes, value: Optional[bytes]) -> None:
        if value is None:
            header_part_lst.append(name.strip())

        else:
            header_part_lst.append(b"%s=%s" % (name.strip(), value.strip()))

    if hasattr(header_parts, "items"):
        for name, value in header_parts.items():  # type: ignore
            add_one_part(name, value)

    else:
        for name, value in header_parts:
            add_one_part(name, value)  # type: ignore

    return b"; ".join(header_part_lst)
