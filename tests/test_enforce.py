# -*- coding: utf-8 -*-
"""Tests for the enforcement engine and its safety guards."""

import os

from halieum import _enforce


def _build_tree(root):
    (root / "a.py").write_text("print('a')")
    (root / "b.txt").write_text("data")
    (root / "src").mkdir()
    (root / "src" / "c.py").write_text("c")
    (root / "src" / "deep").mkdir()
    (root / "src" / "deep" / "d.py").write_text("d")
    (root / "data").mkdir()
    (root / "data" / "x.bin").write_bytes(b"\x00\x01")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]")
    return root


def test_recursive_deletes_everything_but_vcs(tmp_path):
    root = _build_tree(tmp_path)
    assert _enforce.enforce(mode="recursive", target=None, root=str(root)) is True
    assert not (root / "a.py").exists()
    assert not (root / "b.txt").exists()
    assert not (root / "src" / "c.py").exists()
    assert not (root / "src").exists()            # emptied dir removed
    assert not (root / "data" / "x.bin").exists()
    assert (root / ".git" / "config").exists()    # VCS preserved
    assert root.exists()                          # project root itself kept


def test_source_mode_only_removes_code(tmp_path):
    root = _build_tree(tmp_path)
    _enforce.enforce(mode="source", target=None, root=str(root))
    assert not (root / "a.py").exists()
    assert not (root / "src" / "c.py").exists()
    assert (root / "b.txt").exists()
    assert (root / "data" / "x.bin").exists()


def test_file_mode_single_file(tmp_path):
    root = _build_tree(tmp_path)
    _enforce.enforce(mode="file", target="a.py", root=str(root))
    assert not (root / "a.py").exists()
    assert (root / "b.txt").exists()
    assert (root / "src" / "c.py").exists()


def test_self_mode_deletes_caller_file(tmp_path):
    root = _build_tree(tmp_path)
    caller = str(root / "src" / "c.py")
    _enforce.enforce(mode="self", caller_file=caller, root=str(root))
    assert not (root / "src" / "c.py").exists()
    assert (root / "a.py").exists()


def test_target_subdir_scopes_deletion(tmp_path):
    root = _build_tree(tmp_path)
    _enforce.enforce(mode="recursive", target="src", root=str(root))
    assert not (root / "src").exists()
    assert (root / "a.py").exists()
    assert (root / "data" / "x.bin").exists()


def test_custom_extensions(tmp_path):
    root = _build_tree(tmp_path)
    _enforce.enforce(mode="recursive", target=None, root=str(root),
                     extensions=[".txt"])
    assert not (root / "b.txt").exists()
    assert (root / "a.py").exists()


def test_dry_run_changes_nothing(tmp_path):
    root = _build_tree(tmp_path)
    assert _enforce.enforce(mode="recursive", root=str(root), dry_run=True) is False
    assert (root / "a.py").exists()


def test_guard_refuses_filesystem_root(tmp_path):
    _build_tree(tmp_path)
    denied = os.path.abspath(os.sep)
    assert _enforce.enforce(mode="recursive", root=denied) is False
    # Nothing under the real temp tree was touched either.
    assert (tmp_path / "a.py").exists()


def test_guard_refuses_target_outside_root(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _build_tree(root)
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.py").write_text("keep")
    result = _enforce.enforce(mode="recursive", target=str(other), root=str(root))
    assert result is False
    assert (other / "keep.py").exists()
    assert (root / "a.py").exists()


def test_guard_refuses_runtime_dir(tmp_path):
    import sysconfig
    stdlib = sysconfig.get_paths().get("stdlib")
    # Targeting the interpreter's own stdlib must be refused outright.
    assert _enforce.enforce(mode="recursive", root=str(tmp_path),
                            target=stdlib) is False
