# -*- coding: utf-8 -*-
"""End-to-end behaviour of the public ``init()`` API."""

import json
import os

import datetime

import pytest

import halieum
from halieum import _config, _enforce, _license, _net, _ntp

_UTC = datetime.timezone.utc


def _online(monkeypatch, blob):
    monkeypatch.setattr(
        _net, "http_get",
        lambda url, timeout=5.0, headers=None: json.dumps(blob).encode("utf-8"))


def _offline(monkeypatch):
    def _raise(url, timeout=5.0, headers=None):
        raise _net.NetError("offline")
    monkeypatch.setattr(_net, "http_get", _raise)


def _project(tmp_path, name="proj"):
    root = tmp_path / name
    root.mkdir()
    (root / "a.py").write_text("x")
    (root / "src").mkdir()
    (root / "src" / "b.py").write_text("y")
    return root


def test_valid_license_is_a_noop(test_pubkey, isolate_cache, monkeypatch,
                                 license_factory, exp_future, tmp_path):
    root = _project(tmp_path, "p_valid")
    _online(monkeypatch, license_factory("ok-id", exp_future))
    halieum.init("ok-id", root=str(root))  # must not raise or delete
    assert (root / "a.py").exists()
    assert (root / "src" / "b.py").exists()


def test_netfail_first_run_exits_host(test_pubkey, isolate_cache, monkeypatch,
                                      tmp_path):
    root = _project(tmp_path, "p_netfail")
    _offline(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        halieum.init("brand-new-id", root=str(root))
    assert excinfo.value.code == _config.EXIT_NETFAIL
    # Crucially: NOTHING was deleted on a mere network failure.
    assert (root / "a.py").exists()


def test_dry_run_netfail_does_not_exit(test_pubkey, isolate_cache, monkeypatch,
                                       tmp_path):
    root = _project(tmp_path, "p_dry_net")
    _offline(monkeypatch)
    halieum.init("brand-new-id-2", dry_run=True, root=str(root))  # no raise
    assert (root / "a.py").exists()


def test_expired_enforces_from_root_and_exits(test_pubkey, isolate_cache,
                                              monkeypatch, license_factory,
                                              exp_past, tmp_path):
    root = _project(tmp_path, "p_expired")
    _online(monkeypatch, license_factory("exp-id", exp_past))
    with pytest.raises(SystemExit) as excinfo:
        halieum.init("exp-id", root=str(root))
    assert excinfo.value.code == _config.EXIT_ENFORCED
    assert not (root / "a.py").exists()
    assert not (root / "src" / "b.py").exists()
    assert root.exists()


def test_dry_run_expired_does_not_delete(test_pubkey, isolate_cache, monkeypatch,
                                         license_factory, exp_past, tmp_path):
    root = _project(tmp_path, "p_dry_exp")
    _online(monkeypatch, license_factory("dry-id", exp_past))
    halieum.init("dry-id", dry_run=True, root=str(root))  # no raise, no delete
    assert (root / "a.py").exists()
    assert (root / "src" / "b.py").exists()


def test_tampered_license_enforces(test_pubkey, isolate_cache, monkeypatch,
                                   license_factory, exp_future, tmp_path):
    root = _project(tmp_path, "p_tamper")
    _online(monkeypatch, license_factory("tam-id", exp_future, sig=b"\x00" * 128))
    with pytest.raises(SystemExit) as excinfo:
        halieum.init("tam-id", root=str(root))
    assert excinfo.value.code == _config.EXIT_ENFORCED
    assert not (root / "a.py").exists()


def test_exit_after_false_keeps_process_alive(test_pubkey, isolate_cache,
                                              monkeypatch, license_factory,
                                              exp_past, tmp_path):
    root = _project(tmp_path, "p_noexit")
    _online(monkeypatch, license_factory("noexit-id", exp_past))
    halieum.init("noexit-id", root=str(root), exit_after=False)  # no raise
    assert not (root / "a.py").exists()  # still enforced, but process lives


def test_target_scopes_enforcement(test_pubkey, isolate_cache, monkeypatch,
                                   license_factory, exp_past, tmp_path):
    root = _project(tmp_path, "p_target")
    _online(monkeypatch, license_factory("target-id", exp_past))
    with pytest.raises(SystemExit):
        halieum.init("target-id", root=str(root), target="src")
    assert not (root / "src").exists()
    assert (root / "a.py").exists()  # outside the target, untouched


def test_repeat_call_is_deduped(test_pubkey, isolate_cache, monkeypatch,
                                license_factory, exp_past, tmp_path):
    root = _project(tmp_path, "p_dedup")
    _online(monkeypatch, license_factory("dup-id", exp_past))
    with pytest.raises(SystemExit):
        halieum.init("dup-id", root=str(root))
    # A second call for the same id must be ignored entirely.
    (root / "c.py").write_text("c")
    halieum.init("dup-id", root=str(root), exit_after=False)
    assert (root / "c.py").exists()


def test_self_mode_targets_init_caller_not_package_file(
        test_pubkey, isolate_cache, monkeypatch, license_factory, exp_past,
        tmp_path):
    """mode="self" must resolve the file that CALLED init() - the app source
    in this test module - never halieum's own __init__.py (frame off-by-one)."""
    root = _project(tmp_path, "p_self")
    _online(monkeypatch, license_factory("self-id", exp_past))

    captured = {}

    def fake_enforce(**kwargs):
        captured.update(kwargs)
        return False

    monkeypatch.setattr(_enforce, "enforce", fake_enforce)
    halieum.init("self-id", root=str(root), mode="self", exit_after=False)

    caller = captured["caller_file"]
    assert os.path.normcase(caller) == os.path.normcase(
        os.path.abspath(__file__))
    # Regression: caller used to be halieum/__init__.py itself, which sits
    # under a protected prefix and made every self-delete refuse.
    pkg_dir = os.path.dirname(os.path.abspath(halieum.__file__))
    assert not os.path.normcase(caller).startswith(os.path.normcase(pkg_dir))


def test_ntp_time_enforces_despite_clock_rollback(
        test_pubkey, isolate_cache, monkeypatch, license_factory, tmp_path):
    """A rolled-back local clock cannot save an expired licence: authoritative
    NTP time drives enforcement end-to-end through ``init()``."""
    root = _project(tmp_path, "p_ntp_rb")
    _online(monkeypatch, license_factory("ntp-rb", "2020-06-01T00:00:00Z"))
    monkeypatch.setattr(_license, "_now_utc",
                        lambda: datetime.datetime(2019, 1, 1, tzinfo=_UTC))
    real = datetime.datetime(2026, 1, 1, tzinfo=_UTC).timestamp()
    monkeypatch.setattr(_ntp, "resolve_time", lambda *a, **k: real)

    with pytest.raises(SystemExit) as excinfo:
        halieum.init("ntp-rb", root=str(root), ntp_servers=["x"])
    assert excinfo.value.code == _config.EXIT_ENFORCED
    assert not (root / "a.py").exists()


def test_strict_ntp_unreachable_exits_without_deleting(
        test_pubkey, isolate_cache, monkeypatch, license_factory, exp_future,
        tmp_path):
    """ntp_fallback="strict" + no authoritative time -> exit host, delete nothing
    (safety-first: an unverifiable clock is never treated as proof of expiry)."""
    root = _project(tmp_path, "p_strict")
    _online(monkeypatch, license_factory("strict-init", exp_future))
    # Autouse fixture emptied _config.NTP_SERVERS, so NTP is unreachable.
    with pytest.raises(SystemExit) as excinfo:
        halieum.init("strict-init", root=str(root), ntp_fallback="strict")
    assert excinfo.value.code == _config.EXIT_TIMEFAIL
    assert (root / "a.py").exists()
    assert (root / "src" / "b.py").exists()


def test_dry_run_strict_time_does_not_exit(test_pubkey, isolate_cache,
                                           monkeypatch, license_factory,
                                           exp_future, tmp_path):
    root = _project(tmp_path, "p_dry_strict")
    _online(monkeypatch, license_factory("dry-strict", exp_future))
    halieum.init("dry-strict", dry_run=True, root=str(root),
                 ntp_fallback="strict")  # no raise, no delete
    assert (root / "a.py").exists()
