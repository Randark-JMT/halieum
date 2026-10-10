# -*- coding: utf-8 -*-
"""Offline fallback cache stored in the OS temp directory.

After the FIRST successful online verification the license blob is written
here. On later runs, if the network is unavailable, this cache is used to
decide validity. The cached blob still carries the RSA signature, so it cannot
be forged without the private key, and its ``exp`` is still honoured.

A ``_last_seen`` timestamp is stored alongside so callers can notice clock
tampering: it is a high-water mark of the latest instant the licence was known
good, tagged with its ``_last_seen_src`` (``"ntp"`` when it came from an
authoritative server, else ``"local"``). The marker never regresses and a
trusted NTP value is never overwritten by a local reading, so a rolled-back
clock cannot lower it. Cache filenames are derived from a hash of the license
id and use a non-obvious prefix.
"""

import hashlib
import json
import os
import tempfile
import time

from . import _config


def cache_dir():
    """Temp dir used for the cache (overridable for tests)."""
    override = os.environ.get(_config.CACHE_ENV_VAR)
    if override:
        return override
    return tempfile.gettempdir()


def _cache_path(license_id):
    digest = hashlib.sha256(("halieum|" + license_id).encode("utf-8")).hexdigest()
    name = _config.CACHE_PREFIX + digest[:32] + ".dat"
    return os.path.join(cache_dir(), name)


def read(license_id):
    """Return the cached license blob (dict) or None if absent/corrupt."""
    try:
        path = _cache_path(license_id)
        with open(path, "rb") as handle:
            raw = handle.read()
        obj = json.loads(raw.decode("utf-8"))
        if isinstance(obj, dict):
            return obj
        return None
    except Exception:
        return None


def write(license_id, blob, last_seen=None, source="local"):
    """Persist ``blob`` for ``license_id``. Best-effort; returns success bool.

    ``last_seen`` (epoch seconds) records when the licence was last known good
    and ``source`` marks whether that instant came from ``"ntp"`` (trusted) or
    the ``"local"`` clock. The stored marker is monotonic and source-aware: an
    NTP reading keeps the highest NTP value seen, while a local reading can
    never downgrade a previously trusted NTP marker. This keeps the high-water
    mark used for rollback detection honest.
    """
    try:
        path = _cache_path(license_id)
        data = dict(blob)

        if last_seen is None:
            last_seen = int(time.time())
        last_seen = int(last_seen)

        prev = data.get("_last_seen")
        prev_src = data.get("_last_seen_src")
        if not isinstance(prev, int):
            prev = None

        if source == "ntp":
            # Authoritative: retain the highest NTP-observed instant.
            if prev_src == "ntp" and prev is not None and prev > last_seen:
                last_seen = prev
            data["_last_seen"] = last_seen
            data["_last_seen_src"] = "ntp"
        elif prev_src == "ntp" and prev is not None:
            # Never downgrade a trusted NTP marker with a local reading.
            data["_last_seen"] = prev
            data["_last_seen_src"] = "ntp"
        else:
            if prev is not None and prev > last_seen:
                last_seen = prev
            data["_last_seen"] = last_seen
            data["_last_seen_src"] = "local"

        payload = json.dumps(data).encode("utf-8")

        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)

        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(payload)
        # os.replace is atomic on Py3.3+; fall back for older interpreters.
        try:
            os.replace(tmp, path)
        except AttributeError:  # pragma: no cover
            if os.path.exists(path):
                os.remove(path)
            os.rename(tmp, path)
        return True
    except Exception:
        return False


def last_seen(license_id, trusted_only=False):
    """Return the stored ``_last_seen`` epoch seconds, or None.

    With ``trusted_only`` the value is returned only when it was recorded from
    an authoritative NTP reading - the only marker safe to treat as a
    tamper-proof floor for the current time.
    """
    blob = read(license_id)
    if blob:
        value = blob.get("_last_seen")
        if isinstance(value, int):
            if trusted_only and blob.get("_last_seen_src") != "ntp":
                return None
            return value
    return None
