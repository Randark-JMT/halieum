# -*- coding: utf-8 -*-
"""Minimal HTTP GET over the standard library.

``urllib.request`` on Python 3, with a best-effort ``urllib2`` fallback so the
module still imports on ancient interpreters. Every failure mode is normalised
into :class:`NetError` so callers can distinguish "network unavailable" from
"license is provably invalid".
"""

import socket

try:  # Python 3
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:  # pragma: no cover - Python 2 fallback
    from urllib2 import Request, urlopen, HTTPError, URLError  # noqa: F401


class NetError(Exception):
    """Raised for any network / transport level failure."""


def http_get(url, timeout=5.0, headers=None):
    """Fetch ``url`` and return the raw body bytes.

    Raises :class:`NetError` on timeout, DNS failure, connection refusal,
    non-2xx status, TLS problems, etc. TLS verification is intentionally left
    ENABLED (never disabled) so a license cannot be spoofed by a MITM proxy;
    such an interception simply surfaces as :class:`NetError`.
    """
    hdrs = {
        "User-Agent": "halieum/1.0",
        "Accept": "application/json",
        "Cache-Control": "no-cache",
    }
    if headers:
        hdrs.update(headers)

    request = Request(url, headers=hdrs)
    response = None
    try:
        response = urlopen(request, timeout=timeout)
        return response.read()
    except HTTPError as exc:
        raise NetError("http status %s" % getattr(exc, "code", exc))
    except URLError as exc:
        raise NetError("url error: %s" % getattr(exc, "reason", exc))
    except socket.timeout:
        raise NetError("timeout")
    except Exception as exc:  # ssl, connection reset, etc.
        raise NetError("network failure: %r" % (exc,))
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
