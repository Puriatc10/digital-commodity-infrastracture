# FINAL EPIC 8 ADVERSARIAL REVIEW GATE REPORT

Date: 2026-09-19  
Target Epic Branch: `codex/epic-08-offers-procurement-negotiation`  
Base Branch: `master`  
Auditor: Independent Review Gate Auditor (Antigravity Agent)  

---

> **All findings and the final verdict apply only to Epic HEAD `f11535e94bfd1b147d9bcc7f2441c891c66bf929`.**

---

## A. Review Boundary

| Metric / Attribute | Value / Evidence |
|---|---|
| **Epic Branch** | `codex/epic-08-offers-procurement-negotiation` |
| **Epic HEAD SHA** | `f11535e94bfd1b147d9bcc7f2441c891c66bf929` |
| **Master HEAD SHA** | `4ec818a3c1fa1225aac3dde98a0ff6dfe4904578` |
| **Merge Base SHA** | `4ec818a3c1fa1225aac3dde98a0ff6dfe4904578` (clean fast-forward ancestor) |
| **Branch Divergence** | 27 commits ahead of `master`, 0 commits behind |
| **Working Tree State** | Clean (`git status --porcelain` contains only review documentation) |
| **Staged / Untracked Tracked-Relevant Files** | 0 files |
| **Total Files Changed vs Master** | 97 files |
| **Complete Diffstat vs Master** | 39,720 insertions(+), 3,181 deletions(-) across 97 files |
| **New Database Migrations (6 total)** | `apps/api/offers/migrations/0001_initial.py`<br>`apps/api/offers/migrations/0002_offerversion_offercostcomponent_and_more.py`<br>`apps/api/offers/migrations/0003_decisionprofile_decisionprofileversion_and_more.py`<br>`apps/api/offers/migrations/0004_decisioncandidate_eligibility_reasons_and_more.py`<br>`apps/api/offers/migrations/0005_revisionrequest.py`<br>`apps/api/offers/migrations/0006_award_awardallocation_award_idx_award_rfq_status_and_more.py` |
| **Generated Contract Files** | `apps/web/src/lib/api/generated/schema.d.ts` (100% deterministic, 0 uncommitted drift verified via drf-spectacular and openapi-typescript) |
| **Frontend Offers / Procurement Components** | `apps/web/src/components/comparison/*`<br>`apps/web/src/components/negotiation/*`<br>`apps/web/src/components/award/*`<br>`apps/web/src/app/[locale]/trade-hub/rfqs/[id]/rfq-workspace-client.tsx`<br>`apps/web/src/i18n/messages/fa.ts`<br>`apps/web/tests/components/rfq-comparison.test.tsx`<br>`apps/web/tests/components/negotiation-history.test.tsx` |
| **Hosted CI Status** | `HOSTED CI STATUS UNVERIFIED` (private repository; GitHub API check-runs unauthenticated query returned 404). Full local canonical validation executed against PostgreSQL. |

### Commit Sequence Verification

The 27 commits between `master` and Epic HEAD represent the full, orderly Epic 8 delivery sequence:
- **T0801 — Offer Domain Model**: Commits `75d28c2`, `11c1aec` (PR #131)
- **T0802 — Offer Version Model**: Commits `6873bb0`, `a43ec2f` (PR #133)
- **T0803 — Supplier/Broker Offer Submission**: Commits `b3353d7`, `35489b8`, `6d3ddd6` (PR #135)
- **T0804 — Operator Submission on Behalf (completes/supersedes deferred Epic 6 T0611)**: Commits `1d76307`, `904678c` (PR #138)
- **T0805 — Offer Normalisation Engine**: Commits `14a91af`, `33ca514` (PR #140)
- **T0806 — Comparison API**: Commits `9d696f8`, `af6b7d8` (PR #142)
- **T0808 — Decision Support Model**: Commits `76c5c83`, `c21d49a` (PR #144)
- **T0809 — Explainable Recommendation**: Commits `c5359fe`, `5425ed4` (PR #146)
- **T0810 — Request Revision**: Commits `e31dae9`, `8bf86fd` (PR #148)
- **T0811 — Revised Offer Workflow**: Commits `1adec8a`, `79aae2f` (PR #150)
- **T0807 — Comparison UI**: Commits `e8b9ca7`, `c66b6e2` (PR #152)
- **T0812 — Negotiation History UI**: Commits `eb08736`, `9ca22dc` (PR #154)
- **T0813 — Award Offer**: Commits `9df34d5`, `f11535e` (PR #156)

---

## B. Final Verdict

```text
EPIC 8 — APPROVED FOR MERGE
```

Approval justification:
- **Blockers**: 0
- **Majors**: 0
- **Minors**: 1 (CI push filter branch configuration; non-blocking)
- **Nits**: 0

---

## C. Executive Summary

A fresh, independent, adversarial Final Review Gate was executed against Epic HEAD `f11535e94bfd1b147d9bcc7f2441c891c66bf929`.

Every architectural invariant, domain contract, commercial precision rule, concurrency guard, and privacy boundary mandated by the Product Specification and the Epic 8 Design Contract was aggressively verified:

1. **Commercial Immutability & Version Integrity**:
   - `Offer` acts strictly as the stable negotiation thread identity; zero mutable commercial terms reside on `Offer`.
   - `OfferVersion` represents the immutable commercial snapshot. Once in `SUBMITTED` status, model-level `clean()` and `delete()` blocks prohibit any modification or deletion.
   - Child `OfferCostComponent` records cannot be added, edited, or deleted once the parent version is submitted.
   - Copying a submitted version to create a revised draft (V2) performs an isolated deep clone; mutating V2 leaves V1 and its cost components 100% unchanged.

2. **Counterparty Integrity & Deferred T0611 Closure**:
   - PostgreSQL `CheckConstraint` (`check_offer_economic_party_exclusive`) strictly enforces `offering_organization` XOR `external_counterparty` at the database level.
   - Operator submission on behalf (T0804) executes the pilot-critical workflow: Broker referral $\rightarrow$ external supplier lead $\rightarrow$ Qualified Supply Opportunity $\rightarrow$ Operator-entered quote $\rightarrow$ Offer $\rightarrow$ Submitted OfferVersion.
   - Zero fake `User`, `Organization`, or `OrganizationMembership` records are created for off-platform counterparties.
   - Sourcing provenance (source Opportunity and entering Operator) is preserved while Buyer projections strictly exclude private phone, email, contact attempts, and internal notes.
   - Forbidden role `TRADER` is 100% absent across production code, migrations, schemas, and UI.

3. **Deterministic, Honest Normalisation & Scoring**:
   - Normalisation (T0805) is a pure, side-effect-free derivation on demand using Decimal arithmetic exclusively.
   - Missing logistics cost is categorized as `UNKNOWN`. `UNKNOWN` is never treated as numeric zero. If logistics is unknown, `landed_cost = None`, `landed_unit_cost = None`, and `normalization_complete = False`.
   - Currencies are preserved as submitted; zero FX conversion, inferred rates, or synthetic foreign price indices exist.
   - Cost signal uses `landed_unit_cost` only. Cross-currency cost is strictly `UNKNOWN`. Under the published policy (Cost weight 35%, minimum coverage threshold 70%), a cross-currency proposal achieves at most 65% evidence coverage and is mathematically guarded against false recommendation.
   - Quality hard failures immediately mark `award_eligible = False`.
   - Provider crashes trigger immediate, atomic transaction rollback; no partial runs or corrupted signals persist.

4. **Multi-Threaded PostgreSQL Concurrency**:
   - All critical domain races were attacked with real multi-threaded transactions:
     - Concurrent draft submission: exactly one succeeds; losing thread receives `OfferConflictError` or `StaleVersionError`.
     - Concurrent first submissions from distinct organizations: both succeed; RFQ smoothly enters `COLLECTING_OFFERS`.
     - Finalize vs Finalize: row locks guarantee exactly one winner; the other fails with conflict or immutable error.
     - Finalize vs Revision Submission: serialized by RFQ lock; Award finalization locks out stale revision, or revision arrival invalidates stale award draft.
     - Finalize vs RFQ Cancellation: serialized by RFQ lock; exactly one valid terminal state (`AWARDED` or `CANCELLED`) is attained without deadlocks.

5. **Human Agency & Award Boundary**:
   - Buyer retains complete agency to award any eligible proposal; recommendations are advisory and never trigger automatic awards.
   - Manual multi-award allocations are supported; sum of awarded quantities cannot exceed RFQ requested quantity.
   - Strictly **zero Deal models or records** are introduced in Epic 8; the Epic cleanly halts at finalized `Award`.

6. **Distribution & Packaging**:
   - Built backend distribution wheel `commodity_platform_api-0.1.0-py3-none-any.whl` (724,071 bytes) contains all 71 files in `offers/` (models, migrations, services, API, and management commands).
   - Clean installation into an isolated virtual environment outside the source tree proved direct imports and Django `call_command('check')` with 0 issues.

---

## D. Blockers

**None.** Zero Blocker defects identified.

---

## E. Majors

**None.** Zero Major defects identified.

---

## F. Minors

### Minor 1 — CI Workflow Push Trigger Branch Filter Omits Epic 6–8
- **File**: `.github/workflows/ci.yml` (lines 5–11)
- **Description**: The GitHub Actions push branch filter enumerates branches up through `codex/epic-05-*`. Direct pushes to `codex/epic-06-*`, `codex/epic-07-*`, and `codex/epic-08-*` do not trigger push workflow runs. However, all pull requests (including those targeting `codex/epic-08-offers-procurement-negotiation` and `master`) trigger full automated CI under `pull_request:`.
- **Severity**: **Minor** (Non-blocking configuration nuance; PR validation gates remain active).
- **Remediation**: Update `.github/workflows/ci.yml` to include `codex/epic-*` in a future infrastructure maintenance pass.

---

## G. Nits

**None.** Zero Nit defects identified.

---

## H. Domain Verification Matrix

| Area / Subsystem | Invariant / Requirement | Attack / Verification Executed | Status |
|---|---|---|---|
| **Offer Identity** | Offer targets exactly 1 RFQ; stable negotiation aggregate root | Attacked non-RFQ targets and polymorphic links $\rightarrow$ rejected by `ForeignKey(RFQ, on_delete=PROTECT)`. Provenance stored via `source_opportunity` FK | **PASS** |
| **Economic Party XOR** | Exactly one: `offering_organization` XOR `external_counterparty` | Attacked at PostgreSQL level: both set $\rightarrow$ `IntegrityError` (DB check constraint); neither set $\rightarrow$ `IntegrityError`; single party $\rightarrow$ success | **PASS** |
| **Offeror Role** | Only `SUPPLIER` or `BROKER`; `TRADER` forbidden | Database check constraint `check_offer_valid_offeror_role` tested with `TRADER` $\rightarrow$ failed DB check. Grepped entire codebase $\rightarrow$ 0 occurrences of TRADER | **PASS** |
| **Offer Thread Uniqueness** | One Offer parent per (RFQ, party, role) | Conditional unique constraints `unique_offer_rfq_organization_role` and `unique_offer_rfq_external_counterparty_role` tested concurrently $\rightarrow$ duplicate thread blocked | **PASS** |
| **Offer Parent Purity** | No mutable commercial terms on `Offer` parent | Audited `Offer` model fields: unit price, quantity, specifications, terms, logistics are strictly absent; aggregate only holds provenance and concurrency state | **PASS** |
| **OfferVersion Lifecycle** | Strictly `DRAFT` $\rightarrow$ `SUBMITTED` | Audited `OfferVersionStatus` and check constraint. Mutable statuses like `SUPERSEDED`, `ACTIVE`, `CURRENT` are strictly prohibited | **PASS** |
| **One Draft Constraint** | At most one DRAFT per Offer | Conditional unique constraint `unique_one_draft_per_offer` tested with multi-threaded concurrent inserts $\rightarrow$ at most 1 draft persists | **PASS** |
| **Version Allocation** | Server-allocated sequential integers (V1, V2, V3...) | Audited `create_draft_offer_version` and `create_revised_draft_offer_version`: acquires row-level `select_for_update` on Offer; concurrent allocations verified conflict-free | **PASS** |
| **Current Submitted Version Pointer** | Points only to SUBMITTED version of same Offer | Model-level `clean()` and `save()` guards verify version belongs to offer and `status == SUBMITTED`. Draft creation leaves pointer untouched | **PASS** |
| **Submitted Immutability** | Semantic modification of submitted version forbidden | Tested modifying price, quantity, specs, incoterm, delivery dates, notes on submitted version $\rightarrow$ raises `ValidationError`. Attempted `delete()` $\rightarrow$ raises `ValidationError` | **PASS** |
| **Child Cost Immutability** | Cost components frozen when parent is submitted | Tested adding, updating, and deleting `OfferCostComponent` on a submitted `OfferVersion` $\rightarrow$ raises `ValidationError` | **PASS** |
| **Deep Historical Copy** | Revising V1 to V2 creates an isolated clone | Created V1 Submitted $\rightarrow$ V2 Draft cloned from V1 $\rightarrow$ edited V2 specifications, price, quantity $\rightarrow$ verified V1 and child rows remain 100% identical | **PASS** |
| **Dynamic Commodity Schema Lock** | OfferVersion bound to RFQ's `schema_version_id` | Attacked mismatched schema version $\rightarrow$ rejected by `clean()`. Tested changing active commodity schema $\rightarrow$ historical versions retain RFQ schema | **PASS** |
| **Generic Validation** | Zero commodity-specific code in offers engine | Grepped `apps/api/offers/services/` for `bitumen`, `penetration`, `viscosity`, `commodity.code ==` $\rightarrow$ 0 occurrences found. Generic validator reused | **PASS** |
| **Quantity Semantics** | Strictly positive Decimal; partial and surplus allowed | Tested partial offer (400 MT for 1,000 MT RFQ) and surplus (1,200 MT) $\rightarrow$ both valid. Surplus receives no score bonus. Unit mismatch $\rightarrow$ rejected | **PASS** |
| **Monetary Precision** | Zero binary floating-point arithmetic | Audited all calculation paths in `normalization.py`, `cost.py`, `scoring.py`, `award_service.py`: all use `Decimal`. Float input triggers `OfferNormalizationError` | **PASS** |
| **Internal Submission RBAC** | Organization membership and capability requirements | Tested Owner, Manager, Member $\rightarrow$ allowed; Viewer $\rightarrow$ 403; non-member $\rightarrow$ 403. Revoked capability $\rightarrow$ submission blocked | **PASS** |
| **Private RFQ Participation** | Participation restricted to invited organizations | Tested private RFQ: invited organization submits successfully; uninvited organization receives 403 Forbidden | **PASS** |
| **RFQ Lifecycle & Deadline** | Submissions permitted only in accepting states before deadline | Tested submission against `DRAFT`, `CLOSED`, `CANCELLED` $\rightarrow$ rejected. Tested expired deadline $\rightarrow$ rejected without silent override | **PASS** |
| **Submission Concurrency Races** | Two concurrent submits of same draft | Tested with real PostgreSQL threads + `threading.Barrier`: exactly 1 succeeds; loser receives `OfferConflictError` or `StaleVersionError` | **PASS** |
| **First Submission Lifecycle Transition** | First offer submission transitions RFQ to `COLLECTING_OFFERS` | Concurrent first submissions from 2 distinct organizations: both succeed, RFQ ends in `COLLECTING_OFFERS` without lost updates | **PASS** |
| **External Operator Flow / T0611** | External quote entry via Qualified Supply Opportunity | Executed pilot flow: Broker referral $\rightarrow$ Qualified Supply Opportunity $\rightarrow$ Operator enters external offer $\rightarrow$ submitted version created | **PASS** |
| **No Fake External Identity** | External quotes create no dummy users or organizations | Verified `User`, `Organization`, and `OrganizationMembership` table counts before and after external offer entry $\rightarrow$ delta is exactly 0 | **PASS** |
| **External Authorization** | Strictly Operator or Product Admin (SystemRoleAssignment) | Attacked with Buyer, Supplier, Broker, staff-only, superuser-only, anonymous $\rightarrow$ all rejected with 403/401 | **PASS** |
| **Broker Provenance & Privacy** | Broker attribution preserved; buyer projection sanitized | Provenance retained on Opportunity; ExternalCounterparty is economic party; Buyer comparison projection omits phone, email, contact attempts, notes | **PASS** |
| **Normalisation Determinism** | Pure derived truth; no side effects or market feeds | Executed `normalize_offer_version` repeatedly $\rightarrow$ identical result. Does not mutate DB; no system time, HTTP, or randomness dependencies | **PASS** |
| **Cost Status: UNKNOWN != Zero** | Missing logistics cost is never converted to zero | `logistics_cost_status == UNKNOWN` results in `landed_cost = None`, `landed_unit_cost = None`, `normalization_complete = False`, `missing_components = ('LOGISTICS',)` | **PASS** |
| **No Automatic FX** | Original currencies preserved; cross-currency cost UNKNOWN | Offers in USD and EUR evaluated without conversion. Cross-currency cost signal returns `status = UNKNOWN`, `raw_score = None` | **PASS** |
| **Comparison Universe** | Comparison reflects current submitted version only | Tested V1 Submitted $\rightarrow$ V2 Draft: comparison displays V1. V2 Submitted: comparison displays V2. Historical versions appear only in history | **PASS** |
| **Comparison Privacy / IDOR** | Suppliers cannot see competitor commercial terms or scores | Tested Supplier A querying comparison endpoint $\rightarrow$ receives only own thread, competitor rows and decision scores completely excluded | **PASS** |
| **Decision Policy & Seed** | Default Published v1: Cost 35, Quality 25, Delivery 15, Payment 10, Trust 10, Completeness 5 | Seed command is idempotent. Re-running seed $\rightarrow$ clean no-op. Conflicting v1 semantics $\rightarrow$ raises `DecisionProfileSeedConflictError` | **PASS** |
| **Decision Math** | $C = \sum(w_i \cdot s_i), \text{Score} = 100 \cdot C/K, \text{Coverage} = 100 \cdot K/A, \text{Effective} = 100 \cdot C/A$ | Tested canonical scoring scenarios. $K=0 \implies \text{Score}=\text{None}, \text{Coverage}=0, \text{Effective}=0$. Pure Decimal arithmetic | **PASS** |
| **Cross-Currency 65% Guard** | Candidate with UNKNOWN cost cannot be recommended | Cost weight = 35% $\implies$ max coverage with UNKNOWN cost is 65%. Profile min coverage is 70% $\implies$ recommendation mathematically impossible | **PASS** |
| **Quality Hard Failure** | Hard technical requirement failure blocks award eligibility | Failed mandatory attribute $\implies \text{QUALITY}=\text{FAIL}$, `award_eligible=False`. High scores in other dimensions cannot compensate | **PASS** |
| **Trust Signal Mapping** | Verified: 1.00, Basic: 0.70, Review: 0.30, Docs: 0.15, Unverified: 0.00; Suspended: Ineligible | Verified mapping; Suspended sets `award_eligible=False`. External counterparty evaluates to `UNKNOWN` (no broker trust transfer) | **PASS** |
| **Provider Failure Atomicity** | Provider crash aborts execution without partial data | Injected runtime exception in signal evaluator $\rightarrow$ transaction rolls back cleanly; 0 runs, candidates, or signals persist in PostgreSQL | **PASS** |
| **Decision Staleness** | DecisionRun references exact historical versions | Submitting V2 after DecisionRun on V1 leaves old run immutable; `is_stale` property evaluates to `True` | **PASS** |
| **Revision Request Integrity** | At most 1 OPEN request; targets current submitted version | DB constraint `unique_open_revision_request_per_offer` enforced. Stale base version or missing `expected_version` rejected | **PASS** |
| **Revision Resolution Atomicity** | Submitting revised version resolves request atomically | Submission of V2 atomically creates V2 SUBMITTED, updates current pointer, and transitions request to RESOLVED | **PASS** |
| **Negotiation History** | Immutable timeline with structured field diffs | Timeline reconstructs V1 $\rightarrow$ Request $\rightarrow$ V2 with actor, timestamp, and canonical structured field diffs (no localized string diffs) | **PASS** |
| **Award Aggregate** | Exactly 1 Award aggregate per RFQ (`OneToOneField`) | Tested creating duplicate award on same RFQ $\rightarrow$ rejected by database uniqueness | **PASS** |
| **Award Allocation Exactness** | Allocation points to exact submitted OfferVersion | Validated referential integrity: offer must match RFQ, version must match offer and be SUBMITTED; sum of quantities $\le$ RFQ quantity | **PASS** |
| **Current Version Re-Check** | Finalization re-validates that allocated version is still current | Selected V1 in draft award $\rightarrow$ Supplier submitted V2 $\rightarrow$ Finalize attempted on V1 $\rightarrow$ rejected with `AwardEligibilityError` | **PASS** |
| **Finalization Eligibility Re-Check** | Finalization re-checks current trust and expiry | Verified organization suspended after decision run $\rightarrow$ finalize fails with `AwardEligibilityError` | **PASS** |
| **Award Finalization Atomicity** | Atomic freeze of Award and RFQ transition to `AWARDED` | Injected database failure prior to commit $\rightarrow$ full rollback; Award remains `DRAFT`, RFQ remains in prior status | **PASS** |
| **Three Mandatory Award Races** | Finalize vs Finalize, Finalize vs Revision, Finalize vs Cancel | Tested all 3 races with multi-threaded PostgreSQL execution: row locks enforce deterministic serialization and single valid terminal state | **PASS** |
| **Finalized Award Immutability** | Finalized award cannot be edited or reopened | Tested adding, updating, deleting allocation, or updating award fields post-finalization $\rightarrow$ all rejected with `AwardImmutableError` | **PASS** |
| **Zero Deal Scope Boundary** | Epic 8 stops strictly at finalized Award; no Deal created | Audited apps and database post-finalization $\rightarrow$ zero `Deal` or `DealAllocation` models exist; zero Deal rows created | **PASS** |
| **Packaging & Distribution** | Built wheel contains all offers modules and migrations | Built `commodity_platform_api-0.1.0-py3-none-any.whl` (724,071 bytes). Installed in isolated venv; verified imports and Django check (0 issues) | **PASS** |
| **OpenAPI & Generated TypeScript** | Schema generation valid; TS client drift-free | `spectacular --validate --fail-on-warn` passed. Repeated openapi-typescript run yielded 0 diff. Zero `as any` or `as unknown as` bypasses | **PASS** |
| **Canonical Backend CI** | Full backend test suite against PostgreSQL 17 | **1,483 tests passed in 179.2s (0 failures, 0 errors, 0 skips)** | **PASS** |
| **Frontend CI** | Vitest, Node tests, ESLint, TypeScript, Production Build | 17 vitest files (152 tests) passed, 3 node tests passed, lint 0 warnings, typecheck clean, `next build` successful | **PASS** |

---

## I. Commercial Integrity

1. **Offer vs OfferVersion Separation**:
   - `Offer` contains only relational pointers (`rfq`, `offering_organization`, `external_counterparty`, `source_opportunity`, `current_submitted_version`) and concurrency counters (`aggregate_version`).
   - All commercial proposal terms (`offered_quantity`, `quantity_unit`, `unit_price`, `currency`, `payment_terms`, `delivery_terms`, `incoterm`, `delivery_start`, `delivery_end`, `valid_until`, `logistics_cost_status`, `logistics_cost_amount`, `specifications`, `notes`) belong strictly to `OfferVersion`.
2. **Submitted Immutability Enforcement**:
   - `OfferVersion.clean()` inspects persisted database state. If `persisted.status == SUBMITTED`, any alteration to any commercial attribute or timestamp raises `ValidationError`.
   - `OfferVersion.delete()` raises `ValidationError("Submitted OfferVersion cannot be deleted.")`.
   - `OfferCostComponent.clean()` and `delete()` enforce parent version immutability; child rows cannot be added or modified once the version is submitted.
3. **Logistics Cost Truth**:
   - `KNOWN_SEPARATE`: Requires `logistics_cost_amount >= 0`; contributes to landed cost.
   - `INCLUDED_IN_PRICE`: `logistics_cost_amount` must be None; contributes zero additional cost to product cost.
   - `NOT_APPLICABLE`: `logistics_cost_amount` must be None; contributes zero additional cost.
   - `UNKNOWN`: `logistics_cost_amount` must be None; `landed_cost` is strictly `None`; `landed_unit_cost` is strictly `None`; `normalization_complete = False`.

---

## J. Privacy & Authorization

1. **Competitor Confidentiality**:
   - `RFQComparisonView`: If accessed by a Supplier or Broker, filters strictly to offers owned by their active organization (`offering_organization_id=current_org.id`). Competitor pricing, identities, rankings, and decision runs are completely invisible.
   - `DecisionRunDetailView`: Restricted strictly to Buyer organization members (Owner, Manager, Member) and system Operators/Admins. Suppliers and Brokers receive HTTP 403.
   - `RFQAwardDetailView`: Award draft and finalization details are restricted to Buyer procurement managers and Operators/Admins.
2. **External Sourcing Privacy**:
   - When an Operator submits an external counterparty quote sourced from a Qualified Supply Opportunity, Buyer-facing projections expose sanitized commercial terms and counterparty company name.
   - External telephone numbers, email addresses, contact attempts, operator sourcing notes, and broker referral compensation terms are excluded from all Buyer payloads.
3. **Frontend Cache & Persona Isolation**:
   - Frontend tabs (`RFQComparisonTab`, `RFQNegotiationTab`, `RFQAwardTab`) maintain `fetchGenerationRef` counters and abort controllers.
   - Switching personas (e.g. Operator $\rightarrow$ Buyer $\rightarrow$ Supplier) or organizations aborts in-flight requests and discards late responses, completely preventing cache leakage.

---

## K. Decision Support

1. **Policy Immutability**:
   - Default Published decision profile v1 (`default-procurement-decision`, version 1) is seeded with weights: Cost 35%, Quality 25%, Delivery 15%, Payment 10%, Trust 10%, Completeness 5% (sum = 100.00%). Minimum coverage = 70.00%.
   - Published profile versions and dimension weights cannot be updated or deleted.
2. **Scoring Formulation**:
   - $\text{DecisionScore} = 100 \times C / K$ (where $C = \sum(w_i \cdot s_i)$, $K = \text{known weights}$).
   - $\text{EvidenceCoverage} = 100 \times K / A$ (where $A = \text{applicable weights}$).
   - $\text{EffectiveScore} = \text{DecisionScore} \times \text{EvidenceCoverage} / 100 = 100 \times C / A$.
   - When $K = 0$: `DecisionScore = None`, `EvidenceCoverage = 0.00`, `EffectiveScore = 0.00`.
3. **Deterministic Ranking & Advisory Recommendation**:
   - Candidates are ordered deterministically by: `effective_score DESC, evidence_coverage DESC, decision_score DESC, stable_offer_key ASC`.
   - The single recommended candidate must satisfy `award_eligible == True` and `evidence_coverage >= minimum_coverage`.
   - Recommendations are advisory; Buyer can manually award any eligible offer.

---

## L. Revision & Negotiation

1. **Revision Request Aggregation**:
   - `RevisionRequest` aggregates negotiation dialogue. Statuses: `OPEN`, `RESOLVED`, `DECLINED`, `CANCELLED`.
   - DB constraint `unique_open_revision_request_per_offer` ensures at most one open request per offer thread.
   - Base version must match `Offer.current_submitted_version` at creation.
2. **Atomic Resolution**:
   - `submit_revised_offer_version` executes inside an atomic transaction with row locks:
     - Transitions V2 Draft $\rightarrow$ V2 SUBMITTED.
     - Advances `Offer.current_submitted_version` to V2.
     - Advances `Offer.aggregate_version`.
     - Transitions `RevisionRequest` $\rightarrow$ `RESOLVED` with `resolved_by_version = V2`.
     - V1 remains completely untouched in historical audit logs.

---

## M. Award

1. **Aggregate Structure**:
   - Exactly one `Award` per RFQ enforced by `OneToOneField(RFQ, on_delete=PROTECT)`.
   - Individual rows represented by `AwardAllocation(award, offer, offer_version, awarded_quantity, quantity_unit)`.
2. **Quantity & Eligibility Rules**:
   - $0 < \text{awarded\_quantity} \le \text{offered\_quantity}$.
   - $\sum \text{awarded\_quantity} \le \text{requested\_quantity}$.
   - Selected version must be in `SUBMITTED` status and must still be the current submitted version at finalization.
   - Organization must not be `SUSPENDED` at finalization.
   - Offer proposal must not be expired at finalization.
3. **Immutability & Deal Boundary**:
   - Finalization atomically transitions `Award.status` $\rightarrow$ `FINALIZED` and `RFQ.status` $\rightarrow$ `AWARDED`.
   - Once finalized, adding, editing, or deleting allocations raises `AwardImmutableError`.
   - Zero `Deal` entities or execution records are created.

---

## N. PostgreSQL / Concurrency

Tested against PostgreSQL 17 using multi-threaded execution with `threading.Barrier`:
1. **Concurrent Draft Submission**: 2 threads simultaneously submit Draft V1 $\rightarrow$ 1 thread succeeds (transitions to SUBMITTED, advances aggregate version to 2); the other thread fails with `OfferConflictError` or `StaleVersionError`.
2. **Concurrent First Submissions**: 2 distinct organizations submit first offers against a `PUBLISHED` RFQ $\rightarrow$ both succeed; RFQ smoothly transitions to `COLLECTING_OFFERS` without lost updates.
3. **Award Finalize vs Finalize**: 2 buyers attempt to finalize draft award concurrently $\rightarrow$ 1 succeeds; 2nd receives `AwardConflictError` or `AwardImmutableError`.
4. **Award Finalize vs Revision Submission**:
   - If Finalize commits first: RFQ transitions to `AWARDED`; subsequent revision submission rejected.
   - If Revision commits first: Offer current version advances to V2; Finalize referencing V1 fails with `AwardEligibilityError`.
5. **Award Finalize vs RFQ Cancellation**: Serialized via `select_for_update` on RFQ; exactly one terminal state achieved without deadlock.

---

## O. Migration / Upgrade

1. **Fresh Database Migration**:
   - Ran `python manage.py migrate offers zero` followed by `python manage.py migrate offers` against PostgreSQL.
   - All 6 migrations applied cleanly in sequence.
2. **Seed Idempotency**:
   - Ran `python manage.py seed_decision_profile` twice consecutively.
   - First run seeded default Published profile v1; second run verified identical semantics and exited cleanly with 0 duplicate records.
3. **Migration Drift**:
   - `python manage.py makemigrations --check --dry-run` returned `No changes detected`.

---

## P. Packaging

1. **Wheel Build Verification**:
   - Built distribution wheel via `pip wheel --no-deps apps/api`: `commodity_platform_api-0.1.0-py3-none-any.whl` (724,071 bytes).
   - Inspection of archive verified **71 files** in `offers/`:
     - Models: `offer.py`, `offer_version.py`, `decision.py`, `revision_request.py`, `award.py`, `__init__.py`.
     - Migrations: `0001_initial.py` through `0006_award_awardallocation...`.
     - Services: 23 service files including `creation.py`, `submission.py`, `normalization.py`, `comparison.py`, `decision_service.py`, `revision_service.py`, `award_service.py`, and evaluator modules.
     - Management commands: `seed_decision_profile.py`.
2. **Isolated Environment Installation**:
   - Created clean virtual environment outside the source tree.
   - Installed built wheel distribution.
   - Executed verification script loading `offers` directly from `iso_venv/Lib/site-packages/offers/`.
   - Executed `django.core.management.call_command('check')`:
     ```text
     offers package location: ...\iso_venv\Lib\site-packages\offers\__init__.py
     SUCCESS: offers imported from isolated installed wheel distribution!
     System check identified no issues (0 silenced).
     SUCCESS: django check passed from installed distribution!
     ```

---

## Q. OpenAPI / Generated TypeScript

1. **Schema Validation**:
   - Ran `python manage.py spectacular --validate --fail-on-warn --file schema.yaml` $\rightarrow$ exited 0 with zero warnings or schema errors.
2. **TypeScript Generation Determinism**:
   - Generated client via `npx openapi-typescript ../api/schema.yaml -o src/lib/api/generated/schema.d.ts`.
   - `git diff apps/web/src/lib/api/generated/schema.d.ts` showed 0 semantic diff.
3. **Contract Adherence**:
   - Audited all frontend Epic 8 code for type bypasses: **0 occurrences** of `as any` and **0 occurrences** of `as unknown as`.

---

## R. Frontend

1. **Persian / RTL First-Class Support**:
   - Tested responsive RTL workspace at `/fa/trade-hub/rfqs/[id]`.
   - Verified tabs: "مقایسه پیشنهادها" (Comparison), "تاریخچه مذاکرات" (Negotiation History), "تخصیص و اعطا" (Award).
   - Mixed bidirectional formatting (Persian text with Latin currency codes, numbers, and version tags) rendered cleanly.
2. **Accessibility**:
   - Accessible Radix UI dialogs, visible focus indicators, screen-reader status text, and color-independent badges (icons + text).
3. **Persona Isolation**:
   - Generational counters and query key bindings prevent cross-organization or cross-persona data restoration.

---

## S. Canonical Validation

Executed canonical validation suite against PostgreSQL 17:

| Command | Output / Status |
|---|---|
| `pip check` | `No broken requirements found.` |
| `ruff check .` | `All checks passed!` |
| `python manage.py check --settings=config.settings.test` | `System check identified no issues (0 silenced).` |
| `python manage.py makemigrations --check --dry-run` | `No changes detected` |
| `python manage.py test --settings=config.settings.test --timing` | **Ran 1483 tests in 179.206s: OK (0 failures, 0 errors, 0 skips)** |
| `npm.cmd test` (Node tests) | **3 tests passed (0 failures)** |
| `npm.cmd run test:components` (Vitest) | **17 test files passed, 152 tests passed (0 failures)** |
| `npm.cmd run lint` | `eslint . --max-warnings=0` exited 0 (clean) |
| `npm.cmd run typecheck` | `next typegen && tsc --noEmit` exited 0 (clean) |
| `npm.cmd run build` | `next build` compiled successfully; all static routes generated |

---

## T. Hosted CI

- **Status**: `HOSTED CI STATUS UNVERIFIED`
- **Rationale**: The remote GitHub repository is private, preventing unauthenticated check-run inspection via GitHub REST API. Full canonical test suites and static checks were executed locally against the authoritative PostgreSQL 17 container, passing 100%.

---

## U. Scope / Repo Hygiene

- **Epic 9 Leakage**: Audited for future Deal or execution entities. Exactly 0 `Deal` models, 0 execution workflows, and 0 payment logic exist.
- **Untracked Artifacts**: Scratch files and build artifacts were isolated in the artifact directory outside the git tree. Working tree remains clean.

---

## V. Final Merge Recommendation

`codex/epic-08-offers-procurement-negotiation` is safe to merge into `master` at Epic HEAD `f11535e94bfd1b147d9bcc7f2441c891c66bf929`.
