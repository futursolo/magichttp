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

from _version import *
from .exceptions import *
from .initials import *
from .protocols import *
from .streams import *

from . import _version
from . import exceptions
from . import initials
from . import protocols
from . import streams

__all__ = _version.__all__ + exceptions.__all__ + initials.__all__ + \
    protocols.__all__ + streams.__all__


"""
Constants:
h11.CLIENT
h11.SERVER
h11.PRODUCT_ID

Exceptions:
h11.ProtocolError
h11.LocalProtocolError
h11.RemoteProtocolError

Connection:
h11.Connection

Client States:
h11.IDLE
h11.SEND_BODY
h11.DONE
h11.MUST_CLOSE
h11.CLOSED
h11.MIGHT_SWITCH_PROTOCOL
h11.SWITCHED_PROTOCOL
h11.ERROR

Server States:
h11.IDLE
h11.SEND_RESPONSE
h11.SEND_BODY
h11.DONE
h11.MUST_CLOSE
h11.CLOSED
h11.SWITCHED_PROTOCOL
h11.ERROR

"""
