# Epic 1 Review Gate — 2026-09-09

## A. Epic verdict

**EPIC 1 — APPROVED FOR MERGE**

This verdict applies to `codex/epic-01-platform-foundation` at `cbab4e9` **with the uncommitted review fixes listed below**. The original committed head contains the reproduced defects and should not be merged without these fixes. Human review, authorized commit/push, and passing CI on that resulting revision remain required. No commit, push, merge, or Epic 2 branch was created during this review.

Reviewed T0101–T0106 against the roadmap, product invariants, architecture/ADRs, GitHub issues #1/#3/#5, and the T0104–T0106 PR descriptions. GitHub metadata confirms the primary branch is `master`.

## B. Findings

### Blocker

None remaining after fixes.

### Major

All fixed:

- `/api/docs/` returned HTTP 500 because Django had no template backend. Reproduced `TemplateDoesNotExist: drf_spectacular/swagger_ui.html`; added the packaged-template loader and regression coverage. The pre-fix health tests and schema endpoint both passed, so existing CI did not catch this.
- CI pushes targeted `main` although the primary branch is `master`. Backend lint required by T0106 was absent. Corrected the branch and added pinned Ruff development tooling and a CI lint step. Existing migration consistency, migrations, and test steps were retained.
- Local PostgreSQL and MinIO ports bound to all interfaces while using documented development credentials. Restricted the three published ports to loopback; both services remained healthy after recreation, with the same persistent volumes.
- The infrastructure README ran Compose from `infra/docker` without loading the repository-root `.env`, allowing Compose and Django to use different database credentials/ports. Both documented entry points now explicitly select the same file. Verified their resolved service configurations are identical. See [Docker interpolation documentation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

### Minor

All fixed:

- Frontend configuration was placed in the root Django environment, which Next.js does not load. The typed client silently fell back to a hard-coded loopback origin. Added a frontend environment template and an explicit missing-configuration error; the standalone shell still builds without API configuration.
- Local type generation required an API server at a fixed address, while CI used a different file-generation sequence. Both now use the same npm command with validated backend schema export and TypeScript generation. The intermediate schema is ignored.
- npm reported two high-severity package findings caused by one transitive `js-yaml` denial-of-service advisory in the development generator. Redocly pins the affected parser, so a scoped override uses patched 4.3.2. The lockfile changes only that nested parser resolution. Fresh `npm ci` reports zero vulnerabilities. See [GHSA-2883-xcg3-v3hh](https://github.com/advisories/GHSA-2883-xcg3-v3hh).
- README files, AGENTS, the architecture overview, and relevant ADR statuses still described earlier task boundaries or unimplemented foundations. Corrected their implementation/setup statements without changing product requirements or resolving recorded source ambiguities.

### Nit

None raised.

## C. Actual validation results

Validation used Windows, Python 3.12.4, and Node 24.19.0. The system's default Node 20 does not meet the documented requirement; a supported installed runtime was used. An old repository preview on port 3103 locked Next.js dependencies; it was stopped for installation and restored after the build.

A separate local clone under ignored `.cache/epic1-clean-review` received the reviewed source fixes, a copy of `.env.example`, a newly created virtual environment, and a fresh npm installation. No existing `.env`, virtual environment, node_modules, or build output was copied. The backend and frontend gates below also passed there. Docker services were initially created during this review; the isolated checkout subsequently reused their persistent volumes.

| Check | Actual result |
| --- | --- |
| Requested `docker compose -f infra/docker/docker-compose.yml up -d` | Passed; created both containers and named volumes. |
| Final documented Compose startup with explicit environment and `--wait` | Passed in the isolated checkout. |
| PostgreSQL health/version | Healthy; SQL query confirmed PostgreSQL 17.11 and the review database. |
| MinIO health | Healthy; HTTP 200 from `/minio/health/live`; console HTTP 200. |
| Ports and persistence | Loopback 5432, 9000, 9001; `docker_postgres_data` at `/var/lib/postgresql/data`, `docker_minio_data` at `/data`. Volumes preserved across container recreation. |
| Backend dependency installation / `pip check` | Passed, including fresh virtual environment installation. |
| `python -m ruff check .` | Passed. |
| `python manage.py check` | Passed, no issues. |
| `python manage.py makemigrations --check --dry-run` | Passed, no changes detected. |
| `python manage.py migrate --noinput` | Passed against Docker PostgreSQL; no application migrations exist or were added. |
| `python manage.py test` | All 5 tests passed. Tests are database-free; migrations and a separate SQL query verified database connectivity. |
| Live `/api/health` | HTTP 200, JSON `{"status":"ok"}`. |
| Live `/api/schema/` and `/api/docs/` | Both HTTP 200; Swagger UI also rendered in the browser and displayed the health contract. |
| OpenAPI validation | `spectacular --validate --fail-on-warn` passed; OpenAPI 3.0.3. |
| `npm ci` | Passed in both checkouts; final audit reported zero vulnerabilities. |
| `npm run lint` | Passed, zero warnings. |
| `npm run typecheck` | Passed. |
| `npm run build` | Passed in both checkouts. |
| Production routing | `/` → 307 `/fa`; `/fa` → 200; `/en`, `/xx`, `/fa/missing` → 404. |
| Persian/RTL/browser | `lang=fa`, `dir=rtl`; desktop sidebar on the right; no horizontal overflow at desktop or 390px; keyboard skip link focuses main content. |
| Fresh development server | Started successfully; `/fa` returned HTTP 200 with Persian RTL HTML. |
| `npm run api:generate` | Passed in both checkouts; generated TypeScript has no contract diff from HEAD. |
| Contract drift protection | Temporarily changed a copied schema's status type to integer, regenerated, and confirmed the CI diff command failed. Restored the original generated file exactly. |
| Typed client | Live health request passed; missing origin throws clearly. A TypeScript probe confirmed unknown routes and response fields are rejected. |
| CI configuration | Inspected all three jobs; YAML parsed successfully; triggers, PostgreSQL service, backend/frontend gates, and shared generation command verified. Hosted Actions were not rerun because pushing was not authorized. |
| Repository hygiene | No tracked real `.env`, venv, node_modules, build caches, or bytecode. Recognizable private-key/token patterns were absent from tracked files and the scanned branch history. This was a targeted scan, not a full security audit. |
| Final diff | Reviewed for Epic 1 scope; `git diff --check` passed. |

The original local `.env` referred to an older database setup and was preserved. Main-checkout backend validation used process-only overrides for the newly created Docker database; isolated-checkout validation used its example-derived environment without those overrides.

## D. Architecture assessment

Epic 1 matches the approved foundation: Django 6/DRF with structured settings and a modular-monolith home for future apps; PostgreSQL as the only configured database; Next.js/TypeScript App Router, Tailwind, minimal shadcn components, and locale-aware Persian RTL; REST/OpenAPI with backend-authoritative generated TypeScript and a thin typed client; PostgreSQL/MinIO as the only local infrastructure.

Generated code is separate from handwritten client code. No manual DTO duplication, domain abstraction layers, or premature product modules were found. No authentication, organizations, commodities, RFQs, Supply Listings, Opportunity Desk, Matching, Offers, Deals, Execution Monitor, payments, application storage features, Redis, Kafka, RabbitMQ, Elasticsearch, or Kubernetes were implemented. UI design and authoritative specification/roadmap were preserved.

## E. Files changed

Paths below are relative to the repository root. All changes are uncommitted.

| File(s) | Reason |
| --- | --- |
| `apps/api/config/settings/base.py` | Enable packaged Swagger templates. |
| `apps/api/tests/test_schema.py` (new) | Validate the public schema and catch broken docs rendering. |
| `apps/api/pyproject.toml` | Add pinned development-only Ruff and focused lint configuration. |
| `.github/workflows/ci.yml` | Fix primary branch, add lint/dependency check, specify PostgreSQL healthcheck identity, restrict token permissions, reuse canonical generation, remove unused contract-job database service. |
| `infra/docker/docker-compose.yml` | Restrict published ports to loopback. |
| `apps/web/package.json` | Canonical schema/type generation and scoped patched-parser override. |
| `apps/web/package-lock.json` | Resolve nested js-yaml to patched 4.3.2. |
| `apps/web/src/lib/api/client.ts` | Require explicit API origin instead of silent hard-coded fallback. |
| `apps/web/.env.example` (new) | Document the frontend's actual environment location. |
| `.env.example` | Scope the root environment to Django/Compose and remove unused application-storage placeholders. |
| `.gitignore` | Ignore the intermediate backend schema. |
| `README.md` | Describe completed Epic 1, setup, infrastructure, contract, and CI commands. |
| `apps/api/README.md` | Correct infrastructure setup, dependency list, schema/docs behavior, and validation commands. |
| `apps/web/README.md` | Correct API configuration/generation and document the parser override. |
| `infra/docker/README.md` | Explicit shared environment loading, ports, healthchecks, and volume semantics. |
| `AGENTS.md` | Record the authorized review gate scope and preserve owner review/Git restrictions. |
| `docs/architecture/overview.md` | Replace obsolete documentation-only implementation statements. |
| `docs/adr/README.md` | Distinguish implemented platform foundations from pending domain decisions. |
| `docs/adr/0001-django-modular-monolith.md` | Update foundation implementation status. |
| `docs/adr/0002-postgresql-source-of-truth.md` | Update PostgreSQL foundation status. |
| `docs/adr/0004-rest-openapi.md` | Record implemented schema/client tooling and endpoints. |
| `docs/adr/0007-s3-compatible-object-storage.md` | Distinguish implemented MinIO service from future application storage. |
| `docs/adr/0008-locale-aware-frontend.md` | Record implemented locale/RTL foundation. |
| `docs/delivery/epic-01-review-gate.md` (new) | Preserve this review's findings, validation evidence, and merge conditions. |

The generated TypeScript contract has no final change.

## F. Remaining risks

- The amended CI workflow has been inspected and its underlying commands passed locally, but GitHub must run it on the authorized commit before merge.
- Python transitive dependencies are not fully locked; fresh installation passed, but future installations can resolve newer transitive versions.
- Browser API calls are not integrated yet. The actual authentication/cross-origin or same-origin transport configuration must be selected when Epic 2 integration is authorized; the tested client request here was server-side.
- Swagger's interactive assets currently require CDN access. Local schema export/type generation does not require a running API or Swagger CDN.

No unresolved functional Epic 1 defect remains from this review.

## G. Merge recommendation

Merge `codex/epic-01-platform-foundation` into `master` after the owner reviews and authorizes committing/pushing these fixes and CI passes on that revision. Do not merge the original unchanged `cbab4e9`. Do not begin Epic 2 as part of this gate.
