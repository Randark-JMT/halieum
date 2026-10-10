# halieum

A minimal, **dependency-free** license guard for personal Python projects.

English | [中文](README_zh.md)

```python
import halieum
halieum.init("your-license-id")
```

`import halieum` does **nothing** on its own — no network, no file I/O, nooutput, no monkey-patching. It cannot affect the surrounding code. All logic runs inside `init()`.

When the license for `id` is **confirmed invalid** (a validly-signed license whose expiry has passed, or one that was tampered with / forged), halieum enforces from the **project root**. When the license server is merely **unreachable**, it never deletes anything: it falls back to a local cache, and on a first-ever run with no cache it simply exits the host program.

> halieum is a deterrent for the author's own projects. Anyone who can edit the source can delete the two lines above; treat it as a speed bump, not a vault.

---

## How it works

```
init(id)
  -> GET  <PAGES_BASE>/licenses/<id>.json           (GitHub Pages)
  -> verify RSA (PKCS#1 v1.5 + SHA-256) with the embedded PUBLIC key
  -> resolve the current time (NTP by default; local clock only as fallback)
  -> compare exp against that authoritative time
       valid & current        -> cache to temp dir, return silently
       expired / tampered     -> ENFORCE (delete) then exit
  -> if the network failed:
       cache present & valid   -> return silently
       cache present & expired -> ENFORCE (delete) then exit
       no cache (first run)    -> exit host program (never delete)
```

The signature is asymmetric on purpose: the **public** key ships inside the ackage (safe to be public on PyPI — it can only verify), while the **private** key stays in a GitHub Actions secret and signs each license.

---

## Install

```bash
pip install halieum
```

Runtime requires the **standard library only** and targets **Python 3.6+**.

---

## `init()` API

```python
halieum.init(
    id,                 # REQUIRED. License identifier issued by the Action.
    dry_run=False,      # Only determine validity; never delete, never exit.
    debug=False,        # Log to sys.stderr (never print). Default: silent.
    mode="recursive",   # "recursive" | "source" | "self" | "file"
    target=None,        # Dir/file to enforce on. Default: project root.
    root=None,          # Override project-root auto-detection.
    extensions=None,    # Custom extension filter (implies source filtering).
    timeout=None,       # Network timeout in seconds (default 5.0).
    exit_after=True,    # After a destructive enforcement, exit the process.
    ntp=True,           # Verify time via NTP, not the local clock (default).
    ntp_servers=None,   # Custom NTP hosts (default: built-in list).
    ntp_timeout=None,   # Per-server NTP timeout in seconds (default 5.0).
    ntp_fallback=None,  # "local" (default) | "strict" if NTP is unreachable.
)
```

**Modes**

| mode | effect |
|------|--------|
| `recursive` (default) | Delete every file under `target` (default: project root), then remove emptied directories. `.git`/`.hg`/`.svn` are preserved. |
| `source` | Like `recursive`, but only files whose extension is in `extensions` (default: common source extensions). |
| `self` | Delete only the single file that called `init()`. |
| `file` | Delete only the single resolved `target` file. |

**Project root** is the entry-script directory (`__main__.__file__`, else `sys.argv[0]`), falling back to the current working directory. So calling `init()` from a sub-module still resolves to the project root — never the sub-module folder and never the installed package folder.

**Examples**

```python
# Check only, change nothing, print diagnostics:
halieum.init("my-id", dry_run=True, debug=True)

# On failure, delete only the ./src tree:
halieum.init("my-id", target="src")

# On failure, delete only source files, keep data/assets:
halieum.init("my-id", mode="source")

# On failure, delete only the file that calls init():
halieum.init("my-id", mode="self")

# Require authoritative NTP time; refuse to run if it cannot be obtained:
halieum.init("my-id", ntp_fallback="strict")

# Use your own NTP server(s):
halieum.init("my-id", ntp_servers=["time.internal.example.com"])
```

Output never uses `print` (which a host app can hijack); diagnostics go straight to `sys.stderr` and are silent unless `debug=True`.

---

## Time verification & clock tampering

An expiry check is only as trustworthy as the clock it reads. If halieum compared `exp` against the **local** system time, an attacker could simply roll the clock back and keep running an expired licence. So by default halieum reads the current time from **authoritative public NTP servers** over UDP/123:

```
time.cloudflare.com   time.google.com   pool.ntp.org   time.windows.com
time.apple.com        ntp.aliyun.com    cn.pool.ntp.org   ntp.ntsc.ac.cn
```

They are tried in order and the first reply wins; override the list with `ntp_servers`. The behaviour then is:

- **NTP reachable** → its time decides expiry, so a rolled-back (or fast) local clock is simply ignored.
- **NTP unreachable** → halieum falls back to the local clock, but never lets it read *earlier* than a trusted high-water mark cached from the last NTP success — so a rollback below the last verified time is still caught offline.
- **`ntp_fallback="strict"`** → if no authoritative time can be obtained, halieum exits the host program (exit code `77`) instead of trusting a possibly tampered clock. Nothing is deleted in this case.

Set `ntp=False` to opt out and use the local clock only (the legacy behaviour). NTP needs outbound UDP/123; if your runtime blocks it, either allow it, point `ntp_servers` at a reachable internal server, or pass `ntp=False`.

---

## Setting up your own license server (one time)

The signing key, the issuing Action and the Pages distribution all live in this repository.

### 1. Generate the RSA keypair

```bash
pip install pycryptodome
python tools/gen_keys.py
```

This rewrites `src/halieum/_keys.py` with your **public** key and prints the **private** key (PEM) to stdout.

### 2. Store the private key as a secret

Repo → Settings → Secrets and variables → Actions → New repository secret:

- Name: `HALIEUM_SIGNING_KEY`
- Value: the PEM private key printed above

> Until a real public key is generated, `_keys.py` ships a placeholder (`n = 0`) and halieum stays **inert** (it reports "unconfigured" and never enforces).

### 3. Enable GitHub Pages

Repo → Settings → Pages → **Source: GitHub Actions**.

Set your Pages base URL in `src/halieum/_config.py`:

```python
DEFAULT_BASE = "https://<your-username>.github.io/<repo>/"
```

Licenses are then served at `<DEFAULT_BASE>licenses/<id>.json`.

### 4. Issue a license

Repo → Actions → **Issue License** → Run workflow, and provide:

- `id` — the license identifier (the same string passed to `init()`).
- `datetime` — expiry, ISO-8601 UTC, e.g. `2026-12-31T23:59:59Z`.

The workflow signs the license, writes `licenses/<id>.json`, commits it back as the source of truth, and deploys all licenses to Pages. **Re-running with the same `id` updates its `datetime`** and re-signs.

---

## Safety guarantees

halieum is deliberately biased toward *not* deleting:

- A **network failure alone never deletes**. It uses the cache, or (first run) exits the host program.
- **Expiry is judged against authoritative NTP time by default**, so rolling back the local clock cannot revive an expired licence. When NTP is unreachable the local clock is floored at a trusted high-water mark, and `ntp_fallback="strict"` exits the host instead of guessing.
- Deletion happens **only** for a provably invalid license: a correctly signed license past its expiry, or one whose signature/id does not verify.
- The enforcement target is screened against a deny-list of **filesystem roots, critical OS directories, the running interpreter, site-packages and halieum's own package directory**. A target outside the project root is refused.
- `.git`/`.hg`/`.svn` are preserved; each file removal is individually guarded (locked files on Windows are skipped, not fatal).
- Any **internal halieum error** results in a no-op, never a deletion.
- `dry_run=True` disables every destructive action and every exit.
- `import halieum` is inert; nothing runs until `init()` is called, and the same `id` is only ever processed once per process.

---

## Development

```bash
pip install -e ".[dev]"      # editable install + pytest/build/twine
pytest -q                    # run the suite (stdlib only; no crypto needed)
python -m build              # sdist + wheel
twine check dist/*
```

The test-suite signs with a **throwaway** RSA key embedded in `tests/conftest.py` using pure Python, so it needs no third-party crypto. CI (`.github/workflows/ci.yml`) runs the matrix across Python 3.8–3.14 on Ubuntu and Windows.

### Publishing to PyPI

```bash
python -m build
twine upload dist/*
```

---

## License

MIT — see [LICENSE](LICENSE).
