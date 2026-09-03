# -*- coding: utf-8 -*-
"""Offline fallback cache stored in the OS temp directory.

After the FIRST successful online verification the license blob is written
here. On later runs, if the network is unavailable, this cache is used to
decide validity. The cached blob still carries the RSA signature, so it cannot
be forged without the private key, and its ``exp`` is still honoured.

A ``_last_seen`` timestamp is stored alongside so callers can (optionally)
notice clock tampering. Cache filenames are derived from a hash of the license
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


def write(license_id, blob):
    """Persist ``blob`` for ``license_id``. Best-effort; returns success bool."""
    try:
        path = _cache_path(license_id)
        data = dict(blob)
        data["_last_seen"] = int(time.time())
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


def last_seen(license_id):
    """Return the stored ``_last_seen`` epoch seconds, or None."""
    blob = read(license_id)
    if blob:
        value = blob.get("_last_seen")
        if isinstance(value, int):
            return value
    return None
