# -*- coding: utf8 -*-
import codecs
import re
import sys
from os import path

from setuptools import find_packages, setup

try:
    from semantic_release import setup_hook
    setup_hook(sys.argv)
except ImportError:
    pass


def read(*parts):
    file_path = path.join(path.dirname(__file__), *parts)
    return codecs.open(file_path, encoding='utf-8').read()

version = re.search(
    r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]',
    read('api/__init__.py'),
    re.MULTILINE
).group(1)

print(version)

setup(
    name="epguides-api",
    version=version,
    url='http://github.com/frecar/epguides-api',
    author='Fredrik Carlsen',
    author_email='fredrik@carlsen.io',
    description='API for epguides.com',
    long_description=read('README.md'),
    packages=find_packages(exclude=['tests', 'tests.*']),
    tests_require=read('requirements.txt').strip().split('\n'),
    install_requires=read('requirements.txt').strip().split('\n'),
    license='MIT',
    test_suite='runtests.runtests',
    include_package_data=True,
    classifiers=[
        'Programming Language :: Python :: 3',
    ]
)
