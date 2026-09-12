# Epic 4 Review Gate — 2026-09-12

## A. Epic Verdict

**EPIC 4 — CHANGES REQUIRED**

Canonical validation passes, but the committed implementation contains release-blocking verification races and material evidence, privacy, audit, contract, and frontend defects. The gate executed 231 canonical backend tests (all pass), 35 additional adversarial checks (15 pass, 20 fail), real PostgreSQL/MinIO/API integration, and production-browser checks. No application fixes were made; all findings below remain open.

Authority: the owner's final Review Gate request supersedes the older documentation-only task language in AGENTS.md. Read AGENTS.md, roadmap Epic 4/T0401–T0406, the complete Epic 4 execution plan (approved §4 policies), relevant specification §§3–5, 34–35, 42–46, 50–60, glossary, architecture/source review, ADRs 0001/0002/0004/0007/0008/0009, and Epic 1–3 review records. Earlier wave mechanics are historical. Product policy and specification were not changed.

## B. Review Boundary

| Item | Evidence |
| --- | --- |
| Branch | `codex/epic-04-organizations-network-verification` |
| Original/current Epic HEAD | `7617280d8f57aed2e7b982a5505329847e1dd042` |
| `master` HEAD and merge base | `8419eac5408ca88eaac9f562a9413cca64d9c3b8` |
| Complete committed Epic diff | 69 files, 7,210 insertions, 153 deletions; `master...HEAD` |
| Initial working tree | Clean |
| Remote heads | Fresh `git ls-remote` agrees with both local heads |
| Hosted CI | Exact-commit GitHub check-runs request returned HTTP 403/rate limit; hosted green status unverified |
| Final repository change | Only this uncommitted review record; generated TypeScript has no Git diff |
| Git operations | No branch creation, commit, push, merge, reset, rebase, or history rewrite |

The complete committed file inventory is below. Review covered models/migrations, services/actions/permissions, serializers/routes, storage, all new pages/shared provider changes, generated contracts, tests/discovery, dependencies, packaging, CI, and documentation. Existing identity and commodity foundations were reviewed at relevant integration boundaries.

## C. Findings

Evidence labels distinguish executed PostgreSQL/API/browser reproductions from inspection. Gate-only tests are outside the repository and are **not canonical regressions**. Storage is mocked in most isolated policy probes, while real MinIO is used in the canonical storage test, the HTTP integration, standalone privacy/byte check, and orphan reproduction. Concurrent probes use distinct PostgreSQL connections with barriers. Thirty-five checks include multiple scenario matrices; twenty failures are assertions against expected policy, not twenty independent findings. Proposed fixes/regressions below are outstanding.

### Blocker

**B1 — Approval can use evidence replaced after prerequisite evaluation.**

- Reproduction: a two-connection test pauses Basic approval after `_check_documents_accepted`, uploads replacement required evidence while Under Review, then resumes approval. Upload returns 201 and persisted status becomes `basic_verified` despite new pending evidence. Log: `APPROVAL_REPLACEMENT_RACE 201 basic_verified basic_verified`.
- Impact: supported APIs can assign trusted status to evidence that does not satisfy the approved prerequisites.
- Root cause: `organizations/verification/services.py:99–136` checks prerequisites before acquiring the aggregate lock. Upload and checklist mutations do not consistently lock/advance that aggregate.
- Required fix: acquire the shared aggregate lock before reading prerequisites, retain it through decision/history persistence, and serialize/version evidence and checklist changes under the same protocol. Preserve the approved transition matrix.
- Regression evidence: gate test `test_approval_cannot_use_prerequisites_read_before_replacement` fails. The existing canonical concurrency test is sequential and misses this race. Add canonical concurrent approval versus replacement/rejection tests for Basic and Full.

### Major

**M1 — Checklist stale writes and missing versions defeat optimistic concurrency.**

- Reproduction: accept then reject the same document with the same expected case version; both return 200 and the latter persists rejected. An accepted required document can also be changed to rejected while the case remains Basic Verified. Start Review without a version succeeds; serializer validation also permits null. Evidence replacement during Under Review leaves the version unchanged, allowing an old reviewer action.
- Impact/root cause: newer review results and prerequisites can be silently overwritten. `services.py:49–73` checks but does not advance version or restrict review to appropriate lifecycle states; `serializers.py:43–50` makes versions optional/nullable.
- Fix: require versions for existing aggregate mutations, lock and increment atomically, reject stale evidence/reviews, and prevent review edits from leaving contradictory approved trust.
- Regression evidence: four persisted gate failures cover stale checklist, omitted version, replacement followed by stale action, and rejected evidence at approved trust. Browser acceptance also left case version 12 unchanged. Add these as canonical regressions, including explicit null versions.

**M2 — Customer verification detail leaks private decision reasons and reviewer identity.**

- Reproduction: own customer GET after rejection contains the internal reason and reviewer email, while notes correctly return null. The same disclosure was observed through the Next proxy and on a fresh Supplier browser visit to the Operator case URL.
- Impact/root cause: internal review data reaches ordinary organization members. `verification/serializers.py:26–41` includes unconditional `decisions`; `api_views.py:14–23,49–50` reuses it for membership reads and submission responses.
- Fix: explicit separate customer/internal projections and schema contracts; enforce workspace role gating as defense in depth.
- Regression evidence: `test_customer_verification_does_not_expose_decisions` fails; actual HTTP and browser confirm the disclosure. Test all membership roles and submission after prior decisions. Directory/Profile/`me` use separate projections and passed their privacy checks.

**M3 — Customer evidence responses disclose raw object keys.**

- Reproduction: own Owner document-list response contains the persisted `object_key`; upload/list serializer and generated TS expose it as well.
- Impact/root cause: storage metadata violates the explicit private-response contract. `documents/api/serializers.py:8` includes the field. This is not a demonstrated public-byte or foreign-document bypass.
- Fix: remove keys from wire projections, regenerate types, assert exact safe upload/list response fields.
- Regression evidence: `test_document_projection_hides_object_key` fails; foreign byte retrieval remained denied.

**M4 — Evidence currentness and checklist history are not preserved.**

- Reproduction: replacement rewrites the old accepted outcome to `replaced`, without an immutable reviewer/outcome history. Two synchronized first uploads both return 201 and leave **two current rows**. Direct PostgreSQL inserts permit duplicate current evidence and arbitrary checklist outcome strings.
- Impact/root cause: historical review cannot be reconstructed and approval may use an ambiguous category version. `documents/models.py:13–37` conflates currentness/review outcome and lacks current-category uniqueness; upload `views.py:77–94` updates history in place; checklist overwrites a document field without a review record.
- Fix: separate immutable evidence identity/version, currentness and append-only evidence-bound reviews; enforce one current category version and allowed outcomes. Migrate honestly without inventing historical reviewers.
- Regression evidence: historical-outcome, duplicate-current constraint, invalid-outcome constraint and concurrent-upload probes all fail. Add canonical history and real concurrency tests.

**M5 — Database failure leaves uploaded bytes orphaned; the real storage test wipes its configured bucket.**

- Reproduction: inject metadata creation failure after an actual MinIO write. API returns 500 with no metadata, but object stat succeeds. Cleanup-call probe also fails. Separately, inspected `documents/tests/test_minio.py:22–34` setup/teardown removes every object in the configured bucket, which defaults to the application bucket.
- Impact/root cause: ordinary failures leak orphaned evidence; running the test with application settings risks unrelated data. `documents/api/views.py:67–121` has no DB-failure storage compensation; test cleanup lacks ownership scoping.
- Fix: narrowly scoped object compensation with observable cleanup failures; unique test bucket/prefix and cleanup of owned objects only.
- Regression evidence: real orphan and cleanup-call tests fail; the gate manually removed its own orphan and ran canonical tests only with isolated buckets. Add real storage/DB/history failure and unrelated-object survival regressions. Database rollback itself preserves prior current evidence/trust, as separately tested.

**M6 — Optional-at-Basic evidence unnecessarily invalidates Basic trust.**

- Reproduction: replacing Bank Details at Basic Verified returns 201 and persists Documents Submitted. Bank Details/Trade License are required for Full, not Basic; the code also downgrades on their first upload.
- Impact/root cause: valid Basic approval is lost contrary to approved current-level policy. Upload `views.py:96–115` treats every non-Certifications category as required at both levels.
- Fix: determine required categories from the current verification level and distinguish replacement from initial optional upload.
- Regression evidence: `test_optional_for_basic_bank_evidence_does_not_downgrade_basic` fails. Add all-category/level regressions. Actual Full required replacement and optional Certifications behavior passed sequential integration.

**M7 — Format validation trusts the supplied MIME type.**

- Reproduction: `malware.exe` containing `MZ-not-a-pdf` with `application/pdf` is accepted with 201.
- Impact/root cause: unsupported bytes are stored as approved formats. `documents/api/views.py:48–61` checks only MIME/size; no extension/signature/format validation.
- Fix: bounded validation of declared PDF/JPEG/PNG formats and filename/type consistency. Do not call it malware scanning.
- Regression evidence: spoofed-file test fails. Empty, unsupported MIME, missing file, invalid category and over-10-MiB uploads reject; exactly 10 MiB accepts. JPEG/PNG prefix fixtures were accepted, which proves MIME routing, not full image decoding. Add valid-format and mismatch regressions.

**M8 — Operator and evidence UI flows are incomplete and not Persian.**

- Reproduction: production browser shows English queue, case, actions, reasons, notes and history under Persian/RTL routing. Case rows offer Accept/Reject but no evidence download control. No Owner/Manager upload/submission UI exists. Shared shell has only home navigation; Operator pages omit the shell and role gate.
- Impact/root cause: reviewers cannot inspect evidence bytes through the UI before accepting; users cannot complete the requested evidence workflow; locale/access experience violates the approved demo contract. New pages hard-code text and omit workflow controls.
- Fix: localized, role-aware navigation and complete authorized upload/submission/download flows; keep upload authority with Owner/Manager.
- Regression evidence: actual browser inspection and source inventory confirm omissions. Four existing Operator component tests pass but do not cover these flows. Add component/browser regressions using API-derived fixtures.

**M9 — Internal browser state persists after session-role changes.**

- Reproduction: open an Operator case containing an internal note; in a second tab switch the shared demo session to Supplier and verify the Supplier identity. The original case tab continues displaying the internal note and history. A fresh Supplier case visit hides notes but still leaks decisions through M2.
- Impact/root cause: prior privileged content remains visible after the shared session loses its role. Root QueryClient persists, private keys contain organization ID rather than session/role, and internal pages do not use auth state. Document-query errors are also treated as no documents.
- Fix: clear/cancel or scope private cache on session changes, propagate cross-tab auth changes, gate internal routes, and distinguish error/loading/empty states. Invalidate Directory/Profile/queue after relevant case changes.
- Regression evidence: actual cross-tab browser reproduction; source confirms missing cache/auth wiring. Add automated session-switch tests, including delayed/denied refetch. No new backend note-read authorization bypass was observed.

**M10 — OpenAPI is valid but misdescribes the actual wire API.**

- Reproduction: generated schema describes upload file as URI rather than binary multipart, omits Directory query parameters, infers Organization for add-commodity request/response, omits remove-commodity body, labels binary download application/json, and describes notes as arbitrary-object array despite customer null.
- Impact/root cause: generated clients cannot accurately express these requests/responses. Endpoint serializers/annotations and common authorization/not-found/conflict/failure response coverage are incomplete; frontend `any` and `as unknown as undefined` conceal errors.
- Fix: explicit accurate request/response serializers and annotations, request splitting where appropriate, regenerate and remove bypass casts.
- Regression evidence: canonical generation twice passes validation/determinism with no Git drift, while inspected output contains the mismatches. Add wire/schema contract assertions; validity alone is insufficient.

**M11 — Directory filtering/display does not consistently represent lifecycle states.**

- Reproduction: a company without the lazy verification row displays Unverified but disappears from `?verification=unverified`. Directory/Profile map Documents Submitted to the default Unverified badge. Browser Directory has no country/commodity controls, Documents Submitted option, or company-profile links.
- Impact/root cause: misleading verification display and incomplete discovery. `organizations/api/views.py:106–110` filters only existing related rows; frontend mappings/controls omit required cases.
- Fix: include absent-row initial state, map all six statuses, expose specified filters and profile navigation.
- Regression evidence: lazy-state filter probe fails; browser/source establish display/control omissions. Combined repeated filters, deduplication and inactive exclusion separately pass. Add canonical lazy-row, submitted-badge and UI navigation/filter regressions.

**M12 — Decision records omit the required action identity.**

- Reproduction: perform a successful submission and inspect its decision; actor, states, time and reason fields exist, but no `action` field does.
- Impact/root cause: audit contract is incomplete; transitions cannot explicitly identify the operation. `verification/models.py:36–56` omits action from model/API.
- Fix: stable action identity for new events; honest migration provenance for old records; preserve atomic creation.
- Regression evidence: `test_decisions_record_action` fails. State/history rollback probes pass. Add action/actor/time/reason assertions across all lifecycle and replacement events.

### Minor

- Directory query growth measured **7 queries for 2 organizations, 22 for 7** (1 + 3N). Prefetch/select related relations and avoid bypassing their caches. Case actor relations also warrant optimization.
- Malformed document-list organization UUID and note creation before a verification aggregate each reproduced **HTTP 500**. Validate identifiers and use documented 400/404 behavior.
- Decisions/notes/documents/queue use timestamp-only ordering without stable ID tie-breakers.
- Verification/decision/note Django admin registrations are editable/deletable, but admin is **not installed or mounted**. This is a latent supported-tool risk, not a current superuser HTTP bypass. Make history appropriately read-only before enabling it.
- Tracked `apps/web/schema.yaml` is a noncanonical duplicate; generation uses ignored `apps/api/schema.yaml`, contrary to the plan's single-contract-source rule.
- CI starts MinIO without a service healthcheck; Compose `--wait` establishes running-container state only. Add bounded backend readiness. The contract job needlessly starts MinIO.

### Nit

No additional cosmetic findings or unrelated formatting changes.

## D. T0401 — Company Directory

Authenticated active-user access and active-organization visibility pass. Explicit customer-safe fields exclude registration identifiers, memberships, system roles, evidence, notes, reasons and reviewers. No paginated count is exposed. Foreign active companies are intentionally discoverable, while inactive Profile detail returns 404.

Existing individual filters and supplemental combined country + repeated capabilities + repeated commodities + verification filtering pass, including deduplication with multiple matches and inactive exclusion. Malformed filter strings are treated as nonmatching values. Browser name search changes the URL and reduces three demo rows to the Supplier row. Initial-state filtering, submitted badges, required controls/navigation and N+1 queries fail M11/Minor.

OrganizationCommodity remains a generic unique organization/commodity declaration. Actual role matrix permits own active Owner/Manager and global Product Admin association management; Member/Viewer, capability-only authority, Operator alone and Django flags alone do not grant it. No inventory/pricing/matching behavior was introduced.

## E. T0402 — Organization Profile

Company information, capabilities, commodities, country/geography, verification and unavailable activity are present. Explicit projection excludes private fields. Persisted API tests confirm Directory/Profile/`me` contain no synthetic internal reason/note, reviewer or object key. Mass-assignment attempts do not alter trust, active status, roles, memberships or document references.

Browser Profile is Persian and displays the Supplier's safe data with an honest unavailable-activity message. No transaction/rating/volume claims are fabricated. All five Profile component tests pass. Documents Submitted badge and missing Directory-to-Profile navigation remain M11.

## F. T0403 — Verification Domain

Exactly six statuses remain: Unverified, Documents Submitted, Under Review, Basic Verified, Verified, Suspended; rejection returns Unverified. Actions implement submit/start/basic/full/reject/suspend/reopen. Supported edges match approved policy: Unverified→Submitted→Under Review; Under Review→Basic/Verified/Unverified; Basic→Under Review/Suspended; Verified→Suspended; Suspended→Under Review; required evidence replacement at approved trust→Submitted. No generic status PATCH exists.

Persisted matrix attacks of every unsupported source/action combination reject without state/history mutation. Reject/suspend reason validation exists and canonical tests pass. Supplied stale versions reject. Actual parallel approve/reject with the same version produces one winner, one conflict, one decision and version 2. Injected decision failure rolls back state/version/history together. However, optional versions and evidence/checklist races invalidate a general concurrency guarantee (B1/M1).

Operator/Admin review authority and own active Owner/Manager submission authority pass API tests. Inactive organizations remain system-inspectable but all tested mutations/uploads reject. Internal notes are append-created and hidden from new customer responses; decisions leak and lack action identity. Services rely on API authorization/active checks, so arbitrary internal callers are not independently authorized by the service layer.

## G. T0404 — Verification Checklist

Review outcomes are pending/accepted/rejected, but document currentness is conflated with `replaced` and the database permits arbitrary outcomes. Review resolves the exact document ID within the URL organization; category comes from persisted evidence, not an independent client category. Foreign ID and superseded-document attempts reject without mutation in executed tests/integration.

Basic requires current accepted Registration, Tax ID and Authorized Representative; Full adds Trade License and Bank Details; Certifications are optional. Every required category set to pending/rejected/replaced blocks approval sequentially. Old accepted bytes remain accessible to authorized actors, but their acceptance metadata is overwritten. Stale checklist, approval/evidence races and duplicate current rows fail B1/M1/M4. Actual role matrix confines review to Operator/Product Admin.

## H. T0405 — Verification Documents

PostgreSQL stores metadata; MinIO stores bytes. Six categories match policy and invalid category is constrained in PostgreSQL. Server-created keys use organization/random UUID and normalized filename. Supplied bucket/key/uploader fields do not control persisted ownership or retrieval. Download resolves document ownership before reading stored key; no endpoint emits a usable public URL.

Actual Owner/Manager own-active versus Operator/Admin inspection matrix passes; Member/Viewer, capabilities and Django flags alone do not authorize evidence. Foreign retrieval is denied. Real HTTP upload→metadata→authorized exact-byte download passes through the Next proxy; replacement retains old bytes. Raw keys still leak (M3), MIME spoofing succeeds (M7), historical/currentness guarantees fail (M4), and compensation fails (M5).

Required replacement at Full correctly downgrades to Submitted with history; optional Certifications leave Full unchanged. Basic optional categories are mishandled (M6). Storage-write failure preserves metadata/trust; invalidation/history failure rolls back replacement metadata and prior current evidence, but uploaded-object cleanup is absent. PostgreSQL and MinIO are not claimed to share a transaction.

## I. T0406 — Operator UI & Integration

Backend `is_pending=true` selects Documents Submitted/Under Review. Operator without organization membership successfully loads the queue/case. Inactive organizations remain inspectable; queue lacks an active flag to explain non-mutable cases. Case joins notes/decisions with a separate document query; mutations send expected version and refetch after errors.

Browser: queue→Review→case works. Accepting Certifications updates the row but not version. After a separate session rejects version 12 into Unverified/version 13, the old browser Approve Full receives stale-object error and refreshes to version 13 with actions removed; no false success is displayed. Fresh Supplier direct URL reaches case/evidence/history and an Add Note form, although actual unauthorized note mutation is denied. The old Operator tab retains private notes after session switch (M9).

Actual same-origin HTTP flow covers Owner upload, submit, Operator start/checklist/full approval, safe Directory/Profile projection, required replacement/reapproval, optional evidence, suspension/reopen/rejection/resubmission and private notes. This is real PostgreSQL/MinIO integration, **not a complete browser Hero Flow**: missing upload/download UI prevents completing that UI workflow. English content and missing controls/route gating remain M8. Component fixtures are handwritten, not API-derived.

## J. Cross-Organization Security Audit

| Boundary | Executed evidence / limitation |
| --- | --- |
| Organization | Canonical authorization suite confines customer detail/mutation to memberships; adversarial mass assignment protects internal fields. Directory/Profile intentionally show safe foreign active companies. |
| Verification | Foreign/unauthorized action coverage passes canonical permissions; inactive mutations reject. Own customer decision detail leaks through M2. |
| Document | Actual role matrix and real foreign Buyer download return denial; request keys do not override stored ownership. M3 is metadata disclosure, not foreign byte access. |
| Checklist | Foreign document supplied to another organization's case returns 400, leaves outcome pending and adds no decision; superseded evidence also rejects. |
| Notes/history | No independent detail/edit/delete object routes; accessed through aggregate. Unauthorized note writes deny, new customer notes are hidden; decision reads leak and cached old notes persist (M2/M9). |

No cross-organization byte-read or checklist-write success was observed in the exercised paths. Do not interpret that as an exhaustive proof beyond the recorded tests.

## K. Role/Capability Separation

The executed expanded matrix covers Owner, Manager, Member, Viewer, Buyer, Supplier, Broker, Operator, Product Admin, Django staff, Django superuser and anonymous. Capability cases use Viewer membership to prove capabilities add no authority. Canonical tests also exercise inherited product-role boundaries.

| Actor | Evidence/review/association result |
| --- | --- |
| Owner / Manager | Own evidence allowed; foreign evidence denied; checklist/notes/queue denied; own association allowed |
| Member / Viewer | Evidence/review/notes/queue/association mutation denied |
| Buyer / Supplier / Broker | Exactly three multiple-allowed organization capabilities; none grants privileged operations |
| Operator | Global evidence/review/notes/queue allowed without membership; global association mutation denied |
| Product Admin | Explicit `admin` role grants global review and approved organization management |
| Django staff / superuser only | No implicit product evidence/review/association authority |

No unintended role escalation was observed. Customer private-data exposure remains M2/M3/M9. No Trader was introduced; unmounted Django admin registrations are not a present API bypass.

## L. Historical/Audit Integrity

Lifecycle decisions/notes have no normal update/delete API; successful transitions append decisions atomically, and injected failure proves rollback. Action identity is absent. Evidence bytes/rows survive replacement, but prior review outcome/reviewer history does not. Supplied stale state-action versions work; omitted versions, checklist overwrites and evidence races do not. Consequently current trust is not reliably reconstructable from immutable evidence-bound reviews. Privileged ORM/admin/SQL and cascades do not have general append-only protection; no such guarantee is claimed.

## M. PostgreSQL Evidence

Actual service: PostgreSQL **17.11**, `commodity_postgres`, `postgres:17-alpine`, loopback 5432. Python 3.12.4/Django 6.0.8. Canonical dependency installation resolved the old virtualenv's missing MinIO; `pip check`, Ruff and Django system check pass.

The existing `.env` referenced unavailable port 55432 and was preserved. Automatic review initially blocked container-credential extraction (never executed) and new LOGIN/CREATEDB/database ownership changes. The owner explicitly approved the disposable role and cleanup, after which the gate used only the new `epic4_review_20260912` login and isolated databases. No existing credentials were read or changed.

| Check | Actual execution |
| --- | --- |
| Fresh migration | Full graph applies to empty isolated PostgreSQL database |
| Migration drift | `makemigrations --check --dry-run` passes with working PostgreSQL connection |
| Seeds | Bitumen and Base Oil seed commands pass |
| Upgrade | Exported exact master via `git archive` (no branch); migrated/seeding baseline then applied Epic 4; retained existing organization and 2 commodities/2 schemas/13 attributes |
| Canonical backend | **231 tests passed in 161.419 seconds**, including unskipped real MinIO |
| Gate policy/concurrency | **32 tests: 12 pass, 20 fail**, 33.425 seconds; no runner errors |
| Supplemental gate checks | **3 pass**, 2.416 seconds: combined filters/inactive visibility, storage failure rollback, malformed upload fields |
| Constraints | Duplicate verification, invalid verification status and invalid document category reject; duplicate current evidence and invalid checklist outcome do not |
| Concurrent decisions | Same-version approve/reject: one winner, one conflict; correct version/history |
| Concurrent evidence | Both first uploads succeed and leave two current rows; approval can race replacement into Basic Verified |
| Failure atomicity | Injected decision/history and storage-write failures preserve previous database state |

Source additionally contains object-key uniqueness, organization/commodity uniqueness, valid decision-state and inherited membership/capability constraints. Cross-table lifecycle authorization remains service/API responsibility. Existing application databases were not modified.

Cleanup completed: review servers stopped; both `epic4_review_20260912` and `epic4_upgrade_20260912` dropped; Django's `test_epic4_review_20260912` absent; disposable role dropped. Final SQL counts: **review databases 0, review roles 0**.

## N. MinIO Evidence

Actual service: `commodity_minio`, **RELEASE.2025-02-28T09-55-16Z**, commit `8c2c92f7afdc8386b000c0cb57ecec2ee1f5bcb0`, Go 1.23.6, loopback ports 9000/9001. Used documented local demo credentials and isolated gate buckets, not extracted container credentials.

- Standalone upload/stat/get: **31 bytes, exact equality**; direct anonymous object GET **403**. An initial proxy-mediated 502 was discarded; the actual privacy check used direct loopback.
- Canonical real MinIO test runs unmocked and unskipped in the 231-test pass.
- Real Next→Django→PostgreSQL/MinIO integration uploads five required PDF fixtures, stores metadata, authorizes downloads and verifies exact **46-byte** bodies. Foreign Buyer downloads return 403. Replacement retains original bytes; reapproval and trust invalidation persist.
- Actual upload followed by injected DB failure leaves an orphan; the gate verified and removed it (M5). Storage failure and history rollback separately preserve prior DB state.
- Backend CI starts MinIO and ordinary Django discovery reaches the real test, without a conditional skip. Hosted execution remains unverified due to GitHub rate limit.

Cleanup verified: standalone bucket removed, canonical/probe buckets empty then removed, browser bucket's seven objects verified under the synthetic organization prefix and removed with that bucket. All four review bucket names are absent. No application bucket was cleaned. New-bucket privacy was tested; deployment's existing bucket policy was not audited.

## O. CSRF / Session Evidence

SessionAuthentication/CsrfViewMiddleware and same-origin client behavior remain. Executed CSRF-enforcing API clients reject missing and invalid CSRF for lifecycle actions, notes, checklist, submission, association and multipart upload; invalid/expired sessions reject (403 or scoped 404). Unauthorized actors fail the role matrix. All three inherited frontend session/client/preference tests pass.

Real HTTP clients bootstrapped CSRF and session cookies through the Next same-origin proxy, then performed multipart upload, private download and all lifecycle actions. Missing-CSRF note mutation returned 403. Browser stale-action conflict refresh passed; cross-tab private-state isolation failed M9. No new direct browser backend-origin request path was found.

## P. API / OpenAPI / Generated Types

Canonical `npm run api:generate` passed twice, including `spectacular --validate --fail-on-warn`. Repeated LF-byte SHA-256: `F2E406F9346FA5E762D68E1DBAF59FF6A3A0F21F3351074C458CA7009A1CA511`. Generated-file `git diff --exit-code` passes. Initial raw working-copy hash difference was CRLF only, not semantic drift.

M10 documents actual multipart/filter/body/download/nullability/error-contract defects. Generated definitions are used, but Operator `any` casts, untyped action data and Directory's `as unknown as undefined` bypass contract protection. Handwritten component fixtures are not backend-derived evidence. Correct serializers/annotations rather than creating independent wire DTOs. Remove the extra tracked noncanonical schema snapshot.

## Q. Frontend Validation

Node **24.19.0** was selected explicitly; system Node 20 is below the documented requirement.

| Check | Result |
| --- | --- |
| Locked clean `npm ci` | Pass; 563 packages; reported 0 vulnerabilities |
| Lint / typecheck / production build | All pass |
| `npm test` | **3 pass** |
| `npm run test:components` | **31 pass / 6 files**: commodity 18, Directory 4, Profile 5, Operator 4 |
| Actual browser | Operator without membership queue/case; checklist action; persisted stale conflict/error refresh; session switch/cache leak; fresh customer direct case; Directory search; safe Profile |
| Locale | DOM `lang=fa`, `dir=rtl`; no horizontal overflow at observed 1280px; Operator content English, customer pages Persian |

Loading/missing/error permutations and several request assertions are jsdom-only. Full file upload/download Hero Flow cannot be exercised through absent UI controls; actual transfer was tested through HTTP instead. No comprehensive mobile/accessibility audit is claimed.

## R. CI Discovery

| Suite | Canonical command | GitHub Actions job |
| --- | --- | --- |
| Verification domain 7, permissions 8 | `python manage.py test` | `backend` |
| Verification sequential stale action 1 | `python manage.py test` | `backend` |
| Checklist domain 8, API 4 | `python manage.py test` | `backend` |
| Documents access 7, uploads 10 | `python manage.py test` | `backend` |
| Real MinIO 1, no conditional skip | `python manage.py test` | `backend` with MinIO |
| Directory 10, Profile 4 | `python manage.py test` | `backend` |
| Epic integration 3 | `python manage.py test` | `backend` |
| Health/schema 5, identity 42, organizations base/auth 30 (including association tests), commodities 91 | `python manage.py test` | `backend` |
| Directory/Profile/Operator components 13, commodity components 18 | `npm run test:components` | `frontend` |
| Session/client/preferences 3 | `npm test` | `frontend` |
| OpenAPI/generated TS drift | `npm run api:generate`; generated-file `git diff --exit-code` | `contract` |

All 231 discovered backend tests ran successfully. No checked-in automated suite was found orphaned or conditionally skipped. `pytest.ini` does not govern the canonical Django runner. CI's sequential concurrency test and integration tests that seed metadata rows do not cover real concurrent evidence or the complete upload-to-trust flow. Frontend fixtures are handwritten. Gate-only 35 tests, HTTP scripts and browser checks are outside canonical CI; they must not be represented as shipped regression protection. Hosted status on the exact SHA is not confirmed.

## S. Packaging

Built and installed `commodity_platform_api-0.1.0-py3-none-any.whl` into an isolated artifact directory: **91,226 bytes**, SHA-256 `bdfcc6ea509e4db795e9785fa9f3d4004b0114170b530b14e139faa053d3631b`. Inspected organizations, nested verification, documents/storage, config, identity, commodities, migrations and both seed commands. `organizations*` and `documents*` include the required packages. No package-discovery omission remains. A separate server startup from the installed wheel was not attempted.

## T. Epic 1–3 Regression

Canonical PostgreSQL suite passes, including identity **42**, commodity **91**, organization base/authorization **30**, health/schema **5** and all Epic 4 additions. Frontend session **3** and inherited commodity component **18** tests pass; build/typecheck/lint, deterministic OpenAPI generation and migration/seed checks pass. Master→Epic upgrade preserves seeded schema data and an existing organization.

The diff preserves the auth/session and generic commodity engine foundations. No commodity-specific organization columns or validation branches were introduced. The new private query cache/session behavior is an Epic 4 regression risk despite unchanged AuthProvider source (M9).

## U. Scope Audit

No later-Epic implementation found in the full diff/module inventory: no private relationship/invitation graph CRUD, ExternalCounterparty, RFQ, Supply, Offer, Matching, Deal, settlement/execution, analytics, scoring, external KYC, generic operational admin, or generic Notes/Audit platform. Directory is authenticated discovery. “Network” was not expanded into permanent private counterparty ownership. No infrastructure category beyond existing PostgreSQL/MinIO was introduced.

Tracked-file hygiene found no new real `.env`, virtualenv, node_modules, bytecode, SQLite database or evidence binaries in Git. Demo/CI credentials are documented test values; this is not a comprehensive secret-history audit. Existing ignored artifacts and `.env` were preserved.

## V. Fixes Made

**No application fixes were made.** Only repository change: `docs/delivery/epic-04-review-gate.md`, documenting findings and executed evidence. No implementation, migration, canonical test, dependency-manifest, CI or Product Specification changes. Generated TypeScript was regenerated and has no Git diff.

Review scripts/logs, wheel and isolated installation, baseline archive, comparison files and gate-only probes are outside the repository at:

`C:\Users\puria\.codex\visualizations\2026\09\12\01a094f6-0ac3-79c2-8956-8b9f62c3015f`

Principal logs: `epic4-backend.log`, `epic4-probes.log`, `epic4-supplement.log`, `epic4-integration.log`, `epic4-upgrade.log`. Probe source: `review_probes.py` and `review_supplement.py`. Browser observations are recorded in this gate and task tool history. The 35 probes express gate expectations and are not committed CI tests. Local runtime dependencies were installed for canonical validation; disposable databases, role, buckets and servers were cleaned up.

## W. Remaining Risks

### Actual merge risks

B1 and M1–M12 remain unresolved. Canonical green tests miss reproduced trust races, duplicate current evidence, stale checklist edits, internal disclosure, history loss, orphaned bytes and policy/format defects. UI and schema omissions prevent a complete reliable user flow. Hosted CI is unverified. These are implementation/evidence risks, not an outstanding database approval request; approved testing and cleanup are complete.

### Acceptable deployment/future work

Production TLS/host/origin configuration, existing private-bucket provisioning, retention/backups and deployment operations remain environment concerns. No malware-scanning or external KYC guarantee is claimed. Missing later-Epic RFQ/Offer/Deal/settlement features are not defects. Privileged DBA/raw SQL authority is outside API-security guarantees. No policy redesign is required to fix the listed defects.

## X. Architecture Assessment

The Django modular monolith, PostgreSQL source of truth, S3-compatible byte storage and Next.js/REST/OpenAPI structure remain appropriate; no premature infrastructure was added. Executed role and CSRF boundaries preserve product-role separation. Actual private storage/authorized retrieval work, but key projection and compensation are incomplete. Explicit Directory/Profile/`me` projections are safe; verification detail and cached privileged content are not. Backend verification exists but fails aggregate concurrency; evidence-bound checklist currentness and immutable audit history are incomplete. Backend-generated OpenAPI is deterministic but inaccurate. Persian/RTL foundations persist while the Operator UI violates locale and workflow requirements.

## Y. Merge Recommendation

`codex/epic-04-organizations-network-verification` at `7617280d8f57aed2e7b982a5505329847e1dd042` is **not safe to merge into `master`**.

Resolve the defects within approved Epic 4 policy, add canonical regression tests for the failing gate cases and missing UI/contracts, rerun complete validation on the resulting revision, verify hosted CI and obtain owner review. No commit, push, merge or Epic 5 work was performed or authorized by this review.

### Complete committed Epic file inventory

The following inventory is the original `git diff --name-only master...HEAD`; it excludes this newly added review record.
- `.github/workflows/ci.yml`
- `AGENTS.md`
- `apps/api/config/settings/base.py`
- `apps/api/config/urls.py`
- `apps/api/documents/__init__.py`
- `apps/api/documents/api/__init__.py`
- `apps/api/documents/api/serializers.py`
- `apps/api/documents/api/views.py`
- `apps/api/documents/apps.py`
- `apps/api/documents/migrations/0001_initial.py`
- `apps/api/documents/migrations/__init__.py`
- `apps/api/documents/models.py`
- `apps/api/documents/storage.py`
- `apps/api/documents/tests/__init__.py`
- `apps/api/documents/tests/test_access.py`
- `apps/api/documents/tests/test_minio.py`
- `apps/api/documents/tests/test_uploads.py`
- `apps/api/documents/urls.py`
- `apps/api/organizations/admin.py`
- `apps/api/organizations/api/permissions.py`
- `apps/api/organizations/api/serializers.py`
- `apps/api/organizations/api/views.py`
- `apps/api/organizations/migrations/0004_organizationcommodity.py`
- `apps/api/organizations/models.py`
- `apps/api/organizations/test_profiles.py`
- `apps/api/organizations/tests_authorization.py`
- `apps/api/organizations/tests_directory.py`
- `apps/api/organizations/urls.py`
- `apps/api/organizations/verification/__init__.py`
- `apps/api/organizations/verification/api_views.py`
- `apps/api/organizations/verification/apps.py`
- `apps/api/organizations/verification/migrations/0001_initial.py`
- `apps/api/organizations/verification/migrations/__init__.py`
- `apps/api/organizations/verification/models.py`
- `apps/api/organizations/verification/permissions.py`
- `apps/api/organizations/verification/serializers.py`
- `apps/api/organizations/verification/services.py`
- `apps/api/organizations/verification/tests/__init__.py`
- `apps/api/organizations/verification/tests/test_checklist.py`
- `apps/api/organizations/verification/tests/test_checklist_api.py`
- `apps/api/organizations/verification/tests/test_concurrency.py`
- `apps/api/organizations/verification/tests/test_domain.py`
- `apps/api/organizations/verification/tests/test_epic_integration.py`
- `apps/api/organizations/verification/tests_permissions.py`
- `apps/api/organizations/verification/urls.py`
- `apps/api/pyproject.toml`
- `apps/api/pytest.ini`
- `apps/api/uv.lock`
- `apps/web/package-lock.json`
- `apps/web/package.json`
- `apps/web/schema.yaml`
- `apps/web/src/app/[locale]/directory/[id]/client.tsx`
- `apps/web/src/app/[locale]/directory/[id]/layout.tsx`
- `apps/web/src/app/[locale]/directory/[id]/page.tsx`
- `apps/web/src/app/[locale]/directory/client.tsx`
- `apps/web/src/app/[locale]/directory/page.tsx`
- `apps/web/src/app/[locale]/layout.tsx`
- `apps/web/src/app/[locale]/operator/verification/[id]/page.tsx`
- `apps/web/src/app/[locale]/operator/verification/page.tsx`
- `apps/web/src/components/providers.tsx`
- `apps/web/src/components/ui/badge.tsx`
- `apps/web/src/components/ui/table.tsx`
- `apps/web/src/lib/api/generated/schema.d.ts`
- `apps/web/tests/components/directory-page.test.tsx`
- `apps/web/tests/components/directory/profile-client.test.tsx`
- `apps/web/tests/components/operator-verification.test.tsx`
- `docs/delivery/epic-04-execution-plan.md`
- `docs/delivery/roadmap.md`
- `infra/docker/docker-compose.yml`
