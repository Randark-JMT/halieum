# -*- coding: utf-8 -*-
"""Tiny logging helper.

Deliberately avoids the builtin ``print`` (which a host application can
monkey-patch / redirect) and writes straight to ``sys.stderr`` instead.

Default state is fully SILENT. Only ``init(..., debug=True)`` enables
:func:`debug`. :func:`alert` is reserved for exceptional, user-visible
termination messages and is intentionally independent of the debug flag so a
program never dies without a one-line reason.
"""

import sys

_debug_enabled = False


def set_debug(enabled):
    """Enable or disable debug output."""
    global _debug_enabled
    _debug_enabled = bool(enabled)


def is_debug():
    return _debug_enabled


def _write(line):
    try:
        sys.stderr.write("[halieum] " + line + "\n")
        sys.stderr.flush()
    except Exception:
        # Never let logging break the host program.
        pass


def debug(message):
    """Emit a diagnostic line only when debug mode is on."""
    if _debug_enabled:
        _write(str(message))


def alert(message):
    """Emit a concise, always-on line for exceptional termination."""
    _write(str(message))
