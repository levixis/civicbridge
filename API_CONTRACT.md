# HTTP contracts — version 1

## Portal APIs
Django session authentication is required; anonymous requests redirect to `/accounts/login/`. Only the owning citizen or an Education officer can access an application. Inaccessible objects return 404. Operators have monitoring/identity privileges, not document access.

### GET /api/v1/applications/{integer-id}/
Returns `reference` (UUID), `status`, `status_label`, `updated_at` and `events` (label/created_at). Status is pending, processing, verified, approved or rejected. This response contains no certificate payload.

### POST /api/v1/applications/{integer-id}/exchange/
Requires session cookie and Django CSRF token. Returns 202 with `ok`, `message` and `job_id` when queued or already active. Returns 409 for missing/expired/revoked consent or a completed application. CSRF failure is 403; wrong method is 405. Queuing does not mean the certificate has been fetched. Use tracker/UI job history for completion.

### GET /applications/{integer-id}/document/
Returns the authorised shared certificate JSON as a private attachment, only with active consent and a stored document. It records the download and sets Cache-Control no-store. The server cannot revoke a file already downloaded to a user's device.

## Source API (separate service)
### GET /api/v1/income/{resident-id}/
No browser authentication is accepted as a substitute for service authentication. Required headers:
- Authorization: Bearer {server-only REVENUE_API_TOKEN}
- X-Consent-Grant: Django-signed payload, salt civicbridge.exchange.v1, max token age 60 seconds
- X-Request-ID: UUID of the durable exchange job

The signed payload must match the resident ID, income_certificate scope, revenue audience, Scholarship eligibility verification purpose, application UUID, consent revision UUID and a future timezone-aware expiry. The source validates the MAC/signature and these claims; it trusts the integration issuer to enforce current citizen consent. The gateway checks that consent again before committing a response.

200 returns resident_number, certificate_number, resident_name, yearly_income, district_name, issue_date, expiry_date and verified. 401 is bearer rejection; 403 invalid/expired/mismatched grant; 404 source record absent; 409 request-ID reuse for a different consent/application/identity. Other transient 429/500/502/503/504 responses and connection timeouts cause bounded retries. Response bodies are not displayed in portal errors. Redirects are not followed; TLS verification is enabled; body size is limited to 64 KiB.

The source receipt deduplicates request IDs. It does not freeze a certificate's contents: read retries can return the latest source record. The worker allows only its current lease to commit one completion.

## Normalised exchanged document
| Common field | Source field | Validation |
|---|---|---|
| document_id | certificate_number | Nonempty string, max 200 characters |
| type | Adapter-defined | income_certificate |
| holder | resident_name | Nonempty string, max 200 |
| annual_income | yearly_income | Integer, 0 through 10^12 INR |
| district | district_name | Nonempty string, max 200 |
| issued_on | issue_date | ISO date, not future |
| valid_until | expiry_date | ISO date, not expired or before issue |
| verified | verified | Must be boolean true |
| source | Adapter-defined | Revenue API |

The returned resident_number must exactly match the reviewed IdentityLink before schema translation. No fuzzy name matching is used. Shared data is encrypted in the portal database. These are this project's contracts, not claimed government standards. Actual provider onboarding requires an adapter for its authorised contract.

### GET /health/ (both services)
Returns status/service (source also includes contract version). 200 means a database check passed; 503 means unavailable. It does not expose accounts or records.

## API Setu sandbox contract

A separate SandboxRun queue calls POST https://sandbox.api-setu.in/certificate/v3/edistrictup/incer with the exact public playground headers/body in SANDBOX_GUIDE.md. It never substitutes for the authenticated Revenue API or feeds Application/decision records. The public example returned 404 record_not_found in the official browser playground. Successful response structure remains unverified against that service; the UI exposes a bounded escaped payload without inventing a common income-certificate schema.

Local browser routes (session authentication, owner-only):
- GET/POST `/sandbox/`: paginated history and consent form; POST queues one sample run.
- GET `/sandbox/{uuid}/`: inspect source, status, attempts and encrypted response while consent is active.
- GET `/sandbox/{uuid}/status/`: progress JSON without response body.
- POST `/sandbox/{uuid}/revoke/`: revoke consent and remove stored response.

Mutations require CSRF. Private pages/status use Cache-Control private, no-store. Unknown or foreign run IDs return 404. See SANDBOX_GUIDE.md for expiry, error/retry handling and sample/live boundaries.

## Generalised local platform release

`integration/adapters.py` provides one ContractAdapter interface for Revenue JSON, Municipality JSON and Municipality legacy CSV. All produce the versioned common record in `contracts/common-record.schema.json`. New workflow applications use per-provider/per-scope ShareConsent grants. Revenue now accepts a bounded nonempty purpose from the trusted signed grant rather than one hard-coded scholarship purpose; scope, audience, resident, request ID, revision, signature age and grant expiry checks remain enforced.

Both local providers accept authenticated `POST /api/v1/events/` with event UUID, application UUID, sequence, kind, timestamp and a bounded metadata-only payload. Duplicate IDs are idempotent only when their full payload digest matches; sequence conflicts return 409. Mirrors update only for higher application event sequences. No certificate content, citizen profile, government identifier or reviewer note is included in these status events.

Identity authentication is a separate local code/PKCE flow with RS256 ID tokens and JWKS. API bearer credentials are never obtained from citizen login tokens. See `contracts/sources.openapi.yaml` and LOCAL_PLATFORM_GUIDE.md. No production publisher API contract is implied by these local endpoints.
