#!/usr/bin/env python3

# remote_debugging_path_chromium is free software: you can
# redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.

# remote_debugging_path_chromium is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with remote_debugging_path_chromium. If not, see
# <http://www.gnu.org/licenses/>.

from setuptools import setup

with open("README.rst", "r") as fh:
    long_description = fh.read()

setup(
    name="remote_debugging_path_chromium",
    version='0.1.0',
    author='Rian Hunter',
    author_email='rian@alum.mit.edu',
    url='https://github.com/rianhunter/remote_debugging_path_chromium',
    description="UNIX domain path proxy for Chromium's remote debugging tools",
    long_description=long_description,
    license='GPL3',
    packages=["remote_debugging_path_chromium"],
    install_requires=[
        "aiohttp",
    ],
    entry_points={
        'console_scripts': [
            'remote_debugging_path_chromium=remote_debugging_path_chromium.chromium:main'
        ],
    },
)
