# -*- coding: utf-8 -*-
"""Tests for the license decision engine (fetch / verify / cache / decide)."""

import datetime
import json

from halieum import _cache, _keys, _license, _net, _ntp

ZERO_SIG = b"\x00" * 128  # matches the 1024-bit throwaway test key
_UTC = datetime.timezone.utc


def _online(monkeypatch, blob):
    monkeypatch.setattr(
        _net, "http_get",
        lambda url, timeout=5.0, headers=None: json.dumps(blob).encode("utf-8"))


def _offline(monkeypatch):
    def _raise(url, timeout=5.0, headers=None):
        raise _net.NetError("offline")
    monkeypatch.setattr(_net, "http_get", _raise)


def _freeze_local(monkeypatch, dt):
    """Pin the local clock (simulates a user tampering with system time)."""
    monkeypatch.setattr(_license, "_now_utc", lambda: dt)


def _ntp_time(monkeypatch, epoch):
    """Make authoritative NTP resolution return a fixed Unix time."""
    monkeypatch.setattr(_ntp, "resolve_time", lambda *a, **k: epoch)


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


# --- NTP / clock-tampering -------------------------------------------------

def test_ntp_time_exposes_clock_rollback(test_pubkey, isolate_cache,
                                         monkeypatch, license_factory):
    """The headline fix: a rolled-back local clock no longer revives a licence
    that has really expired, because NTP supplies the true current time."""
    exp = "2020-06-01T00:00:00Z"  # long past in real time
    _online(monkeypatch, license_factory("rb", exp))
    _freeze_local(monkeypatch, datetime.datetime(2019, 1, 1, tzinfo=_UTC))
    _ntp_time(monkeypatch, datetime.datetime(2026, 1, 1, tzinfo=_UTC).timestamp())
    decision, _ = _license.evaluate("rb", ntp=True, ntp_servers=["x"])
    assert decision == _license.EXPIRED


def test_clock_rollback_bypasses_only_when_ntp_disabled(
        test_pubkey, isolate_cache, monkeypatch, license_factory):
    """With ``ntp=False`` there is no authoritative time, so the legacy hole
    remains - this documents exactly what ``ntp=True`` (default) closes."""
    exp = "2020-06-01T00:00:00Z"
    _online(monkeypatch, license_factory("rb-off", exp))
    _freeze_local(monkeypatch, datetime.datetime(2019, 1, 1, tzinfo=_UTC))
    decision, _ = _license.evaluate("rb-off", ntp=False)
    assert decision == _license.VALID


def test_ntp_time_before_expiry_is_valid(test_pubkey, isolate_cache,
                                         monkeypatch, license_factory):
    """A wrongly fast local clock must not cause a false expiry: NTP wins."""
    exp = "2030-01-01T00:00:00Z"
    _online(monkeypatch, license_factory("fut", exp))
    _freeze_local(monkeypatch, datetime.datetime(2099, 1, 1, tzinfo=_UTC))
    _ntp_time(monkeypatch, datetime.datetime(2026, 1, 1, tzinfo=_UTC).timestamp())
    decision, _ = _license.evaluate("fut", ntp=True, ntp_servers=["x"])
    assert decision == _license.VALID


def test_ntp_success_records_trusted_marker(test_pubkey, isolate_cache,
                                           monkeypatch, license_factory):
    exp = "2030-01-01T00:00:00Z"
    _online(monkeypatch, license_factory("mark", exp))
    epoch = int(datetime.datetime(2026, 1, 1, tzinfo=_UTC).timestamp())
    _ntp_time(monkeypatch, epoch)
    decision, _ = _license.evaluate("mark", ntp=True, ntp_servers=["x"])
    assert decision == _license.VALID
    assert _cache.last_seen("mark", trusted_only=True) == epoch
    assert _cache.read("mark")["_last_seen_src"] == "ntp"


def test_strict_fallback_reports_unverified_when_ntp_unreachable(
        test_pubkey, isolate_cache, monkeypatch, license_factory, exp_future):
    # The autouse fixture emptied NTP_SERVERS, so resolution fails -> strict.
    _online(monkeypatch, license_factory("strict", exp_future))
    decision, _ = _license.evaluate("strict", ntp=True, ntp_fallback="strict")
    assert decision == _license.TIME_UNVERIFIED


def test_offline_rollback_lifted_to_trusted_marker(
        test_pubkey, isolate_cache, monkeypatch, license_factory):
    """Offline + rolled-back clock: a trusted NTP high-water mark still lifts
    "now" past the expiry so the rollback is caught."""
    exp = "2020-06-01T00:00:00Z"
    trusted = int(datetime.datetime(2021, 1, 1, tzinfo=_UTC).timestamp())
    _cache.write("floor", license_factory("floor", exp),
                 last_seen=trusted, source="ntp")
    _offline(monkeypatch)
    _freeze_local(monkeypatch, datetime.datetime(2019, 1, 1, tzinfo=_UTC))
    decision, _ = _license.evaluate("floor", ntp=True)
    assert decision == _license.EXPIRED


def test_untrusted_local_marker_never_causes_false_expiry(
        test_pubkey, isolate_cache, monkeypatch, license_factory):
    """A LOCAL (untrusted) marker far in the future must not become a floor,
    otherwise a one-off forward clock jump would wrongly expire a licence."""
    exp = "2020-06-01T00:00:00Z"
    bogus = int(datetime.datetime(2099, 1, 1, tzinfo=_UTC).timestamp())
    _cache.write("lfloor", license_factory("lfloor", exp),
                 last_seen=bogus, source="local")
    _offline(monkeypatch)
    _freeze_local(monkeypatch, datetime.datetime(2019, 1, 1, tzinfo=_UTC))
    decision, _ = _license.evaluate("lfloor", ntp=True)
    assert decision == _license.VALID
