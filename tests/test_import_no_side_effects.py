# -*- coding: utf-8 -*-
"""Prove that `import halieum` is inert: no I/O, no network, no output."""

import subprocess
import sys


def test_public_api_shape():
    import halieum
    assert callable(halieum.init)
    assert isinstance(halieum.__version__, str)
    assert halieum.__all__ == ["init", "__version__"]
    assert halieum._INITIALIZED == set()  # nothing executed at import time


def test_import_is_silent_and_lazy_subprocess():
    # Run in a fresh interpreter so no other test has already imported the
    # internal modules. This guarantees we observe import-time behaviour only.
    code = (
        "import sys\n"
        "import halieum\n"
        "lazy = ('halieum._net', 'halieum._license', 'halieum._enforce',\n"
        "        'halieum._cache', 'halieum._root')\n"
        "for name in lazy:\n"
        "    assert name not in sys.modules, name\n"
        "assert halieum._INITIALIZED == set()\n"
        "assert callable(halieum.init)\n"
        "sys.stdout.write('OK')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.decode("utf-8").strip() == "OK"
    assert proc.stderr.decode("utf-8").strip() == ""  # fully silent
