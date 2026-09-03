# -*- coding: utf-8 -*-
"""Embedded RSA *public* keys used to verify license signatures.

The public key is safe to ship inside a public PyPI package: it can only
VERIFY signatures, never create them. The matching PRIVATE key lives solely in
the GitHub Actions secret ``HALIEUM_SIGNING_KEY`` and is used by
``tools/sign_license.py`` to sign licenses.

Generate a real keypair once with::

    pip install pycryptodome
    python tools/gen_keys.py

``gen_keys.py`` rewrites the ``PUBKEYS`` table below with the real modulus.

Structure::

    PUBKEYS = { "<kid>": (n, e), ... }

``kid`` (key id) is carried inside each license so keys can be rotated later:
add a new entry, sign new licenses with the new ``kid``, keep the old entry
until every live license has been re-issued.
"""

DEFAULT_KID = "k1"

# ---------------------------------------------------------------------------
# PLACEHOLDER KEY. While n == 0 the package treats itself as "unconfigured"
# and performs NO enforcement (fail-safe). Run tools/gen_keys.py to fill this.
# ---------------------------------------------------------------------------
PUBKEYS = {
    "k1": (
        0x0,      # <-- modulus (n) as a hex integer; replaced by gen_keys.py
        65537,    # <-- public exponent (e)
    ),
}
