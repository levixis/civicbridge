# API Setu sandbox in CivicBridge

This is a local Django workspace for testing a published government API contract. It runs at **http://127.0.0.1:8000/sandbox/** after starting the project. No website has been deployed online.

## Start and use it

Follow README.md to install dependencies, then run:

```sh
python scripts/run_local.py --seed
```

Sign in with a portal account and select **API Sandbox** in the navigation. Choose a source, tick the sample-test consent checkbox, and queue the exchange. The existing worker processes it and the detail page checks progress every five seconds.

| Source | What happens | Requirements |
| --- | --- | --- |
| Official API Setu sandbox | The Django worker sends the fixed public request to API Setu over HTTPS and shows the returned status/body. | Internet access to sandbox.api-setu.in; no signup or private API key for these demonstration values. |
| Local classroom fixture | The worker returns an explicitly fictional income record locally. The response is labelled as a fixture. | No internet; no government request is made. |

The portal and its databases remain local. Selecting official mode makes an outbound request to the public sandbox; it does not publish the project. No citizen account data, local application UUIDs, phone numbers or government identity links are sent. The exact request is available for inspection before submitting.

## Verified official contract

Official playground:
https://sandbox.api-setu.in/api-collection/edistrictup/0#/docs/paths/certificate-v3-edistrictup-incer/post

Endpoint:

```text
POST https://sandbox.api-setu.in/certificate/v3/edistrictup/incer
Content-Type: application/json
Accept: application/json
X-APISETU-APIKEY: demokey123456ABCD789
X-APISETU-CLIENTID: in.gov.sandbox
```

The key and client ID above are public playground defaults, not private government credentials. The exact published pre-filled body is preserved in `portal/sandbox_samples/edistrictup_income.json`, including its demonstration consent artifact. That artifact is a sample with placeholder fields and a historical timestamp; it is not a production consent signature. CivicBridge separately records the user's consent to the local test.

On **7 October 2026**, submitting this pre-filled body in the official playground returned:

```json
{
  "error": "record_not_found",
  "errorDescription": "No record available in issuer database for given document parameters. Please check your document parameters and try again."
}
```

The HTTP status was **404**. The public parameters are `ApplicationNo: "Application No"` and `CertificateID: "CertificateID"`; these do not establish a usable matching sample record. The app does not invent a certificate or silently replace this response with fixture data. A published matching sample record or publisher guidance would be needed to demonstrate an official 200 income response.

The Python request from the development workspace also timed out. The adapter's actual HTTP transport was tested against a loopback provider with the exact path, headers and body. That verifies our transport code and XML handling, not successful access to API Setu from this environment. Recheck from your own machine with:

```sh
python manage.py check_apisetu_sandbox
```

This command uses the same adapter and fixed public sample, and reports reachability/status. It does not change your application records. A 404 means the service returned an error, not that a certificate was verified. A timeout becomes a command error.

## Processing and access

- One active test per account; duplicate submissions reuse that run. Ten new runs per hour per account.
- Durable queue with a 60-second worker lease and recovery after worker interruption.
- Timeouts and HTTP 429/500/502/503/504 retry after 10, 20 and 40 seconds, up to four attempts. Other HTTP errors finish as failed tests.
- Response bodies are limited to 64 KiB. JSON/XML/PDF responses are retained as text or base64; the UI escapes payloads and does not execute HTML or parse XML entities. No document-signature validation is claimed.
- Both success and error payloads are encrypted with the existing document key. The interface is owner-only, uses CSRF for mutations, and sets private/no-store caching headers.
- Consent lasts 24 hours. Revocation removes the response and prevents an in-flight exchange from restoring it. The running worker purges expired response copies; access is blocked immediately on expiry even while the worker is stopped.
- Audit entries contain mode, local run reference, status and bounded diagnostic messages. They do not contain response payloads. Metadata/history remains after response removal; backups follow OPERATIONS.md.
- SandboxRun has no Application foreign key and is never read by scholarship validation or Education decisions. A 200 response is labelled **Received**, never **Verified**.

Set `SANDBOX_ENABLED=0` in `.env` and restart portal/worker to disable new tests and cancel queued tests. The portal and worker must use the same setting.

## Extend to approved live access later

Live access is a separate onboarding task. It needs publisher-approved credentials, a verified issuer contract, matching record parameters, an identity/consent agreement, signature verification and a reviewed schema mapping. Do not replace this fixed sandbox URL with a production URL or insert private credentials into the sample file. Build a separate live adapter when those contracts are available.

Official sandbox documentation confirms no signup is needed for the sandbox:
https://docs.apisetu.gov.in/document-central/explore-apisetu/Sandbox.html

API Setu overview explains registration/subscription and publisher approval for live access:
https://docs.apisetu.gov.in/document-central/explore-apisetu/Overview.html
