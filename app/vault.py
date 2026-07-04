"""Encrypted API-key vault.

Crypto matches the original browser prototype so blobs are interchangeable:
PBKDF2-HMAC-SHA256 (200k iterations) derives a 256-bit key from the passphrase;
AES-256-GCM with a random 12-byte IV encrypts each value. Ciphertext is stored
as base64 {v,salt,iv,ct} JSON in vault_secrets.blob.

Unlock derives the key once and holds it in memory (auto-locks after idle).
Individual keys are decrypted on demand for provider calls, then dropped.
A plaintext fallback mode stores keys unencrypted for users who accept the risk.
"""
from __future__ import annotations

import base64
import json
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import db
from .config import settings
from .util import audit, now_iso

ITERATIONS = 200_000
_CHECK_PLAINTEXT = b"gofindme-vault-ok"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _ub64(s: str) -> bytes:
    return base64.b64decode(s)


def _derive(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_value(passphrase: str, plaintext: str) -> str:
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = _derive(passphrase, salt)
    ct = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)
    return json.dumps({"v": 1, "salt": _b64(salt), "iv": _b64(iv), "ct": _b64(ct)})


def decrypt_value(passphrase: str, blob: str) -> str:
    obj = json.loads(blob)
    key = _derive(passphrase, _ub64(obj["salt"]))
    pt = AESGCM(key).decrypt(_ub64(obj["iv"]), _ub64(obj["ct"]), None)
    return pt.decode("utf-8")


class VaultState:
    """Holds the active passphrase in memory while unlocked."""

    def __init__(self) -> None:
        self._passphrase: str | None = None
        self._last_use: float = 0.0

    @property
    def plaintext_mode(self) -> bool:
        return settings().vault_plaintext

    def _idle_expired(self) -> bool:
        idle = settings().vault_idle_minutes * 60
        return self._passphrase is not None and (time.time() - self._last_use) > idle

    @property
    def unlocked(self) -> bool:
        if self.plaintext_mode:
            return True
        if self._idle_expired():
            self.lock()
        return self._passphrase is not None

    def _touch(self) -> None:
        self._last_use = time.time()

    def unlock(self, passphrase: str) -> None:
        if self.plaintext_mode:
            return
        meta = db.query_one("SELECT check_blob FROM vault_meta WHERE id=1")
        if meta is None:
            # First unlock establishes the passphrase via a check-blob.
            blob = encrypt_value(passphrase, _CHECK_PLAINTEXT.decode("latin-1"))
            db.execute(
                "INSERT INTO vault_meta (id, check_blob, created_at) VALUES (1, ?, ?)",
                (blob, now_iso()),
            )
        else:
            try:
                if decrypt_value(passphrase, meta["check_blob"]) != _CHECK_PLAINTEXT.decode("latin-1"):
                    raise ValueError
            except Exception:
                audit("warn", "vault", "unlock failed")
                raise ValueError("Wrong passphrase")
        self._passphrase = passphrase
        self._touch()
        audit("audit", "vault", "unlocked")

    def lock(self) -> None:
        self._passphrase = None
        audit("audit", "vault", "locked")

    def set_key(self, provider: str, value: str) -> None:
        if self.plaintext_mode:
            blob, mode = value, "plaintext"
        else:
            if not self.unlocked:
                raise ValueError("Vault is locked")
            assert self._passphrase is not None
            blob, mode = encrypt_value(self._passphrase, value), "encrypted"
            self._touch()
        db.execute(
            "INSERT INTO vault_secrets (provider, blob, mode, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(provider) DO UPDATE SET blob=excluded.blob, mode=excluded.mode, "
            "updated_at=excluded.updated_at",
            (provider, blob, mode, now_iso()),
        )
        audit("audit", "vault", "key set", provider=provider)

    def delete_key(self, provider: str) -> None:
        db.execute("DELETE FROM vault_secrets WHERE provider=?", (provider,))
        audit("audit", "vault", "key deleted", provider=provider)

    def get_key(self, provider: str) -> str | None:
        row = db.query_one("SELECT blob, mode FROM vault_secrets WHERE provider=?", (provider,))
        if row is None:
            return None
        if row["mode"] == "plaintext":
            return row["blob"]
        if not self.unlocked:
            raise ValueError("Vault is locked")
        assert self._passphrase is not None
        self._touch()
        return decrypt_value(self._passphrase, row["blob"])

    def configured_providers(self) -> list[str]:
        rows = db.query("SELECT provider FROM vault_secrets ORDER BY provider")
        return [r["provider"] for r in rows]

    def status(self) -> dict:
        return {
            "mode": "plaintext" if self.plaintext_mode else "encrypted",
            "unlocked": self.unlocked,
            "configured_providers": self.configured_providers(),
            "idle_minutes": settings().vault_idle_minutes,
        }


# Process-wide singleton.
vault = VaultState()
