# Django API

T0102 provides Django 6, Django REST Framework, environment-based PostgreSQL settings, and `GET /api/health`. The response is HTTP 200 with `{"status":"ok"}`. This public JSON endpoint reports application liveness without accessing the database.

OpenAPI generation is configured via `drf-spectacular`. The generated schema is authoritative for API contracts.
New endpoints provided:
- `GET /api/schema/`: Exposes the raw OpenAPI schema.
- `GET /api/docs/`: Provides interactive API documentation using Swagger UI.

## Setup

Use Python 3.12 or newer supported by Django 6.0. PostgreSQL is the only configured database; local Compose provisions PostgreSQL 17 and its database/user. After creating the root `.env`, run `docker compose --env-file .env -f infra/docker/docker-compose.yml up -d --wait` from the repository root. See the [infrastructure guide](../../infra/docker/README.md).

From the repository root, create an ignored `.env` by copying `.env.example` if `.env` does not already exist. Replace the secret-key and database-password placeholders, and set `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, and `POSTGRES_USER` for your instance. To generate a secret after installation, run `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` and put it in `.env` as a single-quoted value.

PowerShell, from the repository root:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
cd apps/api
py -3.12 -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -e '.[dev]'
```

POSIX shell, from the repository root:

```sh
if [ ! -e .env ]; then
    cp .env.example .env
fi
cd apps/api
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

With the virtual environment active, run from `apps/api`:

| Command | Purpose |
| --- | --- |
| `python manage.py check` | Run Django system checks. |
| `python -m ruff check .` | Run backend lint. |
| `python manage.py makemigrations --check --dry-run` | Reject missing migrations. |
| `python manage.py migrate` | Connect to PostgreSQL and run pending migrations. |
| `python manage.py runserver` | Start the local API at `http://127.0.0.1:8000`. |
| `python manage.py test --settings=config.settings.test` | Run backend test suite with test-optimized settings. |
| `python manage.py spectacular --validate --fail-on-warn --file schema.yaml` | Generate and validate the OpenAPI schema. |
| `python -m pip check` | Check installed dependency compatibility. |

Visit `http://127.0.0.1:8000/api/health`, `/api/schema/`, and `/api/docs/` to verify the endpoints. Swagger uses packaged Django templates and CDN-hosted UI assets, so its interactive browser UI requires network access. Epic 2 adds Identity and Organizations migrations, Django auth/contenttypes/sessions, and PostgreSQL-backed tests. The complete `python manage.py test` command includes all foundation, identity, authorization, and review regressions. Django admin is not exposed as an application endpoint.

With this virtual environment active, `npm --prefix ../web run api:generate` runs validated schema generation and TypeScript generation together. `schema.yaml` is an ignored intermediate; commit the generated frontend types when the contract intentionally changes. CI regenerates them and fails on drift.

## Configuration

`manage.py` defaults to `config.settings.local`. Local settings load the repository-root `.env`; existing process environment variables take precedence. Required values are `DJANGO_SECRET_KEY`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`. The host defaults to `127.0.0.1` and port to `5432`.

`DJANGO_DEBUG` is a boolean (`true`/`false`); it defaults to true locally and false in production. `DJANGO_ALLOWED_HOSTS` is a comma-separated list of hostnames without schemes or ports, defaulting to loopback hosts locally.

ASGI/WSGI entry points default to `config.settings.production`, which reads only the process environment. Set `DJANGO_SETTINGS_MODULE=config.settings.production` when running management commands for production. Production rejects debug mode and missing/wildcard allowed hosts, and redirects HTTP to HTTPS. Configure TLS and trusted proxy handling for the actual deployment before use; no proxy headers are trusted by this foundation. Production server/deployment tooling is outside T0102.

Application DRF endpoints render/parse JSON. The schema supports OpenAPI representations and the docs render HTML. Django SessionAuthentication and server-side Organization permissions protect the identity/domain endpoints. The default permission denies anonymous access; health, schema/docs, CSRF bootstrap, and password login are public as designed. Protected anonymous requests return 403 under DRF SessionAuthentication. Foreign Organizations are hidden with 404; forbidden updates to accessible Organizations return 403.

## Structure and dependencies

```text
apps/api/
  manage.py
  pyproject.toml
  README.md
  config/
    __init__.py
    asgi.py
    wsgi.py
    urls.py
    views.py
    settings/
      __init__.py
      base.py
      local.py
      production.py
  tests/
    __init__.py
    test_health.py
    test_schema.py
```

This uses Django's conventional layout without a `src` path shim. Identity and Organizations live directly under `apps/api`, beside `config`, and are included in package discovery. Future apps require separate authorization. No placeholder domain apps or shared service/repository layers are needed.

Direct dependencies are pinned in `pyproject.toml`:

| Package | Reason |
| --- | --- |
| Django 6.0.8 | Required framework, settings, server entry points, migrations, and built-in test runner. |
| djangorestframework 3.18.1 | Required REST framework; JSON responses and HTTP method handling. |
| psycopg[binary] 3.3.5 | PostgreSQL adapter with bundled native client, avoiding local compiler/libpq setup. |
| django-environ 0.14.0 | Typed environment values and local `.env` loading without a custom parser. |
| drf-spectacular 0.30.0 | Authoritative OpenAPI generation, schema validation, and Swagger UI. |

Setuptools is the build backend. The `dev` extra pins Ruff 0.16.6 for the roadmap's backend lint gate; no separate test runner or production server is introduced. Transitive dependencies are resolved by pip; there is no complete dependency lock yet.


## Epic 2 session, authorization, and demo setup

The custom `identity.User` authenticates by unique email (no username) using Django password hashing. Email uniqueness uses PostgreSQL's exact text comparison; the manager normalizes the domain as Django does. Product Operator/Admin assignments are independent of Django staff/superuser flags. `/api/auth/me` exposes the current user's identity, product roles, and active memberships of active Organizations, without Django privilege flags or other users' context.

Organization profile endpoints permit only name, registration identifier, website, and country changes. Viewer/Member can read their Organization; Manager/Owner can update those profile fields. Operator can read all Organizations, including inactive ones, but has no write grant from that system role. Product Admin can update the permitted profile fields globally. An Operator with a separately authorized Owner/Manager membership retains that membership's permissions. Inactive memberships/Organizations grant no membership-based access. PUT requires the profile contract's required fields; PATCH is partial. Neither endpoint changes capabilities, roles, memberships, user security, or active status.

For the documented Next.js development origin, add to the root `.env`:

```dotenv
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
DEMO_PERSONA_SWITCHER_ENABLED=false
```

`GET /api/auth/csrf` sets the CSRF cookie. Login, logout, Organization mutations, and demo switching require the matching `X-CSRFToken` on unsafe requests. Login and switching rotate the token; read the current cookie for subsequent requests. Sessions are HttpOnly/SameSite=Lax. Production enables Secure on both session and CSRF cookies and rejects enabling demo switching. Production domains are environment configuration.

To enable a disposable local demo, explicitly set `DEMO_PERSONA_SWITCHER_ENABLED=true` in the local environment, migrate, then run:

```sh
python manage.py seed_demo_personas
python manage.py seed_demo_personas
python manage.py runserver
```

The command is idempotent and rejects disabled demo environments. It creates `buyer@demo.local` (Manager/Buyer), `supplier@demo.local` (Owner/Supplier), `broker@demo.local` (Member/Broker), and Operator/Admin users with their real system assignments and no fake Organization. Seeded users have unusable passwords: the flag-gated persona switcher is the bootstrap path. The Identity 0003 migration retires the former public seed password on existing reserved demo accounts while preserving independently configured passwords. Apply migrations when upgrading an existing demo database. Treat these reserved addresses and `Demo ...` Organizations as disposable demonstration data, never customer data.

`GET /api/auth/demo-switch` returns 404 when disabled. Its POST requires CSRF and accepts only the five fixed persona keys; a disabled endpoint or absent/inactive predefined account returns 404. A request lacking CSRF can be rejected with 403 before unavailable handling. CSRF decorator failures may be HTML; DRF session failures are JSON. No arbitrary user ID/email impersonation API exists.

Approved Epic 1 did not install Django auth, sessions, or admin and had no application migration graph. A normal Epic 1 database can therefore apply Epic 2 directly. A fresh PostgreSQL database is the recommended disposable development baseline if an independently modified database previously migrated Django's built-in User; preserving such local data is not an approved production migration requirement.

## Epic 3 commodity definitions

`commodities` is a platform-level definition module, independent of Organizations. Run `python manage.py seed_bitumen` and `python manage.py seed_base_oil` after migration. Both commands may be repeated: existing Published v1 definitions are preserved with a warning, and a newer active version is not replaced. Retired v1 is preserved and reported as unavailable for reseeding. Seeds do not update historical semantics to match newer seed code.

Authenticated reads are `GET /api/commodities/`, `GET /api/commodities/{code}/schema/`, and `GET /api/commodity-schemas/{uuid}/`. Discovery excludes inactive commodities and sorts by code. Setup commodities may have no active schema. Active retrieval follows only the explicit same-commodity Published pointer, returning 404 when unavailable; inactive commodities remain addressable by code for reference inspection. Historical retrieval includes Published/Retired and excludes Draft, even if the commodity is inactive. No Organization capability is required to read this platform catalog. Anonymous requests return 403; product write methods return 405.

Use `publish_schema(schema, activate=False)`, `retire_schema(schema)`, and `clone_schema_to_draft(schema)` from `commodities.services`. Publication validates definition metadata. Retirement rejects the currently active schema; activate a replacement or explicitly clear the pointer first. Publishing/activating v2 leaves v1 Published. Cloning copies all attributes into a distinct Draft and allocates versions under a PostgreSQL row lock. Admin status is read-only; use the domain lifecycle functions after saving draft inline edits. Admin is still not mounted as a product endpoint.

Supported model saves, lifecycle functions, Admin changes, and Django model/queryset/cascade deletions enforce historical integrity with current persisted state and transactional locks. PostgreSQL independently enforces foreign keys, unique commodity code, unique commodity/version, unique schema/key, status/type checks, and nonnegative integer fields. Semantic immutability and active-pointer ownership/status are application-enforced, not database triggers. `QuerySet.update`, `bulk_create`, `bulk_update`, `save_base`, raw SQL and historical migration models bypass these guards and are restricted to explicitly reviewed data maintenance/tests. Do not use them for production schema mutations. The seed conflict tests intentionally use such bypasses to prove reseeding preserves history.

`validate_commodity_payload(schema_version, payload)` derives Draft-7 JSON Schema from relational definitions. It never substitutes the current active version. Payloads are flat; enum options use `value`, `label_fa`, `label_en`, and optional `sort_order`; units use `canonical_unit`. Constraints use `minimum`, `maximum`, `minLength`, and `maxLength`. Optional fields may be absent, but no v1 field is nullable. Errors are `ValidationError(code='invalid_payload', params={'errors': [...]})` with stable `field`, `code`, and application-owned `message` values. UI callers can translate codes and pass field messages to the generic Form.

`python manage.py test` discovers all commodity model/lifecycle/validation/API, seed, historical integration, concurrency, and API-fixture regressions. Shared examples in `apps/web/tests/fixtures/commodity-schemas.json` are normalized actual seeded API responses; backend CI compares them and frontend CI consumes them. To deliberately regenerate after a contract change, set `UPDATE_COMMODITY_FIXTURES=1` for `python manage.py test commodities.test_contract_fixtures`, then unset it and run both test suites. No fixture contains business-instance persistence. `npm run api:generate` remains the only canonical OpenAPI/TypeScript generation path; the redundant root `schema.yml` snapshot was removed.

## Epic 13 Demo Dataset & Reset Management

### Commands

```sh
# Initial seed of the realistic demo dataset (T1301 baseline + T1302 Hero scenario):
python manage.py seed_demo_dataset

# Canonical reset to restore Demo environment back to the clean seed baseline:
python manage.py reset_demo
python manage.py reset_demo --no-input
```

### Purpose

`python manage.py reset_demo` restores the Demo environment to its canonical demonstration state after test runs, manual UI testing, or Hero Flow walk-throughs. It deletes all Demo-owned transactional state (Deal executions, milestones, logistics, Deal snapshots, awards, offers, matching runs, opportunities, invitations, and supply listings) and re-invokes the canonical seed pipeline (`seed_demo_dataset`).

### Allowed Environment & Safety Guards

To prevent accidental data loss:
- **Demo Switcher Guard**: Requires `DEMO_PERSONA_SWITCHER_ENABLED=True` (or `"true"` / `"1"`). If disabled, the command terminates immediately before performing any deletions.
- **Production Guard**: Verifies that `DJANGO_SETTINGS_MODULE` is not set to production (`config.settings.production`) and that environment flags (`ENVIRONMENT=production`, `APP_ENV=production`) are absent.
- **Interactive Confirmation**: Prompts for interactive confirmation (`Type 'yes' to continue`) unless `--no-input` is passed.

### Reset Semantics & Boundaries

The reset operation is executed inside an atomic PostgreSQL transaction (`transaction.atomic`):
- **What gets reset (Demo transactional & persona state)**:
  - All Deal Executions and operational sub-records (Milestones, Logistics, Operational Documents) linked to Demo Deals.
  - All Deals, Deal Terms Snapshots, Party Snapshots, Cost Snapshots, and Broker Attributions linked to Demo RFQs/Offers.
  - All Awards and AwardAllocations for Demo offers/RFQs.
  - All Offers (including RevisionRequests, OfferVersions, draft and submitted version pointers).
  - All MatchingRuns for Demo RFQs.
  - All Opportunities and OpportunityContactAttempts linked to Demo entities (including the Hero opportunity `OPP-2026-0001`).
  - Sequence counter for `OpportunityIdentifierSequence` reset to 0 for year 2026 to ensure deterministic opportunity sequence numbering across resets.
  - All Demo RFQs (Hero RFQ, Deal RFQs, active RFQs, expired RFQs, drafts), RFQ invitations, and supply listings.
  - External counterparties associated with Demo organizations.
  - Organization verification records and documents for Demo organizations.
  - Verification state, display names, and capabilities of canonical Demo organizations reset to baseline; any extra demo organizations deleted.
  - Canonical demo users (`buyer@demo.local`, `supplier@demo.local`, `broker@demo.local`, `operator@demo.local`, `admin@demo.local`) have their active status and system roles restored; any extra `@demo.local` users deleted.
  - Re-executes `seed_demo_dataset()`, restoring the 10 historical closed/in-progress deals, active/expired RFQs, matching runs, supply listings, and the exact Hero flow starting state.

- **What is preserved**:
  - Non-demo organizations, users, memberships, and system roles.
  - Unrelated customer/pilot RFQs, opportunities, offers, deals, and executions.
  - Platform catalog definitions and commodity schemas (`seed_bitumen`, `seed_base_oil`).
  - Reference data (geography, country catalogs, units of measurement, delivery terms).
  - Database schema and applied migrations.

### Expected Result

After executing `python manage.py reset_demo`, the database is in the exact identical state as a fresh run of `seed_demo_dataset`:
- 5 Demo Personas active with unusable passwords.
- 10 Realistic Demo Deals (Deals 1 & 2 CLOSED with 10 completed milestone executions; Deal 10 OPEN with in-progress milestones; Deals 3-9 in various operational states).
- 1 Fresh Hero Opportunity (`OPP-2026-0001`) in `PENDING_VALIDATION` ready for the Hero walkthrough.
- 2 Active RFQs (Bitumen 60/70 and Base Oil SN 500) open for bidding with matching runs and invitations.
- Deterministic, repeatable, and idempotent across multiple successive executions.

