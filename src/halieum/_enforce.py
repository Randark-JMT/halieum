# -*- coding: utf-8 -*-
"""Enforcement: the deletion engine, wrapped in conservative safety guards.

Design rule (from the plan): halieum must NEVER delete anything because of its
own bug or an ambiguous state. Deletion happens ONLY for a *provably* invalid
license, and every target is screened against a deny-list of filesystem roots,
critical OS directories and the running interpreter's own packages.

Modes
-----
- ``recursive`` (default): delete every file under ``target`` (default: project
  root), then remove the emptied directories.
- ``source``: like ``recursive`` but only files whose extension is in
  ``extensions`` (default ``_config.SOURCE_EXTENSIONS``).
- ``self``: delete only the single source file that called ``init()``.
- ``file``: delete only the single resolved ``target`` file.
"""

import os
import sys

from . import _config, _log

# Exact critical directories that must never be a deletion target.
_CRITICAL_POSIX = frozenset([
    "/", "/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64", "/boot", "/dev",
    "/proc", "/sys", "/var", "/home", "/root", "/opt", "/mnt", "/media",
    "/srv", "/run", "/tmp",
])


def _norm(path):
    return os.path.normpath(os.path.abspath(path))


def _case(path):
    return os.path.normcase(path)


def _is_fs_root(path):
    p = _norm(path)
    drive, tail = os.path.splitdrive(p)
    return tail in ("", os.sep, "/")


def _runtime_protected_prefixes():
    """Directories (and everything under them) that must never be touched."""
    prefixes = []
    try:
        prefixes.append(os.path.dirname(os.path.abspath(sys.executable or "")))
    except Exception:
        pass
    try:
        import sysconfig
        for key in ("stdlib", "platstdlib", "purelib", "platlib"):
            value = sysconfig.get_paths().get(key)
            if value:
                prefixes.append(_norm(value))
    except Exception:
        pass
    try:
        import site
        for value in site.getsitepackages():
            prefixes.append(_norm(value))
        user_site = getattr(site, "getusersitepackages", None)
        if user_site:
            prefixes.append(_norm(user_site()))
    except Exception:
        pass
    # halieum's own package directory.
    try:
        prefixes.append(_norm(os.path.dirname(os.path.abspath(__file__))))
    except Exception:
        pass
    return [_case(p) for p in prefixes if p]


def _is_denied(path):
    """True if ``path`` must never be deleted (root / critical / runtime)."""
    try:
        p = _norm(path)
    except Exception:
        return True
    if _is_fs_root(p):
        return True

    lowered = p.replace("\\", "/")
    if lowered in _CRITICAL_POSIX or ("/" + lowered.strip("/")) in _CRITICAL_POSIX:
        return True

    drive = os.path.splitdrive(p)[0]
    if drive:
        win_roots = [_case(drive + suffix) for suffix in
                     ("\\Windows", "\\Program Files", "\\Program Files (x86)",
                      "\\Users", "\\ProgramData")]
        if _case(p) in win_roots:
            return True

    cased = _case(p)
    for prefix in _runtime_protected_prefixes():
        if cased == prefix or cased.startswith(prefix + os.sep):
            return True
    return False


def _within(root, target):
    root = _case(_norm(root))
    target = _case(_norm(target))
    return target == root or target.startswith(root + os.sep)


def _normalize_extensions(extensions):
    out = []
    for ext in extensions:
        ext = ext.lower()
        if not ext.startswith("."):
            ext = "." + ext
        out.append(ext)
    return tuple(out)


def _delete_file(path):
    try:
        os.remove(path)
        _log.debug("removed file " + path)
        return True
    except Exception as exc:
        # Windows keeps loaded files locked; skip and continue.
        _log.debug("could not remove " + path + ": " + repr(exc))
        return False


def _resolve_target(root, target):
    if target is None:
        return _norm(root)
    if os.path.isabs(target):
        return _norm(target)
    return _norm(os.path.join(root, target))


def _delete_tree(target_dir, extensions, remove_self=False):
    """Delete files under ``target_dir`` (optionally ext-filtered) + empty dirs.

    When ``remove_self`` is True the (now emptied) ``target_dir`` itself is also
    removed - used when an explicit target directory was requested. The project
    root is never removed (``remove_self`` stays False for target=None).
    """
    removed_dirs = []
    for dirpath, dirnames, filenames in os.walk(target_dir, topdown=True):
        if _is_denied(dirpath):
            dirnames[:] = []
            continue
        keep = []
        for name in dirnames:
            sub = os.path.join(dirpath, name)
            if name in _config.SKIP_DIR_NAMES or _is_denied(sub):
                continue
            keep.append(name)
            removed_dirs.append(sub)
        dirnames[:] = keep

        for name in filenames:
            file_path = os.path.join(dirpath, name)
            if extensions is not None and not name.lower().endswith(extensions):
                continue
            try:
                if _is_denied(os.path.realpath(file_path)):
                    continue
            except Exception:
                pass
            _delete_file(file_path)

    # Remove now-empty directories, deepest first.
    for sub in sorted(removed_dirs, key=lambda p: p.count(os.sep), reverse=True):
        try:
            os.rmdir(sub)
            _log.debug("removed dir " + sub)
        except Exception:
            pass

    if remove_self:
        try:
            os.rmdir(target_dir)
            _log.debug("removed target dir " + target_dir)
        except Exception:
            # Non-empty (e.g. filtered files remain) or locked: leave it.
            pass


def enforce(mode=None, target=None, root=None, caller_file=None,
            extensions=None, dry_run=False):
    """Apply the enforcement action. Returns True if something was deleted."""
    try:
        if dry_run:
            _log.debug("dry_run: no destructive action taken")
            return False

        mode = (mode or _config.DEFAULT_MODE).lower()
        root = _norm(root) if root else _norm(os.getcwd())

        # Hard guard: never act if the resolved project root is a dangerous
        # location (e.g. someone ran the app from a filesystem root).
        if _is_denied(root):
            _log.debug("refusing: project root is a protected path: " + root)
            return False

        exts = None
        if extensions:
            exts = _normalize_extensions(extensions)
        elif mode == "source":
            exts = _config.SOURCE_EXTENSIONS

        if mode == "self":
            if caller_file and os.path.isfile(caller_file):
                if not _is_denied(caller_file):
                    return _delete_file(_norm(caller_file))
                _log.debug("refusing self-delete of protected file")
            return False

        resolved = _resolve_target(root, target)

        if mode == "file":
            if os.path.isfile(resolved) and not _is_denied(resolved):
                return _delete_file(resolved)
            _log.debug("mode=file: nothing safe to delete at " + resolved)
            return False

        # recursive / source over a directory.
        if _is_denied(resolved):
            _log.debug("refusing: target is a protected path: " + resolved)
            return False
        if not _within(root, resolved):
            _log.debug("refusing: target escapes project root: " + resolved)
            return False
        if not os.path.isdir(resolved):
            _log.debug("target is not a directory: " + resolved)
            return False

        _log.debug("enforcing mode=" + mode + " on " + resolved)
        _delete_tree(resolved, exts, remove_self=(target is not None))
        return True
    except Exception as exc:
        # Safety valve: an internal error must never escalate into deletion.
        _log.debug("enforce aborted by error: " + repr(exc))
        return False
