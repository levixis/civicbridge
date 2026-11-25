# CivicBridge

CivicBridge is a Django project that lets citizens apply for a service and authorise departments to share existing records. It demonstrates the [SIH26129 interoperability challenge](https://sih.gov.in/sih2026PS) and the INT253 Django syllabus using fictional records. Revenue and Municipality each keep their own database. The portal coordinates the exchange, review and decision.

[Open the hosted grading demo](https://civicbridge-u80b.onrender.com/services/).

- [Run locally](#run-locally)
- [Walk through the demo](#walk-through-the-demo)
- [Find and explain the code](#find-and-explain-the-code)
- [Run the checks](#run-the-checks)
- [Host the grading demo on Render](#host-the-grading-demo-on-render)
- [Contracts and limits](#contracts-and-limits)

## Run locally

Clone [the GitHub repository](https://github.com/levixis/civicbridge) and open its folder. Use Python 3.12.

```sh
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on macOS or Linux, `.venv\Scripts\Activate.ps1` in PowerShell, or `.venv\Scripts\activate.bat` in Windows Command Prompt.

```sh
python -m pip install -r requirements.txt
python scripts/run_local.py --seed
```

Open [the service catalogue](http://127.0.0.1:8000/services/). Revenue is on port 8001, Municipality on 8002, and Identity on 8003. The exchange worker runs in the background. Use `127.0.0.1` consistently because the shared sign-in checks its registered callback addresses. Press Ctrl+C to stop the services.

Choose **Citizen sign-in → Continue with shared sign-in** to apply as a citizen. To review applications or manage records, choose **Department staff** and select your department. Use the **Identity sign-in** password printed for the selected account. Existing portal accounts can sign in under **Sign in with an existing portal password**. The launcher prints new passwords once and preserves accounts and records on subsequent runs. Use separate browser profiles for the citizen and staff accounts.

## Walk through the demo

| Journey | Citizen shares | Reviewer | Department tracker |
| --- | --- | --- | --- |
| Student scholarship | Revenue income certificate | `education` | Revenue |
| Housing assistance | Revenue income plus Municipality residence and household records | `welfare` | Revenue and Municipality |

1. Sign in as `citizen`, select a service and submit an application.
2. Review the requested records and select **Allow sharing**. Follow the tracker as the worker retrieves and validates the records. Housing shows both JSON and legacy CSV mapped to common record format 1.0.
3. In a separate browser profile, open **Staff sign-in**, choose Education or Welfare, and record a decision with a note.
4. Return to the citizen profile to see the decision and Inbox notification. The `revenue` and `municipality` accounts can open their departmental trackers.
5. Use `operator` to show connector latency, overdue requests and failed deliveries. Copy a workflow, edit the sequential fetch/review steps, and publish a new version. New applications use the latest published version and existing ones retain their original steps.
6. Revoke sharing after a decision. The shared record copies are removed and the decision remains in the tracker.

## Find and explain the code

For any module, start at its URL or entry point. Explain who can call it, the input it validates, what it reads or changes, and what the user sees. Then open a test that shows success or rejection.

| If asked about | Open this code | Explain |
| --- | --- | --- |
| Django projects, apps and URL routing | [manage.py](manage.py), [config/settings.py](config/settings.py), [config/urls.py](config/urls.py), [integration/urls.py](integration/urls.py) | Django loads settings and resolves paths to views. The portal mounts the current workflows under `/services/`. |
| Service catalogue, HTML templates and GET/POST | [integration/views.py](integration/views.py), [catalog.html](templates/platform/catalog.html), [apply.html](templates/platform/apply.html), [base.html](templates/base.html) | GET renders the form. POST validates it and redirects to the new request. Templates inherit a shared layout. |
| Forms, CSRF and validation | [integration/forms.py](integration/forms.py), [detail.html](templates/platform/detail.html) | Django validates the application, agreement and decision note. CSRF tokens protect browser submissions. |
| Models, ORM, migrations and admin | [integration/models.py](integration/models.py), [integration/migrations](integration/migrations), [integration/admin.py](integration/admin.py), [portal/models.py](portal/models.py) | A request references a published definition, stores its own workflow snapshot and has related grants, fetch jobs and decisions. Migrations define the database changes. |
| Login, cookies, sessions and permissions | [portal/forms.py](portal/forms.py), [portal/staff_views.py](portal/staff_views.py), [portal/permissions.py](portal/permissions.py), [federation/views.py](federation/views.py) | Login creates a Django session. Groups control staff roles. Shared sign-in matches a locally provisioned issuer and subject. |
| Identity provider and reviewed department IDs | [identity/views.py](identity_service/identity/views.py), [common/tokens.py](common/tokens.py), [integration/views.py](integration/views.py) | The Identity service issues a short-lived, single-use code with PKCE and signs the ID token. Operators separately verify department ID claims. |
| Consent and record validation | [integration/engine.py](integration/engine.py), [integration/contracts.py](integration/contracts.py), [portal/crypto.py](portal/crypto.py) | Grants are scoped to a request and source. The worker rechecks the consent revision after fetching, validates the record and encrypts the shared copy. |
| Revenue and Municipality APIs | [Revenue views](revenue_service/registry/views.py), [Municipality views](municipal_service/municipal/views.py), [integration/adapters.py](integration/adapters.py) | The sources own their records. The adapters call authenticated HTTP APIs and translate their JSON or CSV fields into common format 1.0. |
| Background jobs, retries and recovery | [run_exchange_worker.py](portal/management/commands/run_exchange_worker.py), [portal/worker.py](portal/worker.py), [integration/engine.py](integration/engine.py) | Jobs live in the database. A worker claims a job for 60 seconds. Retryable fetch failures wait 10, 20 and 40 seconds before the final attempt. |
| Decision, notifications and status tracking | [integration/engine.py](integration/engine.py), [integration/views.py](integration/views.py), [source_bridge/views.py](source_bridge/views.py) | A decision and its outgoing events are saved together. The worker delivers those events afterwards. Source trackers ignore duplicate or older events. |
| Audit and service deadlines | [integration/audit.py](integration/audit.py), [integration/engine.py](integration/engine.py), [monitor.html](templates/platform/monitor.html) | The audit chain detects edits or missing entries against its stored head. The monitor displays measured connector latency and counts requests completed on time. |
| API Setu sample workspace | [portal/sandbox.py](portal/sandbox.py), [portal/sandbox_views.py](portal/sandbox_views.py) | The local sandbox tests a fixed public sample or a fictional offline fixture. Both are separate from application decisions. |
| Original scholarship code | [portal/views.py](portal/views.py), [portal/services.py](portal/services.py), [portal/worker.py](portal/worker.py) | The original screens and data still have support. The current catalogue uses the general workflow in `integration/`. |
| Tests and deployment | [integration/tests.py](integration/tests.py), [scripts/check_local.py](scripts/check_local.py), [scripts/run_hosted.py](scripts/run_hosted.py) | Django tests validate rules. HTTP smoke tests run the services independently. The hosted launcher keeps the worker and the four web services together behind one address. |

### Questions to practise

- **What happens after the citizen gives consent?** Find `grant`, `enqueue_current` and `process_fetch` in `integration/engine.py`. The grant and job are saved, the worker calls the source, and valid evidence advances the request to the next step.
- **Why separate the databases?** Each registry operates independently and remains the authority for its records. The portal gets permission and calls an API to obtain a temporary copy.
- **What happens during a department outage?** The portal can still show the saved status. The worker retries temporary failures and an exhausted fetch can be tried again by the citizen.
- **Can any staff member approve?** The active step specifies a reviewer group and the decision code enforces that group, active permission and valid evidence.
- **What happens if consent is revoked mid-fetch?** The worker checks again before saving the response. Revocation cancels the job and clears shared copies. A final decision stays recorded.
- **How does single sign-on differ from a department role?** Shared sign-in proves identity. Each service decides which permissions that identity has through its own Django account and groups.

## Run the checks

```sh
python scripts/check_local.py
python manage.py verify_audit
```

The first command runs Django checks, migration checks, static collection, test suites and two HTTP integration scripts. The HTTP checks use isolated databases and loopback servers. The audit command verifies the active portal database and prints a checkpoint you can retain independently.

The current local verification passed 140 Django tests and both HTTP scripts. Two portal-only tests were skipped when running the same suite against the source services.

## Host the grading demo on Render

The repository includes a [Render Blueprint](render.yaml) for **one Free web service**. One public address serves the portal, Revenue, Municipality and Identity. The exchange worker runs in the same Docker container and the four Django services keep separate SQLite databases.

1. Sign in to [Render](https://dashboard.render.com/) and connect GitHub. Create a **Blueprint** from `levixis/civicbridge` on `main`. Confirm the service shows **Free** before deploying.
2. Once the service is live, open its `onrender.com` URL and confirm the catalogue loads. Revenue is at `/revenue/`, Municipality at `/municipality/` and Identity at `/identity/`.
3. In the Render service's **Environment** settings, retrieve the generated `DEMO_CITIZEN_PASSWORD` and whichever reviewer passwords the teacher needs. Share the grading link and those demo credentials privately. Operator, source staff and reviewer accounts each have a separate generated password.
4. Test a submission, consent and reviewer decision on the hosted URL before adding it to the submission report.

Render may sleep after inactivity and take about a minute to reopen. Its free service storage is temporary. A restart can reset applications and decisions to fresh fictional demo data, while the generated demo passwords stay the same. The hosted demo uses `DEBUG=0`, HTTPS through Render, and separate loopback ports for the services. API Setu and outbound email are disabled in this profile. [Render Free limits](https://render.com/docs/free)

## Contracts and limits

- [Common record JSON Schema](contracts/common-record.schema.json) defines record format 1.0. [Source OpenAPI contract](contracts/sources.openapi.yaml) describes the Revenue income, Municipality residence and household, and status event endpoints.
- The current portal exposes tracker JSON at `GET /services/api/requests/{uuid}/`. It checks request ownership or staff access and returns the status, current step, due date and event history.
- The original scholarship API remains at `GET /api/v1/applications/{id}/`. The exchange endpoint is `POST /api/v1/applications/{id}/exchange/`, and the encrypted copy can be read through the authorised document view.
- The API Setu adapter sends the public sample from [sandbox_samples](portal/sandbox_samples/edistrictup_income.json) to the eDistrict Uttar Pradesh Income Certificate sandbox. The published sample previously returned `404 record_not_found`. Successful official retrieval remains unverified. Use `python manage.py check_apisetu_sandbox` to check the official sample explicitly. [API Setu sandbox](https://docs.apisetu.gov.in/document-central/explore-apisetu/Sandbox.html)
- CivicBridge demonstrates sequential workflows and service-level measurements with fictional local sources. Real government onboarding, production load, and a baseline for judging service-level improvement are outside the verified project scope. Earlier copies do not automatically update when a source record changes. Audit checkpoints should be kept independently of the database and signing key.
