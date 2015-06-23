# -*- coding: utf8 -*-
from setuptools import setup, find_packages


def _read_long_description():
    try:
        import pypandoc
        return pypandoc.convert('README.md', 'rst', format='markdown')
    except Exception:
        return None


def read_requirements():
    with open('requirements.txt') as f:
        return f.read().splitlines()

setup(
    name="epguides-api",
    version='1.1.0',
    url='http://github.com/frecar/epguides-api',
    author='Fredrik Carlsen',
    author_email='fredrik@carlsen.io',
    description='API for epguides.com',
    long_description=_read_long_description(),
    packages=find_packages(exclude=['tests', 'tests.*']),
    tests_require=read_requirements(),
    license='MIT',
    test_suite='runtests.runtests',
    include_package_data=True,
    classifiers=[
        'Programming Language :: Python :: 3',
    ]
)
