"""Operator-only CLI for private identity bootstrap and local token issuance.

The signing secret is read from ``ARIA_PRIVATE_AUTH_SECRET`` and never accepted
as a command-line argument. This command is for local/private staging; production
deployments must replace the codec with an approved OIDC verifier.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta

from aria.identity import (
    HmacTokenCodec,
    IdentityStore,
    MembershipStatus,
    Principal,
    PrincipalStatus,
    PrincipalType,
    Tenant,
    TenantStatus,
)


def _codec() -> HmacTokenCodec:
    return HmacTokenCodec(
        os.getenv("ARIA_PRIVATE_AUTH_SECRET", ""),
        issuer=os.getenv("ARIA_AUTH_ISSUER", "aria-private-staging"),
        audience=os.getenv("ARIA_AUTH_AUDIENCE", "aria-platform"),
    )


def _issue(
    store: IdentityStore,
    codec: HmacTokenCodec,
    *,
    tenant_id: str,
    principal_id: str,
    ttl: int,
) -> str:
    tenant = store.get_tenant(tenant_id)
    principal = store.get_principal(principal_id)
    membership = store.get_membership(tenant_id, principal_id)
    if tenant is None or tenant.status is not TenantStatus.active:
        raise ValueError("tenant is not active")
    if principal is None or principal.status is not PrincipalStatus.active:
        raise ValueError("principal is not active")
    if membership is None or membership.status is not MembershipStatus.active:
        raise ValueError("membership is not active")
    return codec.issue(
        subject=principal.subject,
        principal_id=principal.principal_id,
        tenant_id=tenant.tenant_id,
        ttl=timedelta(minutes=ttl),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ARIA private identity operator utility")
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser("bootstrap", help="Create a tenant and its first owner")
    bootstrap.add_argument("--tenant-id", required=True)
    bootstrap.add_argument("--tenant-name", required=True)
    bootstrap.add_argument("--principal-id", required=True)
    bootstrap.add_argument("--subject", required=True)
    bootstrap.add_argument("--principal-name", required=True)
    bootstrap.add_argument("--ttl-minutes", type=int, default=30, choices=range(1, 61))

    issue = commands.add_parser("issue-token", help="Issue a token for an active membership")
    issue.add_argument("--tenant-id", required=True)
    issue.add_argument("--principal-id", required=True)
    issue.add_argument("--ttl-minutes", type=int, default=30, choices=range(1, 61))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = IdentityStore()
    try:
        codec = _codec()
        if args.command == "bootstrap":
            store.bootstrap_tenant(
                Tenant(tenant_id=args.tenant_id, display_name=args.tenant_name),
                Principal(
                    principal_id=args.principal_id,
                    subject=args.subject,
                    principal_type=PrincipalType.human,
                    display_name=args.principal_name,
                ),
            )
        token = _issue(
            store,
            codec,
            tenant_id=args.tenant_id,
            principal_id=args.principal_id,
            ttl=args.ttl_minutes,
        )
        print(
            json.dumps(
                {
                    "tenant_id": args.tenant_id,
                    "principal_id": args.principal_id,
                    "token": token,
                    "expires_in_minutes": args.ttl_minutes,
                }
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error_code": "identity_operator_error",
                    "error_type": type(exc).__name__,
                    "detail": "details redacted",
                }
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
