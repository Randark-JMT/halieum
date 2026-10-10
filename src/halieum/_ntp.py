# -*- coding: utf-8 -*-
"""Authoritative time via NTP (RFC 5905) using only the standard library.

halieum decides whether a license has expired by comparing its ``exp`` field
against "now". Trusting the local system clock is unsafe: an attacker can roll
the clock back and revive an expired license. This module instead obtains the
current time from well-known public NTP servers over UDP/123, using nothing but
:mod:`socket`, :mod:`struct` and :mod:`time`, so the package stays
dependency-free.

Every failure mode (DNS, timeout, unreachable, malformed reply) is normalised
into :class:`NTPError` so callers can fall back deliberately instead of
guessing. Importing this module performs no I/O and opens no sockets.
"""

import socket
import struct
import time

# Seconds between the NTP epoch (1900-01-01) and the Unix epoch (1970-01-01).
_NTP_DELTA = 2208988800

# Minimal NTP client packet: LI=0, VN=3, Mode=3 (client) -> first byte 0x1b and
# the remaining 47 bytes zero. The server fills in its timestamps on reply.
_CLIENT_PACKET = b"\x1b" + 47 * b"\x00"

# The transmit timestamp occupies the last 8 bytes of the 48-byte reply.
_TX_OFFSET = 40
_REPLY_LEN = 48


class NTPError(Exception):
    """Raised when no authoritative time could be obtained."""


def query(server, timeout=5.0, port=123):
    """Return the current Unix time (float seconds) reported by one server.

    Raises :class:`NTPError` on any transport or protocol failure. The socket
    timeout bounds a single round trip; the (tiny) round-trip delay is ignored
    because licence expiry only needs second-level accuracy.
    """
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(_CLIENT_PACKET, (server, port))
        data, _addr = sock.recvfrom(1024)
    except socket.timeout:
        raise NTPError("timeout querying %s" % server)
    except Exception as exc:  # DNS failure, unreachable, refused, etc.
        raise NTPError("query failed for %s: %r" % (server, exc))
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    if not data or len(data) < _REPLY_LEN:
        raise NTPError("short reply from %s" % server)

    secs, frac = struct.unpack("!II", data[_TX_OFFSET:_TX_OFFSET + 8])
    if secs == 0:
        raise NTPError("null timestamp from %s" % server)
    return (secs - _NTP_DELTA) + frac / float(1 << 32)


def resolve_time(servers, timeout=5.0, port=123, total_timeout=None):
    """Query ``servers`` in order and return the first good Unix time (float).

    ``total_timeout`` bounds the whole attempt (default ``timeout * 3``) so a
    fully-blocked UDP path fails over quickly instead of stalling on every
    server in turn. Raises :class:`NTPError` only when every server fails.
    """
    servers = list(servers or ())
    if not servers:
        raise NTPError("no NTP servers configured")

    if total_timeout is None:
        total_timeout = timeout * 3
    # time.monotonic() is immune to the very clock tampering we are guarding
    # against, so it is the only safe basis for the deadline.
    deadline = time.monotonic() + total_timeout

    errors = []
    for server in servers:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            errors.append("time budget exhausted before %s" % server)
            break
        try:
            return query(server, timeout=min(timeout, remaining), port=port)
        except NTPError as exc:
            errors.append(str(exc))
            continue
    raise NTPError("all NTP servers failed: " + "; ".join(errors))
