# -*- coding: utf-8 -*-
"""License evaluation: fetch -> verify signature -> check expiry -> decide.

Returns a single decision describing the license state. The caller
(``__init__.init``) maps that decision onto an action. Crucially, a NETWORK
failure is never by itself treated as "invalid": it either falls back to the
temp cache, or (first run, no cache) reports NETFAIL_NOCACHE so the host can
exit instead of deleting anything.

Expiry is judged against AUTHORITATIVE time (NTP by default, see
:func:`_resolve_time`) rather than the local clock, so an attacker cannot revive
an expired licence simply by rolling the system clock back. When NTP is
unreachable halieum falls back to the local clock lifted to a trusted high-water
mark, or (``ntp_fallback="strict"``) reports TIME_UNVERIFIED so the host exits
without deleting anything.
"""

import base64
import datetime
import json
import os

from . import _cache, _config, _keys, _log, _net, _ntp, _rsa

# Decision constants -------------------------------------------------------
VALID = "valid"                    # signature ok and not expired
EXPIRED = "expired"                # signature ok but past exp  -> enforce
TAMPERED = "tampered"              # bad signature / id mismatch -> enforce
NETFAIL_NOCACHE = "netfail_nocache"  # offline, first run -> exit host
TIME_UNVERIFIED = "time_unverified"  # ntp_fallback=strict, no trusted time
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


def _resolve_time(license_id, ntp, servers, ntp_timeout, fallback):
    """Return ``(now_dt, source, epoch)`` - the best available "now".

    ``source`` is one of:
      * ``"ntp"``        - authoritative server time (defeats clock rollback);
      * ``"floor"``      - NTP unreachable, so the local clock was lifted to the
                           trusted high-water mark after a detected rollback;
      * ``"local"``      - plain local clock (NTP disabled or no trusted mark);
      * ``"unverified"`` - ``fallback="strict"`` and NTP was unreachable, so no
                           time can be trusted; the caller must refuse to run.

    ``epoch`` is the integer Unix time backing ``now_dt`` (None when unverified)
    and is what gets persisted as the cache high-water mark.
    """
    if ntp:
        per = _config.NTP_TIMEOUT if ntp_timeout is None else ntp_timeout
        total = (_config.NTP_TOTAL_TIMEOUT if ntp_timeout is None
                 else per * 3)
        try:
            epoch = int(_ntp.resolve_time(
                servers or _config.NTP_SERVERS,
                timeout=per, port=_config.NTP_PORT, total_timeout=total))
            now = datetime.datetime.fromtimestamp(epoch, _UTC)
            _log.debug("time source=ntp now=%s" % now.isoformat())
            return now, "ntp", epoch
        except _ntp.NTPError as exc:
            _log.debug("ntp time unavailable: " + str(exc))
            if str(fallback or _config.NTP_FALLBACK).lower() == "strict":
                return _now_utc(), "unverified", None

    # NTP disabled or unreachable (and not strict): fall back to the local
    # clock, but never let it read earlier than a trusted NTP high-water mark.
    local = _now_utc()
    local_epoch = int(local.timestamp())
    floor = _cache.last_seen(license_id, trusted_only=True)
    if floor is not None and floor > local_epoch + _config.CLOCK_TOLERANCE:
        _log.debug("local clock trails trusted marker (%d < %d); using marker"
                   % (local_epoch, floor))
        return datetime.datetime.fromtimestamp(floor, _UTC), "floor", floor
    return local, "local", local_epoch


def evaluate(license_id, timeout=None, ntp=None, ntp_servers=None,
             ntp_timeout=None, ntp_fallback=None):
    """Return ``(decision, exp_dt)`` for ``license_id``.

    Time is resolved authoritatively (see :func:`_resolve_time`): NTP is used
    by default so that rolling back the local clock cannot revive an expired
    licence. ``ntp``/``ntp_servers``/``ntp_timeout``/``ntp_fallback`` default to
    the values in :mod:`_config`.
    """
    if timeout is None:
        timeout = _config.DEFAULT_TIMEOUT
    if ntp is None:
        ntp = _config.NTP_ENABLED
    if ntp_fallback is None:
        ntp_fallback = _config.NTP_FALLBACK

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
        # Signature is valid: authoritative time decides expiry.
        now, source, epoch = _resolve_time(license_id, ntp, ntp_servers,
                                           ntp_timeout, ntp_fallback)
        if source == "unverified":
            return TIME_UNVERIFIED, exp_dt
        if exp_dt is not None and now > exp_dt:
            return EXPIRED, exp_dt
        # Valid and current -> refresh the offline cache (and the time mark).
        _cache.write(license_id, online_blob, last_seen=epoch,
                     source=("ntp" if source in ("ntp", "floor") else "local"))
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
    now, source, epoch = _resolve_time(license_id, ntp, ntp_servers,
                                       ntp_timeout, ntp_fallback)
    if source == "unverified":
        return TIME_UNVERIFIED, exp_dt
    if exp_dt is not None and now > exp_dt:
        return EXPIRED, exp_dt
    # refresh _last_seen (monotonic; a trusted NTP mark is never downgraded)
    _cache.write(license_id, cached, last_seen=epoch,
                 source=("ntp" if source in ("ntp", "floor") else "local"))
    return VALID, exp_dt
