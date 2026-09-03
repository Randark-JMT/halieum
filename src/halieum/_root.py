# -*- coding: utf-8 -*-
"""Project-root detection.

Per the chosen strategy the root is the *entry script* directory, falling back
to the current working directory. This is what makes a ``halieum.init()`` call
placed in a sub-module still resolve to the PROJECT root rather than the
sub-module's own folder or the installed package folder.
"""

import os
import sys


def _from_main_module():
    try:
        main = sys.modules.get("__main__")
        filename = getattr(main, "__file__", None)
        if filename:
            directory = os.path.dirname(os.path.abspath(filename))
            if os.path.isdir(directory):
                return directory
    except Exception:
        pass
    return None


def _from_argv0():
    try:
        argv0 = sys.argv[0]
        if argv0:
            directory = os.path.dirname(os.path.abspath(argv0))
            if os.path.isdir(directory):
                return directory
    except Exception:
        pass
    return None


def _from_cwd():
    try:
        return os.getcwd()
    except Exception:
        return os.path.abspath(os.sep)


def detect_root():
    """Return the best-guess project root as an absolute path."""
    for candidate in (_from_main_module, _from_argv0, _from_cwd):
        result = candidate()
        if result:
            return os.path.abspath(result)
    return os.path.abspath(os.sep)
