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

from setuptools import setup, find_packages
from pip.req import parse_requirements

import importlib
import os
import sys

if not sys.version_info[:3] >= (3, 6, 0):
    raise RuntimeError("Magicdict requires Python 3.6.0 or higher.")

else:
    try:
        import _modify_version

    except ImportError:
        pass

    else:
        _modify_version.modify("magichttp")

    import _load_version


setup_requirements = [
    "setuptools",
    "pytest-runner"]

install_requirements = [
    str(r.req) for r in parse_requirements("requirements.txt", session=False)]

test_requirements = [
    str(r.req) for r in parse_requirements("dev-requirements.txt", session=False)]

if __name__ == "__main__":
    setup(
        name="magichttp",
        version=_load_version.load("magichttp"),
        author="Kaede Hoshikawa",
        author_email="futursolo@icloud.com",
        url="https://github.com/futursolo/magichttp",
        license="Apache License 2.0",
        description="An http stack for asyncio.",
        long_description=open("README.rst", "r").read(),
        packages=find_packages(),
        include_package_data=True,
        setup_requires=setup_requirements,
        install_requires=install_requirements,
        tests_require=test_requirements,
        extras_require={
            "test": test_requirements
        },
        zip_safe=False,
        classifiers=[
            "Operating System :: MacOS",
            "Operating System :: MacOS :: MacOS X",
            "Operating System :: Microsoft",
            "Operating System :: Microsoft :: Windows",
            "Operating System :: POSIX",
            "Operating System :: POSIX :: Linux",
            "Operating System :: Unix",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3 :: Only",
            "Programming Language :: Python :: Implementation :: CPython"
        ]
    )