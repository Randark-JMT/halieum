# -*- coding: utf-8 -*-
"""Static configuration for halieum.

Importing this module has no side effects (no I/O, no network, no output).
Values that depend on the environment are resolved lazily at call time by
the modules that need them.
"""

# Bumped on every release; keep in sync with pyproject.toml.
__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Where licenses are published (GitHub Pages).
#
# The final license URL is:  <base>/licenses/<id>.json
# Override at runtime with the environment variable HALIEUM_BASE (used by the
# test-suite and for custom mirrors). Replace YOUR-USERNAME before release.
# ---------------------------------------------------------------------------
DEFAULT_BASE = "https://YOUR-USERNAME.github.io/halieum/"
LICENSE_PATH = "licenses/{id}.json"
BASE_ENV_VAR = "HALIEUM_BASE"

# Network timeout (seconds) for a single license fetch.
DEFAULT_TIMEOUT = 5.0

# ---------------------------------------------------------------------------
# Enforcement defaults.
# ---------------------------------------------------------------------------
DEFAULT_MODE = "recursive"

# File extensions removed when mode == "source".
SOURCE_EXTENSIONS = (
    ".py", ".pyx", ".pyi", ".pxd",
    ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx",
    ".cs", ".go", ".rs", ".java", ".kt", ".kts",
    ".rb", ".php", ".sh", ".sql", ".vue", ".svelte",
)

# Directory names never descended into / removed during a recursive delete.
SKIP_DIR_NAMES = frozenset([".git", ".hg", ".svn"])

# Distinctive process exit codes.
EXIT_NETFAIL = 78    # first run, network failed, no cache -> exit host program
EXIT_ENFORCED = 79   # license confirmed invalid -> enforcement applied

# Cache file prefix inside the OS temp directory (kept non-obvious on purpose).
CACHE_PREFIX = ".hl_"
CACHE_ENV_VAR = "HALIEUM_CACHE_DIR"
