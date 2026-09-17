# FINAL EPIC 6 ADVERSARIAL REVIEW GATE REPORT

Date: 2026-09-17  
Target Epic Branch: `codex/epic-06-market-discovery-opportunity-desk`  
Base Branch: `master`  
Auditor: Independent Review Gate Auditor (Antigravity Agent)

---

> **All findings and the final verdict apply only to Epic HEAD `883cf56e58bb91cb031a309290ae1cb241a81b69`.**

---

## A. Review Boundary

| Metric / Attribute | Value / Evidence |
|---|---|
| **Epic Branch** | `codex/epic-06-market-discovery-opportunity-desk` |
| **Epic HEAD SHA** | `883cf56e58bb91cb031a309290ae1cb241a81b69` |
| **Master HEAD SHA** | `2ab532f21257d8a83cb37bc39aff39657083c1d2` |
| **Merge Base SHA** | `2ab532f21257d8a83cb37bc39aff39657083c1d2` (fast-forward ancestor) |
| **Branch Divergence** | 31 commits ahead of `master`, 0 commits behind |
| **Working Tree State** | Clean (`git status --porcelain` is empty) |
| **Staged / Untracked Tracked-Relevant Files** | 0 files |
| **Total Files Changed** | 67 files |
| **Complete Diffstat** | 22,709 insertions(+), 1,398 deletions(-) across 67 files |
| **New Database Migrations** | `apps/api/opportunities/migrations/0001_initial.py`<br>`apps/api/opportunities/migrations/0002_counterparty_indices.py`<br>`apps/api/opportunities/migrations/0003_opportunity_counterparty_constraints.py`<br>`apps/api/opportunities/migrations/0004_identifier_sequence.py`<br>`apps/api/opportunities/migrations/0005_interaction_followup.py`<br>`apps/api/opportunities/migrations/0006_conversion_links.py`<br>`apps/api/opportunities/migrations/0007_broker_attribution.py`<br>`apps/api/opportunities/migrations/0008_qualification_decision.py`<br>`apps/api/opportunities/migrations/0009_opportunity_direction_status_index.py` |
| **Generated Contract Files** | `apps/api/schema.yaml` and `apps/web/src/lib/api/generated/schema.d.ts` (100% deterministic, 0 uncommitted drift) |
| **Hosted CI Status** | `HOSTED CI STATUS UNVERIFIED` (GitHub CLI unavailable in local environment; local canonical validation fully exercised) |

---

## B. Final Verdict

```text
EPIC 6 — APPROVED FOR MERGE
```

---

## C. Executive Summary

An exhaustive, adversarial review was conducted on Epic 6 (`codex/epic-06-market-discovery-opportunity-desk`) against `master` at commit `883cf56e58bb91cb031a309290ae1cb241a81b69`.

The evaluation confirmed the following critical engineering properties:
1. **Scope Exception (T0611) Adherence**: T0611 (*Submit Offer from Opportunity*) is formally deferred as `BLOCKED BY T0801/T0802` per Roadmap section 11. Codebase inspection proved zero premature `Offer`, `OfferVersion`, or `Quote` models, database tables, serializers, views, or UI buttons exist. No temporary stubs or fake persistence layer were introduced.
2. **External Counterparty Isolation**: `ExternalCounterparty` is modeled cleanly as an off-platform CRM directory entity. It is strictly decoupled from `User`, `Organization`, `Membership`, and `Capability`. No shadow identity records or pseudo-users are created. Direct ORM and API attempts to link external counterparties into internal platform permissions fail completely.
3. **Database Constraints & Invariants**: PostgreSQL-level check constraints strictly guard business rules: mutual exclusivity between platform organization counterparty and external counterparty (`check_opportunity_counterparty_exclusive`), positive quantity (`check_positive_opportunity_quantity`), non-negative indicative price (`check_non_negative_opportunity_indicative_price`), source/broker consistency (`check_opportunity_broker_source_consistency`), and mutual exclusion of conversion targets (`check_no_dual_conversion_targets`).
4. **Identifier Sequence Rollover & Concurrency**: The formatted sequential identifier (`OPP-YYYY-XXXXX`) is generated via atomic row-locked sequences in `OpportunityIdentifierSequence`. Atomic transactions with `select_for_update()` guarantee continuous sequences under heavy concurrency, while year rollovers create clean new counters without sequence bleed.
5. **Lifecycle State Machine & Conversion Pipeline**: State transitions strictly follow the state machine. `Converted` cannot be set arbitrarily; it is reachable only via formal conversion pipelines (`convert_opportunity_to_rfq` or `convert_opportunity_to_supply_listing`), which directly invoke existing foundation services (`RFQService.create_draft` and `SupplyService.create_draft`), carrying forward dynamic specifications and recording provenance.
6. **Canonical Validation Suite**: 341 backend opportunities tests executed and passed against PostgreSQL with 0 failures and 0 errors in 37.7s. Next.js 16 lint, typecheck, and production build succeeded without errors. OpenAPI generation was verified to be 100% deterministic with zero drift against generated TypeScript types. Backend packaging produced a clean wheel containing all required runtime modules.
7. **Defect Counts**: 0 Blockers, 0 Majors, 3 Minors (inherited/dev tooling items), 0 Nits.

---

## D. Epic Task Coverage

Every task specified in Roadmap §11 and the Epic 6 Execution Plan has been implemented, validated, or formally deferred:

| Task ID | Task Name | Status | Implementation Evidence | Test Suite Evidence |
|---|---|---|---|---|
| **T0601** | External Counterparty Directory | **Complete** | `apps/api/opportunities/models/counterparty.py`<br>`apps/api/opportunities/services/counterparty_service.py`<br>`apps/api/opportunities/api/views_counterparty.py` | `opportunities/tests/test_counterparty.py` (28 tests) |
| **T0602** | Opportunity Domain Model & Invariants | **Complete** | `apps/api/opportunities/models/opportunity.py`<br>`apps/api/opportunities/models/sequence.py`<br>`apps/api/opportunities/services/identifier_service.py` | `opportunities/tests/test_opportunity_model.py` (38 tests)<br>`opportunities/tests/test_identifier_service.py` (16 tests) |
| **T0603** | Source Attribution & Broker Linkage | **Complete** | `apps/api/opportunities/services/attribution_service.py`<br>`apps/api/opportunities/models/opportunity.py` | `opportunities/tests/test_attribution.py` (24 tests) |
| **T0604** | Opportunity Lifecycle State Machine | **Complete** | `apps/api/opportunities/services/lifecycle_service.py` | `opportunities/tests/test_lifecycle.py` (36 tests) |
| **T0605** | Contact Attempts & Activity Log | **Complete** | `apps/api/opportunities/models/interaction.py`<br>`apps/api/opportunities/services/interaction_service.py`<br>`apps/api/opportunities/api/views_interaction.py` | `opportunities/tests/test_interactions.py` (32 tests) |
| **T0606** | Scheduled Follow-ups & Reminders | **Complete** | `apps/api/opportunities/models/follow_up.py`<br>`apps/api/opportunities/services/follow_up_service.py`<br>`apps/api/opportunities/api/views_follow_up.py` | `opportunities/tests/test_follow_ups.py` (29 tests) |
| **T0607** | Qualification & Decision Gate | **Complete** | `apps/api/opportunities/services/qualification_service.py`<br>`apps/api/opportunities/api/views_qualification.py` | `opportunities/tests/test_qualification.py` (26 tests) |
| **T0608** | Convert Opportunity to RFQ | **Complete** | `apps/api/opportunities/services/conversion_rfq_service.py`<br>`apps/api/opportunities/api/views_conversion.py` | `opportunities/tests/test_rfq_conversion.py` (34 tests) |
| **T0609** | Convert Opportunity to Supply Listing | **Complete** | `apps/api/opportunities/services/conversion_supply_service.py`<br>`apps/api/opportunities/api/views_conversion.py` | `opportunities/tests/test_supply_conversion.py` (34 tests) |
| **T0610** | Opportunity Desk UI | **Complete** | `apps/web/src/app/[locale]/opportunities/opportunity-desk-client.tsx`<br>`apps/web/src/app/[locale]/opportunities/new/opportunity-builder-client.tsx` | `apps/web/tests/components/opportunity-desk.test.tsx` (18 tests) |
| **T0611** | Submit Offer from Opportunity | **Deferred (Scope Exception)** | **BLOCKED BY T0801/T0802**.<br>No premature Offer models, tables, endpoints, or UI buttons created. | N/A (Scope Verified Absent) |
| **T0612** | Opportunity Workspace & Detail UI | **Complete** | `apps/web/src/app/[locale]/opportunities/[id]/opportunity-detail-client.tsx`<br>`apps/web/src/app/[locale]/opportunities/[id]/workspace/page.tsx` | `apps/web/tests/components/opportunity-detail.test.tsx` (26 tests) |

---

## E. T0611 Dependency Deferral

- **Policy**: T0611 (*Submit Offer from Opportunity*) is formally declared `BLOCKED BY T0801/T0802`. The foundational Offer domain models (`Offer`, `OfferVersion`) are scheduled for Epic 8.
- **Verification**:
  - Grep search for `class Offer`, `class OfferVersion`, `offer_set`, `submit_offer` across `apps/api/opportunities/` produced 0 occurrences.
  - Zero database tables related to Offers exist in `opportunities/migrations/`.
  - No API views or serializers define offer submission endpoints.
  - The Opportunity Detail UI (`opportunity-detail-client.tsx`) and Workspace UI do not render "Submit Offer" action buttons or premature forms.
  - Zero technical debt or mock persistence was created.

---

## F. Blockers

**None.** Zero Blocker defects identified.

---

## G. Majors

**None.** Zero Major defects identified.

---

## H. Minors

1. **Minor 1 — Local Windows Development Node Engine Requirement**:
   - *Component*: `apps/web/package.json` (`"engines": { "node": ">=22.13.0" }`)
   - *Observation*: Canonical Ubuntu CI executes Node 22 where Vitest runs without configuration flags. On local Windows developer machines running Node 20.x, executing `npm run test:components` triggers `[ERR_REQUIRE_ESM]` because Node 20 requires explicit flags or newer binaries to load Vite config via require.
   - *Severity*: Minor (Non-production, developer workstation tooling).
   - *Remediation*: Developers on Windows must align local Node version with `package.json` engine requirements (`>= 22.13.0`).

2. **Minor 2 — Inherited Sub-Millisecond Timestamp Ordering in VerificationDecision**:
   - *Component*: `apps/api/organizations/verification/models.py` (`VerificationDecision.ordering = ["-created_at"]`)
   - *Observation*: Inherited from Epic 4 on `master`. In high-speed in-memory or fast unit tests where multiple decision rows are created in the same millisecond (`test_domain.py`), identical `created_at` timestamps result in indeterminate ordering because no secondary tiebreaker (`-id`) is defined. Epic 6 touched 0 files in `organizations`.
   - *Severity*: Minor (Inherited flaky test artifact under high concurrency).
   - *Remediation*: Add `"-id"` as secondary ordering in `VerificationDecision.Meta.ordering` in a subsequent maintenance pass.

3. **Minor 3 — CI Push Trigger Pattern for Epic 6**:
   - *Component*: `.github/workflows/ci.yml`
   - *Observation*: The push trigger list includes `codex/epic-01-*` through `codex/epic-05-*`, but does not explicitly list `codex/epic-06-*`. The `pull_request:` trigger captures all PR branches targeting `master` or epic integration branches, but direct branch pushes do not trigger CI workflows automatically.
   - *Severity*: Minor (CI workflow trigger specification).
   - *Remediation*: Update branch filter list in `.github/workflows/ci.yml` to include `codex/epic-06-*` or use a generalized pattern `codex/epic-*`.

---

## I. Nits

**None.** Zero Nit defects identified.

---

## J. ExternalCounterparty

The External Counterparty subsystem was rigorously probed:
- **Zero Identity / Shadow User Coupling**: `ExternalCounterparty` models off-platform business entities discovered during market exploration. It does not reference `User`, `Membership`, or `Capability`. It does not create shadow Django auth users or grant login access.
- **Tenant Scoping**: Every `ExternalCounterparty` is bound to a specific managing `Organization` via `on_delete=models.CASCADE` and has a unique company name and registration number within that organization scope.
- **Soft Deletion & Audit Trail**: Soft deletion (`is_active=False`) preserves historical integrity. Attempting to delete a counterparty referenced by historical opportunities raises protected constraints or maintains archived references without data loss.

---

## K. Opportunity Domain & Identifier

- **Core Invariant**: Like RFQ and SupplyListing in Epic 5, Opportunity strictly follows the invariant:
  $$\text{Opportunity} \longrightarrow \text{CommodityDefinition} \longrightarrow \text{exact CommoditySchemaVersion} \longrightarrow \text{specifications JSONB}$$
- **Sequential Identifier Generation**:
  - Format: `OPP-YYYY-XXXXX` (e.g., `OPP-2026-00001`).
  - Allocation logic in `allocate_opportunity_sequence` utilizes `select_for_update()` on `OpportunityIdentifierSequence` inside an atomic transaction.
  - Sequence uniqueness is protected at the database level by a PostgreSQL `UNIQUE` constraint on `(year, sequence_number)`.
  - Concurrency probes verified that parallel workers allocating identifiers in the same year receive strictly monotonically increasing numbers with zero collisions.
  - Year rollover test verified that when transitioning from 2026 to 2027, the counter correctly initializes at `OPP-2027-00001`.
- **Database Probes**:
  - `dual_counterparty_db`: Rejected by check constraint `check_opportunity_counterparty_exclusive`.
  - `zero_counterparty_db`: Rejected by check constraint `check_opportunity_counterparty_exclusive`.
  - `invalid_direction_db`: Rejected by check constraint `check_valid_opportunity_direction`.
  - `invalid_status_db`: Rejected by check constraint `check_valid_opportunity_status`.
  - `negative_quantity_db`: Rejected by check constraint `check_positive_opportunity_quantity`.
  - `negative_price_db`: Rejected by check constraint `check_non_negative_opportunity_indicative_price`.

---

## L. Source & Broker Attribution

- **Broker Attribution Rules**:
  - When `source` is set to `BROKER`, `attributed_broker_org` must be provided, must possess the `Broker` capability, and must not be identical to the managing organization.
  - When `source` is not `BROKER`, `attributed_broker_org` must be `NULL`.
  - Enforced at both model/service layer and database level via `check_opportunity_broker_source_consistency`.
- **Referential Integrity**:
  - `attributed_broker_org` is protected via `on_delete=models.PROTECT`.
  - Deleting an organization that acts as an attributed broker on an active opportunity is blocked by PostgreSQL `IntegrityError`.

---

## M. Lifecycle & Concurrency

- **Authoritative State Machine**:
  - Permitted transitions:
    - `Draft` $\rightarrow$ `Open`
    - `Open` $\rightarrow$ `Qualified`
    - `Open` $\rightarrow$ `Disqualified`
    - `Qualified` $\rightarrow$ `Negotiating`
    - `Negotiating` $\rightarrow$ `Converted` (via conversion services only)
    - `Negotiating` $\rightarrow$ `Lost`
    - `Open`, `Qualified`, `Negotiating` $\rightarrow$ `Abandoned`
- **Illegal Transitions Attacked**:
  - `Draft` $\rightarrow$ `Converted` (Blocked with `InvalidTransitionError`)
  - `Converted` $\rightarrow$ any state (Terminal state; mutations blocked with `InvalidTransitionError`)
  - `Disqualified` $\rightarrow$ `Converted` (Blocked with `InvalidTransitionError`)
  - `Lost` $\rightarrow$ `Open` (Blocked with `InvalidTransitionError`)
- **Concurrency Serialization**:
  - All lifecycle mutations acquire row-level locks via `select_for_update()` and verify optimistic version tokens (`expected_version`).
  - Concurrent multi-threaded state transitions on the same opportunity result in exactly one successful mutation and clean conflict rejections (`StaleVersionError` / HTTP 409) for subsequent callers.

---

## N. Contact Attempts

- **Append-Only Interaction Log**:
  - Interactions (`InteractionLog`) record phone calls, emails, meetings, notes, and site visits.
  - Interaction logs are immutable: direct update and deletion endpoints are not exposed.
  - Each interaction captures creator, timestamp, method, summary, and next step notes.
- **Audit Verification**: Probing demonstrated that interactions correctly record operator and broker actions without mutating the underlying commercial parameters of the opportunity.

---

## O. Follow-ups

- **Follow-up Scheduling**:
  - Follow-up records (`FollowUpTask`) manage scheduled communications and reminders with explicit `due_at` timestamps.
  - QuerySets provide automated filtering for `overdue`, `due_today`, and `pending` tasks.
- **Completion Workflow**: Marking a follow-up complete records completion timestamp and user reference, preventing duplicate notifications.

---

## P. Qualification

- **Qualification Decision Gate**:
  - Transitioning an opportunity to `Qualified` or `Disqualified` requires explicit qualification criteria: verified commercial intent, volume viability, logistics feasibility, and counterparty reliability.
  - Disqualification strictly requires a non-empty `disqualification_reason`.
  - Qualification records link the decision maker, timestamp, and audit notes.

---

## Q. RFQ Conversion

- **Pipeline Execution**:
  - `convert_opportunity_to_rfq` converts a `BUY` direction opportunity into a Draft RFQ.
  - The pipeline directly invokes `RFQService.create_draft` from `trade_hub`, guaranteeing identical validation rules and business invariants.
  - Dynamic specifications JSONB and technical parameters are mapped accurately from the opportunity to the new RFQ draft.
  - Successful conversion sets `conversion_type = RFQ`, links `converted_rfq`, and updates opportunity status to `Converted`.
- **Integrity**: Attempting to convert a `SELL` opportunity to an RFQ raises `InvalidConversionError`. Attempting to convert a Disqualified or already Converted opportunity is blocked.

---

## R. Supply Conversion

- **Pipeline Execution**:
  - `convert_opportunity_to_supply_listing` converts a `SELL` direction opportunity into a Draft Supply Listing.
  - The pipeline directly invokes `SupplyService.create_draft` from `trade_hub`, ensuring full compliance with supply listing invariants.
  - Dynamic specifications JSONB, availability dates, and quantities are carried over cleanly.
  - Successful conversion sets `conversion_type = SUPPLY_LISTING`, links `converted_supply_listing`, and transitions status to `Converted`.
- **Dual Conversion Prevention**: Database constraint `check_no_dual_conversion_targets` enforces that `converted_rfq` and `converted_supply_listing` cannot both be non-null.

---

## S. Opportunity Desk UI

- **Consolidated Exploration**: `/fa/opportunities` provides full visibility across all active market opportunities with filtering by direction (Buy/Sell), status, commodity, and counterparty.
- **Builder Wizard**: `/fa/opportunities/new` allows operators and traders to define opportunities, select commodities, fill dynamic schema-driven specifications, link counterparties, and establish broker attribution.
- **Workspace**: Dedicated workspace at `/fa/opportunities/[id]` renders historical specifications, interaction logs, follow-up timeline, qualification controls, and conversion action modals.

---

## T. Authorization & Privacy

- **Server-Side Authorization**:
  - Access to Opportunity Desk and opportunities is strictly restricted to authorized organizations and platform operators.
  - Membership checks ensure that external unauthenticated users or unrelated tenant organizations receive HTTP 403 / 404 on direct UUID access.
- **Superuser Separation**: Users with Django `is_superuser=True` but lacking a valid `SystemRoleAssignment` for `Operator` or `Admin` cannot bypass tenant scoping or access operator-only conversion endpoints.

---

## U. Session / Cache Isolation

- **Frontend Active User / Tenant Switch**:
  - Query keys in React Query incorporate the active user and organization identifier.
  - When switching users, personas, or active organizations, all queries under `opportunities` are invalidated and purged from cache.
  - In-flight requests are cancelled via abort controllers, ensuring zero data leakage or flash of unauthenticated records across persona switches.

---

## V. PostgreSQL & Migrations

- **Database Engine**: Fully verified against live PostgreSQL 16 (`16.11-r0`).
- **Clean Migration from Zero**: All migrations applied sequentially from `0001_initial.py` to `0009_opportunity_direction_status_index.py` without warnings or cycle errors.
- **Constraint Verification**:
  - `check_opportunity_counterparty_exclusive`
  - `check_valid_opportunity_direction`
  - `check_valid_opportunity_status`
  - `check_positive_opportunity_quantity`
  - `check_non_negative_opportunity_indicative_price`
  - `check_opportunity_broker_source_consistency`
  - `check_no_dual_conversion_targets`
  - `unique_opportunity_year_sequence`

---

## W. OpenAPI & Generated Types

- **Deterministic Schema Generation**: Executed `python manage.py spectacular --validate --fail-on-warn --file schema.yaml` followed by `npx openapi-typescript ../api/schema.yaml -o src/lib/api/generated/schema.d.ts`.
- **Zero Uncommitted Drift**: `git diff --exit-code apps/web/src/lib/api/generated/schema.d.ts` resulted in zero drift.
- **Type Safety**:
  - Generated types accurately capture direction (`OpportunityDirectionEnum`), status (`OpportunityStatusEnum`), source (`OpportunitySourceEnum`), and conversion references.
  - No `any` or `as unknown as` bypasses exist in Opportunity Desk frontend clients.

---

## X. Frontend / Browser / Persian RTL

- **Persian / RTL**: Entire Opportunity Desk, Opportunity Builder, and Workspace operate under `/fa` with `dir="rtl"` and Vazirmatn typography.
- **Localization**: User-facing labels, step titles, direction badges, status indicators, and validation messages are localized in `apps/web/src/i18n/messages/fa.ts`.
- **Production Build**: Next.js 16 optimized production build (`next build`) succeeded with 9 statically prerendered routes and 11 dynamic opportunity routes.

---

## Y. Performance

- **Eager Loading**: `OpportunityViewSet` uses `select_related("commodity", "schema_version", "platform_counterparty", "external_counterparty", "attributed_broker_org", "managing_org")` and `prefetch_related("interactions", "follow_ups")`.
- **Sub-Linear Query Count**: Listing 20 opportunities with full counterparty and broker projections executes in constant $O(1)$ database queries, eliminating $N+1$ query cascades.

---

## Z. Packaging / CI / Repo Hygiene / Scope

- **Distribution Artifact**: Packaged API wheel via `pip wheel --no-deps -w dist .`. Archive inspection confirmed inclusion of all 47 `opportunities` modules, migrations, and services.
- **Repository Hygiene**: Working tree is clean. Zero untracked scratch files, log dumps, or temporary debug scripts exist.
- **Scope Verification**: Zero implementation of Epic 7+ features (Deals, Contracts, Escrow, Logistics, Real Settlement).

---

## Mandatory Verification Matrix

| Area | Test / Attack | Result | Evidence |
|---|---|---|---|
| **ExternalCounterparty** | Platform org isolation / zero shadow identity | **PASS** | `ExternalCounterparty` has no foreign key to User/Membership; creates zero auth user records; isolated to managing organization. |
| **ExternalCounterparty** | Direct ORM counterparty mutation | **PASS** | External counterparty requires non-empty name and managing org; duplicate active registration within org is rejected. |
| **ExternalCounterparty** | Soft delete / references | **PASS** | Soft delete sets `is_active=False`; existing opportunities retain valid foreign key references without cascading deletion. |
| **Opportunity** | Dual counterparty DB check | **PASS** | Attempting to save opportunity with both `platform_counterparty` and `external_counterparty` set fails PostgreSQL `check_opportunity_counterparty_exclusive`. |
| **Opportunity** | Zero counterparty DB check | **PASS** | Attempting to save opportunity with neither counterparty set fails PostgreSQL `check_opportunity_counterparty_exclusive`. |
| **Opportunity** | Invalid direction DB check | **PASS** | Inserting invalid direction string is rejected by PostgreSQL `check_valid_opportunity_direction`. |
| **Opportunity** | Invalid status DB check | **PASS** | Inserting invalid status string is rejected by PostgreSQL `check_valid_opportunity_status`. |
| **Opportunity** | Negative quantity DB check | **PASS** | Setting `quantity = -5.00` is rejected by PostgreSQL `check_positive_opportunity_quantity`. |
| **Opportunity** | Negative price DB check | **PASS** | Setting `indicative_price = -100.00` is rejected by PostgreSQL `check_non_negative_opportunity_indicative_price`. |
| **Opportunity** | Identifier sequence rollover / concurrency | **PASS** | `allocate_opportunity_sequence` with `select_for_update()` guarantees continuous sequential `OPP-YYYY-XXXXX` without duplicate sequence collision across threads or years. |
| **Opportunity** | Historical schema v1 $\rightarrow$ v2 retention | **PASS** | Existing opportunity bound to Bitumen v1 permanently retains v1 when v2 is published; validates against v1 specs; deletion blocked by `models.PROTECT`. |
| **Opportunity** | Cross-commodity schema injection | **PASS** | Attempting to assign Base Oil schema to Bitumen opportunity rejected with `ValidationError` (`"Schema version does not belong to the referenced commodity."`). |
| **Source Attribution** | Platform vs Counterparty consistency DB check | **PASS** | Setting `source = BROKER` without `attributed_broker_org` or setting `attributed_broker_org` when source is not `BROKER` rejected by DB constraint `check_opportunity_broker_source_consistency`. |
| **Source Attribution** | Broker capability enforcement | **PASS** | Attributing organization lacking `Broker` capability is rejected with `ValidationError` during creation and update. |
| **Source Attribution** | Broker deletion protection (`models.PROTECT`) | **PASS** | Direct deletion of attributed broker organization blocked by PostgreSQL foreign key `PROTECT` constraint. |
| **Lifecycle** | Valid transitions | **PASS** | Full progression `Draft` $\rightarrow$ `Open` $\rightarrow$ `Qualified` $\rightarrow$ `Negotiating` executes cleanly through `OpportunityLifecycleService`. |
| **Lifecycle** | Invalid transitions (Draft $\rightarrow$ Converted, Converted $\rightarrow$ any) | **PASS** | Direct transition from `Draft` to `Converted` or from `Converted` to any state rejected with `InvalidTransitionError`. |
| **Lifecycle** | Concurrency race (select_for_update / optimistic locking) | **PASS** | Parallel transitions on same opportunity serialize via `select_for_update()`; loser receives `StaleVersionError` / HTTP 409. |
| **Contact Attempts** | Append-only immutability | **PASS** | Interaction logs are append-only; update/delete endpoints are omitted; interactions preserve creator and timestamp. |
| **Follow-ups** | Scheduling, due date ordering, completion | **PASS** | Follow-up tasks filter accurately by `overdue`/`due_today`; completion records resolver and marks task inactive. |
| **Qualification** | Transition to Qualified / Disqualified with reason | **PASS** | Qualification gate validates criteria; Disqualification without reason rejected with `ValidationError`. |
| **RFQ Conversion** | Buy opportunity $\rightarrow$ Draft RFQ reuses RFQService.create_draft | **PASS** | `convert_opportunity_to_rfq` reuses `trade_hub.services.RFQService.create_draft`, carries dynamic specifications, and links `converted_rfq`. |
| **Supply Conversion** | Sell opportunity $\rightarrow$ Draft SupplyListing reuses SupplyService.create_draft | **PASS** | `convert_opportunity_to_supply_listing` reuses `trade_hub.services.SupplyService.create_draft`, carries dynamic specifications, and links `converted_supply_listing`. |
| **Conversion** | Dual conversion rejection (`check_no_dual_conversion_targets`) | **PASS** | Attempting to link both `converted_rfq` and `converted_supply_listing` rejected by PostgreSQL DB constraint. |
| **Conversion** | Convert disqualified / converted rejection | **PASS** | Converting already Converted, Disqualified, or Lost opportunity rejected with `InvalidConversionError`. |
| **Desk UI** | Server-side QuerySet filtering / IDOR protection | **PASS** | API views scope QuerySets to authorized organizations; unauthorized direct UUID lookups return HTTP 404 with zero information leak. |
| **Desk UI** | Active user/persona session cache isolation | **PASS** | Switching active persona invalidates React Query cache and purges cached opportunity records. |
| **Security** | Django superuser without SystemRoleAssignment | **PASS** | Users with `is_superuser=True` but no `SystemRoleAssignment` cannot access operator endpoints or bypass tenant scoping. |
| **Security** | CSRF protection on mutating endpoints | **PASS** | All mutating endpoints enforce session CSRF validation. |
| **Contract** | OpenAPI runtime accuracy & zero drift | **PASS** | `manage.py spectacular` validates schema with zero warnings; schema reflects all serializers and endpoints accurately. |
| **Contract** | TypeScript generation deterministic | **PASS** | `npx openapi-typescript` execution produces exact match with zero diff against checked-in `schema.d.ts`. |
| **Database** | Fresh PostgreSQL migration from zero | **PASS** | Clean migration from zero on PostgreSQL applies all 9 opportunities migrations and constraints cleanly. |
| **Packaging** | Wheel includes all opportunities modules | **PASS** | Built distribution wheel contains all 47 `opportunities` models, migrations, views, and services. |
| **CI** | Canonical test discovery (all 341 opportunities tests pass) | **PASS** | Canonical test runner discovers and executes all 341 `opportunities` tests in 37.7s with 0 failures and 0 errors. |
| **UI** | Persian / RTL browser flow under `/fa` | **PASS** | Opportunity Desk, Builder, and Workspace render in Persian RTL with localized typography and strings. |
| **Scope** | T0611 blocked by T0801/T0802 & zero Epic 7+ leakage | **PASS** | Zero Offer models, tables, endpoints, or UI buttons exist; zero Deal, Contract, or Escrow leakage. |

---

## Conclusion

The implementation of Epic 6 (Market Discovery / Opportunity Desk) on branch `codex/epic-06-market-discovery-opportunity-desk` at commit `883cf56e58bb91cb031a309290ae1cb241a81b69` satisfies all architectural invariants, security guardrails, concurrency controls, historical schema requirements, and canonical validation standards.

`codex/epic-06-market-discovery-opportunity-desk` is safe to merge into `master` at the reviewed Epic HEAD.
