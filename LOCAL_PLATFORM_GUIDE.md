# Local platform walkthrough and scope

The complete current platform starts with `python scripts/run_local.py --seed`. All four HTTP servers bind to 127.0.0.1, and a fifth process handles exchanges and events. The launcher forces local source/identity origins and SQLite databases even if an older environment contains remote provider or PostgreSQL settings; it does not overwrite those stored settings.

## What is connected

| System | Independent storage | Role in the housing journey |
| --- | --- | --- |
| Citizen/Education/Welfare portal | Portal SQLite database | Requests, scoped grants, workflow snapshots, encrypted common records, decisions, notifications and outbox |
| Revenue source | Revenue SQLite database | Income certificate issuing and authenticated JSON API |
| Municipality source | Municipal SQLite database | Residence JSON API and legacy household CSV API |
| Identity service | Identity SQLite database | Shared authentication; stable subject identifiers and single-use authorization codes |

A new request snapshots the selected service definition. Each fetch step has its own consent scope and connector. A fetched record must match a reviewed departmental subject, supported record schema, verified flag, field types and current certificate dates. Review steps require their specified local Django group. Neither the citizen nor an operator without that reviewer role can approve the request.

## Demonstrate the project in ten minutes

**Thirty-second introduction.** A housing application needs information held by two separate departments. With the citizen’s permission, CivicBridge retrieves three existing records from Revenue and Municipality, checks that they belong to the applicant, and converts them into a common format. Welfare reviews the application, and the citizen sees the decision in one tracker. The demo uses fictional records and independent local services.

1. Start the launcher. Record the separately labelled Identity account passwords printed once for new seed users.
2. On the homepage, select **Browse services**. Point out the two department sources on the Housing assistance card.
3. Select **Start application**, use shared sign-in as `citizen`, and submit the application. The application page shows which records will be shared and the reviewing department.
4. Select **Allow sharing**, then follow the progress through Revenue, Municipality and Welfare. Under Shared records, open **How this record was matched** to show that both JSON and legacy CSV are converted to common record format 1.0.
5. In a separate browser profile, sign in as `welfare`. Open the request from **Review workspace**, check the shared records, and approve it with a note.
6. Return to the citizen profile: the tracker updates and Inbox contains delivered notifications. Open each source registry as its provisioned staff user and select Application tracker: both mirrors show the decision.
7. As `operator`, inspect Platform operations: real connector health, exchange latency, deadlines, completed/on-time counts and event failures. No fabricated improvement percentage is shown.
8. Copy the scholarship workflow into a new version. Add a Municipality fetch step before the Education review, give it a unique id, and publish. New applications use this configuration; existing applications retain their earlier version.
9. Revoke citizen access on the approved housing request. The encrypted shared copy disappears while the decision remains recorded.
10. Run `python manage.py verify_audit` to verify the HMAC chain and print a checkpoint.

To demonstrate an outage, stop the Revenue process in a separately started multi-terminal setup, queue a request, and restart Revenue. Retries occur after 10, 20 and 40 seconds. After four failed attempts the request becomes exchange_failed; the citizen can authorise/retry once the source is available. The automated original HTTP test exercises outage/recovery in isolated test processes.

For worker interruption, stop the worker, submit/authorise an application, then start it. Jobs stay in the database. An interrupted running lease becomes eligible after 60 seconds. Failed event delivery does not roll back an already committed decision; it remains independently retryable.

## Requirement comparison

| Official SIH26129 component | Current local implementation | Practical boundary |
| --- | --- | --- |
| API exchange without replacing systems | Independent source databases and authenticated HTTP APIs | Demonstrated with local sources, not live government platforms |
| Common standards | Common record schema 1.0, published JSON Schema, source contracts | Internal standard, not government conformance certification |
| Master-data management | Canonical citizen UUID with reviewed per-department identifiers, conflict blocking and controlled correction | No fuzzy identity guessing or automatic account merges |
| Consent-controlled sharing | Separate scope/provider grants, expiry, revocation, pre/post-IO checks and encrypted retention | Real issuer access agreements still required |
| Single sign-on/federated identity | Local authorization-code/PKCE identity provider, RS256/JWKS, stable subject binding | Focused local implementation; no government identity provider, certification, MFA or coordinated logout |
| Event-driven notifications | Transactional outbox, inbox deliveries, provider webhooks, retries and dead-letter recovery | Database-backed messaging, one local worker; no distributed broker |
| Unified application tracking | Versioned multi-service portal workspace and event-updated source mirrors | Legacy scholarship applications are listed separately with their original workflow |
| Configurable orchestration | Immutable versions with declarative sequential fetch/review steps | No arbitrary branches, parallel orchestration or script execution |
| Reusable legacy/modern connectors | One adapter interface, registered JSON and CSV mappings | Additional provider contracts require trusted developer integration |
| Audit, access, quality and exception handling | HMAC chain, roles/ownership/CSRF, schema validation, scoped grants and retries | Privileged host/key compromise and independent security review remain outside verified guarantees |
| Monitoring and service-level outcomes | Connector measurements, deadlines, one-time breach alerts, completed/on-time counts | No measured pre-project baseline, production load or external SLA assessment |

The official statement is at https://sih.gov.in/sih2026PS under SIH26129. It describes a broad interoperability framework; it does not prescribe a specific number of connected departments or require an online student deployment. The local examples are a chosen implementation scope, not a government-approved acceptance rule.

## Sources and relevant standards

- SIH26129: https://sih.gov.in/sih2026PS
- OpenID Connect Core: https://openid.net/specs/openid-connect-core-1_0.html
- PKCE S256: https://www.rfc-editor.org/rfc/rfc7636
- Official API Setu sandbox documentation: https://docs.apisetu.gov.in/document-central/explore-apisetu/Sandbox.html

The identity implementation supports a specific subset of these protocols. Protocol-inspired implementation and tests are not OpenID certification or a claim of production readiness.
