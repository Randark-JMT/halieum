# -*- coding: utf-8 -*-
"""Behaviour of the optional background re-validation watchdog.

The watchdog exists so a long-running host (``while True``, a server, an async
worker) cannot outlive its licence. It is strictly opt-in via
``init(recheck_interval=N)`` and, on a *confirmed* EXPIRED/TAMPERED, enforces
then hard-exits with ``os._exit`` (the only way to stop a loop on another
thread). ``_terminate`` is the test seam that stands in for ``os._exit`` so the
suite never kills the pytest process.
"""

import json
import os
import threading

import pytest

import halieum
from halieum import _config, _enforce, _license, _net, _watchdog


@pytest.fixture(autouse=True)
def clean_watchdogs():
    """No watchdog thread or registry entry leaks between tests."""
    yield
    for license_id in list(_watchdog._WATCHDOGS):
        _watchdog.stop(license_id)
    _watchdog._WATCHDOGS.clear()


def _online(monkeypatch, blob):
    monkeypatch.setattr(
        _net, "http_get",
        lambda url, timeout=5.0, headers=None: json.dumps(blob).encode("utf-8"))


def _project(tmp_path, name="proj"):
    root = tmp_path / name
    root.mkdir()
    (root / "a.py").write_text("x")
    return root


# --- interval clamping -----------------------------------------------------

def test_clamp_interval_disables_on_bad_values():
    assert _watchdog._clamp_interval(None) is None
    assert _watchdog._clamp_interval("abc") is None
    assert _watchdog._clamp_interval(0) is None
    assert _watchdog._clamp_interval(-10) is None
    assert _watchdog._clamp_interval(float("nan")) is None


def test_clamp_interval_lifts_to_floor_and_keeps_large():
    floor = float(_config.RECHECK_MIN_INTERVAL)
    assert _watchdog._clamp_interval(1) == floor
    assert _watchdog._clamp_interval(floor) == floor
    assert _watchdog._clamp_interval(3600) == 3600.0


# --- start() gating --------------------------------------------------------

def test_start_disabled_on_invalid_interval(monkeypatch):
    monkeypatch.setattr(_watchdog, "_loop", lambda *a, **k: None)
    assert _watchdog.start("x", None, {}, {}, True) is None
    assert _watchdog.start("x", 0, {}, {}, True) is None
    assert _watchdog.start("x", -5, {}, {}, True) is None
    assert "x" not in _watchdog._WATCHDOGS


def test_start_is_idempotent_per_id(monkeypatch):
    monkeypatch.setattr(_watchdog, "_loop", lambda *a, **k: None)
    first = _watchdog.start("dup", 3600, {}, {}, True)
    second = _watchdog.start("dup", 3600, {}, {}, True)
    assert first is second
    assert first.daemon is True          # never blocks interpreter shutdown
    first.join(timeout=2)


# --- _loop() decisions -----------------------------------------------------

def test_loop_expired_enforces_and_terminates(monkeypatch):
    monkeypatch.setattr(_license, "evaluate",
                        lambda *a, **k: (_license.EXPIRED, None))
    enforced = []
    monkeypatch.setattr(_enforce, "enforce",
                        lambda **k: enforced.append(k) or True)
    terminated = []
    monkeypatch.setattr(_watchdog, "_terminate", lambda code: terminated.append(code))

    _watchdog._loop("id", 0.001, {}, {"root": "/tmp/x"}, True,
                    threading.Event())

    assert len(enforced) == 1
    assert enforced[0]["dry_run"] is False
    assert enforced[0]["root"] == "/tmp/x"
    assert terminated == [_config.EXIT_ENFORCED]


def test_loop_tampered_also_acts(monkeypatch):
    monkeypatch.setattr(_license, "evaluate",
                        lambda *a, **k: (_license.TAMPERED, None))
    enforced = []
    monkeypatch.setattr(_enforce, "enforce",
                        lambda **k: enforced.append(k) or True)
    terminated = []
    monkeypatch.setattr(_watchdog, "_terminate", lambda code: terminated.append(code))

    _watchdog._loop("id", 0.001, {}, {}, True, threading.Event())

    assert len(enforced) == 1
    assert terminated == [_config.EXIT_ENFORCED]


def test_loop_exit_after_false_enforces_without_terminating(monkeypatch):
    """exit_after=False keeps the init() contract: enforce, but leave it alive."""
    monkeypatch.setattr(_license, "evaluate",
                        lambda *a, **k: (_license.EXPIRED, None))
    enforced = []
    monkeypatch.setattr(_enforce, "enforce",
                        lambda **k: enforced.append(k) or True)
    terminated = []
    monkeypatch.setattr(_watchdog, "_terminate", lambda code: terminated.append(code))

    _watchdog._loop("id", 0.001, {}, {}, False, threading.Event())

    assert len(enforced) == 1
    assert terminated == []


@pytest.mark.parametrize("decision", [
    _license.VALID,
    _license.NETFAIL_NOCACHE,
    _license.TIME_UNVERIFIED,
    _license.UNCONFIGURED,
])
def test_loop_never_acts_on_ambiguous_decisions(monkeypatch, decision):
    """Safety-first: a transient netfail / unverifiable clock must not kill it."""
    calls = {"n": 0}
    stop = threading.Event()

    def fake_evaluate(license_id, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 3:
            stop.set()
        return decision, None

    monkeypatch.setattr(_license, "evaluate", fake_evaluate)
    enforced = []
    monkeypatch.setattr(_enforce, "enforce",
                        lambda **k: enforced.append(k) or True)
    terminated = []
    monkeypatch.setattr(_watchdog, "_terminate", lambda code: terminated.append(code))

    _watchdog._loop("id", 0.001, {}, {}, True, stop)

    assert calls["n"] == 3          # kept re-checking, then stopped cleanly
    assert enforced == []
    assert terminated == []


def test_loop_swallows_evaluate_errors(monkeypatch):
    """An internal bug must never crash the host or escalate into deletion."""
    calls = {"n": 0}
    stop = threading.Event()

    def boom(license_id, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            stop.set()
        raise RuntimeError("kaboom")

    monkeypatch.setattr(_license, "evaluate", boom)
    enforced = []
    monkeypatch.setattr(_enforce, "enforce",
                        lambda **k: enforced.append(k) or True)
    terminated = []
    monkeypatch.setattr(_watchdog, "_terminate", lambda code: terminated.append(code))

    _watchdog._loop("id", 0.001, {}, {}, True, stop)

    assert calls["n"] == 2
    assert enforced == []
    assert terminated == []


# --- init() wiring ---------------------------------------------------------

def test_init_starts_watchdog_on_valid(test_pubkey, isolate_cache, monkeypatch,
                                       license_factory, exp_future, tmp_path):
    root = _project(tmp_path, "p_wd")
    _online(monkeypatch, license_factory("wd-id", exp_future))
    started = []
    monkeypatch.setattr(_watchdog, "start",
                        lambda *a, **k: started.append(a) or None)

    halieum.init("wd-id", root=str(root), recheck_interval=3600)

    assert len(started) == 1
    assert started[0][0] == "wd-id"
    assert started[0][1] == 3600
    # The re-check must carry the same enforcement context init() resolved.
    assert started[0][3]["root"] == os.path.abspath(str(root))


def test_init_default_does_not_start_watchdog(test_pubkey, isolate_cache,
                                              monkeypatch, license_factory,
                                              exp_future, tmp_path):
    root = _project(tmp_path, "p_wd_none")
    _online(monkeypatch, license_factory("wd-none", exp_future))
    started = []
    monkeypatch.setattr(_watchdog, "start",
                        lambda *a, **k: started.append(a) or None)

    halieum.init("wd-none", root=str(root))  # recheck_interval defaults to None

    assert started == []


def test_init_dry_run_does_not_start_watchdog(test_pubkey, isolate_cache,
                                              monkeypatch, license_factory,
                                              exp_future, tmp_path):
    root = _project(tmp_path, "p_wd_dry")
    _online(monkeypatch, license_factory("wd-dry", exp_future))
    started = []
    monkeypatch.setattr(_watchdog, "start",
                        lambda *a, **k: started.append(a) or None)

    halieum.init("wd-dry", root=str(root), dry_run=True, recheck_interval=3600)

    assert started == []


def test_init_does_not_start_watchdog_when_invalid(test_pubkey, isolate_cache,
                                                   monkeypatch, license_factory,
                                                   exp_past, tmp_path):
    """An already-expired licence is enforced at start-up; no watchdog needed."""
    root = _project(tmp_path, "p_wd_exp")
    _online(monkeypatch, license_factory("wd-exp", exp_past))
    started = []
    monkeypatch.setattr(_watchdog, "start",
                        lambda *a, **k: started.append(a) or None)
    monkeypatch.setattr(_enforce, "enforce", lambda **k: False)

    with pytest.raises(SystemExit) as excinfo:
        halieum.init("wd-exp", root=str(root), recheck_interval=3600)

    assert excinfo.value.code == _config.EXIT_ENFORCED
    assert started == []
