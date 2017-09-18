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

import magicdict


def parse_semicolon_header(
        value: bytes) -> magicdict.TolerantMagicDict[bytes, Optional[bytes]]:
    header_dict = magicdict.TolerantMagicDict()
    for part in value.split(b";"):
        part = part.strip()

        if not part:
            continue

        splitted = part.split(b"=", 1)

        part_name = splitted.pop(0).strip()
        part_value = splitted.pop().strip() if splitted else None

        if part_value and part_value.startswith(b'"') and \
                part_value.endswith(b'"'):
            part_value = part_value[1:-1]

        header_dict.add(part_name, part_value)

    return header_dict


def compose_semicolon_header(
        header_dict: Mapping[bytes, Optional[bytes]]) -> bytes:
    header_list = []

    for name, value in header_dict.items():
        part = name.strip()

        if value is not None:
            part += b"=" + value.strip()

        header_list.append(part)

    return b"; ".join(header_list)
