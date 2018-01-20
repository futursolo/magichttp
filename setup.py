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

from setuptools import setup, find_packages

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


setup_requires = [
    i for i in open("setup-requirements.txt").read().split("\n") if i]

install_requires = [
    i for i in open("requirements.txt").read().split("\n") if i]

tests_require = [
    i for i in open("test-requirements.txt").read().split("\n") if i]


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
        setup_requires=setup_requires,
        install_requires=install_requires,
        tests_require=tests_require,
        extras_require={
            "test": tests_require
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
