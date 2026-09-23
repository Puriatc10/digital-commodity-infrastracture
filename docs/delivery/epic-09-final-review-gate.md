# FINAL EPIC 9 ADVERSARIAL REVIEW GATE REPORT

Date: 2026-09-23  
Target Epic Branch: `codex/epic-09-deal-attribution`  
Base Branch: `master`  
Auditor: Independent Review Gate Auditor (Antigravity Agent)  

---

> **All findings and the final verdict apply only to Epic HEAD `9762692a111a375e301b2cc2017ae9175453113b`.**

---

## A. Review Boundary

| Metric / Attribute | Value / Evidence |
|---|---|
| **Epic Branch** | `codex/epic-09-deal-attribution` |
| **Epic HEAD SHA** | `9762692a111a375e301b2cc2017ae9175453113b` |
| **Master HEAD SHA** | `b06e74b7cd8c110c5a617de52f3f79684edc0fef` |
| **Merge Base SHA** | `b06e74b7cd8c110c5a617de52f3f79684edc0fef` (clean fast-forward ancestor) |
| **Branch Divergence** | 12 commits ahead of `master`, 0 commits behind |
| **Working Tree State** | Clean (`git status --porcelain` contains only review documentation) |
| **Staged / Untracked Tracked-Relevant Files** | 0 files |
| **Total Files Changed vs Master** | 55 files |
| **Complete Diffstat vs Master** | 15,170 insertions(+), 101 deletions(-) across 55 files |
| **New Database Migrations (4 total)** | `apps/api/deals/migrations/0001_initial.py`<br>`apps/api/deals/migrations/0002_dealcostsnapshot_dealpartysnapshot_and_more.py`<br>`apps/api/deals/migrations/0003_dealattribution.py`<br>`apps/api/deals/migrations/0004_dealbrokerattribution_dealopportunityattribution.py` |
| **Generated Contract Files** | `apps/web/src/lib/api/generated/schema.d.ts` (100% deterministic, 0 uncommitted drift verified via drf-spectacular and openapi-typescript) |
| **Frontend Deals Components** | `apps/web/src/app/[locale]/deals/[id]/deal-workspace-client.tsx`<br>`apps/web/src/app/[locale]/deals/[id]/page.tsx`<br>`apps/web/src/app/[locale]/deals/deals-list-client.tsx`<br>`apps/web/src/app/[locale]/deals/page.tsx`<br>`apps/web/src/components/shell-navigation.tsx`<br>`apps/web/src/i18n/messages/fa.ts`<br>`apps/web/tests/components/deal-workspace.test.tsx` |
| **Hosted CI Status** | `HOSTED CI STATUS UNVERIFIED` (private repository; GitHub API check-runs unauthenticated query returned 404). Full local canonical validation executed against PostgreSQL 17. |

### Commit Sequence Verification

The 12 commits between `master` and Epic HEAD represent the full, orderly Epic 9 delivery sequence:
- **Design Contract**: Commit `1de0f18` — `feat(docs): add epic 9 design contract doc`
- **T0901 — Deal Domain Model & Materialization Foundation**: Commits `700af63`, `3da43e5` (PR #160)
- **T0902 — Deal Snapshots (Terms, Cost, Party)**: Commits `726fe56`, `2b1953a` (PR #163)
- **T0903 — Deal Attribution Resolution Engine**: Commits `d62f86b`, `255586a` (PR #165)
- **T0904 — Broker & Opportunity Provenance Attribution**: Commits `324b6de`, `f88036d` (PR #166)
- **T0905 — Deal Workspace UI & Navigation**: Commits `b61fe00`, `443f36b`, `9762692` (PR #168)

---

## B. Final Verdict

```text
EPIC 9 — APPROVED FOR MERGE
```

Approval justification:
- **Blockers**: 0
- **Majors**: 0
- **Minors**: 1 (CI push filter branch configuration; non-blocking)
- **Nits**: 0

---

## C. Executive Summary

A fresh, independent, adversarial Final Review Gate was executed against Epic HEAD `9762692a111a375e301b2cc2017ae9175453113b`.

Every architectural invariant, domain contract, commercial precision rule, concurrency guard, attribution precedence policy, and privacy boundary mandated by the Product Specification and the Epic 9 Design Contract was aggressively verified:

1. **Deal Cardinality & Source Graph Integrity**:
   - `Deal.award_allocation` is a `OneToOneField` backed by a native PostgreSQL UNIQUE constraint: exactly 1 `AwardAllocation` produces exactly 1 `Deal`. Multi-award allocations materialize into $N$ distinct Deal records; multi-party deals are strictly prohibited.
   - Economic Seller XOR constraint (`check_deal_seller_exclusive`) strictly enforces `seller_organization` XOR `seller_external_counterparty` at the database level.
   - Buyer Organization is derived authoritatively from `RFQ.organization_id`, never client-supplied.
   - All commercial sources (Award, Allocation, RFQ, Offer, OfferVersion, Buyer, Seller, CreatedBy) are protected with `on_delete=models.PROTECT`, preventing cascade deletion of historical records.

2. **Explicit Materialization & Finalized-Only Gate**:
   - Deals can only be materialized via `POST /api/awards/{award_id}/materialize-deals/`. Generic `POST /deals/` creation endpoints do not exist.
   - Materialization strictly requires `Award.status == FINALIZED`. Draft awards trigger immediate rejection with HTTP 400 (`AwardNotFinalizedError`).
   - Materialization is idempotent: re-calling materialization on an already materialized award returns HTTP 200 with the existing Deals and `created=False` without regenerating or mutating snapshots.

3. **Multi-Threaded PostgreSQL Concurrency & Row Locks**:
   - Materialization locks the parent `RFQ` and `Award` rows using `select_for_update()`, preventing concurrent materialization races and guaranteeing serialization.
   - Manual attribution resolution locks the `DealAttribution` row using `select_for_update()`, enforcing optimistic concurrency via `expected_version`; conflicting resolution attempts fail cleanly with HTTP 409 Conflict.
   - Concurrency stress tests across multiple PostgreSQL threads executed with 0 deadlocks, 0 integrity corruptions, and 0 uncaught 500 errors.

4. **Commercial Immutability & Snapshot Exactness**:
   - `DealTermsSnapshot` locks the commercial terms: awarded quantity (from `AwardAllocation.awarded_quantity`, never `offered_quantity`), unit price, currency, payment terms, delivery terms, Incoterms, delivery dates, and dynamic specifications JSONB.
   - Product cost snapshot is computed using strictly Decimal arithmetic (`unit_price * quantity`). Logistics cost uncertainty (`UNKNOWN`) is preserved as non-numeric uncertainty without converting to zero.
   - `DealCostSnapshot` deep-copies child breakdown costs from `OfferCostComponent` without maintaining a live foreign key.
   - `DealPartySnapshot` stores minimal legal commercial identity (name, country, registration identifier) for BUYER and SELLER without leaking PII, telephone numbers, emails, notes, or verification files.
   - Model-level `clean()` and `delete()` methods permanently block updates and deletions across all snapshot tables once persisted.

5. **Deterministic Attribution Precedence & ACL Separation**:
   - Attribution resolver strictly executes the 5-tier roadmap precedence:
     1. `BUYER_EXISTING_SUPPLIER` (prior completed/active deal exists between buyer and seller)
     2. `BROKER` (explicit broker referral on RFQ, Supply Opportunity, or broker seller role)
     3. `OPPORTUNITY_DESK` (matched or operator-qualified supply opportunity without broker)
     4. `PLATFORM_NETWORK` (independent platform discovery without broker or desk match)
     5. `DIRECT_SUPPLIER` (direct supplier participation without platform network match)
   - Status transitions deterministically to `RESOLVED` when evidence is unambiguous, or remains `PENDING` when operator review is required.
   - Attribution is immutable once `RESOLVED`; subsequent calls cannot overwrite or reopen the resolution.
   - **Attribution $\neq$ ACL Invariant**: Broker attribution records historical credit only and grants **zero** Deal access. Attributed brokers who are not the economic seller receive HTTP 403 Forbidden across all deal endpoints.
   - Projection sanitization: Customer-facing endpoints strictly redact `evidence_snapshot`, `resolved_by`, `resolution_reason`, and nested broker/opportunity attribution details.

6. **Dynamic Specifications & Commodity Agnosticism**:
   - Generic deal code contains zero hard-coded branching on commodity definitions or attributes (bitumen, penetration grade, viscosity).
   - Historical `CommoditySchemaVersion` is locked at deal materialization time, guaranteeing that subsequent schema activations or version upgrades never invalidate or mutate existing deals.

7. **Distribution, Packaging & Frontend Workspace**:
   - Backend wheel `commodity_platform_api-0.1.0-py3-none-any.whl` (818,485 bytes) packages all 34 files across `deals/`. Direct external installation verified clean `django check`.
   - Generated TypeScript client (`schema.d.ts`) matches the OpenAPI schema with 0 diff and 0 type bypasses (`as any`).
   - Frontend Deal Workspace provides a full Persian RTL experience (`/fa/deals/[id]`), structured snapshots, attribution status, and read-only commercial guarantees.

---

## D. Blockers

**None.** Zero Blocker defects identified.

---

## E. Majors

**None.** Zero Major defects identified.

---

## F. Minors

### Minor 1 — CI Workflow Push Trigger Branch Filter Omits Epic 6–9
- **File**: `.github/workflows/ci.yml` (lines 5–11)
- **Description**: The GitHub Actions push branch filter enumerates branches up through `codex/epic-05-*`. Direct pushes to `codex/epic-06-*`, `codex/epic-07-*`, `codex/epic-08-*`, and `codex/epic-09-*` do not trigger push workflow runs. However, all pull requests (including those targeting `codex/epic-09-deal-attribution` and `master`) trigger full automated CI under `pull_request:`.
- **Severity**: **Minor** (Non-blocking configuration nuance; PR validation gates remain active).
- **Remediation**: Update `.github/workflows/ci.yml` to include `codex/epic-*` in a future infrastructure maintenance pass.

---

## G. Nits

**None.** Zero Nit defects identified.

---

## H. Domain Verification Matrix

| Area / Subsystem | Invariant / Requirement | Attack / Verification Executed | Status |
|---|---|---|---|
| **Deal Aggregate Identity** | 1 `AwardAllocation` $\to$ exactly 1 `Deal` | Attacked with duplicate creation for same allocation $\to$ rejected by DB unique constraint (`OneToOneField`) | **PASS** |
| **Multi-Award Materialization** | Multi-allocation Award creates $N$ distinct Deals | Finalized multi-award (3 allocations) materialized $\to$ exactly 3 distinct Deals created, each linking to its respective allocation | **PASS** |
| **Seller XOR Constraint** | Exactly one: `seller_organization` XOR `seller_external_counterparty` | Tested both set $\to$ `IntegrityError` (DB check constraint); neither set $\to$ `IntegrityError`; single seller $\to$ success | **PASS** |
| **External Counterparty Seller** | Deal supports off-platform `ExternalCounterparty` seller | Materialized deal from external quote $\to$ `is_external=True`, `seller_display_name` populated, `seller_organization=None` | **PASS** |
| **Buyer Derivation** | Buyer organization derived strictly from `RFQ.organization` | Attacked materialization with mismatched buyer $\to$ rejected by `clean()` and materialization service | **PASS** |
| **Source Graph Integrity** | Allocation, Award, RFQ, Offer, OfferVersion must referentially align | Mismatched RFQ, Offer, or Version injected $\to$ rejected with `DealSourceIntegrityError` and `ValidationError` | **PASS** |
| **No Cascade Deletions** | All source entities use `on_delete=models.PROTECT` | Attempted deletion of Award, Allocation, RFQ, Offer, Version, Buyer Org, Seller Org, User $\to$ all raise `ProtectedError` | **PASS** |
| **Materialization Endpoint Gate** | No generic `POST /deals/` creation API | Audited `deals/urls.py` and views: only `POST /api/awards/{id}/materialize-deals/` exists; direct deal creation blocked | **PASS** |
| **Finalized-Only Award Gate** | Awards in `DRAFT` status cannot materialize deals | Attacked draft award materialization $\to$ rejected with HTTP 400 (`AwardNotFinalizedError`) | **PASS** |
| **Materialization RBAC** | Buyer Owner/Manager/Member or Platform Operator/Admin only | Attacked with competitor supplier, foreign buyer, inactive member, viewer, unauthenticated $\to$ all rejected with 403/401 | **PASS** |
| **Materialization Idempotency** | Calling materialize multiple times returns existing deals without side effects | Re-ran materialization on finalized award $\to$ returns HTTP 200, identical Deal IDs, `created=False`, 0 duplicate rows | **PASS** |
| **Optimistic Concurrency (Materialize)** | `expected_version` prevents materialization against stale Award | Injected version mismatch $\to$ rejected with `StaleVersionError`; non-positive integer $\to$ rejected with `DealValidationError` | **PASS** |
| **Concurrent Materialization Race** | 2 concurrent requests to materialize same Award | Tested with multi-threaded PostgreSQL execution + `threading.Barrier` $\to$ both return valid Deals, 0 duplicate deals, 0 500s | **PASS** |
| **Terms Snapshot Awarded Quantity** | Quantity must equal `AwardAllocation.awarded_quantity` | Verified against partial award (500 MT awarded vs 1000 MT offered) $\to$ terms snapshot quantity is exactly 500 MT | **PASS** |
| **Monetary Precision & Product Cost** | Decimal arithmetic exclusively (`unit_price * quantity`) | Audited calculation: `Decimal(unit_price) * Decimal(quantity)` rounded to 2 decimal places. Floating-point arithmetic strictly absent | **PASS** |
| **Logistics Cost Truth** | `UNKNOWN` preserved as uncertainty, never converted to 0 | Evaluated `UNKNOWN` logistics status $\to$ `logistics_cost_amount=None`; `KNOWN_SEPARATE` requires amount $\ge 0$ | **PASS** |
| **Delivery Window Invariant** | `delivery_start <= delivery_end` when both are present | DB check constraint `check_deal_terms_delivery_window_valid` tested with inverted dates $\to$ rejected by DB constraint | **PASS** |
| **Cost Snapshot Breakdown** | Independent child rows deep-copied from `OfferCostComponent` | Materialized deal with 2 cost components $\to$ 2 `DealCostSnapshot` rows created; no live FK to `OfferCostComponent` | **PASS** |
| **Party Snapshot Completeness** | Exactly 1 BUYER and 1 SELLER snapshot per Deal | DB unique constraint `unique_deal_party_role` and XOR backing checked $\to$ minimal identity stored, 0 PII leaked | **PASS** |
| **Dynamic Commodity Schema Lock** | Historical `CommoditySchemaVersion` locked at creation | Activated newer commodity schema version $\to$ existing DealTermsSnapshot retains historical schema version intact | **PASS** |
| **Commodity Agnosticism** | Zero commodity-specific branching in deal logic | Grepped `deals/` for `bitumen`, `penetration`, `viscosity`, `commodity.code ==` $\to$ 0 occurrences found | **PASS** |
| **Terms & Party Immutability** | Modification or deletion of snapshots forbidden | Tested `save()` mutation and `delete()` on Terms, Party, Cost snapshots $\to$ all raise `ValidationError` | **PASS** |
| **DealAttribution 1:1 Linkage** | Exactly 1 `DealAttribution` per `Deal` (`OneToOneField`) | Tested creating duplicate attribution for same deal $\to$ rejected by DB unique constraint | **PASS** |
| **Attribution Status Lifecycle** | Exactly `PENDING` (null channel) or `RESOLVED` (non-null channel) | DB check constraint `check_deal_attribution_status_channel_consistency` tested with inverted combinations $\to$ rejected | **PASS** |
| **Deterministic Precedence: Tier 1** | `BUYER_EXISTING_SUPPLIER` takes highest precedence | Tested buyer with prior deal with supplier $\to$ resolves to `BUYER_EXISTING_SUPPLIER` even if broker referral exists | **PASS** |
| **Deterministic Precedence: Tier 2** | `BROKER` takes second precedence | Tested broker referral on RFQ / Supply Opportunity $\to$ resolves to `BROKER` | **PASS** |
| **Deterministic Precedence: Tier 3** | `OPPORTUNITY_DESK` takes third precedence | Tested matched supply opportunity without broker $\to$ resolves to `OPPORTUNITY_DESK` | **PASS** |
| **Deterministic Precedence: Tier 4** | `PLATFORM_NETWORK` takes fourth precedence | Tested platform discovery without broker or desk match $\to$ resolves to `PLATFORM_NETWORK` | **PASS** |
| **Deterministic Precedence: Tier 5** | `DIRECT_SUPPLIER` takes fifth precedence | Tested direct supplier participation without platform network match $\to$ resolves to `DIRECT_SUPPLIER` | **PASS** |
| **Server-Owned Attribution Audit** | Client cannot forge resolution audit metadata | Resolving attribution records authenticated `resolved_by`, `resolved_at`, and structured `evidence_snapshot` | **PASS** |
| **Attribution Immutability** | Once `RESOLVED`, cannot be altered or reopened | Tested re-resolving or updating resolved attribution $\to$ raises `ValidationError` / HTTP 400 | **PASS** |
| **Attribution Concurrency Races** | Concurrent manual resolutions of same attribution | Tested 2 concurrent resolution threads with `expected_version` $\to$ 1 succeeds, 1 receives HTTP 409 Conflict | **PASS** |
| **Broker Provenance Entity** | `DealBrokerAttribution` records broker role and opportunity | Tested unique constraint `UNIQUE NULLS NOT DISTINCT (deal, broker, role, opportunity)` $\to$ duplicates blocked | **PASS** |
| **Opportunity Provenance Entity** | `DealOpportunityAttribution` records opportunity linkage | Tested unique constraint `(deal, opportunity, role)` $\to$ duplicates blocked | **PASS** |
| **Attribution $\neq$ ACL Invariant** | Attributed broker has ZERO deal access unless economic seller | Tested attributed broker querying Deal API endpoints $\to$ returns HTTP 403 Forbidden | **PASS** |
| **Deal Detail View ACL** | Buyer Org, Seller Org, or Operator/Admin only | Tested foreign buyer, competitor supplier, unauthenticated user $\to$ returns HTTP 403 / 401 | **PASS** |
| **Customer Projection Privacy** | Internal resolution details redacted for customers | Buyer/Seller view of DealAttribution: `evidence_snapshot=null`, `resolved_by=null`, broker/opp lists `[]` | **PASS** |
| **Operator Projection Completeness** | Operator/Admin receives full resolution audit details | Operator view includes complete `evidence_snapshot`, `resolved_by_id`, `resolution_reason`, and provenance rows | **PASS** |
| **Migration Reversibility** | Migrations 0001 through 0004 apply and unapply cleanly | Ran `python manage.py migrate deals zero` then `python manage.py migrate deals` against PostgreSQL 17 $\to$ clean | **PASS** |
| **Migration 0004 Backfill** | Data migration backfills existing deals deterministically | Tested backfill function on deals with and without provenance $\to$ exact rows created, zero fabrication | **PASS** |
| **Packaging & Distribution** | Built wheel contains all deals modules and migrations | Built `commodity_platform_api-0.1.0-py3-none-any.whl` (818,485 bytes), installed outside repo, verified `django check` | **PASS** |
| **OpenAPI & Generated TypeScript** | Schema generation valid; TS client drift-free | `spectacular --validate --fail-on-warn` passed. Repeated openapi-typescript run yielded 0 diff. Zero `as any` bypasses | **PASS** |
| **Frontend Deal Workspace** | Persian RTL `/fa/deals/[id]` workspace with snapshots | Tested Deal workspace client: renders tabs, summary metrics, commercial terms, parties, and attribution | **PASS** |
| **Clean Epic Boundaries** | Zero Epic 10/11 leakage (execution, logistics, payments) | Audited codebase: zero execution milestone models, payment processors, or escrow logic introduced | **PASS** |
| **Canonical Backend CI** | Full backend test suite against PostgreSQL 17 | **1,620 tests passed in 244.1s (0 failures, 0 errors, 0 skips)** | **PASS** |
| **Frontend CI** | Vitest, Node tests, ESLint, TypeScript, Production Build | 18 vitest files (166 tests) passed, 3 node tests passed, lint 0 warnings, typecheck clean, `next build` successful | **PASS** |

---

## I. Commercial Integrity & Immutability Audit

1. **Award Allocation vs Deal Correspondence**:
   - `Deal.award_allocation` is a `OneToOneField` with `on_delete=models.PROTECT`.
   - Multi-award allocations materialize into $N$ distinct Deal records. There is no concept of a combined multi-seller Deal aggregate.
   - Awarded quantity is strictly taken from `AwardAllocation.awarded_quantity`. In partial award scenarios, the offered quantity (which was higher) is completely ignored in favor of the awarded quantity.

2. **Snapshot Immutability Enforcement**:
   - `DealTermsSnapshot.clean()` checks if `self.pk` exists in the database. If already persisted, any call to `save()` raises `ValidationError("DealTermsSnapshot is immutable and cannot be updated.")`.
   - `DealTermsSnapshot.delete()` raises `ValidationError("DealTermsSnapshot is immutable and cannot be deleted.")`.
   - `DealPartySnapshot.clean()` and `delete()` enforce identical immutability: once written, party legal identity snapshots cannot be changed or removed.
   - `DealCostSnapshot.clean()` and `delete()` prohibit any modification or deletion of breakdown cost components.

3. **Logistics Cost & Uncertainty**:
   - `UNKNOWN`: Logistics cost status `UNKNOWN` is preserved as genuine uncertainty. `logistics_cost_amount` is forced to `None`. The database check constraint `check_deal_terms_logistics_cost_consistency` guarantees that non-`KNOWN_SEPARATE` statuses cannot possess a numeric logistics amount.
   - `KNOWN_SEPARATE`: Requires `logistics_cost_amount >= 0`. Contributes directly to the total commercial landed cost.

---

## J. Privacy, Authorization & ACL Verification

1. **Strict Deal Access Control**:
   - `_check_deal_read_access` restricts deal visibility exclusively to:
     - Platform OPERATOR or ADMIN (via active `SystemRoleAssignment`).
     - Active members (Owner, Manager, Member, Viewer) of the `buyer_organization`.
     - Active members (Owner, Manager, Member, Viewer) of the `seller_organization`.
     - If the seller is an off-platform `ExternalCounterparty`, only Buyer and Operators can view the deal.
   - All other parties (including foreign buyers and competitor suppliers) receive HTTP 403 Forbidden.

2. **Attribution $\neq$ ACL Guard**:
   - A Broker who originated or referred the supply opportunity or RFQ may be awarded historical broker attribution in `DealBrokerAttribution`.
   - However, attribution confers **zero** operational or read permissions on the Deal aggregate. Unless the Broker is the actual economic seller organization, querying `GET /api/deals/{id}/` returns HTTP 403 Forbidden.

3. **Customer vs Internal Wire Sanitization**:
   - In `DealAttributionDetailView`:
     - Customer projection (Buyer / Seller): `evidence_snapshot` is set to `null`, `resolved_by_id` is set to `null`, `resolution_reason` is set to `null`, and `broker_attributions` / `opportunity_attributions` are set to `[]`.
     - Internal projection (Operator / Admin): Exposes the complete frozen evidence dictionary, resolution timestamp, operator user ID, manual reason, and all associated broker and opportunity attribution records.
   - Customer-facing party snapshots expose only `name_snapshot`, `country_snapshot`, and `registration_identifier_snapshot`. Phone numbers, email addresses, and verification files are never captured or projected.

---

## K. Provenance & Attribution Precedence Engine

1. **Precedence Hierarchy Execution**:
   - The attribution resolver evaluates candidate evidence strictly in the authoritative sequence:
     ```text
     Tier 1: BUYER_EXISTING_SUPPLIER
     Tier 2: BROKER
     Tier 3: OPPORTUNITY_DESK
     Tier 4: PLATFORM_NETWORK
     Tier 5: DIRECT_SUPPLIER
     Fallback: PENDING (requires manual Operator resolution)
     ```
   - Prior commercial relationships between the Buyer and Seller always take priority over broker referrals (`BUYER_EXISTING_SUPPLIER`).
   - If a broker referral is present on the RFQ, Offer, or Supply Opportunity, and no prior relationship exists, `BROKER` attribution is awarded.

2. **Nullable Uniqueness in PostgreSQL**:
   - `DealBrokerAttribution` uses PostgreSQL 15+ native `UNIQUE NULLS NOT DISTINCT ("deal_id", "broker_organization_id", "role", "related_opportunity_id")`.
   - This constraint prevents duplicate attribution rows for the same broker and role even when `related_opportunity_id` is null.

3. **Manual Resolution Governance**:
   - When an attribution is `PENDING`, an Operator or Admin can authoritatively resolve it via `POST /api/deals/{id}/attribution/resolve/`.
   - Manual resolution strictly requires `primary_channel`, `resolution_reason`, and `expected_version`.
   - Once resolved, the attribution status is permanently `RESOLVED`, and further resolution attempts are rejected.

---

## L. Materialization & Idempotency Mechanics

1. **Atomic Transaction Scope**:
   - `materialize_deals_from_award` is wrapped in `@transaction.atomic`.
   - If any snapshot creation fails, or if an allocation graph is inconsistent, the entire transaction rolls back cleanly without leaving orphan Deal records.

2. **Idempotent Re-Execution**:
   - Re-materializing an already materialized Award retrieves existing Deal records via `Deal.objects.filter(award_id=award_id)`.
   - Existing deals are returned with `created=False`.
   - No duplicate Deal records, duplicate terms snapshots, or duplicate party snapshots are created.

---

## M. PostgreSQL Concurrency & Transaction Isolation

1. **Materialization Concurrency**:
   - Tested using 2 concurrent threads attempting to materialize the same Award simultaneously.
   - PostgreSQL row locks (`select_for_update()`) on the `Award` and `RFQ` serialize the requests.
   - Exactly one thread creates the Deal rows (`created=True`), while the second thread safely retrieves the existing Deals (`created=False`). Both return HTTP 200/201 with zero errors.

2. **Attribution Resolution Concurrency**:
   - Tested 2 concurrent threads attempting manual attribution resolution on the same `PENDING` deal attribution.
   - Both provide `expected_version=1`.
   - Thread A acquires the row lock, validates version 1, increments version to 2, transitions status to `RESOLVED`, and commits.
   - Thread B acquires the lock, detects version 2 (mismatch with expected version 1), and immediately raises `StaleVersionError` (mapped to HTTP 409 Conflict).

---

## N. Migration & Upgrade Safety

1. **Fresh Migration & Reversibility**:
   - Applied all 4 migrations against PostgreSQL 17:
     - `0001_initial`: Created `Deal` model and indexes.
     - `0002_dealcostsnapshot_dealpartysnapshot_and_more`: Created `DealTermsSnapshot`, `DealCostSnapshot`, `DealPartySnapshot`.
     - `0003_dealattribution`: Created `DealAttribution` model.
     - `0004_dealbrokerattribution_dealopportunityattribution`: Created `DealBrokerAttribution`, `DealOpportunityAttribution`, and backfilled existing deals.
   - Reversed cleanly to `deals zero` and reapplied to `0004` without error.

2. **Zero Schema Drift**:
   - `python manage.py makemigrations --check --dry-run` reported `No changes detected`.

---

## O. Packaging & Distribution Verification

1. **Wheel Build Verification**:
   - Built distribution wheel via `pip wheel --no-deps apps/api`: `commodity_platform_api-0.1.0-py3-none-any.whl` (818,485 bytes).
   - Inspection of archive verified all **34 files** across `deals/`:
     - Models: `__init__.py`, `deal.py`, `terms_snapshot.py`, `party_snapshot.py`, `attribution.py`, `broker_attribution.py`, `opportunity_attribution.py`.
     - Migrations: `0001_initial.py` through `0004_...`.
     - Services: `materialization.py`, `specifications.py`, `attribution_resolver.py`, `attribution_manual.py`, `provenance.py`.
     - API: `views.py`, `serializers.py`, `urls.py`.
     - Admin: `admin.py`.

2. **Isolated Environment Installation**:
   - Created clean virtual environment outside the source tree.
   - Installed built wheel distribution.
   - Executed verification script loading `deals` directly from site-packages.
   - Executed `django.core.management.call_command('check')`:
     ```text
     deals package location: ...\site-packages\deals\__init__.py
     SUCCESS: deals imported from isolated installed wheel distribution!
     System check identified no issues (0 silenced).
     SUCCESS: django check passed from installed distribution!
     ```

---

## P. OpenAPI & Generated TypeScript Contract

1. **OpenAPI Schema Generation**:
   - Ran `python manage.py spectacular --validate --fail-on-warn --file schema.yaml` $\rightarrow$ exited 0 with zero warnings or schema errors.

2. **TypeScript Generation Determinism**:
   - Generated client via `npx openapi-typescript ../api/schema.yaml -o src/lib/api/generated/schema.d.ts`.
   - `git diff apps/web/src/lib/api/generated/schema.d.ts` verified 0 diff against the committed contract.

3. **Type Safety & Zero Bypasses**:
   - Audited frontend Epic 9 code: **0 occurrences** of `as any` and **0 occurrences** of `as unknown as`.

---

## Q. Frontend Architecture & Workspace Verification

1. **Persian / RTL First-Class Support**:
   - Tested responsive RTL Deal Workspace at `/fa/deals/[id]`.
   - Verified tabs: Overview, Commercial Terms, Parties, Attribution & Provenance, and Execution Monitor.
   - Execution Monitor presents staged empty state explaining that execution tracking commences in Epic 10.

2. **Component Tests**:
   - Executed 18 Vitest test suites (166 component tests) covering the Deal Workspace, snapshots rendering, attribution status, and permissions. All passed with 0 failures.

---

## R. Canonical Validation Results

Executed canonical validation suite against PostgreSQL 17:

| Command | Output / Status |
|---|---|
| `pip check` | `No broken requirements found.` |
| `ruff check .` | `All checks passed!` |
| `python manage.py check --settings=config.settings.test` | `System check identified no issues (0 silenced).` |
| `python manage.py makemigrations --check --dry-run` | `No changes detected` |
| `python manage.py test --settings=config.settings.test --timing` | **Ran 1620 tests in 244.087s: OK (0 failures, 0 errors, 0 skips)** |
| `python manage.py test deals --settings=config.settings.test` | **Ran 137 tests in 25.102s: OK (0 failures, 0 errors, 0 skips)** |
| `npm.cmd test` (Node tests) | **3 tests passed (0 failures)** |
| `npm.cmd run test:components` (Vitest) | **18 test files passed, 166 tests passed (0 failures)** |
| `npm.cmd run lint` | `eslint . --max-warnings=0` exited 0 (clean) |
| `npm.cmd run typecheck` | `next typegen && tsc --noEmit` exited 0 (clean) |
| `npm.cmd run build` | `next build` compiled successfully; all static routes generated |

---

## S. Hosted CI Status & Rationale

- **Status**: `HOSTED CI STATUS UNVERIFIED`
- **Rationale**: The remote GitHub repository is private, preventing unauthenticated check-run inspection via GitHub REST API. Full canonical test suites and static checks were executed locally against the authoritative PostgreSQL 17 container, passing 100%.

---

## T. Scope & Repository Hygiene

- **Epic 10/11 Leakage**: Audited for future execution milestones, payments, tracking, or settlement logic. Exactly 0 models, 0 services, and 0 workflows exist for downstream execution; the Deal Workspace displays staged empty states only.
- **Untracked Artifacts**: Scratch files and build wheels were isolated in the artifact directory outside the git tree. Working tree remains clean.

---

## U. Final Merge Recommendation

`codex/epic-09-deal-attribution` is safe to merge into `master` at Epic HEAD `9762692a111a375e301b2cc2017ae9175453113b`.
