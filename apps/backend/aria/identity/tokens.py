"""Private-staging signed access tokens.

The codec is deliberately small and local: HMAC-SHA256, strict issuer/audience,
bounded lifetime, and no role claims. Production OIDC can implement the same
verification protocol later without changing the authorization/store layer.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from aria.identity.models import TokenClaims


class AuthenticationError(PermissionError):
    """A credential is absent, malformed, invalid, or expired."""


class AuthenticationConfigurationError(RuntimeError):
    """The authenticated API boundary is not safely configured."""


class TokenVerifier(Protocol):
    def verify(self, token: str, *, now: datetime | None = None) -> TokenClaims: ...


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise AuthenticationError("invalid access token encoding") from exc


class HmacTokenCodec:
    """Issue and verify local staging tokens without storing token material."""

    def __init__(
        self,
        key: bytes | str,
        *,
        issuer: str = "aria-private-staging",
        audience: str = "aria-platform",
        max_ttl: timedelta = timedelta(hours=1),
    ) -> None:
        key_bytes = key.encode("utf-8") if isinstance(key, str) else bytes(key)
        if len(key_bytes) < 32:
            raise AuthenticationConfigurationError(
                "ARIA private authentication requires at least 32 bytes of key material"
            )
        self._key = key_bytes
        self._issuer = issuer
        self._audience = audience
        self._max_ttl = max_ttl

    def issue(
        self,
        *,
        subject: str,
        principal_id: str,
        tenant_id: str,
        ttl: timedelta = timedelta(minutes=30),
        now: datetime | None = None,
    ) -> str:
        if ttl <= timedelta(0) or ttl > self._max_ttl:
            raise ValueError("token lifetime must be positive and within the configured maximum")
        issued_at = (now or datetime.now(UTC)).astimezone(UTC)
        claims = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": subject,
            "pid": principal_id,
            "tid": tenant_id,
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + ttl).timestamp()),
            "jti": f"tok-{uuid.uuid4().hex}",
        }
        payload = _b64encode(
            json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = _b64encode(hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest())
        return f"aria1.{payload}.{signature}"

    def verify(self, token: str, *, now: datetime | None = None) -> TokenClaims:
        try:
            prefix, payload, signature = token.split(".")
        except ValueError as exc:
            raise AuthenticationError("malformed access token") from exc
        if prefix != "aria1":
            raise AuthenticationError("unsupported access token version")
        expected = hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest()
        supplied = _b64decode(signature)
        if not hmac.compare_digest(expected, supplied):
            raise AuthenticationError("invalid access token signature")
        try:
            raw = json.loads(_b64decode(payload))
            if not isinstance(raw, dict):
                raise ValueError("claims must be an object")
            if raw.get("iss") != self._issuer or raw.get("aud") != self._audience:
                raise AuthenticationError("access token issuer or audience is invalid")
            issued_at = datetime.fromtimestamp(int(raw["iat"]), UTC)
            expires_at = datetime.fromtimestamp(int(raw["exp"]), UTC)
            claims = TokenClaims(
                issuer=str(raw["iss"]),
                audience=str(raw["aud"]),
                subject=str(raw["sub"]),
                principal_id=str(raw["pid"]),
                tenant_id=str(raw["tid"]),
                issued_at=issued_at,
                expires_at=expires_at,
                token_id=str(raw["jti"]),
            )
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("invalid access token claims") from exc
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if claims.issued_at > current + timedelta(seconds=30):
            raise AuthenticationError("access token is not yet valid")
        if claims.expires_at <= current:
            raise AuthenticationError("access token has expired")
        if claims.expires_at - claims.issued_at > self._max_ttl:
            raise AuthenticationError("access token lifetime exceeds policy")
        return claims


__all__ = [
    "AuthenticationConfigurationError",
    "AuthenticationError",
    "HmacTokenCodec",
    "TokenVerifier",
]
