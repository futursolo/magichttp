magichttp
=========
.. image:: https://travis-ci.org/futursolo/magichttp.svg?branch=master
    :target: https://travis-ci.org/futursolo/magichttp

.. image:: https://coveralls.io/repos/github/futursolo/magichttp/badge.svg?branch=master
    :target: https://coveralls.io/github/futursolo/magichttp

.. image:: https://img.shields.io/pypi/v/magichttp.svg
    :target: https://pypi.org/project/magichttp/

Asynchronous http, made easy.

Magichttp is an http stack for asyncio, which provides one the ability to create
their own async http client/server without diving into the http protocol
implementation.

Install
-------

.. code-block:: shell

  $ pip install magichttp -U


Usage
-----
See :code:`examples/echo_client.py` and :code:`examples/echo_server.py`.

Under Development
-----------------
Magichttp is in beta. Basic unittests and contract checks are in place;
however, it still may have unknown bugs. Bug reports and pull requests are
always welcomed.

License
-------
Copyright 2018 Kaede Hoshikawa

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
