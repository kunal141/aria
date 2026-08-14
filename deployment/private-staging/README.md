# ARIA Private Staging

This package runs the frozen ARIA platform locally as a deterministic private
staging system. It is not a public deployment and does not enable provider
models, live connectors, external writes, or production authentication.

## Boundary

- Execution mode is pinned to `offline_mock`.
- Connectors are pinned to `fixtures`.
- Live execution is disabled.
- Backend and frontend ports bind to `127.0.0.1` only.
- The service network is internal and the only persistent mount is the named
  volume at `/data/aria`.
- No API key, `.env`, provider SDK, Docker socket, privileged mode, or host
  source mount is used.
- Publication remains blocked pending employer/IP approval.

The repository's accepted execution-mode value is `offline_mock`; it is the
implemented equivalent of the planning brief's generic `mock` label.

## Prerequisites

- Docker Engine with Docker Compose v2
- At least 2 GB free memory and 2 GB free disk space
- Local access to the base images and package registries needed at image-build
  time. Runtime operation itself requires no external network.

No credentials are required. Do not provide an `.env` file or provider keys.

## Build

From the repository root:

```bash
docker compose -f compose.private.yml build --no-cache
```

The backend image is `aria-private-backend:staging`. The frontend image is
`aria-private-frontend:staging`.

The exact backend process is:

```bash
python -m uvicorn aria.api.staging:build_staging_app --factory --host 0.0.0.0 --port 8000 --no-access-log
```

The frontend process is Nginx in the foreground (`nginx -g 'daemon off;'`) on
port `8080`; same-origin `/api/*` and `/voice/*` requests proxy to the backend.

## Start And Stop

```bash
docker compose -f compose.private.yml up -d
docker compose -f compose.private.yml ps
docker compose -f compose.private.yml logs --tail=200 backend frontend
docker compose -f compose.private.yml down
```

Stopping the services does not delete the named data volume.

## Health And Smoke Tests

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8080/frontend-health
python deployment/private-staging/smoke_test.py
```

Health responses expose only safe mode/state labels. Readiness verifies the
confined data root and the staging authority stores on request; importing the
application does not create databases.

## End-To-End And Restart Proof

Run the deterministic employee workflow and retain only its generated IDs:

```bash
python deployment/private-staging/acceptance_test.py run \
  --state-file .aria-staging-acceptance.json
docker compose -f compose.private.yml restart backend
python deployment/private-staging/acceptance_test.py verify \
  --state-file .aria-staging-acceptance.json
```

Delete `.aria-staging-acceptance.json` after verification. It contains IDs,
not business input or credentials. The proof verifies the failed first quality
attempt, persisted repair, successful retry, explicit approval, manager report,
estimated ROI, unique receipts, and correlated Work Ledger timeline.

## Persistent Data

Runtime state is stored in Docker's named volume
`aria-private-staging-data`, mounted only at `/data/aria` in the backend.
Inspect its Docker-managed location without copying its contents:

```bash
docker volume inspect aria-private-staging-data
```

Do not commit, email, or publish volume contents. Treat backups as private
business data.

### Backup

Stop writes first, then create a local archive in a private directory outside
the repository:

```bash
docker compose -f compose.private.yml stop backend
docker run --rm \
  -v aria-private-staging-data:/data:ro \
  -v /approved/private/backup:/backup \
  alpine:3.21 sh -c 'tar czf /backup/aria-private-staging.tgz -C /data .'
docker compose -f compose.private.yml start backend
```

On Windows, replace `/approved/private/backup` with a Docker-accessible private
absolute directory outside this repository. Never use a shared/public folder.

### Restore

Restore only into an empty staging volume while services are stopped:

```bash
docker compose -f compose.private.yml down
docker volume create aria-private-staging-data
docker run --rm \
  -v aria-private-staging-data:/data \
  -v /approved/private/backup:/backup:ro \
  alpine:3.21 sh -c 'test -f /backup/aria-private-staging.tgz && tar xzf /backup/aria-private-staging.tgz -C /data'
docker compose -f compose.private.yml up -d
python deployment/private-staging/smoke_test.py
```

Verify the archive source and access controls before restoring it.

### Safe Reset

This permanently removes staging state. Confirm the exact volume name first:

```bash
docker compose -f compose.private.yml down
docker volume inspect aria-private-staging-data
docker volume rm aria-private-staging-data
docker compose -f compose.private.yml up -d
```

Do not use broad Docker prune commands.

## Regression Commands

Run repository tests from the host environment:

```bash
cd apps/backend
uv run --group dev python -m pytest -q tests/test_private_staging.py
uv run --group dev python -m pytest -q tests/test_v4_2_model_routing.py
uv run --group dev python -m pytest -q tests/test_final_virtual_employee.py
uv run python -m compileall -q aria
cd ../frontend
npm test -- --run
npm run build
```

The container images deliberately exclude test and provider dependencies.

## Rollback

The immutable source reference is:

```text
commit 64b93a54f94418dd4a3833608de67235d08ce716
tag    aria-final-private-platform
```

The deployment branch must never move or recreate that tag. To inspect the
frozen source without changing this branch, use a separate worktree or clone at
the tag. Rolling back containers means stopping this Compose project and
rebuilding from that verified source; it does not mean rewriting the tag.

## Tenant Credentials And Jira Reads

The staging API supports tenant-scoped AES-GCM credential custody and Jira
reads. Fixture Jira is still the default and needs no credential or network.
Credential values are accepted only by authenticated owner/admin routes and are
never returned by the API.

Generate a local vault key and place it only in the private deployment
environment:

```powershell
python -c "from aria.credentials import CredentialCipher; print(CredentialCipher.generate_key())"
```

Live Jira remains fail-closed unless all three mode/host settings are explicit:
`CONNECTOR_MODE=read_only_live`, `CONNECTOR_PROVIDER_ALLOWLIST=jira`, and the
exact Jira HTTPS hostname in `JIRA_HOST_ALLOWLIST`. It also requires the vault
key and an active tenant-owned Jira credential. Only fixed read-only GET
operations exist; there is no Jira comment, transition, create, or update route.

## Known Limitations

- Deterministic fixture/mock execution only; no real model intelligence.
- No production authentication or multi-user authorization layer.
- No live connectors, external writes, deployment automation, or public access.
- ROI is explicitly estimated and is not production financial evidence.
- Container build/start/restart proof requires Docker Engine. If Docker is not
  installed, only native/static tests can be completed and container validation
  must remain reported as blocked, never inferred.
