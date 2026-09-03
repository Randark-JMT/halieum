# -*- coding: utf-8 -*-
"""Tests for the temp-dir offline cache."""

import os

from halieum import _cache


def test_write_read_roundtrip(isolate_cache, license_factory, exp_future):
    blob = license_factory("cache-demo", exp_future)
    assert _cache.write("cache-demo", blob) is True
    got = _cache.read("cache-demo")
    assert got["id"] == "cache-demo"
    assert got["exp"] == exp_future
    assert got["sig"] == blob["sig"]
    assert isinstance(got["_last_seen"], int)


def test_read_missing(isolate_cache):
    assert _cache.read("does-not-exist") is None


def test_read_corrupt(isolate_cache):
    path = _cache._cache_path("corrupt-id")
    with open(path, "wb") as handle:
        handle.write(b"{ this is not valid json")
    assert _cache.read("corrupt-id") is None


def test_cache_dir_override(isolate_cache):
    assert _cache.cache_dir() == isolate_cache
    assert _cache._cache_path("x").startswith(isolate_cache + os.sep)


def test_last_seen(isolate_cache, license_factory, exp_future):
    _cache.write("ls-demo", license_factory("ls-demo", exp_future))
    assert isinstance(_cache.last_seen("ls-demo"), int)
    assert _cache.last_seen("absent") is None
