# INT253 syllabus alignment and project explanation

## Explain the problem simply
Government departments have independent portals. A citizen applies for a scholarship on Education's portal, but their income certificate exists in Revenue's portal. If the portals cannot communicate, the citizen downloads and uploads the certificate again, and must track progress in separate places. That is fragmented service delivery.

System integration means connecting the systems. Interoperability means they can exchange and correctly interpret data despite different identifiers and formats. CivicBridge demonstrates a permission-controlled bridge, with a common record format and one visible service journey.

## Syllabus mapping
| Unit | Required topic | Concrete project evidence |
|---|---|---|
| I | Python/Django setup, project/app structures, manage.py | config, portal and departments apps; requirements; migrate, seed_demo, runserver |
| II | Views, URLs, HTTP methods, parameters, request/response, errors | citizen and department views; integer application URL parameters; GET tracker/filter; POST consent; 403/404/405 responses |
| III | DTL, variables, loops, conditions, inheritance, debugging/testing | base template; loops over applications/events; role/consent conditions; TestCase workflow tests |
| IV | Django forms, GET/POST, CSRF, redirect, validation | registration/application/consent/decision/record forms; csrf_token; filter GET; redirect after POST |
| V | Models, migrations, ORM, foreign keys, admin, groups/users | relational models and schema migrations; IdentityLink constraints; admin; department groups |
| VI | Cookies, sessions, user management, login/logout, login views | Django authentication LoginView/LogoutView, registration, login_required; database-backed sessions and session cookie |

## Project objectives
1. Reuse a verified source document without asking the citizen to upload it again.
2. Record specific citizen consent and enforce expiry/revocation.
3. Translate a source record into a common document structure.
4. Give citizens and Education the same application progress.
5. Record successes, failures and denials for operator inspection.

## Modules and relationships
Citizen belongs to a Django User. IdentityLink maps the Citizen to a Revenue resident number. IncomeCertificate belongs to the independent Revenue service and its separate database. Application belongs to Citizen. Consent belongs to one Application. Application has many Events and Audit records. Education officers decide Applications; Revenue officers issue source records; integration operators inspect exchange activity. Administrators provision identity links.

## Processing flow
Citizen submission → recorded consent → durable job → reviewed identity lookup → authenticated Revenue HTTP API → validated, encrypted shared copy → Education review → citizen tracker.

## Useful viva answers
- Why Django? It supplies views, forms, templates, ORM, admin, authentication and sessions matching INT253.
- Why middleware? A common format and access policy let the consumer use records from a differently structured source.
- Where is interoperability? Revenue exposes resident_number/yearly_income/district_name over HTTP; the portal adapter translates them to document_id/annual_income/district through a validated contract.
- Is it real government integration? No government API access is claimed. An independent Revenue service is connected through a real authenticated HTTP API. Government providers need authorised adapters.
- Why not just show two dashboards? Dashboards alone do not exchange records; the adapter, identity map, consent check and audit are the functional bridge.
- What protects access? Login, ownership checks, groups, CSRF, scoped consent and a new policy check on each exchange/decision.
- What happens on revocation? Future exchanges stop and the current shared copy is removed. An undecided verified application returns to pending; completed decisions and audit history remain.
- What happens on expiry? Document display, fetch and decisions are blocked. The worker removes expired shared copies.
- Why SQLite? It runs locally without installing a database server and demonstrates the same Django ORM and migrations.
- What is the event system? A durable database job queue performs asynchronous HTTP exchange; application events are persisted transactionally. It is not a distributed event bus.
- What makes the audit useful? It records who attempted an operation, its time, result and reason, including denied and failed exchanges.

Suggested submission title: **CivicBridge: Consent-Based Interoperability for Government Digital Services using Django**.


## Operational engineering beyond the syllabus
INT253 remains visible in every core feature. Independent service boundaries, HTTP authentication, signed transport grants, document encryption, background retry/lease processing, PostgreSQL configuration, Gunicorn/static delivery and TLS deployment are additional engineering necessary for operation beyond a single classroom process. They do not replace Django forms/templates/auth/ORM with a different frontend stack.

## Sandbox addition

The API Setu workspace adds a separate Django model/migration, authenticated views, validated consent form, inherited templates, session/CSRF checks, UUID routing, history pagination, ORM constraints and a management command. Its worker performs actual HTTP requests with a verified public contract, bounded responses, encrypted storage, lease recovery and retries. Explain the difference between a real API error, a fictional offline fixture, and approved live citizen access during the viva. SANDBOX_GUIDE.md records the official playground's current 404 and the workspace's external-network limitation.

## Current local platform extension

The latest release generalises the original flow into two versioned services and multi-department fetch/review workflows. `integration` adds Django models, foreign keys, conditional uniqueness constraints, forms, UUID routes, inherited templates, admin restrictions and management commands. `federation` reuses Django sessions/authentication with a local shared identity provider. Municipality is a second independent Django source, exposing JSON and legacy CSV schemas through the same connector interface.

The current event system is a transactional database outbox with durable inbox and authenticated department webhook deliveries. It supports retries, deduplication and ordered source mirrors; it is not Kafka or a distributed broker. Audit integrity uses an HMAC chain and a checkpoint verifier, with the privileged-host limitation documented. See LOCAL_PLATFORM_GUIDE.md for the current requirement comparison rather than treating the original single-scholarship walkthrough as the full release scope.
