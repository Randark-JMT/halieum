# -*- coding: utf-8 -*-
"""Static configuration for halieum.

Importing this module has no side effects (no I/O, no network, no output).
Values that depend on the environment are resolved lazily at call time by
the modules that need them.
"""

# Bumped on every release; keep in sync with pyproject.toml.
__version__ = "0.2.5"

# ---------------------------------------------------------------------------
# Where licenses are published (GitHub Pages).
#
# The final license URL is:  <base>/licenses/<id>.json
# Override at runtime with the environment variable HALIEUM_BASE (used by the
# test-suite and for custom mirrors). Replace YOUR-USERNAME before release.
# ---------------------------------------------------------------------------
DEFAULT_BASE = "https://Randark-JMT.github.io/halieum/"
LICENSE_PATH = "licenses/{id}.json"
BASE_ENV_VAR = "HALIEUM_BASE"

# Network timeout (seconds) for a single license fetch.
DEFAULT_TIMEOUT = 5.0

# ---------------------------------------------------------------------------
# NTP time verification (defeats local-clock tampering).
#
# Judging expiry against the local clock lets an attacker roll the clock back
# and revive an expired licence. When NTP is enabled (the default) halieum asks
# authoritative public servers for the current time instead. All are reached
# over UDP/123; the list is tried in order and the first reply wins. The mix
# spans global pools plus China-region servers so a nearby responder exists in
# most deployments.
# ---------------------------------------------------------------------------
NTP_ENABLED = True
NTP_PORT = 123
NTP_TIMEOUT = 5.0             # per-server round-trip timeout (seconds)
NTP_TOTAL_TIMEOUT = 15.0      # bound for the whole NTP attempt (seconds)
NTP_SERVERS = (
    "time.cloudflare.com",
    "time.google.com",
    "pool.ntp.org",
    "time.windows.com",
    "time.apple.com",
    "ntp.aliyun.com",
    "cn.pool.ntp.org",
    "ntp.ntsc.ac.cn",
)
# What to do when NTP is enabled but unreachable:
#   "local"  -> fall back to the local clock, but never before the trusted
#               high-water mark (a rolled-back clock is lifted up to it).
#   "strict" -> refuse to run: exit the host program without deleting anything.
NTP_FALLBACK = "local"
# Seconds of slack before the local clock trailing the trusted marker counts as
# a rollback (absorbs ordinary NTP-daemon drift and minor skew).
CLOCK_TOLERANCE = 300

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
EXIT_TIMEFAIL = 77   # ntp_fallback="strict" and no authoritative time -> exit

# ---------------------------------------------------------------------------
# Optional background re-validation watchdog (init(recheck_interval=N)).
#
# init() checks the licence only once, so a long-running host (a ``while True``
# loop, a server, an async worker) can outlive its licence. Passing a positive
# ``recheck_interval`` starts one daemon thread that re-checks every N seconds
# and enforces on a confirmed expiry. The floor below clamps a too-small
# interval up so it cannot hammer the licence server and the NTP pool.
# ---------------------------------------------------------------------------
RECHECK_MIN_INTERVAL = 60   # seconds; smaller requests are lifted to this

# Cache file prefix inside the OS temp directory (kept non-obvious on purpose).
CACHE_PREFIX = ".hl_"
CACHE_ENV_VAR = "HALIEUM_CACHE_DIR"
