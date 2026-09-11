# Epic 4 — Organizations, Network & Verification: execution plan

Planning and policy synchronization date: 2026-09-11. Status: owner-approved Epic 4 policies and execution protocol persisted; the current synchronization task is documentation-only and starts no implementation.

Epic integration branch: `codex/epic-04-organizations-network-verification`. At initial planning, inspected local HEAD was `8419eac5408ca88eaac9f562a9413cca64d9c3b8`, merge PR #42, with `a502bab` (Epic 3 review fixes) in its ancestry, and the working tree was clean. This establishes historical local provenance, not current hosted CI status. The synchronization preserves that existing plan and records the owner's policies below. No branches, application code, migrations, or generated contracts were changed in these documentation tasks.

## 1. Authority and readiness

Sources read: [roadmap](roadmap.md) §8 and delivery gates; [Product Specification](../product/product-spec.md) §§3–5, 21, 34–35, 42–43, 45–46, 50–60; [glossary](../domain/glossary.md); [architecture](../architecture/overview.md); [source review](../architecture/source-review.md); ADRs [0001](../adr/0001-django-modular-monolith.md), [0002](../adr/0002-postgresql-source-of-truth.md), [0004](../adr/0004-rest-openapi.md), [0007](../adr/0007-s3-compatible-object-storage.md), [0008](../adr/0008-locale-aware-frontend.md), [0009](../adr/0009-authentication-architecture.md); [Epic 1](epic-01-review-gate.md), [Epic 2](epic-02-review-gate.md), and [Epic 3](epic-03-review-gate.md) review records; and [AGENTS.md](../../AGENTS.md).

The owner's synchronization request authorizes Epic 4 under this execution protocol and approves §4's policies. AGENTS.md and roadmap now reflect that scope. This synchronization itself is documentation-only: do not implement T0401–T0406 or perform Git mutations. GitHub Issues remain the formal backlog; their live contents were not inspected or changed in these repository-only documentation tasks. Reconcile each assigned Issue with this inventory and approved policies before dispatch.

**Readiness: a fresh Jules T0403 session has sufficient repository policy context.** Dispatch must still name the assigned Issue and exact Wave Base SHA with baseline CI evidence. Wave 1 deliberately contains only T0403, so it is not a multi-session wave. Maximum concurrency is two in Waves 2 and 3, subject to the contracts and ownership below. Fifteen available slots do not imply fifteen independent tasks.

The stale scope/branch instructions in AGENTS.md and the roadmap have been reconciled. Ensure the synchronized documents are present on the recorded Wave Base before fresh sessions start. No implementation begins as part of this synchronization.

## 2. Exact roadmap inventory

Roadmap §8 labels the Epic **P1** and supplies exactly the following six tasks, in this order. Its task entries supply no task-level dependency lists, separate acceptance-criteria sections, dedicated integration task, or named Epic 4 Review Gate. The descriptions below reproduce those entries; the roadmap now links this plan's owner-approved §4 policies for detailed behavior. Dependency/file ownership tables remain execution design, not renamed roadmap tasks.

| Task ID | Exact task name | Exact roadmap description / supplied acceptance surface |
| --- | --- | --- |
| T0401 | Company Directory | List + search + filters. Filters: capability; geography; commodity; verification. |
| T0402 | Organization Profile | نمایش: company information; capabilities; commodities; geography; verification; activity summary. |
| T0403 | Verification Domain | Implement statuses: Unverified; Documents Submitted; Under Review; Basic Verified; Verified; Suspended. |
| T0404 | Verification Checklist | Operator بتواند verification items را review کند. |
| T0405 | Verification Documents | Document metadata + MinIO upload. |
| T0406 | Verification Operator UI | Operator workspace برای: pending cases; documents; notes; approve/reject/suspend. |

The Persian descriptions mean display the listed profile information (T0402), let the Operator review verification items (T0404), and an Operator workspace for the listed actions (T0406). No source task IDs or names are replaced, reordered, or invented.

## 3. Existing foundation and product boundary

Implementation evidence lives in `apps/api/organizations/{models.py,api/permissions.py,api/serializers.py,api/views.py,urls.py}`, `apps/api/identity/{models.py,serializers.py}`, and `apps/web/src/lib/{auth-context.tsx,organization-preference.ts}`.

- Organization already has UUID, name, registration_identifier, website, country, is_active, and timestamps. Extend it; do not introduce another Company identity. Epic 4 geography is exactly the existing country field under §4.
- OrganizationCapability is exactly Buyer/Supplier/Broker, multiple allowed, with unique organization/capability and valid-value DB constraints. OrganizationMembership is exactly Owner/Manager/Member/Viewer with unique organization/user and valid-role constraints. SystemRoleAssignment is exactly Operator/Admin; a user may have both. Do not introduce Trader or infer permissions from capabilities.
- Existing `/api/organizations/` provides list/retrieve/PUT/PATCH. Ordinary users see only active organizations with active memberships. Owner/Manager can update safe profile fields; Member/Viewer cannot. Operator/Admin have global read, including inactive organizations; Product Admin can update safe profile fields globally. Operator alone cannot edit profiles. Independent Owner/Manager membership can still grant that user's own profile edits.
- Django staff/superuser flags grant no Product Admin rights. The current writable profile fields are name, registration_identifier, website, country. Memberships, capabilities, roles and active state are not writable through that serializer. Preserve these controls and the reviewed foreign-object 404 behavior.
- Identity's `OrganizationContextSerializer` embeds `OrganizationSerializer`; broadening that serializer also changes `/me`. Prefer explicit safe read projections for directory/profile and verification rather than accidentally adding internal data to every session response.
- AuthProvider consumes generated `/me` types, supports zero organizations for system actors, validates selected organization IDs, and refreshes session state with a stale-response guard. Selection is UX state, never authorization. Preserve server sessions, same-origin proxy, CSRF and production-disabled demo switching.

Epic 4 delivers organization discovery/profile presentation and manual verification with evidence files and an internal Operator workspace. Verification is metadata about manual review, not a computed reputation score, real KYC integration, or proof of transaction performance. The document categories supplied by spec §34 are Company Registration, Tax ID, Trade License, Bank Details, Authorized Representative, Certifications; the owner-approved §4 policy specifies which categories each level requires; Certifications remain optional.

“Network” in the Epic title does not define a relationship model or private-network CRUD task. Preserve Broker privacy; do not infer permission to expose a Broker's contacts, create ownership links, or add relationship invitations. ExternalCounterparty belongs to T0604; conversion/contact attempts/Opportunity Desk remain later work. RFQ, Supply Listing, Offer, Matching, Deal, Execution, settlement, performance analytics and fake activity counts are out of scope. T0402 activity summary must use agreed available facts or explicit unavailable/empty state, not fabricated future transactions.

T0406 requires notes and spec §§42–43 require customer-hidden internal notes and verification auditability. The owner approves verification-local append-only notes and decision history here; do not implement generic T1101/T1102 across other entities. T0403 owns this domain boundary; T0406 consumes it. Files stay in S3-compatible storage/MinIO; PostgreSQL stores metadata. No new infrastructure category is required.

## 4. Owner-approved Epic 4 policies — 2026-09-11

The following policy text is persisted from the owner's documentation synchronization request, with heading depth adjusted only. It supplies the detailed Epic 4 policy alongside the Product Specification; it replaces the earlier unresolved-policy table.

### Verification lifecycle

Statuses remain exactly:

* Unverified
* Documents Submitted
* Under Review
* Basic Verified
* Verified
* Suspended

Do NOT introduce `Rejected`.

Approved transitions/actions:

* initial → Unverified
* Unverified → Documents Submitted via submission
* Documents Submitted → Under Review via Operator/Admin review start
* Under Review → Basic Verified via basic approval
* Under Review → Verified via full approval
* Under Review → Unverified via rejection
* Basic Verified → Under Review for upgrade/re-review
* Basic Verified → Suspended
* Verified → Suspended
* Suspended → Under Review via explicit reopen

Unsupported/repeated/stale transitions must reject without partial state/history changes.

Reject and suspend require a reason.

Lifecycle decisions/history must be atomic.

### Permissions

* Owner/Manager may submit and access verification evidence for their own active Organization.
* Member/Viewer may see only customer-safe verification state.
* Operator and Product Admin may review all verification cases, documents, checklist results and internal verification notes, and perform approved verification actions.
* Django staff/superuser alone grants no product verification authority.
* Inactive Organizations remain inspectable by Operator/Admin but do not accept new verification mutations.

### Persistence boundary

Use one current `OrganizationVerification` aggregate per Organization for v1.

Keep append-only:

* VerificationDecision history
* verification-local internal notes

Do not implement generic Epic 11 notes/audit infrastructure.

Documents/object metadata remain owned by the documents/storage boundary.

No hard deletion of verification decision history.

### Company Directory

Directory is authenticated-product-user only.

It exposes active Organizations using an explicit safe read projection.

Safe directory fields may include:

* ID
* company name
* website
* country
* capabilities
* associated commodities
* current customer-safe verification level

Do NOT expose:

* registration identifiers unless explicitly required by a later approved profile projection
* members
* system roles
* verification documents
* Bank Details
* internal notes
* audit history
* Broker private network/contact relationships

Anonymous directory access is out of scope.

### Geography and Commodity association

For Epic 4 geography means the existing `country` field.

Do not introduce city/region models.

Organization ↔ CommodityDefinition means the Organization declares that it operates in that Commodity.

It is not:

* inventory
* supply
* pricing
* transaction history

Owner/Manager may maintain their own Organization's commodity associations; Product Admin may maintain them globally.

Activity summary must use real currently available data or explicit empty/unavailable state. Never fabricate future transaction metrics.

### Checklist policy

Keep checklist/document review state separate from Organization verification state.

Use simple review outcomes:

* pending
* accepted
* rejected

For v1:

Basic Verified requires accepted:

* Company Registration
* Tax ID
* Authorized Representative

Verified additionally requires accepted:

* Trade License
* Bank Details

Certifications are optional.

Do not claim this is a universal external regulatory standard; it is the product's initial internal verification policy.

### Evidence replacement

Documents are immutable/versioned.

Replacement creates a new evidence version and retains the superseded one.

If evidence required for the Organization's current verification level is replaced:

* invalidate that category's previous review;
* transition the Organization to Documents Submitted;
* require review again.

Do not preserve stale trust from superseded evidence.

### Storage

For v1 allow:

* PDF
* JPEG
* PNG

Maximum file size:

10 MB per document.

Storage bucket/object access is private.

Object keys are generated server-side.

Clients cannot choose arbitrary object keys.

Authorized download occurs through the backend application boundary.

Owner/Manager access only their own Organization evidence.

Operator/Admin may access all verification evidence.

Superseded verification evidence is retained rather than hard-deleted.

Storage/database failure handling must avoid permanently inconsistent bytes/metadata state.

### Notes and audit

Verification internal notes:

* Operator/Admin only
* append-only for v1
* never exposed in customer-safe directory/profile/session context

Verification decisions record at least:

* actor
* action
* previous status
* resulting status
* reason where applicable
* timestamp

Reject/suspend require reason.

### Application to task boundaries

Evidence replacement is an explicit additional lifecycle event supplied by the owner, alongside the listed review actions: replacement of required evidence at Basic Verified or Verified invalidates that category's review and moves the aggregate to Documents Submitted. It is not a general-purpose status PATCH or permission to bypass suspension. Unsupported/repeated/stale transitions still reject; no mutation is allowed for an inactive Organization. Keep the new evidence version, review invalidation, lifecycle decision and history consistent under failure. Do not extend this rule to unapproved state transitions.

T0403 owns the single OrganizationVerification aggregate, guarded action contract and append-only decisions/notes. It must encode the approved approval prerequisites and evidence-replacement event contract without implementing T0404's checklist or T0405's storage. No approval may succeed by treating absent checklist integration as satisfied. T0404 connects real category outcomes to those guards; T0405 connects immutable evidence replacement; T0406 proves the complete flow. These are integrated later, so T0403's domain tests may use explicit evidence-policy inputs/test doubles without fake production evidence tables or an allow-all fallback. This preserves the existing dependency graph.

T0401 owns the organization–commodity association and its authorized management API, together with the safe directory projection. The existing membership-scoped Organization API and safe profile editing remain intact; authenticated directory access to other active companies does not grant mutation or evidence access. T0402 must not broaden registration-identifier exposure without the later explicit profile approval required above.

Remaining bounded details: define the exact pending-queue filter before T0406 and the exact byte interpretation of 10 MB before T0405 boundary tests. Endpoint names, storage failure compensation/reconciliation, and migration layout remain engineering choices within the approved policies. No remaining owner-policy decision blocks the T0403 domain session. Assigned Issue reconciliation, the actual Wave Base SHA and baseline CI evidence are still dispatch prerequisites.
## 5. Dependencies, ownership and risk inventory

All dependencies below are **derived for the proposed implementation boundaries**; the roadmap itself supplies none at task level. Hard means the complete task cannot correctly begin under this plan before the prerequisite is integrated. Soft means a task can start against the common base but must adapt to sibling integration. Independent means no required sibling output, not zero Git overlap. Earlier integrated Epic foundations and approved policies are universal prerequisites.

Backend paths below are relative to `apps/api/`, frontend paths to `apps/web/`; proposed paths do not exist yet unless identified as current hotspots.

| Task | Primary goal | Hard dependencies | Soft dependencies | Likely modules and ownership | Shared/hot files | Area | Migration risk | Security risk | Conflict risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T0401 | Search/filter directory with approved visibility and real filter data | T0403: authoritative verification state/read boundary | T0405: shared generated contract only | organizations backing associations, directory query/API, directory page/components, directory tests | organizations/models.py, api/serializers.py, api/views.py, urls.py; generated schema; shell and Persian messages | Backend / Frontend / Contract | Medium: likely org–commodity relation; organizations next migration after 0003 | High: directory scope and field leakage | High: central org model/API plus shared types/navigation |
| T0402 | Display all six supplied profile sections | T0401: backing data/read contract; T0403 transitively | T0404: refreshed verification metadata if additive | organizations profile projection/page/components, profile tests | org serializers/views/urls; `/me` embedding risk; generated schema; Persian messages | Backend / Frontend / Contract | Low: expected none; missing shared fields should be resolved in T0401 | High: private profile and internal evidence leakage | Medium: reuses integrated org contract; sibling uses verification module |
| T0403 | Establish six-state manual verification domain and agreed guarded actions | Approved Epic 1–3 baseline and lifecycle decisions | None | proposed verification app, domain service, decision history/local note contract, read projection and internal action API | config/settings/base.py, config/urls.py, pyproject.toml, generated schema, ci.yml | Backend / Contract; minimal CI plumbing | High: new verification graph, organization FK and historical policy | High: privilege escalation/state/history corruption | High globally; isolated in Wave 1 |
| T0404 | Operator reviews verification checklist/evidence | T0403 and T0405: review identity, actions and actual document metadata contract | T0402: shared generated types only | verification checklist records/services/API and dedicated tests | verification models/services/API/migrations; generated schema | Backend / Contract | Medium: verification successor migration, serialized after T0403 | High: evidence substitution and unauthorized review | Medium with profile sibling; high if paired with another verification schema writer |
| T0405 | Authorized verification metadata and real MinIO upload/access | T0403: verification ownership/FK and evidence contract | T0401: generated contract integration | proposed documents app, upload/access service/API; MinIO config, tests | config/settings/base.py, config/urls.py, pyproject.toml and relevant lock; .env.example; ci.yml; generated schema | Backend / Contract / Infra configuration | High: new documents graph plus verification FK; no organizations schema edits | High: sensitive files and object-ID/key tampering | Medium under ownership rules; generated contract overlaps directory |
| T0406 | Complete Operator workspace and Epic integration | T0402 and T0404, transitively all T0401–T0405 | None | verification pages/components, local UI strings, cross-task integration tests | application-shell.tsx, Persian messages, generated schema only if genuine API correction, shared API routes if integration defect | Frontend / Contract integration / Backend tests | Low: expected none; domain correction returns to owning task | High: controls can conceal backend failures/stale trust | Medium: broad consumption after all producers are integrated |

T0403 is before T0401 because the verification filter needs a real authoritative value. T0401 owns necessary directory/profile associations; T0402 is not a second competing foundation model task. T0404 follows T0405 because the selected checklist design reviews actual evidence metadata and its validity; building a speculative document surrogate would defeat this boundary. No dependency requires later procurement features.

Direct hard dependency graph (transitive edges omitted):

```text
Approved baseline + resolved T0403 policy
                    |
                  T0403
                 /     \
              T0401   T0405
                |       |
              T0402   T0404
                 \     /
                  T0406
                    |
          Epic 4 Codex Review Gate
```

Independent sibling pairs: T0401/T0405, then T0402/T0404. Each pair has only a soft generated-contract synchronization dependency. Every other pair is ordered by the hard graph or by wave barriers. No stacked lane is proposed.

## 6. Waves and integration order

Every Wave Base is an immutable recorded Epic integration commit, not merely a branch name. Record its actual SHA in both sibling prompts at dispatch. Future SHAs cannot be supplied now. Before Wave 1, confirm the approved prior-epic fixes, synchronized policies and fresh CI evidence on the selected baseline, then dispatch only T0403. `8419eac...` is the original inspected baseline, not an assertion of current CI green or a substitute for a base containing this synchronization.

| Wave | Common Wave Base | Start concurrently | Why parallel-safe / expected overlap | Merge order | Barrier |
| --- | --- | --- | --- | --- | --- |
| 1 | Approved baseline plus approved policy/dispatch documentation | T0403 only | Shared verification state, FKs, history and action contracts must stabilize first. No sibling migration writer. | T0403 | Domain/action/read contract integrated; lifecycle/permission decisions recorded; canonical CI green on integrated state; owner review |
| 2 | Exact Epic commit after Wave 1 barrier | T0401 + T0405 | Directory owns organizations structure/UI; documents owns a separate app referencing already-integrated verification. Shared generated schema only; T0405 owns root storage/config/CI changes. | **T0405, then T0401** | Both integrated after sibling synchronization; real storage tests reachable and green; directory visibility/data decisions accepted; canonical CI green on final base |
| 3 | Exact Epic commit after both Wave 2 tasks | T0402 + T0404 | Profile consumes stable organizations/read state; checklist changes verification and consumes stable documents. No shared-app model writers. Shared generated schema; profile owns UI strings. | **T0404, then T0402** | Both integrated; checklist/evidence/action behavior agreed and tested; profile safely exposes current state; canonical CI green on final base |
| 4 | Exact Epic commit after both Wave 3 tasks | T0406 only | All real producer contracts available; integration requires the complete workspace. | T0406 | Cross-task tests and component flow green; all six tasks reviewed; canonical CI green; ready for separately authorized Codex Review Gate |

T0405 lands before T0401 because it finalizes storage configuration/CI and the evidence contract consumed by the next wave; directory then regenerates the combined contract. T0404 lands before T0402 because it finalizes review behavior before the last profile consumer is verified. These are integration choices, not numerical priority: 0405 precedes 0401, and 0404 precedes 0402. Reversing sibling order is possible only with an explicit updated integration plan and equivalent final checks, not by dropping the sync requirement.

Proposed temporary branch names:

```text
jules/t0401-company-directory
jules/t0402-organization-profile
jules/t0403-verification-domain
jules/t0404-verification-checklist
jules/t0405-verification-documents
jules/t0406-verification-operator-ui
```

Every PR targets `codex/epic-04-organizations-network-verification`, never `master`. Each session implements exactly its existing Issue. Branch names are future instructions; none were created here.

Sibling process: implement from common SHA → canonical CI green → owner review → authorized merge into Epic branch. Remaining sibling merges latest Epic into its temporary branch (preferred to preserve reviewed remote history), resolves conflicts, regenerates types from combined backend, reruns full canonical CI, obtains owner review, then merges with authorization. Rebase is acceptable only within owner Git policy and without force-pushing reviewed history. Old sibling CI is insufficient after contracts or shared files change. Validate the final integrated commit at every barrier, not just a pre-merge PR head. No automatic merging is authorized by this plan.

## 7. File overlap and migration controls

1. T0403 owns registration/packaging for verification and the minimal Epic 4 CI push trigger. T0405 owns documents registration, storage settings/library, metadata and MinIO CI execution. T0401 must not edit those files in Wave 2 without coordinating with T0405. Both reference existing Organization; neither rewrites identity roles or the organization base migration.
2. T0401 owns organization metadata associations/migrations. T0402 consumes them; if a new schema field is demonstrably needed, revise the shared contract before Wave 3 rather than hiding the change in UI work. T0405 may not add evidence columns to organizations or redefine verification state. If this split proves impossible, serialize the pair and revise the schedule before dispatch.
3. T0404 alone extends the verification schema after T0403. T0405's document FK points to its integrated predecessor; T0404 may reference integrated documents, avoiding a circular initial migration dependency. Do not assign migration numbers in advance. Inspect actual leaves at task start and again after sync.
4. Never run two same-app model writers concurrently by default. If an unforeseen collision occurs, stop integration; reconcile model intent, regenerate/rebase only unintegrated migrations against the latest graph, and test a fresh database plus upgrade from the wave base. Preserve already-integrated/applied history. Do not use an empty merge migration to conceal conflicting schema intent.
5. Backend contract producer owns serializer/OpenAPI annotations and runs `npm run api:generate`. `apps/web/src/lib/api/generated/schema.d.ts` is an unavoidable shared file; after sync regenerate from combined Django, never choose one sibling's file or manually splice generated declarations. No independent frontend DTOs or tracked duplicate schema snapshot.
6. T0401 owns directory navigation and localized directory strings; T0402 owns profile strings; T0406 owns Operator navigation/strings. Prefer new feature-scoped dictionaries/components, following the existing `commodity-messages.ts` pattern, with small sequential shell edits. Do not redesign shared shell, auth-context or UI primitives for aesthetics. `package.json`/lock changes require demonstrated dependency or command need; no planned frontend test-runner replacement.
7. `identity/serializers.py` reuses OrganizationSerializer. Any serializer extension requires `/me` safe-field regression tests even if identity has no text diff. `api/permissions.py` helpers may be reused, but organization read permission is insufficient for verification mutation and files.

Current organizations tests are `tests.py` and `tests_authorization.py`. Do not add an `organizations/tests/` package alongside `tests.py`, or reorganize established tests merely for appearance. Add discoverable sibling files `organizations/test_directory.py` and `organizations/test_profiles.py`. For new apps choose a test package at inception: `verification/tests/{__init__.py,test_domain.py,test_checklist.py,test_permissions.py,test_epic_integration.py}` and `documents/tests/{__init__.py,test_uploads.py,test_access.py,test_minio.py}`. Each task owns its test module; no simultaneous append into a monolithic file. The task owning a discovered existing regression can minimally amend that test without relocating the suite.

## 8. Executable testing and adversarial targets

These concrete testing targets derive from supplied scope, security invariants and the approved §4 policies. A denied request must prove persisted state/evidence did not change, not only an HTTP status. Every task is security-sensitive. T0403 must cover every listed action, required rejection/suspension reasons, no inactive-Organization mutation, append-only history/notes, and rejection of repeated/stale operations with atomic rollback. T0404 must prove the exact three-category basic and five-category full approval gates; T0405 must prove PDF/JPEG/PNG and 10 MB boundaries, version retention and the required-evidence reset to Documents Submitted.

CI path keys: **B** = new discoverable backend `test*.py` → unrestricted `python manage.py test` in `apps/api` → `backend` job with PostgreSQL 17. **F** = `apps/web/tests/components/**/*.test.{ts,tsx}` → `npm run test:components` → `frontend`; transport/session `.test.mjs` files in `tests/` → `npm test` → same job. **C** = Django schema → `npm run api:generate` → generated TypeScript drift check → `contract` job. **S** = proposed T0405 MinIO-backed tests discovered through B, with explicit CI MinIO service/startup/configuration and no silent skip. S is missing today, not a claimed existing check.

| Task | Observable behavior CI must prove | Negative/adversarial cases to include in Jules prompt | Planned test ownership and canonical path |
| --- | --- | --- | --- |
| T0401 | Real list/search and each capability/geography/commodity/verification filter; combined filters; multiple capabilities without duplicate organizations; valid empty results; visibility applied before counts/results; generic commodity references | Anonymous/inactive user; foreign org UUID and forged query params; unauthorized field/count leakage; mixing Buyer/Supplier/Broker capabilities to gain access; malformed filter values; inactive memberships/orgs according to explicit directory policy | organizations/test_directory.py; directory component file; B/F/C |
| T0402 | All six profile sections match actual permitted API facts; multi-capability display; commodities/geography; authoritative verification label; honest activity empty state; loading/error/not-found paths | Direct foreign detail ID; internal notes/bank data/object keys in profile or `/me`; tampered profile PATCH cannot modify verification, memberships, roles, capabilities or active flag; persona/org switch cannot show previous private data | organizations/test_profiles.py plus profile components; preserve existing auth regressions; B/F/C |
| T0403 | Exactly six persisted statuses; approved transition matrix and state-read contract; who/what/when/old/new history; atomic state/history updates; persisted-state checks and agreed repeated-action behavior; relational constraints | Owner/Manager or all capabilities cannot approve; Django superuser without product grant cannot approve; inactive actor; forged organization/state/actor; unsupported transitions; stale simultaneous approve/suspend, rollback failure, direct bulk inserts of invalid statuses/FKs. Distinguish DB constraints from privileged raw-SQL bypasses. | verification domain/permissions tests; PostgreSQL TransactionTestCase where concurrent requests matter; B/C |
| T0404 | Operator reviews actual items/evidence; agreed checklist completeness controls decisions; reviewer/outcome traceability; evidence version/replacement invalidates stale review according to policy | Foreign document/item ID, mismatched parent case/org, review without role, missing mandatory evidence, duplicate/replayed review, changing evidence after review, mass assignment of reviewer/outcome; failed changes leave state/history intact | verification/test checklist and permissions modules under chosen package; B/C |
| T0405 | Real upload puts bytes in MinIO and metadata in PostgreSQL; uploader assigned from session; authorized retrieval returns exact bytes; agreed type/size boundaries; failure/retry behavior preserves consistent metadata and avoids overwrite | Anonymous/unauthorized upload/download; own metadata ID paired with another org's object; arbitrary key/path/name or uploader/status injection; oversized/invalid file; failed storage write; public unauthenticated object access; retry cannot replace another object's evidence; CSRF missing on upload | documents upload/access/MinIO tests; B/S/C; frontend upload interaction can be in T0406 |
| T0406 | Operator with no organization membership can use pending queue, documents, notes and approved approve/reject/suspend actions; backend result refreshes queue and profile/directory verification; Persian RTL and accessible errors; real API-backed fixtures | Actor with neither Operator nor Product Admin attempts direct URL/API action; both authorized system roles tested; expired session/CSRF; stale queue action after another reviewer; failed action must not show success or cache stale trust; organization/persona switch clears private evidence and notes; reject follows agreed state mapping | verification/tests/test_epic_integration.py; verification-operator component tests and API-derived fixtures; B/F/C plus inherited S |

Document/checklist review outcomes are exactly pending/accepted/rejected under §4, separate from the six Organization statuses. Do not introduce an Organization Rejected status. Store no file bytes in a JSONB/database column. A test naming “network visibility” means approved safe directory visibility in Epic 4; it does not justify inventing a relationship table. Foreign active organizations are intentionally discoverable through that projection; private evidence, original membership-scoped endpoints and mutations remain separately protected.

## 9. Canonical CI reachability audit

Inspected `.github/workflows/ci.yml`, `apps/web/package.json`, `apps/web/vitest.config.ts`, and backend test layout. Current paths are:

- Backend: editable install with dev extras and `pip check`; Ruff; Django check; `makemigrations --check --dry-run`; `migrate --noinput`; unrestricted `python manage.py test` with PostgreSQL 17. New app test packages must include `__init__.py`, be discoverable, registered where needed, and included in setuptools discovery in `apps/api/pyproject.toml`. Previous gates caught omitted package modules; do not repeat that failure.
- Frontend: `npm ci`, lint, typecheck, production build, `npm test && npm run test:components`. Node tests match only top-level `tests/*.test.mjs`; Vitest matches `tests/components/**/*.test.{ts,tsx}`. Files elsewhere are not automatically covered by these commands.
- Contract: Django `spectacular --validate --fail-on-warn` then openapi-typescript through `npm run api:generate`; `git diff --exit-code apps/web/src/lib/api/generated/schema.d.ts`. The contract job has no database service: schema inspection must not query runtime rows or contact MinIO at import time. Validate multipart requests, download responses and permission/error responses against actual behavior.
- CI triggers all pull requests, so Jules PRs to Epic 4 are covered. Push filters currently name master and Epic 1/2/3 only. T0403 should add the minimal Epic 4 push pattern so integrated barrier commits run canonical CI. Temporary Jules pushes need no new pattern when covered by PRs.
- No current MinIO CI execution path exists. T0405 should add a bounded MinIO startup/readiness/configuration step or service to the backend job and run its real storage tests through the ordinary test command, with isolated test objects and cleanup. Mock-only upload tests cannot prove T0405's MinIO acceptance. Do not skip these tests silently when the service is missing in CI. Reuse existing infrastructure type; do not redesign CI or introduce new services beyond MinIO.
- No current canonical Playwright command/job exists. Real browser visual, proxy/multipart and permission flow checks are explicitly **Epic Review Gate-only** in this plan. Do not claim component/API tests are a browser E2E. If automated browser tests later become Task DoD, wire them into canonical CI within the owning task before claiming completion; do not leave an ad-hoc local script as task evidence.

Each PR records exact new test paths → commands → jobs and shows discovery, not just a targeted local invocation. All Task DoD automated tests must be CI-reachable unless explicitly designated Review Gate-only. Run all existing foundation tests after sibling sync; contract drift, session permissions, commodity genericity and generated API fixtures remain required. No CI edits or tests were executed as part of this documentation task.

## 10. Existing final task as integration point

Use **T0406 — Verification Operator UI** as the Epic integration task, retaining its exact name and ID. The roadmap does not explicitly call it an integration task, but its workspace already consumes domain/checklist/documents. Assign cross-task acceptance to its existing Issue under this plan; no T0407 or renamed roadmap task is needed.

Critical flow, using approved transitions rather than an invented fixed state sequence:

1. Create test organizations with multiple capabilities, geography and commodity associations through legitimate fixtures/setup; expose only approved directory/profile fields.
2. Authorized actor submits real evidence under the agreed permission/state rules; metadata belongs to the correct organization/review record and bytes reside in MinIO.
3. Operator with a system role and no synthetic organization membership sees the case in the agreed pending queue, retrieves permitted evidence and reviews checklist items.
4. Operator writes a customer-hidden note and performs an allowed approval action. Assert the chosen Basic Verified/Verified result, prerequisite guards, actor/time/old/new audit, and consistent profile/directory filter state after refresh.
5. Separate fixtures exercise rejection/resubmission and suspension according to the approved matrix. A second reviewer using stale state cannot overwrite a later decision; evidence replacement cannot preserve trust incorrectly under the agreed rules.
6. Customers cannot access internal notes or perform review actions. Own active-Organization Owner/Manager can access evidence; Member/Viewer and foreign-Organization users cannot. Operator/Admin can inspect all evidence, including inactive organizations, but cannot mutate inactive organizations. Ordinary safe profile editing and session/context behavior remain intact.

Backend integration uses real PostgreSQL domain/API paths and real MinIO under S. Component tests consume backend-verified API fixtures through generated types, following the Epic 3 lesson that hand-written matching mocks can hide real wire mismatches. T0406 tests the complete Operator interaction with loading/empty/error and failed mutations. No RFQ/Offer/Deal or fake business-instance table is necessary.

## 11. Final Codex Review Gate preview

Do not execute this gate now. After Wave 4 and separate owner authorization, review the Epic branch against master, including every sibling integration and the final generated contract. Attack beyond ordinary happy-path CI:

- Cross-organization enumeration via list/search/filter counts and detail IDs; compare customer-safe projections against Operator views and `/me`. Inspect accidental expansion of the original OrganizationSerializer and its writable fields.
- Role/capability confusion: all capability combinations and all membership roles, Operator without membership, Product Admin according to approved matrix, inactive actors/organizations, Django staff/superuser without product assignment. Test direct backend calls with genuine sessions/CSRF.
- Verification privilege escalation, unsupported transitions, double/stale decisions, concurrent approval/suspension, rollback, missing/misattached evidence, and stale checklist approval following document replacement. Assert history as well as current state.
- Raw/bulk DB constraint probes for enums/FKs/uniqueness and explicit documentation of application-only guards; fresh PostgreSQL migrations and upgrade from baseline. Do not claim application guards prevent privileged DBA edits.
- Document-ID/object-key substitution, direct unauthenticated MinIO access, download authorization, sensitive metadata exposure, storage failure/retry cleanup, and real browser multipart through the same-origin proxy. No customer leakage of Bank Details or internal notes.
- Exact API/OpenAPI request/response agreement, generated types and backend-derived fixtures; unfiltered queue/profile stale-state disagreements after actions.
- CI discovery and task-proof audit: new packages included in distributions; tests in actual runner globs; no conditional skipping; MinIO path really executes; final Epic commit CI, not obsolete sibling green.
- Real Persian/RTL browser interaction, keyboard/focus/error usability, session expiry and persona/context switching. Explicitly record browser evidence separately from jsdom/HTTP checks.
- Scope regression: no private-network ownership/relationship invention, real KYC provider, trust scoring, transaction analytics, procurement or settlement logic; preserve all Epic 1–3 regression and commodity-definition invariants.

Record findings, fixes if later authorized, actual checks, limitations and merge conditions in a future Epic 4 review record. Human review remains required; this plan is neither that review nor merge approval.

## 12. Documentation consistency findings — synchronized

| Finding | Resolution / remaining boundary |
| --- | --- |
| AGENTS.md and roadmap previously named the Epic 3 review as current scope | Replaced with authorized Epic 4 scope, the existing Epic branch, and this execution plan. The present synchronization remains documentation-only. Historical gate records are preserved. |
| Generic sequential/per-task branch examples conflicted with Jules waves | Epic-specific protocol now takes precedence: exact common base, isolated temporary branches, Epic-target PRs, sibling sync and canonical CI, complete wave barriers. |
| Rejection had no mapped Organization status | Owner maps Under Review → Unverified, requires a reason, and forbids a Rejected Organization status. Checklist/document rejected outcome is separate. |
| Directory visibility was undefined relative to the existing membership API | Owner authorizes authenticated product users to read active companies through an explicit safe projection. Existing membership-scoped APIs and mutation permissions remain protected. |
| Geography, commodity association and activity summary lacked boundaries | Country only; declared operation in a CommodityDefinition, maintained by own Owner/Manager or global Product Admin; actual available activity or empty/unavailable state. No relationship model, inventory or analytics expansion. |
| Notes/audit overlapped generic Epic 11 tooling | Owner approves one current aggregate per Organization and append-only local notes/decisions; no generic Epic 11 infrastructure or history hard deletion. |
| Checklist, evidence replacement and storage policy were missing | Owner supplies required categories, pending/accepted/rejected outcomes, immutable retained evidence versions, required-evidence reset, private backend-authorized PDF/JPEG/PNG access and 10 MB limit in §4. |
| Evidence replacement reset was absent from the review-action list | Persist both owner policies: the reset is a distinct required-evidence replacement event, not an unrestricted action or suspension bypass; see §4 application notes. |
| Glossary/overview describe membership roles as examples; implementation has four constrained values | Preserve the exact Owner/Manager/Member/Viewer contract. No new role is authorized; no broader glossary rewrite is needed. |
| Some architecture/ADR summaries still describe old implementation stages | Historical/general summaries do not override this linked Epic policy or current code/review evidence. No architecture decision changes are needed for this synchronization. |

No actual contradiction with Product Specification intent requires an amendment: these policies elaborate its manual verification and document boundaries. Product Specification, glossary and architecture documents remain unchanged. Unrelated source-review differences remain open. Pending-queue selection and the precise 10 MB byte boundary remain bounded later-task details identified in §4; no T0403 policy blocker remains. GitHub Issues and hosted CI were not inspected or changed, so dispatch must reconcile the Issue and record the actual synchronized base SHA/CI evidence.
## 13. Dispatch checklist and completion of planning

Before each Jules assignment, provide its exact Issue ID/name, scope and approved acceptance decisions, common Wave Base SHA, temporary branch/PR target, hard prerequisites, owned files and sibling exclusions, required adversarial cases from §8, CI path, and no-merge-without-owner-authorization rule. State that all other tasks and future Epics are out of scope. Require a final report of changed behavior, validation, migration/contract impact and unresolved risks.

Documentation synchronization is complete. The approved policies supply sufficient T0403 context; a fresh assigned session can implement that task once its synchronized Wave Base and baseline checks are recorded. Use two sessions for each subsequent independent pair only after its complete wave barrier. This documentation task starts none of T0401–T0406 and makes no commit, push or merge.
