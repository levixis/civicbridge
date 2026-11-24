# Verification record — local platform release, 7 October 2026

Runtime: Python 3.12, Django 5.2.18. Runtime dependencies remain pinned in requirements.txt.

## Current verification

**113 Django tests passed:**

| Component | Tests | Evidence |
| --- | ---: | --- |
| Portal | 70 | 29 original workflow tests, 16 official-sandbox adapter tests, 21 platform engine tests and 4 relying-party identity tests |
| Revenue | 22 | 12 original source tests, 6 authenticated event/tracker tests and 4 relying-party identity tests |
| Municipality | 14 | 4 JSON/CSV source tests, 6 event/tracker tests and 4 relying-party identity tests |
| Identity provider | 7 | Code/PKCE exchange, single-use redemption, invalid client/redirect/verifier, expiry/inactive identity, token audience/nonce/issuer/key checks, discovery and signup CSRF |

All four projects passed system checks, static collection and migration-drift checks. The supported verification command is `python scripts/check_local.py`.

## Real HTTP integration

Two automated scripts passed with independent processes and temporary SQLite databases:

1. **Original scholarship flow:** registration, reviewed identity, scoped consent, real Revenue HTTP exchange, deliberate source outage, durable retry/recovery, duplicate-request protection, encrypted storage, Education decision, tracker, revocation and ownership/role isolation. Its offline sandbox test also exercises the actual HTTP portal and worker.
2. **Current five-process platform:** portal, Revenue, Municipality, Identity and worker. The test signs in through actual authorization-code/PKCE requests, submits housing assistance, queues work while the worker is stopped, verifies one live fetch after duplicate submissions, starts the worker, retrieves JSON and CSV records over actual HTTP, verifies encrypted storage, records a Welfare decision, drains durable notifications/webhooks, and checks both independent source databases show approved. It also exercises shared identity sessions across relying parties, denies unprovisioned departmental staff access, checks anonymous application access, revokes shared copies and verifies the audit chain.

These scripts use fictional local records. They do not mock the adapters and do not call government services or modify ordinary local databases.

## Fresh local launcher

A clean copy without .env, keys, databases or collected assets was started with `scripts/run_local.py --seed`. It generated private configuration and an RSA key, migrated/seeded four separate databases, and made all four loopback health endpoints ready. The login page rendered successfully. Launcher shutdown released all HTTP ports. Existing user data was not used for this check.

## Tested failure/security behaviour

Platform tests cover multi-source consent, encryption, expired permissions before worker cleanup, refresh requiring new fetches, revocation during network IO, retry exhaustion and user retry, abandoned leases/stale workers, reviewer-role restrictions and repeated decisions, intermediate-review withdrawal, workflow version immutability/snapshots, malformed contracts, owner isolation/CSRF, idempotent notifications, failed-event retries, one-time deadline alerts to operators, duplicate identity conflicts, mapping correction invalidation, changed audit entries, missing chain tails and a deleted audit head.

Source tracker tests verify authenticated delivery, exact duplicate idempotency, event-ID/sequence conflicts and out-of-order events that cannot regress status. Sign-in tests verify issuer/subject binding rather than username/email matching and ensure unknown identities cannot inherit existing staff permissions.

## Official API Setu evidence retained

The published eDistrict Uttar Pradesh Income Certificate playground and its fixed headers/body were inspected at https://sandbox.api-setu.in/api-collection/edistrictup/0 . The official playground returned HTTP 404 record_not_found for its pre-filled placeholder parameters on 7 October 2026. Direct Python access timed out. No official 200 certificate response or live citizen retrieval has been verified.

The adapter's exact transport was separately tested through loopback HTTP/XML. Official errors are displayed as failures; the explicitly selected offline fixture never impersonates an official response and cannot influence service eligibility. See SANDBOX_GUIDE.md.

## Verification limits

- No online deployment occurred.
- Docker/Compose execution and PostgreSQL concurrency/migrations remain untested. The new complete optional local profile is compose.platform.yaml; older hosting/two-service recipes are historical references.
- No government identity provider, live government certificate, government digital-signature verification, protocol certification, public TLS, SMTP delivery, backup/restore rehearsal, visual browser QA, load test or independent security review was completed.
- The local Identity provider is a focused code/PKCE implementation, not a certified general-purpose production identity server.
- The local architecture uses sequential configurable workflows and one durable database worker, not arbitrary branching/parallel orchestration or a distributed broker.
- Source record changes do not automatically invalidate prior shared copies. The app must be extended with the actual provider's revocation/change contract before relying on such behaviour.
- HMAC audit verification detects changes against its chain/head. A privileged operator controlling both key and database can rewrite both unless an independent checkpoint is retained.

Earlier Gunicorn/deployment-setting checks applied to the previous two-service release. They are not evidence of production validation for the expanded four-service platform. Passing tests establishes the implemented local behaviour; it does not establish government approval, statutory compliance, production scale or overall SIH acceptance.
