# Operations and provider onboarding

## Architecture
Portal requests → portal PostgreSQL job queue → supervised worker → scoped signed grant and bearer token over HTTP → independent Revenue service → Revenue PostgreSQL. The worker translates/validates the response, encrypts the shared copy and records the event. Application state and job completion commit together. Identity/consent/decision mutations lock the application row where applicable. No distributed transaction across departments is claimed.

SQLite supports the single-worker local mode. Use PostgreSQL for multi-process production. Network IO does not hold application row locks. Job delivery is at least once: a failed worker lease expires after 60 seconds; another worker can claim it with a new token. A stale token cannot commit a response. Four attempts are allowed; temporary outages retry after 10, 20 and 40 seconds. Failed requests return the application to pending, with a visible result and a new request action. The source receipt is idempotent for a job ID, consent revision and application identity.

## HTTPS deployment profile
Requires a real server, Docker Engine, Compose with `!reset` support (2.24.4+), DNS for two domains, and inbound ports 80/443. The default profile is loopback development only. For an initial staging deployment:
1. Run `python scripts/init_env.py`; keep generated keys private and persistent.
2. In .env set DJANGO_DEBUG=0, DJANGO_ALLOWED_HOSTS to your portal domain plus localhost/127.0.0.1 for healthchecks, and REVENUE_ALLOWED_HOSTS to the source domain plus revenue/localhost/127.0.0.1. Set PORTAL_DOMAIN and REVENUE_DOMAIN to your actual DNS names.
3. Set CSRF_TRUSTED_ORIGINS=https://YOUR_PORTAL_DOMAIN and REVENUE_CSRF_TRUSTED_ORIGINS=https://YOUR_REVENUE_DOMAIN. Configure SMTP and DEFAULT_FROM_EMAIL for password reset.
4. `docker compose -f compose.yaml -f compose.production.yaml up --build -d`.
5. `docker compose -f compose.yaml -f compose.production.yaml exec portal python manage.py check --deploy` and the equivalent `exec revenue python manage.py check --deploy`.
6. Create administrator accounts separately with createsuperuser. Register staff accounts and provision reviewed organisational roles. Development seeding is disabled.
7. Verify health, static assets, password reset mail, certificate issue, identity review, exchange, decisions and revocation in the deployed environment before onboarding users.

The production override removes direct app ports. Caddy overwrites X-Forwarded-Proto and terminates public HTTPS; Django trusts that header only in this profile. The services share a private Compose network. The Compose adapter uses HTTP inside that network with explicit ALLOW_LOCAL_HTTP=1. This is a single-host deployment choice, not end-to-end TLS. Across hosts, disable ALLOW_LOCAL_HTTP and configure the source URL with HTTPS; keep certificate verification enabled. Strict internal-TLS deployments need appropriate network/certificate configuration and an override to the internal URL. Never put bearer/signing keys in browser JS or public configuration.

## Accounts and permissions
Citizen accounts see only their own applications. Education officers see the department queue and can decide verified requests. Operators see operational logs and review identity links but cannot download citizen certificates. Revenue staff see/edit their source-owned registry in a separate authentication domain. Superusers manage accounts. Provision staff from reviewed identities; the public registration form cannot assign groups. Login attempts are limited to five failures per peer-address/username in a 15-minute window. Behind a reverse proxy the peer limit is shared conservatively; add appropriately configured upstream rate limits for larger deployments. MFA/SSO integration is not included.

## Consent and retention
Consent applies to one application, one document type, one purpose and seven days. Source requests carry a signed consent revision, resident ID, application UUID, audience and expiry; the source also limits the signed token age to 60 seconds. The worker rechecks current consent and lease after IO. Revocation cancels queued/running jobs, removes the current encrypted shared copy and prevents new exchanges. Approved/rejected decisions remain. The worker deletes expired shared copies each tick in batches of 200. A standalone purge_expired_documents command is supplied. Expired sessions can be removed with Django's clearsessions command. Audits and source disclosure receipts are retained; organisations must define their retention schedule. Portal expiry does not delete source records. Offline source receipt verification trusts the integration issuer; federated consent authority is not implemented.

## Backup and recovery
Use PostgreSQL-native backups for each database, plus a separately protected copy of encryption/signing secrets. Losing DOCUMENT_ENCRYPTION_KEY makes shared records unreadable. Never store keys alongside openly accessible backup downloads.

Examples (private server shell, no passwords in command arguments):
```sh
docker compose exec -T portal-db sh -c 'pg_dump -U "$POSTGRES_USER" -d civicbridge -Fc' > portal.dump
docker compose exec -T revenue-db sh -c 'pg_dump -U "$POSTGRES_USER" -d revenue -Fc' > revenue.dump
```
Store these files in your approved encrypted backup system, with restrictive access. For a rehearsed restore into an empty isolated database:
```sh
docker compose exec -T portal-db sh -c 'pg_restore -U "$POSTGRES_USER" -d civicbridge --no-owner' < portal.dump
docker compose exec -T revenue-db sh -c 'pg_restore -U "$POSTGRES_USER" -d revenue --no-owner' < revenue.dump
```
Restore secrets from the protected key store before starting application processes. Test record decryption and application counts. Do not run restore against an active database containing current records. Establish backup frequency/recovery objectives according to the operating organisation. The restore procedure is provided, not exercised here.

## Monitoring and incidents
- `/health/` checks each service's own database connectivity; it does not prove the exchange worker is processing.
- `/monitor/` shows source reachability, active job count, audit results and worker heartbeat. Treat an old heartbeat as a stopped worker.
- If source is down, jobs retry automatically. Check source health, token configuration and TLS. Never mark a job succeeded manually.
- A permanent failure (bad schema, identity mismatch, missing source record, 401/403) is visible and does not retry automatically. Correct the source/link/credentials, then request a new exchange.
- If a worker crashes, restart it. Lease tokens protect against late responses from the old attempt.
- If credentials leak, stop the worker, rotate the bearer/signing keys on both services, and restart after confirming configuration. Existing issued tokens naturally expire within 60 seconds. Fernet key rotation requires re-encrypting existing rows or purging authorised shared copies and refetching; do not simply replace the encryption key while rows still use it.
- Inspect audits without exposing certificate payloads in general logs. Current logging intentionally avoids connector headers and response bodies.

## Add an actual government provider
Obtain the API access agreement and documented source schema, authentication method, sandbox, identity identifiers, consent policy, certificate validity/revocation behaviour and operational limits. Implement a new adapter with the provider's authentication and schema translation; do not assume the included Revenue token/grant format is recognised by the government provider. Configure its fixed trusted origin and secrets on the server. Add contract tests against the authorised sandbox, verification of returned identity, bounded timeouts/retries, revocation event handling, and a deployment test with no personal data. Only then onboard authorised live traffic. If a provider supports digitally signed certificates or formal consent artefacts, validate that provider's actual standard rather than equating the current signed transport grant with official certificate verification.

## Local sandbox operation

The exchange worker also processes sample-only SandboxRun records. Keep it running to process/retry tests and remove expired encrypted responses. `SANDBOX_ENABLED=0` disables new tests and cancels pending sandbox work when the worker ticks. Synchronise that setting in portal and worker environments. Sample responses use DOCUMENT_ENCRYPTION_KEY, so key backup/restore requirements apply. Revocation/expiry removes the current response copy; it does not remove database backups or audit metadata.

The API Setu endpoint and public demo credentials are fixed in code. No private API Setu credentials are needed. Do not put real identifiers or private keys in sandbox_samples. Official requests require outbound HTTPS access to sandbox.api-setu.in. A timeout or record_not_found is not verification; inspect the reported error and consult SANDBOX_GUIDE.md.

## Local platform release addendum (7 October 2026)

The complete current startup is `python scripts/run_local.py --seed`. It forces loopback providers and four SQLite databases. The native route is verified; `compose.platform.yaml` is an optional unexecuted local profile. Earlier production/two-service recipes in this document are historical architecture references and must not be used as current full-platform instructions.

Back up portal, Revenue, Municipality and Identity databases together with `.env` and `private/identity.pem`. Stop local processes before copying SQLite files, or use SQLite's online-backup facility. Losing the document encryption key loses access to encrypted copies. Losing the audit key prevents verification of existing audit entries. Changing the Identity issuer changes federated identity namespace; migrate reviewed bindings deliberately. Never include secrets/private keys in submitted source archives.

Keep audit checkpoints from `python manage.py verify_audit` in an independently controlled location. App roles cannot alter chain rows through UI; direct database administration can alter them, and verification detects changes unless a privileged attacker also rewrites the chain with the key. This is not a substitute for externally retained audit evidence.

One exchange worker handles all exchange/event/expiry/deadline jobs. Events and notifications do not require internet. Failed webhooks are retained and visible under Platform operations; operators may retry them. Source tracker sequence numbers protect against stale delivery. An event backlog does not cancel a committed departmental decision.

Federated identity mappings are provisioned by trusted administrators with `bind_identity`. No username/email matching grants access. Use source createsuperuser or an independently reviewed staff account, then bind its verified subject. Source staff roles remain separate from portal reviewer groups. The local Identity provider is a focused code/PKCE implementation and not certified production identity infrastructure.
