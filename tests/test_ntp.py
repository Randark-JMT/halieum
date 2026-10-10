# -*- coding: utf-8 -*-
"""Tests for the stdlib NTP client (packet parsing + server iteration).

No real network is used: ``socket.socket`` is replaced with an in-test fake for
``query``, and ``query`` itself is stubbed for ``resolve_time``.
"""

import socket
import struct

import pytest

from halieum import _ntp


def _reply(epoch, length=48):
    """Craft an NTP reply whose transmit timestamp encodes ``epoch``."""
    data = bytearray(length)
    secs = int(epoch) + _ntp._NTP_DELTA
    if length >= 48:
        struct.pack_into("!II", data, 40, secs, 0)
    return bytes(data)


class _FakeSocket(object):
    """Minimal UDP socket stand-in: records the request, replays a canned reply."""

    def __init__(self, reply=None, recv_exc=None):
        self._reply = reply
        self._recv_exc = recv_exc
        self.sent = None
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendto(self, data, addr):
        self.sent = (data, addr)
        return len(data)

    def recvfrom(self, bufsize):
        if self._recv_exc is not None:
            raise self._recv_exc
        return self._reply, ("203.0.113.1", 123)

    def close(self):
        self.closed = True


def _install(monkeypatch, fake):
    monkeypatch.setattr(_ntp.socket, "socket", lambda *a, **k: fake)


def test_query_parses_transmit_timestamp(monkeypatch):
    epoch = 1700000000
    fake = _FakeSocket(reply=_reply(epoch))
    _install(monkeypatch, fake)

    got = _ntp.query("time.example.com")

    assert abs(got - epoch) < 1.0
    # A well-formed client packet: 48 bytes, first byte 0x1b, sent to UDP/123.
    packet, addr = fake.sent
    assert len(packet) == 48
    assert packet[0:1] == b"\x1b"
    assert addr == ("time.example.com", 123)
    assert fake.closed is True


def test_query_honours_custom_port(monkeypatch):
    fake = _FakeSocket(reply=_reply(1700000000))
    _install(monkeypatch, fake)
    _ntp.query("time.example.com", port=1234)
    assert fake.sent[1] == ("time.example.com", 1234)


def test_query_timeout_raises(monkeypatch):
    fake = _FakeSocket(recv_exc=socket.timeout())
    _install(monkeypatch, fake)
    with pytest.raises(_ntp.NTPError):
        _ntp.query("time.example.com", timeout=0.01)
    assert fake.closed is True


def test_query_dns_failure_raises(monkeypatch):
    fake = _FakeSocket(recv_exc=OSError("name or service not known"))
    _install(monkeypatch, fake)
    with pytest.raises(_ntp.NTPError):
        _ntp.query("no-such-host.invalid")


def test_query_short_reply_raises(monkeypatch):
    fake = _FakeSocket(reply=b"\x00" * 10)
    _install(monkeypatch, fake)
    with pytest.raises(_ntp.NTPError):
        _ntp.query("time.example.com")


def test_query_null_timestamp_raises(monkeypatch):
    fake = _FakeSocket(reply=bytes(48))  # all-zero -> transmit seconds == 0
    _install(monkeypatch, fake)
    with pytest.raises(_ntp.NTPError):
        _ntp.query("time.example.com")


def test_resolve_time_returns_first_success(monkeypatch):
    calls = []

    def fake_query(server, timeout=5.0, port=123):
        calls.append(server)
        if server == "bad":
            raise _ntp.NTPError("down")
        return 1700000000.0

    monkeypatch.setattr(_ntp, "query", fake_query)
    got = _ntp.resolve_time(["bad", "good", "unused"], timeout=1.0)
    assert got == 1700000000.0
    assert calls == ["bad", "good"]  # stops at the first working server


def test_resolve_time_all_fail(monkeypatch):
    def fake_query(server, timeout=5.0, port=123):
        raise _ntp.NTPError("down")

    monkeypatch.setattr(_ntp, "query", fake_query)
    with pytest.raises(_ntp.NTPError):
        _ntp.resolve_time(["a", "b"], timeout=1.0)


def test_resolve_time_no_servers_raises():
    with pytest.raises(_ntp.NTPError):
        _ntp.resolve_time([])
