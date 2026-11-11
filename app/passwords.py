"""Access codes and secret hashing.

Employee access codes are random, 10 characters from a 32-symbol alphabet without
look-alike characters (about 50 bits), shown as XXXXX-XXXXX. They are hashed with
scrypt and a per-secret salt; only the hash is stored. The plaintext exists once,
when it is issued (app/users.py prints it to the operator's terminal), and is never
logged, audited or persisted.

The stored format is self-describing so the cost can be raised later:
    scrypt$<N>$<r>$<p>$<salt b64>$<hash b64>
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1
CODE_LENGTH = 10
_N, _R, _P = 2**14, 8, 1  # about 16 MB and a few tens of milliseconds
_DKLEN = 32


def generate_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:5]}-{raw[5:]}"


def normalize_code(code: str) -> str:
    """Case, spaces and dashes do not matter when typing a code on a phone."""
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_secret(secret: str, *, n: int = _N, r: int = _R, p: int = _P) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_DKLEN, maxmem=64 * 1024 * 1024)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(digest)}"


def verify_secret(secret: str, stored: str | None) -> bool:
    """Constant-time check. A missing or malformed hash verifies against nothing (still spends the work)."""
    stored = stored or DUMMY_HASH
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            raise ValueError("unknown scheme")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
        digest = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
                                dklen=len(expected), maxmem=64 * 1024 * 1024)
    except Exception:
        hashlib.scrypt(b"x", salt=b"x" * 16, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=64 * 1024 * 1024)
        return False
    return hmac.compare_digest(digest, expected) and stored is not DUMMY_HASH


# A hash nobody knows the secret of: unknown names verify against it so the work done
# (and the time taken) matches a real account.
DUMMY_HASH = hash_secret(secrets.token_urlsafe(32))
