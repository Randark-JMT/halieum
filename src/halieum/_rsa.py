# -*- coding: utf-8 -*-
"""Pure-Python RSASSA-PKCS1-v1_5 signature *verification* with SHA-256.

Standard library only (``hashlib`` + ``hmac``). This mirrors exactly what
pycryptodome's ``Crypto.Signature.pkcs1_15`` produces on the signing side
(the GitHub Action), so a license signed there verifies here with no third
party dependency and across every supported Python version.

Only verification is implemented: the private key never ships in the package.
"""

import hashlib
import hmac

# DER ``DigestInfo`` prefix for SHA-256 (RFC 8017, 9.2 notes).
_SHA256_DIGEST_INFO = (
    b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01"
    b"\x05\x00\x04\x20"
)


def _i2osp(value, length):
    """Integer -> big-endian octet string of exactly ``length`` bytes."""
    if value < 0:
        raise ValueError("negative integer")
    out = bytearray()
    while value:
        out.insert(0, value & 0xFF)
        value >>= 8
    if len(out) > length:
        raise ValueError("integer too large")
    while len(out) < length:
        out.insert(0, 0)
    return bytes(out)


def _os2ip(octets):
    """Big-endian octet string -> integer (portable, no int.from_bytes)."""
    value = 0
    for byte in bytearray(octets):
        value = (value << 8) | byte
    return value


def verify_pkcs1v15_sha256(n, e, message, signature):
    """Return True iff ``signature`` is a valid PKCS#1 v1.5 SHA-256 signature.

    Never raises: any malformed input simply yields ``False``.
    """
    try:
        if not isinstance(n, int) or not isinstance(e, int) or n <= 0:
            return False
        k = (n.bit_length() + 7) // 8
        if k < 11 or len(signature) != k:
            return False
        s = _os2ip(signature)
        if s >= n:
            return False
        em = _i2osp(pow(s, e, n), k)

        digest = hashlib.sha256(message).digest()
        t = _SHA256_DIGEST_INFO + digest
        ps_len = k - len(t) - 3
        if ps_len < 8:
            return False
        expected = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t

        # Constant-time comparison of the full encoded message.
        return hmac.compare_digest(em, expected)
    except Exception:
        return False
