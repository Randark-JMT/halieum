# -*- coding: utf-8 -*-
"""License evaluation: fetch -> verify signature -> check expiry -> decide.

Returns a single decision describing the license state. The caller
(``__init__.init``) maps that decision onto an action. Crucially, a NETWORK
failure is never by itself treated as "invalid": it either falls back to the
temp cache, or (first run, no cache) reports NETFAIL_NOCACHE so the host can
exit instead of deleting anything.
"""

import base64
import datetime
import json
import os

from . import _cache, _config, _keys, _log, _net, _rsa

# Decision constants -------------------------------------------------------
VALID = "valid"                    # signature ok and not expired
EXPIRED = "expired"                # signature ok but past exp  -> enforce
TAMPERED = "tampered"              # bad signature / id mismatch -> enforce
NETFAIL_NOCACHE = "netfail_nocache"  # offline, first run -> exit host
UNCONFIGURED = "unconfigured"      # no usable public key -> safe no-op

_UTC = datetime.timezone.utc


def _now_utc():
    # datetime.now(tz) is used instead of the deprecated utcnow().
    return datetime.datetime.now(_UTC)


def _parse_exp(exp):
    """Parse the canonical ``YYYY-MM-DDTHH:MM:SSZ`` form (all-version safe)."""
    try:
        dt = datetime.datetime.strptime(exp, "%Y-%m-%dT%H:%M:%SZ")
        return dt.replace(tzinfo=_UTC)
    except Exception:
        return None


def canonical_message(license_id, exp):
    """Bytes that BOTH the Action signs and this package verifies.

    Must stay byte-for-byte identical to ``tools/sign_license.py``.
    """
    return (
        b"halieum|v=1|id=" + license_id.encode("utf-8") +
        b"|exp=" + exp.encode("utf-8")
    )


def _public_key(kid):
    key = _keys.PUBKEYS.get(kid) or _keys.PUBKEYS.get(_keys.DEFAULT_KID)
    if not key:
        return None
    try:
        n, e = key
    except Exception:
        return None
    if not isinstance(n, int) or n <= 0:
        return None
    return (n, e)


def _verify_blob(blob, expected_id):
    """Return (status, exp_dt).

    status is one of TAMPERED / UNCONFIGURED / VALID. When VALID, ``exp_dt``
    is the parsed expiry (the caller decides whether it has passed).
    """
    try:
        if not isinstance(blob, dict) or blob.get("v") != 1:
            return TAMPERED, None
        blob_id = blob.get("id")
        exp = blob.get("exp")
        sig_b64 = blob.get("sig")
        kid = blob.get("kid", _keys.DEFAULT_KID)

        if blob_id != expected_id:
            return TAMPERED, None
        if not isinstance(exp, str) or not isinstance(sig_b64, str):
            return TAMPERED, None

        key = _public_key(kid)
        if key is None:
            return UNCONFIGURED, None
        n, e = key

        try:
            signature = base64.b64decode(sig_b64)
        except Exception:
            return TAMPERED, None

        if not _rsa.verify_pkcs1v15_sha256(n, e, canonical_message(blob_id, exp),
                                           signature):
            return TAMPERED, None

        exp_dt = _parse_exp(exp)
        if exp_dt is None:
            return TAMPERED, None
        return VALID, exp_dt
    except Exception:
        return TAMPERED, None


def _resolve_url(license_id):
    base = os.environ.get(_config.BASE_ENV_VAR, _config.DEFAULT_BASE)
    if not base.endswith("/"):
        base += "/"
    return base + _config.LICENSE_PATH.format(id=license_id)


def _fetch_online(license_id, timeout):
    url = _resolve_url(license_id)
    _log.debug("fetching " + url)
    raw = _net.http_get(url, timeout=timeout)
    blob = json.loads(raw.decode("utf-8"))
    if not isinstance(blob, dict):
        raise _net.NetError("malformed license payload")
    return blob


def evaluate(license_id, timeout=None):
    """Return ``(decision, exp_dt)`` for ``license_id``."""
    if timeout is None:
        timeout = _config.DEFAULT_TIMEOUT

    # 1) Try the network first.
    online_blob = None
    online = False
    try:
        online_blob = _fetch_online(license_id, timeout)
        online = True
    except _net.NetError as exc:
        _log.debug("online fetch failed: " + str(exc))
    except Exception as exc:
        _log.debug("online fetch error: " + repr(exc))

    if online:
        status, exp_dt = _verify_blob(online_blob, license_id)
        if status == UNCONFIGURED:
            return UNCONFIGURED, None
        if status == TAMPERED:
            return TAMPERED, None
        # Signature is valid: expiry decides.
        if exp_dt is not None and _now_utc() > exp_dt:
            return EXPIRED, exp_dt
        # Valid and current -> refresh the offline cache.
        _cache.write(license_id, online_blob)
        return VALID, exp_dt

    # 2) Offline: fall back to the cache written by a previous success.
    cached = _cache.read(license_id)
    if not cached:
        return NETFAIL_NOCACHE, None

    status, exp_dt = _verify_blob(cached, license_id)
    if status == UNCONFIGURED:
        return UNCONFIGURED, None
    if status == TAMPERED:
        return TAMPERED, None
    if exp_dt is not None and _now_utc() > exp_dt:
        return EXPIRED, exp_dt
    _cache.write(license_id, cached)  # refresh _last_seen
    return VALID, exp_dt
