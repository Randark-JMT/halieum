#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sign / update a halieum license. Invoked by the "Issue License" Action.

Environment
-----------
  LIC_ID               : license id (required)
  LIC_EXP              : expiry datetime, ISO-8601 (required)
  HALIEUM_SIGNING_KEY  : RSA private key PEM (required; GitHub Actions secret)
  LIC_KID              : key id (optional, default "k1")

Writes ``licenses/<id>.json``. If the file already exists it is UPDATED with
the new expiry (and re-signed), which is exactly the "same id -> update
datetime" behaviour required by the workflow.

The signed message is byte-for-byte identical to
``halieum._license.canonical_message``::

    halieum|v=1|id=<id>|exp=<YYYY-MM-DDTHH:MM:SSZ>
"""

import base64
import datetime
import json
import os
import re
import sys

_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_EXP_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def _normalize_exp(value):
    value = (value or "").strip()
    for fmt in _EXP_FORMATS:
        try:
            dt = datetime.datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    raise SystemExit(
        "invalid datetime %r - use ISO-8601, e.g. 2026-12-31T23:59:59Z"
        % value)


def _validate_id(license_id):
    if not _ID_RE.match(license_id):
        raise SystemExit(
            "invalid id %r - allowed characters: A-Z a-z 0-9 . _ - (max 128)"
            % license_id)
    return license_id


def main():
    try:
        from Crypto.PublicKey import RSA
        from Crypto.Signature import pkcs1_15
        from Crypto.Hash import SHA256
    except ImportError:
        sys.stderr.write("pycryptodome is required: pip install pycryptodome\n")
        return 2

    license_id = _validate_id((os.environ.get("LIC_ID") or "").strip())
    kid = (os.environ.get("LIC_KID") or "k1").strip() or "k1"
    pem = os.environ.get("HALIEUM_SIGNING_KEY") or ""
    if not pem.strip():
        raise SystemExit("HALIEUM_SIGNING_KEY secret is required")

    exp = _normalize_exp(os.environ.get("LIC_EXP"))

    here = os.path.dirname(os.path.abspath(__file__))
    license_dir = os.path.normpath(os.path.join(here, "..", "licenses"))
    if not os.path.isdir(license_dir):
        os.makedirs(license_dir)
    path = os.path.join(license_dir, license_id + ".json")
    existed = os.path.isfile(path)

    message = ("halieum|v=1|id=" + license_id + "|exp=" + exp).encode("utf-8")
    key = RSA.import_key(pem)
    signature = pkcs1_15.new(key).sign(SHA256.new(message))

    blob = {
        "v": 1,
        "kid": kid,
        "id": license_id,
        "exp": exp,
        "sig": base64.b64encode(signature).decode("ascii"),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(blob, handle, indent=2, sort_keys=True)
        handle.write("\n")

    sys.stdout.write("[sign_license] %s id=%s exp=%s -> %s\n"
                     % ("updated" if existed else "created",
                        license_id, exp, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
