"""AES-GCM encryption for tenant credentials."""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_ENV = "ARIA_CREDENTIAL_MASTER_KEY"


class CredentialConfigurationError(RuntimeError):
    """Credential encryption is unavailable or misconfigured."""


class CredentialDecryptionError(RuntimeError):
    """Encrypted credential material failed authentication."""


@dataclass(frozen=True)
class EncryptedSecret:
    key_id: str
    nonce: bytes
    ciphertext: bytes = field(repr=False)


class CredentialCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise CredentialConfigurationError("credential master key must decode to 32 bytes")
        self._key = bytes(key)
        self.key_id = hashlib.sha256(self._key).hexdigest()[:16]
        self._cipher = AESGCM(self._key)

    @classmethod
    def from_environment(cls) -> CredentialCipher:
        raw = os.getenv(_KEY_ENV, "").strip()
        if not raw:
            raise CredentialConfigurationError("credential master key is not configured")
        try:
            key = base64.b64decode(raw.encode("ascii"), altchars=b"-_", validate=True)
        except (ValueError, UnicodeEncodeError) as exc:
            raise CredentialConfigurationError("credential master key is malformed") from exc
        return cls(key)

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")

    def encrypt(self, secret: str, *, aad: bytes) -> EncryptedSecret:
        if not secret or not secret.strip():
            raise ValueError("credential secret cannot be empty")
        if len(secret.encode("utf-8")) > 16_384:
            raise ValueError("credential secret is too large")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, secret.encode("utf-8"), aad)
        return EncryptedSecret(key_id=self.key_id, nonce=nonce, ciphertext=ciphertext)

    def decrypt(self, encrypted: EncryptedSecret, *, aad: bytes) -> str:
        if encrypted.key_id != self.key_id:
            raise CredentialDecryptionError("credential was encrypted with another key")
        try:
            plaintext = self._cipher.decrypt(encrypted.nonce, encrypted.ciphertext, aad)
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise CredentialDecryptionError("credential authentication failed") from exc


__all__ = [
    "CredentialCipher",
    "CredentialConfigurationError",
    "CredentialDecryptionError",
    "EncryptedSecret",
]
