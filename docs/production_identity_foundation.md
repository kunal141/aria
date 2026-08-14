# ARIA Production Identity Foundation

Status: **implemented as an authenticated private-staging boundary**.

This milestone adds real signed identity and store-authoritative tenant
authorization without claiming that ARIA's older fixture APIs are already
multi-tenant.

## What is protected

The `/api/platform` surface requires a signed bearer token. The token identifies
a principal and tenant; roles and permissions are loaded from the SQLite identity
authority on every request. Revoking a membership invalidates an already-issued
token immediately.

Available operations:

```text
GET    /api/platform/me
GET    /api/platform/tenants/{tenant_id}/members
POST   /api/platform/tenants/{tenant_id}/members
DELETE /api/platform/tenants/{tenant_id}/members/{principal_id}
```

There is deliberately no HTTP bootstrap, login, token-minting, secret,
connector, or execution endpoint.

## Private staging setup

Set at least 32 bytes of random key material in the process environment. Do not
put real key material in source control.

```powershell
$env:ARIA_PRIVATE_AUTH_SECRET = "<at-least-32-random-bytes>"
Set-Location apps/backend
uv run python -m aria.identity.cli bootstrap `
  --tenant-id tenant-example `
  --tenant-name "Example Organization" `
  --principal-id owner-example `
  --subject subject-owner-example `
  --principal-name "Example Owner"
```

The command prints a short-lived private-staging bearer token. It reads the
secret from the environment rather than accepting it as a command-line argument.
Tokens and signing keys are never persisted to SQLite or the Work Ledger.

## Security properties

- Tenant, principal, and membership state lives under
  `${ARIA_DATA_DIR}/identity/store.sqlite`.
- Runtime paths are confined below `ARIA_DATA_DIR`.
- Roles are not trusted from token claims.
- Tenant and membership suspension is checked for every request.
- Cross-tenant requests fail closed.
- Service identities cannot approve work or execute actions.
- The final active tenant owner cannot be revoked.
- Identity mutations and their audit records commit through one transaction and
  a durable outbox.
- Raw exception text, bearer tokens, and signing secrets are never logged or
  persisted.

## Important boundary

This does **not** make the existing V2/V3/V4 fixture APIs multi-tenant. They retain
their accepted local-prototype behavior. Production OIDC, tenant-aware Work
Ledger writers, tenant-scoped business stores, and real read-only connectors are
separate follow-on milestones.

For production, replace the private HMAC token codec with an approved OIDC
verifier. Do not expose the operator CLI as a network service.
