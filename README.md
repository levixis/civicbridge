# CivicBridge — local government-service interoperability project

CivicBridge is a Django platform for consent-controlled exchange between independently running departmental services. This release runs **locally only**. No online deployment has been performed.

The platform implements versioned service workflows, reusable JSON/CSV connectors, reviewed cross-department identity mappings, local federated sign-in, durable exchange/event processing, unified tracking, notifications, audit integrity and service-deadline monitoring. It is a working local implementation with fictional seeded records; it does not establish access to live government systems.

## Start locally

Python 3.12 is recommended. Extract this archive, open a terminal inside **civicbridge**, and create a virtual environment:

```sh
python -m venv .venv
```

Activate it on Windows Command Prompt with `.venv\Scripts\activate.bat`, on PowerShell with `.venv\Scripts\Activate.ps1`, or on macOS/Linux with `source .venv/bin/activate`.

```sh
python -m pip install -r requirements.txt
python scripts/run_local.py --seed
```

The launcher creates or upgrades `.env` without replacing existing secrets, generates a private local identity signing key, migrates four separate databases, creates fictional seed data, and starts five processes. New account passwords are printed once. Existing passwords and records are preserved. Ctrl+C stops the child processes.

| Local address | Component |
| --- | --- |
| http://127.0.0.1:8000/services/ | Citizen portal and service catalog |
| http://127.0.0.1:8000/services/workspace/ | Citizen/reviewer application workspace |
| http://127.0.0.1:8001/ | Independent Revenue registry |
| http://127.0.0.1:8002/ | Independent Municipality registry |
| http://127.0.0.1:8003/ | Local shared identity provider |
| Background process | Exchange worker, events, notifications, expiry cleanup and deadline alerts |

Use **127.0.0.1 consistently** for sign-in: redirect URIs are registered exactly. Using `localhost` for one component and `127.0.0.1` for another creates different cookie/session contexts.

## Accounts and shared sign-in

Select **Shared sign-in** on a login page. The Identity service has fictional development accounts `citizen`, `education`, `welfare`, `operator`, `revenue` and `municipality`. Use the **Identity** password printed for the chosen account, not its separate department password. Local department login remains available.

Shared sign-in accepts the username or email address for the same Identity account. The fictional demo addresses use `username@civicbridge.test`, for example `citizen@civicbridge.test`. New shared identities can add an email during registration. Portal-only accounts can enter their registered email under the **Local portal account** form.

Portal seed accounts have reviewed local roles: Education reviews scholarships, Welfare reviews housing, and the operator configures workflows and reviews identity claims. Revenue and Municipality staff are provisioned only in their respective source services. An unprovisioned identity cannot become department staff. A new identity can create a citizen profile in the portal, but needs reviewed department ID links before fetching records.

Signing out ends that application's session. The next shared sign-in to that application asks for credentials so you can switch accounts. You can also select **Use a different shared account** on a sign-in page. Application sessions expire after one hour.

## Two complete local journeys

### Student scholarship

1. Sign in as `citizen`, open Services and start Student scholarship.
2. Authorise the listed income record for this service.
3. The worker retrieves it from the independent Revenue HTTP API, maps it to common schema 1.0, validates it and encrypts the shared copy.
4. Sign in as `education` and open the service workspace. Record a reviewed decision with a note.
5. The citizen sees the decision and receives an inbox notification. Revenue's Application tracker receives authenticated status events.

### Housing assistance

The citizen authorises income, residence and household records. The same engine calls Revenue JSON, Municipality JSON and Municipality's legacy CSV endpoint. Welfare reviews the combined records and records a decision. Both source services receive the unified application's status through durable event deliveries. No document upload is required.

Seed identities link fictional `REV-MH-1001` and `MUN-MH-2001` to one citizen UUID. These are local examples, not Maharashtra government identifiers.

## Configure services and resolve identities

As `operator`, open **Workflows**. A workflow has 2–10 sequential steps, each either a registered connector fetch or a reviewed departmental decision. Publish a new version, or copy an existing definition into another version. Published definitions are immutable through the application. Every application keeps its original workflow snapshot.

Supported reviewer roles are Education Officers, Welfare Officers and Municipal Reviewers. Workflow definitions accept no Python code or arbitrary URLs. Registered connectors and record mappings are in `integration/adapters.py`. Another department needs a reviewed adapter contract and trusted provider configuration; new workflows using existing connectors require no code change.

Citizens request/correct department mappings under Reviewed identity links. Operators must independently verify ownership and record evidence. Duplicate department identifiers are blocked as conflicts. Corrections revoke affected grants and remove shared records; the platform does not guess identities or automatically merge people.

Provision reviewed portal roles with:

```sh
python manage.py provision_role USERNAME welfare
```

Roles also include `education`, `operator` and `municipal`. Bind a reviewed local account to a verified Identity subject using that component's manage.py:

```sh
python manage.py bind_identity USERNAME SUBJECT_UUID
```

Obtain the subject from the trusted identity administrator. Never bind staff accounts merely because an email or username matches. Unknown SSO identities in the portal receive new citizen accounts without staff privileges.

## Queue, consent and audit behaviour

- One active fetch per application; bounded HTTP reads and four attempts with backoff. Worker leases recover interrupted work.
- Signed, short-lived provider grants contain the request, reviewed subject, consent revision, audience, purpose and scope. Consent is checked again after network IO.
- Record copies are encrypted with Fernet. Consent expires after seven days; revocation removes copies immediately. Expiry blocks access immediately and the worker removes retained copies.
- A consent refresh requires fresh source retrieval. Revoking a partially reviewed multi-review journey withdraws it; begin a new request rather than reusing an old reviewer decision. Completed decisions remain recorded after revocation.
- Transactional outbox events deliver to citizen/reviewer inboxes and authenticated department tracker endpoints. Deliveries are idempotent, leased and retried. Failed deliveries can be retried by an operator. Event sequence checks stop delayed deliveries regressing source trackers.
- The platform's HMAC audit chain covers framework actions and new legacy portal audit entries. It detects changed/deleted rows and missing tails against its stored head. Run `python manage.py verify_audit` and retain the printed checkpoint independently. A host administrator who controls the key and database can rewrite both; this is not an externally immutable ledger. Existing pre-upgrade audit rows are not retroactively certified.
- Monitoring reports actual connector latency, completed/on-time requests, mean completion hours, overdue requests and failed events. Deadline breaches generate durable alerts once per request. No improvement percentage is claimed without a baseline.

## Official API Setu sandbox

The **API Sandbox** page is a separate sample-only workspace. Its official mode uses the public eDistrict Uttar Pradesh income-certificate contract. The inspected public sample returned `404 record_not_found`; Python access from this environment timed out. Successful official certificate retrieval remains unverified. A separate, explicitly labelled offline fixture is available. Sandbox records cannot influence departmental decisions.

```sh
python manage.py check_apisetu_sandbox
```

See `SANDBOX_GUIDE.md` for the fixed sample, exact headers, evidence and limits. The portal remains local; choosing official mode makes an outbound sample HTTPS request.

## Verification

```sh
python scripts/check_local.py
```

This collects static files, checks all four projects and migration drift, runs their test suites, and runs two HTTP integration scripts using temporary databases. The tests do not modify normal databases or call government services. See `VERIFICATION.md` for results and limits.

## Optional local containers

The Python launcher is the validated route. A complete local container profile is supplied but has not been executed in this environment:

```sh
python scripts/init_env.py
docker compose -f compose.platform.yaml up --build
```

Seed the four component containers with their respective seed commands, then run `seed_platform` in the portal container. Ports bind to loopback. SQLite volumes persist data. The older `compose.yaml` and recipes under `deploy/legacy/` describe the previous two-service architecture and are historical references, not current startup instructions. Do not use a previously configured external PostgreSQL host in the local container profile.

## Boundaries

This release supports sequential fetch/review workflows. It does not implement arbitrary branching/parallel BPMN, government SSO, national identity verification, government signature validation, MFA, coordinated single logout, or event adapters for externally changed/revoked government certificates. Source edits do not invalidate earlier shared copies automatically; reviewers should request fresh data before decisions where current source state matters.

The local Identity service implements a focused authorization-code flow with PKCE S256, signed RS256 ID tokens, discovery and JWKS. It is not an OpenID certification claim or a production identity product. Local HTTP is restricted to loopback; container-only service names require an explicit trusted internal-host configuration.

Tests use SQLite and one exchange worker. Docker execution, PostgreSQL concurrency, load testing, SMTP, external TLS, backup/restore rehearsal and an independent security review remain unverified. Live departmental use needs authorised contracts, organisational identity/data policies and deployment validation. The project can be evaluated entirely offline with the local services; online deployment is not required.

## Documentation

- `LOCAL_PLATFORM_GUIDE.md`: detailed demonstration and requirements mapping.
- `API_CONTRACT.md`: original Revenue exchange contract.
- `contracts/`: common record JSON Schema and source OpenAPI descriptions.
- `SANDBOX_GUIDE.md`: official sandbox limits.
- `SYLLABUS_MAPPING.md`: INT253 coverage.
- `OPERATIONS.md`: operational notes plus local platform addendum.
