"""Tenant credential metadata contracts. Secret material is never modeled here."""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aria.identity.models import validate_structural_id


class CredentialProvider(StrEnum):
    jira = "jira"


class CredentialStatus(StrEnum):
    active = "active"
    revoked = "revoked"


class CredentialMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    credential_id: str
    tenant_id: str
    provider: CredentialProvider
    label: str = Field(min_length=1, max_length=160)
    username: str = Field(min_length=1, max_length=320)
    endpoint_url: str = Field(min_length=1, max_length=2048)
    key_id: str = Field(min_length=8, max_length=64)
    version: int = Field(ge=1)
    status: CredentialStatus
    created_at: datetime
    updated_at: datetime

    @field_validator("credential_id")
    @classmethod
    def _credential_id(cls, value: str) -> str:
        return validate_structural_id(value, field_name="credential_id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str) -> str:
        return validate_structural_id(value, field_name="tenant_id")


def utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = ["CredentialMetadata", "CredentialProvider", "CredentialStatus", "utc_now"]
