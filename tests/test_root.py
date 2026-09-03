# -*- coding: utf-8 -*-
"""Tests for project-root detection (entry-script dir -> argv[0] -> cwd)."""

import os
import sys
import types

from halieum import _root


def _blank_main(monkeypatch):
    """Install a __main__ module without __file__."""
    monkeypatch.setitem(sys.modules, "__main__", types.ModuleType("__main__"))


def test_from_main_file(tmp_path, monkeypatch):
    fake = types.ModuleType("__main__")
    fake.__file__ = str(tmp_path / "app.py")
    monkeypatch.setitem(sys.modules, "__main__", fake)
    assert _root.detect_root() == os.path.abspath(str(tmp_path))


def test_from_argv0(tmp_path, monkeypatch):
    _blank_main(monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "main.py")])
    assert _root.detect_root() == os.path.abspath(str(tmp_path))


def test_from_cwd(tmp_path, monkeypatch):
    _blank_main(monkeypatch)
    monkeypatch.setattr(sys, "argv", [""])
    monkeypatch.chdir(tmp_path)
    assert _root.detect_root() == os.path.abspath(str(tmp_path))


def test_submodule_call_still_uses_entry_root(tmp_path, monkeypatch):
    # Simulate: entry script at project root, init() called from a sub-module.
    project = tmp_path / "project"
    (project / "pkg").mkdir(parents=True)
    entry = project / "main.py"
    fake = types.ModuleType("__main__")
    fake.__file__ = str(entry)
    monkeypatch.setitem(sys.modules, "__main__", fake)
    monkeypatch.setattr(sys, "argv", [str(entry)])
    # Detection is independent of the caller's own file location.
    assert _root.detect_root() == os.path.abspath(str(project))
