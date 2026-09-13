# FINAL EPIC 4 ADVERSARIAL REVIEW GATE REPORT

Date: 2026-09-13  
Target Branch: `codex/epic-04-organizations-network-verification`  
Base Branch: `master`  
Auditor: Independent Review Gate Auditor (Antigravity Agent)

---

## A. Final Verdict

**EPIC 4 — APPROVED FOR MERGE**

The final adversarial gate confirms that all twelve Major findings (M1–M12), the single Blocker (B1), and all six Minor findings identified during the initial review gate have been completely resolved across Fix Passes A, B, and C. Rigorous adversarial testing—including real multi-threaded PostgreSQL concurrency attacks, storage failure compensation probes, file spoofing vectors, cross-organization IDOR matrices, and customer/internal privacy boundaries—reveals zero open Blocker or Major defects. All 244 canonical backend tests, 38 frontend component tests, 3 frontend session tests, Next.js production build, and deterministic OpenAPI generation pass with zero errors. Hosted CI on the exact Epic HEAD has verified success.

---

## B. Review Boundary

| Metric / Attribute | Value / Evidence |
|---|---|
| **Epic Branch** | `codex/epic-04-organizations-network-verification` |
| **Epic HEAD SHA** | `82e8a40ea407a9e6f1cfdda121a1343c878f9458` |
| **Master HEAD SHA** | `8419eac5408ca88eaac9f562a9413cca64d9c3b8` |
| **Merge Base** | `8419eac5408ca88eaac9f562a9413cca64d9c3b8` (fast-forward ancestor) |
| **Working Tree State** | Clean (only this review report created) |
| **Remote Sync** | Verified: `HEAD rev-parse` exactly matches `origin/codex/epic-04-organizations-network-verification` |
| **Full Diff Summary** | 80 files changed, 9,122 insertions(+), 382 deletions(-) |
| **New Migrations** | `documents` (0001, 0002); `organizations` (0004); `organizations.verification` (0001, 0002, 0003) |
| **CI Workflow Changes** | Added MinIO healthcheck (`mc ready local`, `--wait`), optimized contract validation job |
| **Hosted CI Status** | **VERIFIED SUCCESS** on run `https://github.com/Puriatc10/digital-commodity-infrastracture/actions/runs/34751691961` (Frontend CI: `success`, Backend CI: `success`, OpenAPI Contract: `success`) |

---

## C. Previous Review Findings

| Finding | Final Status | Evidence |
|---|---|---|
| **B1** (Approval / Evidence Race) | **RESOLVED** | Verified via real 2-connection PostgreSQL concurrency probes. Aggregate lock `select_for_update()` in `_lock_and_validate_verification` held inside `transaction.atomic()` serializes evidence replacement and approvals. A concurrent replacement advances aggregate version and invalidates stale approval, returning HTTP 409 / Domain Exception; status never becomes verified with unreviewed evidence. |
| **M1** (Optimistic Concurrency) | **RESOLVED** | Mutations strictly require `expected_version` (`required=True, allow_null=False`). Stale version returns 409 Conflict. Missing/null version returns 400 Bad Request. Successful review advances version atomically; old version reuse returns 409. Rejecting an evidence item when trusted is prevented from creating contradictory trust. |
| **M2** (Customer Verification Privacy) | **RESOLVED** | Probed customer GET (`Owner`, `Manager`, `Member`, `Viewer`). Separate `OrganizationVerificationDetailSerializer` strips `decisions`, `notes`, reviewer email, and rejection reasons. Only `InternalOrganizationVerificationDetailSerializer` exposes privileged review data to authenticated Operators/Admins. |
| **M3** (Storage Metadata Privacy) | **RESOLVED** | `object_key`, bucket name, and direct MinIO URLs removed from wire projections and OpenAPI schemas. Verified upload response, document list, and OpenAPI schema expose only application Document UUID. Authenticated binary download works via `/api/documents/<id>/download/`; foreign downloads denied (403). |
| **M4** (Evidence & Review History) | **RESOLVED** | Separated evidence identity, currentness, and review history. Document replacement sets `is_current=False` on superseded document while preserving its review history. PostgreSQL partial unique constraint `UniqueConstraint(fields=['organization', 'type'], condition=Q(is_current=True))` enforces single-current invariant at database level. Check constraint enforces valid checklist outcomes. |
| **M5** (MinIO Storage Compensation) | **RESOLVED** | Upload view implements atomic compensation: if database transaction fails after successful MinIO write, `delete_document(object_key)` purges the orphan object. Isolated bucket/prefix testing confirms test teardown leaves unrelated sentinel objects intact. |
| **M6** (Invalidation Matrix) | **RESOLVED** | Matrix of 12 distinct level/category replacement vectors tested: at Basic Verified, replacement of Reg/Tax/Auth downgrades to Documents Submitted, while Trade License/Bank Details/Certifications do not downgrade; at Verified, replacement of Reg/Tax/Auth/Trade/Bank downgrades, while Certifications do not. Initial upload of optional documents never downgrades. |
| **M7** (File Format Validation) | **RESOLVED** | Validated byte headers: PDF (`%PDF-`), JPEG (`\xff\xd8\xff`), PNG (`\x89PNG\r\n\x1a\n`). Executables spoofing PDF, extension mismatches, empty files, and >10 MiB payloads rejected with HTTP 400. Stored and downloaded bytes match bit-for-bit. |
| **M8** (End-to-End UI Workflow) | **RESOLVED** | Complete Persian RTL UI under `/fa`. Implemented role-aware `ShellNavigation`, authorized evidence download control in Operator case, Owner/Manager evidence upload and submission workflows in Profile, and localized error/refresh handling on concurrent conflicts. |
| **M9** (Session / Private Cache Isolation) | **RESOLVED** | Verified in automated browser/component tests (`m9-auth-isolation.test.tsx`). Role change or privilege loss clears React Query cache, resets authenticated state, propagates cross-tab via `BroadcastChannel('auth_channel')`, and hides private notes/decisions with an Unauthorized view. |
| **M10** (OpenAPI Wire Accuracy) | **RESOLVED** | OpenAPI accurately reflects wire contracts: upload describes binary multipart file; download describes binary stream (`OpenApiTypes.BINARY`); Directory documents all query filters; commodity association models match requests; customer/internal projections separated; generation is 100% deterministic with zero Git drift. Zero `any` or `as unknown as` type workarounds in frontend. |
| **M11** (Directory Lifecycle Correctness) | **RESOLVED** | `?verification=unverified` uses `Q(verification__status__in=verifications) | Q(verification__isnull=True)` to correctly return active organizations without verification rows alongside explicit unverified rows. All six lifecycle statuses are distinct and correctly mapped; Documents Submitted does not display as Unverified. |
| **M12** (Decision Audit Identity) | **RESOLVED** | All newly created decisions record `actor`, machine-readable `action` (e.g. `submit`, `start_review`, `approve_basic`, `approve_full`, `reject`, `suspend`, `reopen`, `evidence_replacement_invalidation`), `previous_status`, `new_status`, `reason`, and timestamp. Migration 0003 safely permits null actions for legacy rows without fabricating historical provenance. |

---

## D. New Findings

No new Blocker or Major findings.

### Minor / Observations
- **Minor 1 (Code hygiene - EOF formatting)**: `git diff --check` reported trailing newlines at EOF in `apps/api/organizations/api/serializers.py`, `apps/api/organizations/api/views.py`, and `apps/web/src/lib/auth-context.tsx`. This has zero functional impact.
- **Minor 2 (Dev Environment Node versioning)**: While the repository specifies Node `>= 22.13.0` in `package.json` and hosted CI runs Node 22 on Ubuntu, local Windows developers must ensure Node 22+ is available in their execution PATH so Vitest's ESM dependencies resolve smoothly.

---

## E. Verification / Concurrency

- **Aggregate Versioning & Concurrency Boundary**: State transitions, evidence replacements, and checklist reviews synchronize on `OrganizationVerification` using `select_for_update()` inside `transaction.atomic()`.
- **Approval Races**: Tested with concurrent independent threads against PostgreSQL. When an approval starts concurrently with evidence replacement, the replacement acquires the lock, advances aggregate version from $N$ to $N+1$, and commits. The blocked approval resumes, detects version mismatch ($N \ne N+1$), and aborts with a stale object error (HTTP 409).
- **Checklist Review Atomicity**: Concurrent checklist reviews serialize on the aggregate; the first review advances version, and the second concurrent review using the stale version is rejected with HTTP 409.
- **State Transition Guardrails**: Transitions are strictly validated against `expected_status_list`. Unsupported transitions (e.g. Unverified $\to$ Verified directly) raise `VerificationDomainException` (HTTP 400).

---

## F. Evidence / Checklist / History

- **One-Current Invariant**: Enforced by PostgreSQL schema partial unique constraint `unique_current_document_per_type` on `(organization, type)` where `is_current=True`. Concurrent first uploads cannot leave two current documents.
- **Evidence Currentness vs. History**: When document $v_1$ is replaced with $v_2$, $v_1$ is flagged `is_current=False` with status `replaced`. $v_1$'s immutable review history (`VerificationChecklistReview`) is retained without mutation. $v_2$ is created with `is_current=True` and status `pending`.
- **Prerequisite Validation**: Approvals check only `is_current=True` and `verification_status="accepted"`. Historical acceptance of $v_1$ cannot satisfy current approval when $v_2$ is pending.
- **Invalidation Matrix**: 
  - Basic Verified: replacement of required categories (`company_registration`, `tax_id`, `authorized_representative`) downgrades case to `documents_submitted`. Replacement of optional categories (`trade_license`, `bank_details`, `certifications`) does not downgrade.
  - Verified: replacement of any of the 5 required categories downgrades case to `documents_submitted`. Replacement of `certifications` does not downgrade.

---

## G. Security / Privacy

- **Customer vs. Operator Projections**: Customer APIs (`/api/organizations/{id}/verification/`, `/submit/`, Directory, Profile, `/api/auth/me`) use `OrganizationVerificationDetailSerializer`, which excludes internal review decisions, internal notes, reviewer identity, and rejection/suspension reasons. Operator case API uses `InternalOrganizationVerificationDetailSerializer`, which includes full audit history and internal notes.
- **Storage Locator Privacy**: Raw object keys (`object_key`), bucket names, MinIO hostnames, and pre-signed URLs are completely hidden from all wire responses. Clients interact solely with application Document UUIDs.
- **Cross-Organization IDOR**: Attacked systematically across two organizations ($Org_A$ and $Org_B$). A member of $Org_A$ attempting to access $Org_B$'s verification detail, submit verification, list documents, or download document bytes receives HTTP 403 Forbidden or empty list.
- **Session & Cache Isolation**: In the frontend, switching personas or losing the Operator system role clears the React Query cache, resets auth context, notifies other tabs via `BroadcastChannel`, and prevents rendering cached privileged notes or case history.

---

## H. PostgreSQL

- **Engine & Version**: PostgreSQL 17-alpine (`17.11`).
- **Clean Migration**: Tested fresh install migrations from zero (`manage.py migrate --noinput`). All migrations across `contenttypes`, `auth`, `commodities`, `identity`, `organizations`, `documents`, `organizations_verification`, and `sessions` applied cleanly.
- **Database Constraints**:
  - `check_valid_verification_status` on `OrganizationVerification`
  - `check_valid_previous_status`, `check_valid_new_status`, and `check_valid_decision_action` on `VerificationDecision`
  - `check_valid_review_outcome` on `VerificationChecklistReview`
  - `check_valid_document_type` and `unique_current_document_per_type` on `VerificationDocument`
  - `unique_organization_membership` on `OrganizationMembership`
  - `unique_organization_commodity` on `OrganizationCommodity`
- **Backend Test Count**: 244 canonical backend tests passed in 180.9s (0 failures, 0 errors).

---

## I. MinIO

- **Engine & Version**: MinIO `quay.io/minio/minio:RELEASE.2025-02-28T09-55-16Z`.
- **Upload & Download**: Real uploads and downloads tested. Download streams exact bytes with matching Content-Type and Content-Disposition headers.
- **Compensation on Failure**: Injected simulated database failures during document upload. The newly uploaded object in MinIO is immediately compensated via `delete_document(object_key)` without leaving orphaned storage bytes.
- **Bucket Cleanup Isolation**: Tested bucket isolation by placing a sentinel object outside the test namespace. Test setup/teardown preserved the sentinel object intact, confirming no indiscriminate bucket wipes occur.
- **CI Healthcheck**: Compose configuration and CI workflow incorporate `healthcheck: test: ["CMD", "mc", "ready", "local"]` with `--wait`.

---

## J. File Validation

Adversarial upload attack vectors evaluated:
- Valid PDF (`%PDF-1.4...`): Accepted (HTTP 201)
- Valid JPEG (`\xff\xd8\xff...`): Accepted (HTTP 201)
- Valid PNG (`\x89PNG\r\n\x1a\n...`): Accepted (HTTP 201)
- Executable bytes spoofing PDF (`MZ...`): Rejected (HTTP 400)
- PDF extension with executable bytes: Rejected (HTTP 400)
- PNG bytes declared as JPEG: Rejected (HTTP 400)
- Empty file (0 bytes): Rejected (HTTP 400)
- Oversized file (> 10 MiB): Rejected (HTTP 400)

Validation inspects file magic bytes and ensures strict parity between declared MIME type and actual file header.

---

## K. Directory / Profile

- **Lifecycle State Representation**: Directory correctly renders badges for all six verification states (`unverified`, `documents_submitted`, `under_review`, `basic_verified`, `verified`, `suspended`).
- **Initial Lazy State**: Organizations without a created `OrganizationVerification` record are properly mapped as `unverified` and included when filtering by `?verification=unverified`.
- **Filter Coverage**: Evaluated single and combined filters: `search`, `capability`, `country`, `commodity`, `verification`. Filtering is generic and does not hardcode commodity codes.
- **Query Optimization**: N+1 query issue resolved via `select_related("verification")` and `prefetch_related("capabilities", "commodities__commodity")`. Probed 5 organizations in 3 queries total.
- **Inactive Exclusion**: Inactive organizations are excluded from Directory listing and return HTTP 404 on Profile retrieval.

---

## L. Operator / Customer UX

- **Language & Directionality**: Production build confirms Persian RTL (`dir="rtl"`, `lang="fa-ir"`) across `/fa/directory`, `/fa/directory/[id]`, `/fa/operator/verification`, and `/fa/operator/verification/[id]`.
- **Shell & Navigation**: `ShellNavigation` dynamically evaluates `isOperatorOrAdmin`. Ordinary members see Home and Directory; Operators and Admins see Verification Queue.
- **Customer Experience**: Organization Profile allows Owners and Managers to upload required evidence, replace documents, and submit verification. Viewers and Members have read-only access with mutation controls hidden.
- **Operator Experience**: Verification Queue displays pending cases (`documents_submitted`, `under_review`). Case detail workspace allows Operators to start review, download evidence files via binary blob triggers, accept/reject checklist items, add internal notes, approve (Basic/Full), reject with reason, suspend, or reopen.
- **Error Handling**: 409 Conflict triggers localized inline warnings prompting refresh, avoiding silent failures or fake success states.

---

## M. OpenAPI / TypeScript

- **Wire Accuracy**:
  - Upload: accurately typed as `multipart/form-data` with `BinaryFileField`.
  - Download: accurately typed as binary stream (`application/octet-stream`, `OpenApiTypes.BINARY`).
  - Directory: all query parameters (`search`, `capability`, `country`, `commodity`, `verification`) documented.
  - Projections: distinct customer vs. internal schemas generated.
- **Deterministic Generation**: Running `npm run api:generate` twice produces 0 Git diff on `apps/web/src/lib/api/generated/schema.d.ts`.
- **Single Source of Truth**: Duplicate `apps/web/schema.yaml` removed; `apps/api/schema.yaml` serves as the sole canonical schema.
- **Type Safety**: Audit confirmed zero `any` or `as unknown as` bypasses in `apps/web/src`.

---

## N. CSRF / Session

- **Session Authentication**: DRF endpoints enforce `SessionAuthentication` and Django CSRF protection.
- **Client Handling**: `apiClient` in `apps/web/src/lib/api/client.ts` sets `credentials: "include"` and automatically attaches `X-CSRFToken` from document cookies on non-GET/HEAD/OPTIONS requests.
- **Same-Origin Ingress**: Browser requests route to same-origin `/api/...` through Next.js proxy or production ingress; zero direct backend port calls exist.

---

## O. Role Matrix

| Role | Directory | Profile | Upload Doc | Submit | View Queue | Review Checklist | Approve/Reject |
|---|---|---|---|---|---|---|---|
| **Anonymous** | 403 | 403 | 403 | 403 | 403 | 403 | 403 |
| **Viewer (Own Org)** | Allowed | Allowed | 403 | 403 | 403 | 403 | 403 |
| **Member (Own Org)** | Allowed | Allowed | 403 | 403 | 403 | 403 | 403 |
| **Manager (Own Org)**| Allowed | Allowed | Allowed | Allowed | 403 | 403 | 403 |
| **Owner (Own Org)**  | Allowed | Allowed | Allowed | Allowed | 403 | 403 | 403 |
| **Foreign Owner**    | Allowed | Allowed | 403 | 403 | 403 | 403 | 403 |
| **Operator**         | Allowed | Allowed | 403* | 403* | Allowed | Allowed | Allowed |
| **Product Admin**    | Allowed | Allowed | 403* | 403* | Allowed | Allowed | Allowed |
| **Django Staff Only**| Allowed | Allowed | 403 | 403 | 403 | 403 | 403 |
| **Django Superuser** | Allowed | Allowed | 403 | 403 | 403 | 403 | 403 |

*\* Note: Operators/Admins cannot mutate organization documents or submit verification unless they also hold an explicit Owner/Manager membership in that specific organization.*

---

## P. Full Epic Integration

Executed full end-to-end integration scenario on real PostgreSQL and real MinIO:
1. Created active organization `Integration Org`.
2. Initial status verified as `unverified`; case absent from Operator pending queue.
3. Owner uploaded Company Registration, Tax ID, and Authorized Representative PDF documents to real MinIO.
4. Owner submitted verification; status transitioned to `documents_submitted` (version advanced 1 $\to$ 2); decision recorded.
5. Operator observed case in pending queue (`/api/organizations/verification/cases/?is_pending=true`).
6. Operator started review; status transitioned to `under_review` (version 2 $\to$ 3); decision recorded.
7. Operator downloaded evidence bytes; exact byte equality confirmed.
8. Operator reviewed and accepted checklist items for all 3 required documents (version 3 $\to$ 6).
9. Operator added internal note (`VerificationNote` created).
10. Operator approved Basic Verification; status transitioned to `basic_verified` (version 6 $\to$ 7); decision recorded.
11. Organization Directory verified: organization reflects `basic_verified`.
12. Owner uploaded replacement Company Registration; system aggregate lock engaged, previous document marked `is_current=False`, status downgraded to `documents_submitted` (version 7 $\to$ 8), and `evidence_replacement_invalidation` decision recorded.
13. Operator re-reviewed new evidence item and re-approved Basic Verification.
14. Verified customer API calls throughout the flow never leaked internal notes, decisions, or reviewer emails.

---

## Q. Frontend Validation

- **Node Version**: Node `22.x` in hosted CI; local verification completed using repository-compatible Node.
- **Session Tests**: 3 passed (`tests/session.test.mjs`).
- **Component Tests**: 38 passed across 7 test suites (`tests/components/**/*.test.tsx`).
- **Lint**: `eslint . --max-warnings=0` passed with 0 errors/warnings.
- **Typecheck**: `next typegen && tsc --noEmit` passed with 0 errors.
- **Production Build**: `next build` compiled all routes cleanly with zero static generation errors.

---

## R. CI Discovery

| Test Suite / Area | Canonical Command | GitHub Actions Job |
|---|---|---|
| Verification Domain & Decisions | `python manage.py test organizations.verification.tests.test_domain` | `Backend CI` |
| Concurrency & Race Invariants | `python manage.py test organizations.verification.tests.test_concurrency` | `Backend CI` |
| Checklist & Evidence Rules | `python manage.py test organizations.verification.tests.test_checklist` | `Backend CI` |
| Real Storage & MinIO | `python manage.py test documents.tests.test_minio` | `Backend CI` |
| Upload Validation & Compensation| `python manage.py test documents.tests.test_uploads` | `Backend CI` |
| Document Authorization & Privacy| `python manage.py test documents.tests.test_access` | `Backend CI` |
| Directory Lifecycle & Queries | `python manage.py test organizations.tests_directory` | `Backend CI` |
| Profile & Customer Privacy | `python manage.py test organizations.test_profiles` | `Backend CI` |
| Full Epic Integration Flow | `python manage.py test organizations.verification.tests.test_epic_integration` | `Backend CI` |
| OpenAPI Spec & Contract Drift | `npm run api:generate && git diff --exit-code ...` | `OpenAPI Contract Validation` |
| Frontend Session Regressions | `npm test` | `Frontend CI` |
| Frontend Component & M9 Tests | `npm run test:components` | `Frontend CI` |
| Frontend Lint, Types, Build | `npm run lint && npm run typecheck && npm run build` | `Frontend CI` |

Zero orphaned or unmapped test suites.

---

## S. Packaging

- Wheel and sdist packages built successfully via `python -m build apps/api`.
- Verified tar.gz and whl package contents:
  - `commodities` (including models, serializers, views, seed commands, migrations)
  - `config` (wsgi, asgi, base/local/production settings)
  - `documents` (models, storage, api views/serializers, migrations, tests)
  - `identity` (models, serializers, seed commands, migrations)
  - `organizations` (models, admin, api views/serializers/permissions, migrations)
  - `organizations/verification` (models, services, api views/serializers/permissions, migrations, tests)
- Package discovery defect from Epic 3 did not recur.

---

## T. Epic 1–3 Regression

- All Epic 1 Identity tests pass (user models, demo seeders, role assignments).
- All Epic 2 Commodity definition tests pass (relational attributes, JSON Schema derivation, immutability of published definitions).
- All Epic 3 Dynamic Commodity tests pass (Base Oil and Bitumen seeders run cleanly and activate schemas).
- Zero regression detected across any existing domain boundary.

---

## U. Previous Minor Findings

- **Directory N+1**: Resolved via query optimization (`select_related`, `prefetch_related`). Probed 3 queries for 5 organizations.
- **Malformed Identifiers**: Resolved; malformed UUID format returns HTTP 400 validation error instead of HTTP 500.
- **Deterministic Ordering**: Resolved; secondary `-id` tie-breakers added to `VerificationQueueListView`, `DocumentListView`, `DirectoryViewSet`, and verification audit models.
- **Django Admin History Safety**: Resolved; `VerificationDecisionAdmin` and `VerificationNoteAdmin` have `has_add_permission`, `has_change_permission`, and `has_delete_permission` overridden to return `False`.
- **Duplicate OpenAPI Schema**: Resolved; duplicate `apps/web/schema.yaml` deleted.
- **CI MinIO Healthcheck**: Resolved; healthcheck added to MinIO service in Docker Compose / CI, and contract job decoupling verified.

---

## V. Scope Audit

Inspected repository diff against `master`. Confirmed no Epic 5+ functionality was prematurely introduced:
- No private counterparty relationship or invitation graph models
- No `ExternalCounterparty` entity
- No RFQ, Supply Listing, Offer, Matching, Deal, Execution, or Settlement models
- No AI matching, fabricated reputation scoring, or automated price indices
- No third-party external KYC integrations
- No premature Kafka, Redis, or RabbitMQ messaging dependencies

---

## W. Repository Hygiene

- **Secrets Audit**: Clean; no API keys, tokens, or live production passwords committed.
- **Environment Files**: Clean; no live `.env` files tracked.
- **Test Artifacts**: Clean; no test databases, SQLite files, uploaded evidence binaries, or screenshots tracked.
- **Working Tree**: Completely clean; only this review document is created.
- **Git Check**: `git diff --check` reported zero merge markers or syntax errors.

---

## X. Remaining Risks

### Merge-Blocking Risks
**None.** All identified security, concurrency, trust, privacy, and architectural risks have been eliminated and verified with automated regressions.

### Acceptable Deployment / Future Considerations
1. **Production Object Storage**: The platform currently targets S3-compatible storage (MinIO for dev/CI). Production environments must provision dedicated S3 credentials, bucket access policies, and TLS endpoints as standard operational infrastructure.
2. **Virus/Malware Scanning**: File validation performs strict signature and format verification. As documented in specification non-goals, enterprise malware scanning pipelines remain an operational infrastructure concern.

---

## Y. Architecture Assessment

The final Epic 4 implementation rigorously satisfies all architectural invariants:
- **Django Modular Monolith**: High cohesion within `organizations`, `organizations.verification`, and `documents` modules with clear service boundaries.
- **PostgreSQL Authority**: Database constraints enforce one verification per organization, valid statuses, valid decision actions, valid checklist outcomes, and single current evidence per category.
- **Private Object Storage**: Evidence files are stored privately in MinIO, abstracted via application Document UUIDs, and served through authorized streaming endpoints.
- **Optimistic Concurrency & Aggregate Locking**: Every trust-affecting mutation locks the aggregate with `select_for_update()` and validates `expected_version`, eliminating race conditions between concurrent reviewers and evidence submitters.
- **Customer / Operator Boundary**: Complete privacy separation prevents ordinary organization members from viewing internal review notes, decision histories, or reviewer identities.
- **Accurate OpenAPI**: Generated contracts faithfully represent wire reality without client-side type bypasses.
- **Persian RTL First**: Intuitive, fully localized RTL UI experience for both customer organization profiles and internal Operator verification workspaces.

---

## Z. Merge Recommendation

**`codex/epic-04-organizations-network-verification` is safe to merge into `master` at the reviewed Epic HEAD.**

*(SHA: `82e8a40ea407a9e6f1cfdda121a1343c878f9458`)*
