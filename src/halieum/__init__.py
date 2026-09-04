# -*- coding: utf-8 -*-
"""halieum - a minimal, dependency-free license guard for personal projects.

Usage in a protected project::

    import halieum
    halieum.init("your-license-id")

``import halieum`` performs NO network access, NO file I/O, NO output and does
not modify ``sys`` or import hooks - it cannot affect existing code. All work
happens inside :func:`init`.

If the license for ``id`` is confirmed invalid (a validly-signed license whose
expiry has passed, or a tampered/forged one), enforcement runs from the PROJECT
root. If the license server is merely unreachable, halieum falls back to a
temp-dir cache; on a first-ever run with no cache it exits the host program
instead of deleting anything.
"""

from __future__ import absolute_import

__all__ = ["init", "__version__"]
__version__ = "0.1.0"

# ids already handled in this process (init may be called from many modules).
_INITIALIZED = set()


def init(id, dry_run=False, debug=False, mode="recursive", target=None,
         root=None, extensions=None, timeout=None, exit_after=True):
    """Verify the license ``id`` and enforce on failure.

    Parameters
    ----------
    id : str
        Required license identifier (matches the ``id`` issued by the Action).
    dry_run : bool
        Only determine validity; take NO destructive action and do NOT exit.
    debug : bool
        Emit diagnostics to ``sys.stderr`` (never ``print``). Default silent.
    mode : str
        Enforcement scope: ``"recursive"`` (default, all files under target),
        ``"source"`` (extension-filtered), ``"self"`` (only the calling file),
        ``"file"`` (only the single resolved target).
    target : str or None
        Path (dir or file) to enforce on. Default is the project root. A
        relative value such as ``"src"`` resolves under the root.
    root : str or None
        Override project-root auto-detection (entry-script dir, else cwd).
    extensions : list or None
        Custom extension filter (implies source-style filtering).
    timeout : float or None
        Network timeout in seconds for the license fetch.
    exit_after : bool
        After a destructive enforcement, exit the host program (default True).
    """
    try:
        # Lazy imports keep `import halieum` free of side effects.
        from . import _config, _enforce, _license, _log, _root
        import os
        import sys
    except Exception:
        return

    try:
        _log.set_debug(debug)

        license_id = str(id)
        if license_id in _INITIALIZED:
            return
        _INITIALIZED.add(license_id)

        if root is None:
            project_root = _root.detect_root()
        else:
            project_root = os.path.abspath(root)

        # The module that called init() (frame(1) is init itself; frame(0)
        # would be this helper - so resolve it here, not in a helper).
        # mode="self" is only allowed to delete that application file.
        caller_file = None
        try:
            filename = sys._getframe(1).f_code.co_filename
            if filename:
                caller_file = os.path.abspath(filename)
        except Exception:
            pass

        decision, exp = _license.evaluate(license_id, timeout=timeout)
        _log.debug("id=%s decision=%s exp=%s root=%s"
                   % (license_id, decision, exp, project_root))

        if decision == _license.VALID:
            return
        if decision == _license.UNCONFIGURED:
            _log.debug("public key not configured; skipping enforcement")
            return

        if dry_run:
            _log.debug("dry_run: decision=%s (no action taken)" % decision)
            return

        if decision == _license.NETFAIL_NOCACHE:
            _log.alert("license server unreachable and no local cache; exiting")
            sys.exit(_config.EXIT_NETFAIL)
            return

        # EXPIRED or TAMPERED -> enforce from the project root.
        _enforce.enforce(mode=mode, target=target, root=project_root,
                         caller_file=caller_file, extensions=extensions,
                         dry_run=False)
        if exit_after:
            _log.alert("license invalid (%s); enforcement applied; exiting"
                       % decision)
            sys.exit(_config.EXIT_ENFORCED)
    except SystemExit:
        # Intentional termination must propagate to actually stop the program.
        raise
    except Exception as exc:
        # Safety valve: an internal halieum bug must never delete files or
        # crash the host. Swallow it (log only when debugging).
        try:
            _log.debug("internal error (ignored): " + repr(exc))
        except Exception:
            pass
        return
