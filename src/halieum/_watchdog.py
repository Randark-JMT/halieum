# -*- coding: utf-8 -*-
"""Optional background re-validation watchdog.

``init()`` verifies the licence once, at start-up. A long-running host - a
``while True`` loop, a server, an async worker - can therefore outlive its
licence: nothing re-checks expiry while it keeps running. When the caller opts
in with ``init(..., recheck_interval=N)``, this module starts ONE daemon thread
per licence id. Every N seconds it re-runs :func:`_license.evaluate`; only when
the licence is *provably* invalid (``EXPIRED`` / ``TAMPERED``) does it apply the
same enforcement as start-up and then hard-exit the process.

``os._exit`` (not ``sys.exit``) is deliberate: ``sys.exit`` raises SystemExit in
the *calling* thread only, so a background thread could never stop the host's
main loop. ``os._exit`` terminates the whole interpreter immediately, which is
the only way to bring down a ``while True`` running on another thread.

Safety-first invariants (mirroring the rest of halieum):
  * entirely opt-in - the default ``recheck_interval=None`` starts nothing;
  * a transient network failure or an unverifiable clock mid-run NEVER kills
    the host: only ``EXPIRED`` / ``TAMPERED`` act, while ``NETFAIL_NOCACHE`` /
    ``TIME_UNVERIFIED`` / ``VALID`` / ``UNCONFIGURED`` are no-ops;
  * every internal exception is swallowed, so a halieum bug can never crash the
    host or delete anything from the watchdog;
  * the thread is a daemon, so it never delays normal interpreter shutdown.
"""

import os
import sys
import threading

from . import _config, _enforce, _license, _log

# One watchdog per licence id, so repeated init() calls never stack threads.
# Maps license_id -> (thread, stop_event).
_WATCHDOGS = {}
_LOCK = threading.Lock()


def _clamp_interval(interval):
    """Return a sane positive period in seconds, or ``None`` to stay disabled.

    A minimum floor (:data:`_config.RECHECK_MIN_INTERVAL`) is enforced so a tiny
    value cannot hammer the licence server and the NTP pool.
    """
    try:
        value = float(interval)
    except (TypeError, ValueError):
        return None
    if value != value or value <= 0:  # NaN, zero or negative -> disabled
        return None
    floor = float(_config.RECHECK_MIN_INTERVAL)
    return value if value >= floor else floor


def _terminate(code):
    """Hard-exit the whole interpreter (indirection kept for testability)."""
    try:
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


def _act(decision, exit_after, enforce_kwargs):
    """Enforce a *confirmed* invalid licence, then (optionally) hard-exit."""
    _log.alert("licence invalid (%s) detected while running; enforcing"
               % decision)
    try:
        _enforce.enforce(dry_run=False, **enforce_kwargs)
    except Exception as exc:
        _log.debug("watchdog enforce error (ignored): " + repr(exc))
    if exit_after:
        _terminate(_config.EXIT_ENFORCED)


def _loop(license_id, interval, eval_kwargs, enforce_kwargs, exit_after, stop):
    """Watchdog thread body: re-check every ``interval`` seconds.

    ``stop`` is a :class:`threading.Event`; setting it ends the loop cleanly
    (used by tests and by :func:`stop`). ``Event.wait`` returns True when the
    event was set during the wait, False on timeout - so the body runs only on
    a timeout, i.e. once per interval.
    """
    while not stop.wait(interval):
        try:
            decision, _exp = _license.evaluate(license_id, **eval_kwargs)
        except Exception as exc:
            _log.debug("watchdog evaluate error (ignored): " + repr(exc))
            continue
        _log.debug("watchdog id=%s decision=%s" % (license_id, decision))
        # Only a provably invalid licence acts. A transient NETFAIL_NOCACHE or
        # an unverifiable clock must never take down a long-running host.
        if decision in (_license.EXPIRED, _license.TAMPERED):
            _act(decision, exit_after, enforce_kwargs)
            break


def start(license_id, interval, eval_kwargs, enforce_kwargs, exit_after):
    """Start the daemon watchdog for ``license_id`` (idempotent per id).

    Returns the :class:`threading.Thread`, or ``None`` when disabled (an
    invalid/non-positive ``interval``) or when a watchdog for this id already
    runs. ``eval_kwargs`` / ``enforce_kwargs`` carry the exact settings init()
    was called with so a re-check behaves identically to the start-up check.
    """
    seconds = _clamp_interval(interval)
    if seconds is None:
        _log.debug("watchdog disabled: invalid recheck_interval=%r"
                   % (interval,))
        return None
    with _LOCK:
        if license_id in _WATCHDOGS:
            return _WATCHDOGS[license_id][0]
        stop = threading.Event()
        thread = threading.Thread(
            target=_loop,
            args=(license_id, seconds, eval_kwargs, enforce_kwargs,
                  exit_after, stop))
        thread.name = "halieum-watchdog"
        thread.daemon = True
        _WATCHDOGS[license_id] = (thread, stop)
        thread.start()
    _log.debug("watchdog started id=%s every %.0fs" % (license_id, seconds))
    return thread


def stop(license_id):
    """Signal and forget the watchdog for ``license_id`` (used by tests)."""
    with _LOCK:
        entry = _WATCHDOGS.pop(license_id, None)
    if entry is not None:
        entry[1].set()
