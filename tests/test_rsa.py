# -*- coding: utf-8 -*-
"""Tests for the pure-Python RSA PKCS#1 v1.5 verifier."""

from halieum import _rsa
from halieum._license import canonical_message


def test_verify_valid_signature(test_pubkey, signer):
    n, e = test_pubkey
    msg = b"halieum|v=1|id=demo|exp=2099-12-31T23:59:59Z"
    assert _rsa.verify_pkcs1v15_sha256(n, e, msg, signer(msg)) is True


def test_verify_tampered_message(test_pubkey, signer):
    n, e = test_pubkey
    msg = b"halieum|v=1|id=demo|exp=2099-12-31T23:59:59Z"
    sig = signer(msg)
    assert _rsa.verify_pkcs1v15_sha256(n, e, msg + b"X", sig) is False


def test_verify_tampered_signature(test_pubkey, signer):
    n, e = test_pubkey
    msg = b"halieum|v=1|id=demo|exp=2099-12-31T23:59:59Z"
    sig = bytearray(signer(msg))
    sig[10] ^= 0xFF
    assert _rsa.verify_pkcs1v15_sha256(n, e, msg, bytes(sig)) is False


def test_verify_wrong_length_signature(test_pubkey):
    n, e = test_pubkey
    assert _rsa.verify_pkcs1v15_sha256(n, e, b"x", b"\x00" * 10) is False


def test_verify_rejects_unconfigured_key(signer):
    # n == 0 is the shipped placeholder; it must never verify anything.
    msg = b"halieum|v=1|id=demo|exp=2099-12-31T23:59:59Z"
    assert _rsa.verify_pkcs1v15_sha256(0, 65537, msg, signer(msg)) is False


def test_verify_signature_above_modulus_rejected(test_pubkey, signer):
    n, e = test_pubkey
    msg = b"halieum|v=1|id=demo|exp=2099-12-31T23:59:59Z"
    k = (n.bit_length() + 7) // 8
    assert _rsa.verify_pkcs1v15_sha256(n, e, msg, b"\xff" * k) is False


def test_canonical_message_is_stable():
    assert canonical_message("abc", "2030-01-01T00:00:00Z") == \
        b"halieum|v=1|id=abc|exp=2030-01-01T00:00:00Z"
