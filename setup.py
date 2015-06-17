# -*- coding: utf8 -*-
from setuptools import setup, find_packages


def _read_long_description():
    try:
        import pypandoc
        return pypandoc.convert('README.md', 'rst', format='markdown')
    except Exception:
        return None

setup(
    name="epguides-api",
    version='1.0.1',
    url='http://github.com/frecar/epguides-api',
    author='Fredrik Carlsen',
    author_email='fredrik@carlsen.io',
    description='API for epguides.com',
    long_description=_read_long_description(),
    packages=find_packages(exclude='tests'),
    tests_require=[
        'flask',
        'flask-cache',
        'redis',
        'flake8',
        'coverage',
        'tox'
    ],

    license='MIT',
    test_suite='runtests.runtests',
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python",
        'Programming Language :: Python :: 2.7',
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Framework :: Flask",
        "Environment :: Web Environment",
        "Operating System :: OS Independent",
        "Natural Language :: English",
    ]
)
