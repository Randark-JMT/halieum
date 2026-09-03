# -*- coding: utf-8 -*-
"""Tests for the license decision engine (fetch / verify / cache / decide)."""

import json

from halieum import _cache, _keys, _license, _net

ZERO_SIG = b"\x00" * 128  # matches the 1024-bit throwaway test key


def _online(monkeypatch, blob):
    monkeypatch.setattr(
        _net, "http_get",
        lambda url, timeout=5.0, headers=None: json.dumps(blob).encode("utf-8"))


def _offline(monkeypatch):
    def _raise(url, timeout=5.0, headers=None):
        raise _net.NetError("offline")
    monkeypatch.setattr(_net, "http_get", _raise)


def test_online_valid_caches(test_pubkey, isolate_cache, monkeypatch,
                             license_factory, exp_future):
    _online(monkeypatch, license_factory("demo", exp_future))
    decision, _ = _license.evaluate("demo")
    assert decision == _license.VALID
    assert _cache.read("demo") is not None


def test_online_expired(test_pubkey, isolate_cache, monkeypatch,
                        license_factory, exp_past):
    _online(monkeypatch, license_factory("demo-exp", exp_past))
    decision, _ = _license.evaluate("demo-exp")
    assert decision == _license.EXPIRED
    assert _cache.read("demo-exp") is None  # never cache an expired license


def test_online_tampered_signature(test_pubkey, isolate_cache, monkeypatch,
                                   license_factory, exp_future):
    _online(monkeypatch, license_factory("demo-t", exp_future, sig=ZERO_SIG))
    decision, _ = _license.evaluate("demo-t")
    assert decision == _license.TAMPERED


def test_online_id_mismatch(test_pubkey, isolate_cache, monkeypatch,
                            license_factory, exp_future):
    _online(monkeypatch, license_factory("real-id", exp_future))
    decision, _ = _license.evaluate("other-id")
    assert decision == _license.TAMPERED


def test_unconfigured_key_is_inert(isolate_cache, monkeypatch,
                                   license_factory, exp_future):
    # Explicitly simulate the "unconfigured" placeholder (n == 0) so this test
    # is independent of whether a real key has been generated into _keys.py.
    monkeypatch.setattr(_keys, "PUBKEYS", {"k1": (0, 65537)})
    _online(monkeypatch, license_factory("demo-u", exp_future))
    decision, _ = _license.evaluate("demo-u")
    assert decision == _license.UNCONFIGURED


def test_netfail_without_cache(test_pubkey, isolate_cache, monkeypatch):
    _offline(monkeypatch)
    decision, _ = _license.evaluate("never-cached")
    assert decision == _license.NETFAIL_NOCACHE


def test_offline_uses_valid_cache(test_pubkey, isolate_cache, monkeypatch,
                                  license_factory, exp_future):
    _cache.write("demo-c", license_factory("demo-c", exp_future))
    _offline(monkeypatch)
    decision, _ = _license.evaluate("demo-c")
    assert decision == _license.VALID


def test_offline_expired_cache(test_pubkey, isolate_cache, monkeypatch,
                               license_factory, exp_past):
    _cache.write("demo-ce", license_factory("demo-ce", exp_past))
    _offline(monkeypatch)
    decision, _ = _license.evaluate("demo-ce")
    assert decision == _license.EXPIRED


def test_offline_tampered_cache(test_pubkey, isolate_cache, monkeypatch,
                                license_factory, exp_future):
    _cache.write("demo-ct", license_factory("demo-ct", exp_future, sig=ZERO_SIG))
    _offline(monkeypatch)
    decision, _ = _license.evaluate("demo-ct")
    assert decision == _license.TAMPERED
