#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Minimal shim for legacy tooling.

All real packaging metadata lives in ``pyproject.toml``. This file only exists
so older ``pip``/``setup.py``-based workflows (and editable installs on legacy
setuptools) keep functioning.
"""

from setuptools import setup

setup()
