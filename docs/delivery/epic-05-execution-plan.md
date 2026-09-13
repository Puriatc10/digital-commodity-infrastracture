# Epic 5 — Trade Hub & RFQ: Execution Plan

Planning Date: 2026-09-13  
Target Integration Branch: `codex/epic-05-trade-hub-rfq`  
Baseline Master SHA: `e63ab9b3da3b17e24520ad71add518f8654c07c0`  
Status: Planning-Only Document — Authorization for Epic 5 Planning Only; no implementation code, migrations, generated types, or branches created in this session.

---

## 1. Authority, Baseline, and Readiness

### 1.1 Authoritative Sources Read
This execution plan is synthesized directly from:
1. `AGENTS.md` (authoritative repository rules, business actors, non-goals, git policies)
2. `docs/delivery/roadmap.md` (§9 Epic 5 — Trade Hub & RFQ; §1–3, §18–27 delivery rules and gates)
3. `docs/product/product-spec.md` (§1–2 vision/positioning; §3–5 principles, actors, organization capabilities; §6–10 dynamic commodity architecture and versioned schemas; §11 Trade Hub; §12 RFQ; §13 RFQ Workspace; §14 Supply Listing; §50–57 architecture, persistence, invariants, non-goals; §58–60 testing, DOD)
4. `docs/domain/glossary.md` (canonical terminology, actors, business definitions)
5. `docs/architecture/overview.md` (modular monolith, PostgreSQL truth, REST/OpenAPI, S3/MinIO, domain boundaries)
6. `docs/architecture/source-review.md` (source alignment history, recorded ambiguities)
7. Relevant ADRs:
   - ADR-0001 (Django Modular Monolith)
   - ADR-0002 (PostgreSQL as Source of Truth)
   - ADR-0003 (Dynamic Commodity Specifications)
   - ADR-0004 (REST + OpenAPI Generation)
   - ADR-0005 (Monitoring-First Execution Layer)
   - ADR-0006 (Human-Assisted Market Discovery)
   - ADR-0007 (S3-Compatible Object Storage)
   - ADR-0008 (Locale-Aware Frontend / Persian RTL)
   - ADR-0009 (Authentication Architecture & CSRF)
8. Historical Review Gates & Plans:
   - `docs/delivery/epic-01-review-gate.md`
   - `docs/delivery/epic-02-review-gate.md`
   - `docs/delivery/epic-03-review-gate.md` & `docs/product/epic-03-dynamic-commodity-design-contract.md`
   - `docs/delivery/epic-04-execution-plan.md`
   - `docs/delivery/epic-04-review-gate.md`
   - `docs/delivery/epic-04-final-review-gate.md`
9. Current domain implementations: `apps/api/identity`, `apps/api/organizations` (including `organizations.verification`), `apps/api/commodities`, `apps/api/documents`, and `apps/web/src`.

### 1.2 Baseline Verification
- **Exact `master` SHA**: `e63ab9b3da3b17e24520ad71add518f8654c07c0`
- **Current Branch**: `master` (synchronized with `origin/master`)
- **Working Tree State**: Clean (zero uncommitted files, zero staged modifications)
- **Latest Merged Epic 4 Ancestry**: 
  - Merge commit `e63ab9b` (Merge pull request #62 from `Puriatc10/codex/epic-04-organizations-network-verification`)
  - Merged PR #61 (`fc3428c`), PR #60 (`6c5c779`), PR #59 (`82e8a40`), PR #57 (`2756e70`)
  - Ancestry includes full Epic 4 review gate approvals (`3f981a1`, `95273fa`, `e4cb144`, `0fd5be7`).
- **Hosted CI Status**: Verified passing across Backend CI, Frontend CI, and OpenAPI Contract Validation on `codex/epic-04-organizations-network-verification` (e.g. run 34751691961) prior to merge into `master`.
- **Readiness Verdict**: Epic 4 is cleanly integrated into `master`. The repository baseline is fully stabilized and ready for Epic 5 planning.

---

## 2. Exact Roadmap Inventory

Roadmap §9 designates Epic 5 as **Priority: P0 (Core Product)**.  
The roadmap supplies exactly ten tasks in the following inventory without task-level dependencies, detailed sub-specifications, or dedicated integration IDs:

| Task ID | Exact Task Name | Exact Roadmap Description |
|---|---|---|
| **T0501** | RFQ Domain Model | Core: organization; commodity; schema version; specifications; quantity; unit; commercial terms; delivery; visibility; lifecycle. |
| **T0502** | RFQ Lifecycle | Suggested statuses: Draft; Published; Collecting Offers; Negotiating; Awarded; Closed; Cancelled. |
| **T0503** | RFQ Builder API | Create/update/publish. Validation کامل (Complete validation). |
| **T0504** | RFQ Builder UI | Multi-section UI: Product; Commercial; Delivery; Quality; Participation; Preview. Dynamic commodity fields باید از Schema بیایند (Dynamic commodity fields must come from Schema). |
| **T0505** | RFQ Visibility | Implement: Private; Network; Public. Permission tests ضروری (Permission tests required). |
| **T0506** | RFQ Invitations | Buyer/Operator بتواند Suppliers و Brokers را invite کند (Buyer/Operator can invite Suppliers and Brokers). |
| **T0507** | RFQ Workspace | Tabs: Overview; Participants; Offers; Comparison; Negotiation; Activity; Documents. |
| **T0508** | Supply Listing Domain | Supply-side counterpart RFQ. Fields: commodity; specifications; quantity; geography; availability; indicative terms; visibility. |
| **T0509** | Supply Listing UI | Supplier/Operator create/edit/list. |
| **T0510** | Trade Hub | Unified view: Demand; Supply; با search/filter (with search/filter). |

**Supplied Epic 5 Review Gate Criterion (Roadmap §9):**  
> Hero slice: Buyer → Create RFQ → Publish → Invite Supplier/Broker must work end-to-end.

---

## 3. Foundation Audit (Epic 1–4 Reusable Assets)

Epic 5 must strictly consume existing foundations without reinvention:

### 3.1 Platform Foundation (Epic 1)
- Modular monolith in Django 6 + Django REST Framework (`apps/api/config`).
- PostgreSQL 17 source of truth with strict foreign keys, check constraints, and transactional atomicity.
- Next.js 16 + TypeScript + Tailwind CSS + shadcn/ui frontend (`apps/web`).
- OpenAPI generation pipeline (`python manage.py spectacular`) + TypeScript contract generation (`openapi-typescript` → `apps/web/src/lib/api/generated/schema.d.ts`).
- First-class Persian RTL layout (`/fa`, `dir="rtl"`, Vazirmatn font).

### 3.2 Identity, Organizations, and Authorization (Epic 2)
- Session-based authentication with `SessionAuthentication` and CSRF cookie transport (`apps/api/identity`).
- `Organization` core aggregate: UUID, name, registration identifier, country, is_active (`apps/api/organizations/models.py`).
- `OrganizationCapability`: `buyer`, `supplier`, `broker` (multiple allowed per organization).
- `OrganizationMembership`: `owner`, `manager`, `member`, `viewer` roles per organization.
- `SystemRoleAssignment`: `operator`, `admin`.
- Invariant: Django `is_staff` / `is_superuser` flags alone do **not** confer Product Admin or Operator authorization.
- Frontend `AuthProvider` and `useAuth` exposing user, selected organization, active capabilities, and system roles with stale-cache invalidation.

### 3.3 Dynamic Commodity Engine (Epic 3)
- `CommodityDefinition`, `CommoditySchemaVersion`, and `CommodityAttributeDefinition` (`apps/api/commodities/models.py`).
- Deterministic JSON Schema generation and reusable server-side validator:  
  `commodities.services.validate_commodity_payload(schema_version, payload)`  
  providing deterministic field-level structured errors.
- Dynamic specification form and view renderers in frontend:  
  `apps/web/src/components/commodity/commodity-specification-form.tsx`  
  `apps/web/src/components/commodity/commodity-specification-view.tsx`.
- **Absolute Architectural Invariant**:
  ```text
  Business Record (RFQ / Supply Listing)
          ↓
  commodity_id (FK to CommodityDefinition)
          ↓
  schema_version_id (FK to CommoditySchemaVersion)
          ↓
  specifications (JSONB payload validated against exact schema_version)
  ```
  Historical records permanently retain their creation-time `schema_version`. Active schema changes never mutate or revalidate existing records against new versions. Core tables must never include hard-coded commodity attributes (`penetration_grade`, `viscosity`, etc.).

### 3.4 Verification, Profile, and Storage Boundaries (Epic 4)
- Customer-safe organization directory and profile projections (`apps/api/organizations/api/serializers.py`).
- `OrganizationVerification` aggregate with verification levels: `unverified`, `documents_submitted`, `under_review`, `basic_verified`, `verified`, `suspended`.
- `OrganizationCommodity` association tracking which commodities an organization operates in.
- `documents` application providing private MinIO object storage abstracted behind application Document UUIDs and authorized streaming endpoints (`apps/api/documents/`).

---

## 4. Product Policy Gaps & Architecture Defaults

The roadmap and Product Specification leave several operational details unstated. Below, all ambiguities are classified into **Blocking** (none found that prevent starting planning) and **Non-blocking** with explicit, conservative architecture-safe defaults proposed for owner approval:

### 4.1 RFQ Lifecycle Boundaries in Epic 5 (Non-blocking)
- **Ambiguity**: Roadmap T0502 lists `Draft`, `Published`, `Collecting Offers`, `Negotiating`, `Awarded`, `Closed`, `Cancelled`. However, `Offer` entities belong to Epic 8, and `Deal`/`Award` belong to Epic 8/9.
- **Approved Architecture Default**:
  - The model status enum will define all 7 statuses to ensure database schema forward-compatibility.
  - Active transitions permitted during Epic 5 are strictly limited to:
    - `Draft` → `Published` (upon completing required fields and validating dynamic specifications)
    - `Draft` → `Cancelled`
    - `Published` → `Closed` (manual close by Buyer/Operator, or submission deadline passed)
    - `Published` → `Cancelled` (with required cancellation reason)
  - Transitions into `Collecting Offers`, `Negotiating`, and `Awarded` are guarded domain exceptions in Epic 5 and will be unlocked in Epic 8 when offers exist.

### 4.2 Post-Publication Immutability (Non-blocking)
- **Ambiguity**: Can a Buyer edit an RFQ after it is Published?
- **Approved Architecture Default**:
  - Once an RFQ moves to `Published`, its core commercial and technical attributes are **strictly frozen/immutable**: `commodity`, `schema_version`, `specifications` JSONB, `quantity`, `unit`, `payment_terms`, `incoterm`, `origin`, and `destination`.
  - Only administrative metadata may be updated post-publication: extending `submission_deadline`, appending new invitations, or updating internal notes.
  - If a Buyer requires materially different specifications or terms, the current RFQ must be `Cancelled` and a new RFQ drafted.

### 4.3 Visibility Semantics: Private vs. Network vs. Public (Non-blocking)
- **Ambiguity**: How are `Public`, `Network`, and `Private` visibility evaluated across capabilities and commodities?
- **Approved Architecture Default**:
  - **Public**: Visible to any authenticated organization holding `Supplier` or `Broker` capability once published.
  - **Network**: Visible to authenticated organizations holding `Supplier` or `Broker` capability **AND** associated with that specific commodity via `OrganizationCommodity` once published.
  - **Private**: Visible **ONLY** to:
    1. The creator organization (Buyer);
    2. Explicitly invited organizations (`RFQInvitation` target);
    3. Platform Operators and Product Admins.
  - Draft RFQs of any visibility are visible **exclusively** to the creator organization and Operator/Admin.

### 4.4 Invitation Target Identity (Non-blocking)
- **Ambiguity**: Can invitations target external email addresses or unverified parties?
- **Approved Architecture Default**:
  - In Epic 5, invitations target existing active platform `Organization` entities via foreign key (`target_organization`).
  - Off-platform external counterparty invitations are scheduled for Epic 6 (T0604 `ExternalCounterparty`). Epic 5 will not build premature external email invite flows.

### 4.5 Supply Listing Lifecycle & Fields (Non-blocking)
- **Ambiguity**: Roadmap T0508 lists fields but no explicit lifecycle status machine.
- **Approved Architecture Default**:
  - Lifecycle statuses: `Draft`, `Active`, `Expired`, `Closed`.
  - Active listings are visible in Trade Hub according to `visibility` (`Public`, `Network`, `Private`).
  - Owner/Manager of a Supplier organization (or Operator) can create, publish (Draft → Active), and close listings.

### 4.6 Operator on-behalf Provenance (Non-blocking)
- **Ambiguity**: How are Operator actions on behalf of counterparties tracked?
- **Approved Architecture Default**:
  - Models store `organization` (the counterparty owning the record), `created_by` (the authenticated user), and a boolean `created_by_operator`.
  - If `created_by` is an Operator who is not a member of `organization`, `created_by_operator=True` is recorded automatically.

---

## 5. Domain Boundaries & Owning Architecture

To preserve modular monolith cohesion and avoid micro-app sprawl, all Epic 5 models and services will reside in a single new backend domain app: **`trade_hub`** (`apps/api/trade_hub/`).

```text
apps/api/
  ├── trade_hub/
  │    ├── __init__.py
  │    ├── apps.py                      # TradeHubConfig (registered in INSTALLED_APPS & pyproject.toml)
  │    ├── models/
  │    │    ├── __init__.py
  │    │    ├── rfq.py                  # RFQ aggregate, RFQStatus, RFQVisibility
  │    │    ├── invitation.py           # RFQInvitation, InvitationStatus
  │    │    └── supply.py               # SupplyListing, SupplyStatus
  │    ├── services/
  │    │    ├── __init__.py
  │    │    ├── rfq_service.py          # Draft creation, dynamic spec validation, locking, publish
  │    │    ├── visibility_service.py   # QuerySet scoping for Public/Network/Private
  │    │    ├── invitation_service.py   # Participant invitation, state transitions
  │    │    └── supply_service.py       # Supply listing creation, validation, lifecycle
  │    ├── api/
  │    │    ├── __init__.py
  │    │    ├── serializers_rfq.py      # RFQ request, response, customer/internal projections
  │    │    ├── serializers_invitation.py# Invitation serializers
  │    │    ├── serializers_supply.py   # Supply listing serializers
  │    │    ├── views_rfq.py            # RFQ CRUD, publish, cancel, close, workspace
  │    │    ├── views_invitation.py     # Invitation endpoints
  │    │    ├── views_supply.py         # Supply listing endpoints
  │    │    └── views_trade_hub.py      # Unified trade hub summary & discovery
  │    ├── urls.py
  │    └── tests/                       # Unit, API, Concurrency, PostgreSQL tests
```

### Module Responsibilities
- **`trade_hub.models.rfq`**: Contains `RFQ` aggregate model, linking `Organization`, `CommodityDefinition`, `CommoditySchemaVersion`, dynamic `specifications` JSONB, relational commercial/delivery terms, optimistic concurrency `version`, and lifecycle timestamps.
- **`trade_hub.models.invitation`**: Contains `RFQInvitation`, linking an `RFQ` to a target `Organization` (Supplier or Broker) with participant lifecycle status (`invited`, `viewed`, `responded`, `declined`, `expired`).
- **`trade_hub.models.supply`**: Contains `SupplyListing`, linking `Organization` (Supplier), `CommodityDefinition`, `CommoditySchemaVersion`, dynamic `specifications` JSONB, quantity, availability window, and visibility.
- **`trade_hub.services.visibility_service`**: Authoritative QuerySet filtering rules enforcing server-side visibility across Buyer, Supplier, Broker, and Operator actors.

---

## 6. Dependency Graph

All task-level dependencies are derived engineering recommendations based on structural coupling and contract generation order (the roadmap itself provides none):

```text
Approved Master Baseline (Epic 1–4)
               ↓
    T0501: RFQ Domain Model
               ↓
    T0502: RFQ Lifecycle
               ↓
    T0505: RFQ Visibility
               ↓
    T0506: RFQ Invitations
               ↓
    T0503: RFQ Builder API
               ↓
    T0504: RFQ Builder UI
               ↓
    T0507: RFQ Workspace
               ↓
    T0508: Supply Listing Domain
               ↓
    T0509: Supply Listing UI
               ↓
    T0510: Trade Hub & Final Integration
               ↓
    Epic 5 Codex Review Gate
```

---

## 7. Recommended Sequential Execution Order & Rationale

Previous parallel/wave execution experiments are retired. The authoritative execution model is:
```text
One Task → Implementation → Review → CI Green → Merge into Epic Branch → Next Task
```

### Optimal Sequential Sequence:
1. **T0501 — RFQ Domain Model**
2. **T0502 — RFQ Lifecycle**
3. **T0505 — RFQ Visibility**
4. **T0506 — RFQ Invitations**
5. **T0503 — RFQ Builder API**
6. **T0504 — RFQ Builder UI**
7. **T0507 — RFQ Workspace**
8. **T0508 — Supply Listing Domain**
9. **T0509 — Supply Listing UI**
10. **T0510 — Trade Hub & Integration**
11. **Epic 5 Codex Review Gate**

### Why this sequence differs from strict numerical roadmap order:
- In roadmap numerical order, **T0504 (Builder UI)** was placed before **T0505 (Visibility)** and **T0506 (Invitations)**.
- If a developer implements the Builder UI (T0504) before Visibility rules (T0505) and Invitations (T0506) exist, the UI's "Participation & Visibility" section and invitation picker would have no backend models, API endpoints, or OpenAPI types. The UI would either be forced to use temporary stub types or skip the participation section entirely, requiring a costly rewrite later.
- By placing **T0505 (Visibility)** and **T0506 (Invitations)** immediately after the core model (T0501) and lifecycle (T0502), and completing the consolidated Builder API (T0503), the entire backend contract for creation, dynamic validation, visibility selection, and counterpart invitations is fully stabilized and typed.
- **T0504 (Builder UI)** can then build the complete 6-section wizard cleanly against authoritative OpenAPI types in a single pass with zero mock code.
- **T0507 (Workspace)** naturally follows the Builder UI so published RFQs can be inspected.
- **T0508 and T0509 (Supply Listing Domain and UI)** build the complementary supply side.
- **T0510 (Trade Hub)** brings Demand and Supply together into a unified discovery interface and performs full Hero Slice integration verification.

---

## 8. Task Ownership and Risk Inventory

| Task | Roadmap Scope | Dependencies | Why This Position in Sequence | Domain Owner | Migration Risk | Security / Privacy Risk | Contract & UI Impact | Critical Tests |
|---|---|---|---|---|---|---|---|---|
| **T0501** | RFQ Domain Model | Epic 1–4 Baseline | Foundational table required by all subsequent RFQ tasks. | `trade_hub.models.rfq` | High (New `trade_hub` app and initial table; FKs to organizations & commodities) | Medium (Foreign key integrity and field validations) | Backend models only; no immediate wire contract | Model constraints, positive numbers, FK protect, valid enums |
| **T0502** | RFQ Lifecycle | T0501 | Lifecycle transitions, locking, and concurrency must precede API operations. | `trade_hub.services.rfq_service` | Low (No schema changes unless transition history table added) | High (Illegal state bypasses, concurrent double-publish) | Adds status enum overrides to OpenAPI | Concurrency race tests, invalid transition rejections, row-lock verification |
| **T0505** | RFQ Visibility | T0502 | Visibility rules govern QuerySet scoping needed by all read/write endpoints. | `trade_hub.services.visibility_service` | Low (None) | Critical (Private RFQ data leakage to uninvited organizations) | Filters on RFQ list/detail endpoints | Private vs. Network vs. Public visibility matrices, uninvited 404/403 tests |
| **T0506** | RFQ Invitations | T0505 | Invitations grant access to Private RFQs; must precede complete Builder API. | `trade_hub.models.invitation` | Medium (New `RFQInvitation` table; unique constraint per org) | High (Inviting unauthorized parties, IDOR on participant status) | Invitation endpoints in OpenAPI schema | Unique invitation constraint, Buyer/Operator invite permissions, participant status transitions |
| **T0503** | RFQ Builder API | T0506 | Exposes full create, draft update, dynamic validation, and publish endpoints. | `trade_hub.api.views_rfq` | Low (None) | High (Payload injection, validating wrong schema version, post-publish edit) | Full RFQ CRUD and action endpoints in OpenAPI | Dynamic payload validation against exact schema version, draft edit vs. published frozen tests |
| **T0504** | RFQ Builder UI | T0503 | Consumes generated API types for multi-step creation wizard with dynamic specs. | `apps/web/src/app/[locale]/trade-hub/rfqs/new` | Low (None) | Low (Client-side validation supports server enforcement) | Multi-step wizard page, Persian RTL strings | Multi-step form step progression, dynamic spec rendering, client-side error handling |
| **T0507** | RFQ Workspace | T0504 | Detail workspace displaying overview, dynamic specs, participants, and staged tabs. | `apps/web/src/app/[locale]/trade-hub/rfqs/[id]` | Low (None) | Medium (Client caching leaking private data across organization switch) | Workspace tabs, invitation dialogs | Workspace tab navigation, invitation sending, session switch cache clearing |
| **T0508** | Supply Listing Domain | T0507 | Establishes supply-side counterpart with dynamic spec validation and API. | `trade_hub.models.supply` | Medium (New `SupplyListing` table; FKs to organizations & commodities) | High (Supplier capability enforcement, private listing leakage) | Supply listing endpoints in OpenAPI | Supplier capability requirement, dynamic spec validation, listing lifecycle |
| **T0509** | Supply Listing UI | T0508 | Supplier and Operator UI to create, edit, and view supply listings. | `apps/web/src/app/[locale]/trade-hub/supply-listings/` | Low (None) | Low (UI adheres to backend authorization) | Supply listing pages in frontend | Form submission, dynamic commodity form integration, Persian RTL presentation |
| **T0510** | Trade Hub & Integration | T0509 | Unifies Demand and Supply; executes Hero Slice integration verification. | `apps/web/src/app/[locale]/trade-hub/page.tsx` & integration tests | Low (None) | High (Cross-domain query optimization, information leakage in public search) | Unified Trade Hub UI, search & filtering | Full Hero E2E test (Buyer RFQ → Publish → Invite), filter combinatorics, regression of Epics 1–4 |

---

## 9. Migration Strategy

Because tasks execute strictly sequentially:
1. **One Writer at a Time**: Only one task modifies database schema at a time. No parallel sibling branches exist to cause migration graph forks.
2. **Never Preassign Numbers**: Migration numbers will be generated dynamically by Django (`manage.py makemigrations trade_hub`) when the respective model task is executed.
3. **Preserve Prior Migrations**: Migrations in `identity`, `organizations`, `commodities`, and `documents` remain untouched.
4. **App Registration**: The new `trade_hub` app is created in T0501. It must be registered in:
   - `apps/api/config/settings/base.py` (`INSTALLED_APPS`)
   - `apps/api/pyproject.toml` (`[tool.setuptools.packages.find] include = [..., "trade_hub*"]`)
5. **Clean Migration Verification**: Every migration-generating task must verify:
   - `python manage.py makemigrations --check --dry-run` (detects uncommitted model changes)
   - `python manage.py migrate --noinput` (clean apply on fresh and existing databases)
   - Backward unapply and reapply (`migrate trade_hub zero && migrate trade_hub`).
6. **No Merge Migrations**: Because sequential execution eliminates concurrent migration authors, merge migrations are strictly prohibited.

---

## 10. Authorization & Permissions Matrix

All permissions must be enforced strictly server-side. The matrix below defines allowed actions across relevant business capabilities and system roles:

| Actor / Context | Create RFQ Draft | Edit Draft RFQ | Publish RFQ | View Public RFQ | View Network RFQ | View Private RFQ | Invite to RFQ | Cancel / Close RFQ | Create Supply Listing | View Supply Listing |
|---|---|---|---|---|---|---|---|---|---|---|
| **Anonymous** | 401/403 | 401/403 | 401/403 | 401/403 | 401/403 | 401/403 | 401/403 | 401/403 | 401/403 | 401/403 |
| **Buyer Owner / Manager** (Own Org) | Allowed | Allowed | Allowed | Allowed | Allowed (if commodity matched) | Allowed (Own Org) | Allowed | Allowed | 403 (unless also Supplier) | Allowed (Public/Network) |
| **Buyer Member / Viewer** (Own Org) | 403 | 403 | 403 | Allowed | Allowed (if commodity matched) | Allowed (Own Org read-only) | 403 | 403 | 403 | Allowed (Public/Network) |
| **Supplier Owner / Manager** (Other Org) | 403 (unless also Buyer) | 403 | 403 | Allowed | Allowed (if commodity matched) | Allowed **ONLY IF** Invited | 403 | 403 | Allowed (Own Org) | Allowed |
| **Supplier Member / Viewer** (Other Org) | 403 | 403 | 403 | Allowed | Allowed (if commodity matched) | Allowed **ONLY IF** Invited | 403 | 403 | 403 (Read-only) | Allowed |
| **Broker** (Other Org) | 403 (unless also Buyer) | 403 | 403 | Allowed | Allowed (if commodity matched) | Allowed **ONLY IF** Invited | 403 | 403 | 403 (unless also Supplier) | Allowed |
| **Foreign Org** (Uninvited, Private RFQ) | 403 | 403 | 403 | Allowed | 404/403 | 404/403 | 403 | 403 | N/A | 404/403 (if Private) |
| **Platform Operator** | Allowed (on behalf) | Allowed (on behalf) | Allowed | Allowed | Allowed | Allowed (All) | Allowed (All) | Allowed | Allowed (on behalf) | Allowed (All) |
| **Product Admin** | Allowed | Allowed | Allowed | Allowed | Allowed | Allowed (All) | Allowed (All) | Allowed | Allowed | Allowed (All) |
| **Django Staff Only** (No Role Assignment) | 403 | 403 | 403 | 403* | 403* | 403 | 403 | 403 | 403 | 403* |

*\* Note: Users without active organization membership and without Operator/Admin system roles cannot access procurement listings.*

---

## 11. Historical Integrity & Immutability Contracts

For each business entity in Epic 5:

### 11.1 RFQ
- **Creation-Time Schema Version**: `schema_version` is fixed at creation time to a `Published` schema version of the specified `CommodityDefinition`. Once stored, `schema_version` is **immutable**. Subsequent publications of new commodity schema versions (e.g. Bitumen v2) do not alter existing RFQs.
- **Specification Snapshot**: Dynamic specifications in `specifications` JSONB are validated at creation and publication against the stored `schema_version`. Once `Published`, the `specifications` dictionary is frozen.
- **Commercial Core Immutability**: Upon transitioning to `Published`, fields defining the commercial agreement (`quantity`, `unit`, `target_price`, `currency`, `payment_terms`, `incoterm`, `origin`, `destination`) become read-only.
- **Foreign Key Protection**: References to `organization`, `commodity`, `schema_version`, and `created_by` use `on_delete=models.PROTECT`. Referenced organizations or definitions cannot be hard-deleted while active RFQs exist.

### 11.2 Supply Listing
- Operates under identical immutability principles: `commodity`, `schema_version`, and dynamic `specifications` JSONB are frozen upon publication (`status = "active"`).

### 11.3 RFQ Invitations
- `RFQInvitation` records historical participation timestamps (`created_at`, `viewed_at`, `responded_at`).
- Status history is preserved; invitations are never hard-deleted when participants decline or expire.

---

## 12. Concurrency, Locking, and Lifecycle State Machine

Learning from the concurrency findings in Epic 4 (Review Gate Findings B1 and M1), version fields alone are insufficient without database row locks:

### 12.1 Transaction Boundaries & Row Locking
- All state-mutating actions (`publish`, `cancel`, `close`, `invite`) must execute inside `transaction.atomic()`.
- The aggregate root (`RFQ` or `SupplyListing`) must be locked using `select_for_update()` before reading version or validating prerequisites:
  ```python
  @transaction.atomic
  def publish_rfq(rfq_id: uuid.UUID, user: User, expected_version: int) -> RFQ:
      rfq = RFQ.objects.select_for_update().get(pk=rfq_id)
      if rfq.version != expected_version:
          raise StaleObjectError("RFQ has been modified by another action. Please refresh.")
      if rfq.status != RFQStatus.DRAFT:
          raise InvalidTransitionError(f"Cannot publish RFQ in status {rfq.status}.")
      
      validate_rfq_for_publish(rfq)
      rfq.status = RFQStatus.PUBLISHED
      rfq.published_at = timezone.now()
      rfq.version += 1
      rfq.save()
      return rfq
  ```

### 12.2 Optimistic Concurrency Protocol
- Mutation endpoints (`POST /publish/`, `POST /cancel/`, `POST /close/`, `PATCH /`) must require `expected_version` in the request payload.
- Mismatched versions return **HTTP 409 Conflict** with an explicit error code (`stale_version`).
- Missing versions return **HTTP 400 Bad Request**.

### 12.3 Unique Constraints & Idempotency
- Concurrent invitations targeting the same organization on the same RFQ are serialized by a PostgreSQL unique constraint `(rfq_id, target_organization_id)`, converting duplicate concurrent invitations into an atomic database constraint conflict rather than duplicate participant records.

---

## 13. PostgreSQL Structural Invariants & Indexing Policy

### 13.1 Database Invariants (PostgreSQL Schema Constraints)
```python
# trade_hub/models/rfq.py
class RFQ(models.Model):
    # ...
    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=[
                    "draft", "published", "collecting_offers", "negotiating",
                    "awarded", "closed", "cancelled"
                ]),
                name="check_valid_rfq_status"
            ),
            models.CheckConstraint(
                condition=models.Q(visibility__in=["private", "network", "public"]),
                name="check_valid_rfq_visibility"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="check_positive_rfq_quantity"
            ),
            models.CheckConstraint(
                condition=models.Q(target_price__gt=0) | models.Q(target_price__isnull=True),
                name="check_positive_rfq_target_price"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(delivery_window_end__gte=models.F("delivery_window_start")) |
                    models.Q(delivery_window_start__isnull=True) |
                    models.Q(delivery_window_end__isnull=True)
                ),
                name="check_valid_rfq_delivery_window"
            ),
        ]

# trade_hub/models/invitation.py
class RFQInvitation(models.Model):
    # ...
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rfq", "organization"],
                name="unique_rfq_organization_invitation"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[
                    "invited", "viewed", "responded", "offer_submitted", "declined", "expired"
                ]),
                name="check_valid_rfq_invitation_status"
            )
        ]
```

### 13.2 Indexing Policy
- **Relational B-Tree Indexes**: Placed on high-cardinality foreign keys and filter fields:
  - `RFQ(organization_id)`
  - `RFQ(commodity_id)`
  - `RFQ(status, visibility)`
  - `RFQ(created_at DESC)`
  - `RFQInvitation(organization_id, status)`
  - `SupplyListing(organization_id, commodity_id, status)`
- **JSONB Indexing**: Per ADR 0002 and Epic 3 specifications, **no speculative GIN/JSONB indexes will be added in Epic 5**. Searches and filters in Trade Hub and RFQ lists operate on static relational columns (`commodity_id`, `status`, `country`, `visibility`, `quantity`). Specification matching occurs in Epic 7; adding GIN indexes now without demonstrated queries violates project invariants.

---

## 14. API & OpenAPI Contract Boundary

### 14.1 Wire Contract Endpoints
- **RFQ Management**:
  - `GET /api/trade-hub/rfqs/`: Paginated list of RFQs filtered by visibility.
  - `POST /api/trade-hub/rfqs/`: Create new RFQ draft.
  - `GET /api/trade-hub/rfqs/{id}/`: Retrieve full RFQ detail.
  - `PUT/PATCH /api/trade-hub/rfqs/{id}/`: Update draft RFQ fields.
  - `POST /api/trade-hub/rfqs/{id}/publish/`: Explicit publish action (`expected_version` required).
  - `POST /api/trade-hub/rfqs/{id}/cancel/`: Explicit cancel action (`expected_version`, `reason` required).
  - `POST /api/trade-hub/rfqs/{id}/close/`: Explicit close action (`expected_version` required).
  - `GET /api/trade-hub/rfqs/{id}/workspace/`: Consolidated workspace detail endpoint.
- **Invitations**:
  - `GET /api/trade-hub/rfqs/{id}/invitations/`: List invited participants (Buyer and Operator only).
  - `POST /api/trade-hub/rfqs/{id}/invitations/`: Invite an organization to the RFQ.
  - `POST /api/trade-hub/rfqs/{id}/invitations/{invitation_id}/respond/`: Participant response (`declined`).
- **Supply Listings**:
  - `GET /api/trade-hub/supply-listings/`: Paginated list of supply listings filtered by visibility.
  - `POST /api/trade-hub/supply-listings/`: Create supply listing draft.
  - `GET /api/trade-hub/supply-listings/{id}/`: Retrieve supply listing detail.
  - `PATCH /api/trade-hub/supply-listings/{id}/`: Update draft listing.
  - `POST /api/trade-hub/supply-listings/{id}/publish/`: Explicit publish action.
  - `POST /api/trade-hub/supply-listings/{id}/close/`: Explicit close action.
- **Trade Hub**:
  - `GET /api/trade-hub/summary/`: Summary metrics (active RFQ count, active Supply count for current user context).

### 14.2 Serializer Projections & Privacy
- **Public / Counterparty RFQ Projection**: Strips internal notes, participant invitation lists of competitors, and creator internal audit details. Competitor suppliers cannot see who else is invited.
- **Owner / Operator RFQ Projection**: Includes full participant lists, invitation statuses, internal notes, and administrative controls.
- **OpenAPI Rule**: All endpoints registered with `drf-spectacular`. Zero manual DTOs in frontend. Frontend types regenerated via `npm run api:generate`.

---

## 15. Frontend Architecture & User Experience (/fa RTL)

### 15.1 Routing Structure
All user-facing views reside under `apps/web/src/app/[locale]/`:
- `/fa/trade-hub`: Unified Trade Hub landing page with tabbed toggle:
  - **Demand Tab (RFQ)**: Search bar, commodity selector, status badges, listing cards with key terms, "Create RFQ" button.
  - **Supply Tab (Supply Listings)**: Search bar, commodity selector, listing cards, "Create Supply" button.
- `/fa/trade-hub/rfqs/new`: Multi-step RFQ Builder wizard.
- `/fa/trade-hub/rfqs/[id]`: Dedicated RFQ Workspace.
- `/fa/trade-hub/supply-listings/new`: Supply Listing creation form.
- `/fa/trade-hub/supply-listings/[id]`: Supply Listing detail view.

### 15.2 RFQ Builder Wizard UX (T0504)
A stepped, navigable wizard providing instant validation and state recovery:
1. **Section 1: Product**: Commodity picker, Dynamic specification form (`CommoditySpecificationForm`), Quantity, Unit.
2. **Section 2: Commercial**: Currency, Target Price (optional), Payment Terms, Incoterm.
3. **Section 3: Delivery**: Origin country/port, Destination country/port, Delivery window date range.
4. **Section 4: Quality & Inspection**: Inspection requirement toggle, Quality notes.
5. **Section 5: Participation & Visibility**: Visibility selection (`Public`, `Network`, `Private`). In Private mode, multi-select search picker for Supplier/Broker organizations from the verified network directory.
6. **Section 6: Preview & Publish**: Comprehensive preview utilizing `CommoditySpecificationView`, commercial summary, terms confirmation, and "Publish RFQ" action.

### 15.3 RFQ Workspace UX (T0507)
A tabbed operational workspace for the published RFQ:
- **Overview Tab**: Dynamic specification view (`CommoditySpecificationView`), commercial summary, delivery window, status badge, action toolbar (Cancel, Close).
- **Participants Tab**: Visible to Buyer/Operator. Table of invited organizations, capabilities, invitation timestamps, and status badges (`Invited`, `Viewed`, `Responded`, `Declined`). Includes "Invite More" dialog.
- **Offers Tab**: Explicit staged state ("Offers module will be available in Epic 8. Received offers will appear here.").
- **Comparison Tab**: Explicit staged state ("Offer comparison will be available in Epic 8.").
- **Negotiation Tab**: Explicit staged state ("Negotiation history will be available in Epic 8.").
- **Activity Tab**: Chronological audit timeline (Created, Published, Participants Invited, Modified).
- **Documents Tab**: Associated specification sheets or term sheets.

### 15.4 Localization & RTL Invariants
- Strict Persian RTL (`dir="rtl"`, `lang="fa-ir"`, Vazirmatn font).
- Localized Persian messages placed in `apps/web/src/i18n/messages/fa.ts`.
- Zero hardcoded English strings in reusable components.
- Responsive design with Tailwind CSS and Radix UI / shadcn primitives.

---

## 16. Testing Contract, Acceptance Criteria & Canonical CI Mapping

Every task must implement executable automated tests covering the full acceptance criteria. Ad-hoc untracked scripts are prohibited.

### 16.1 Test Path & CI Job Mapping

| Test Domain | File Path | Canonical Command | GitHub Actions Job |
|---|---|---|---|
| RFQ Model & Constraints | `apps/api/trade_hub/tests/test_models.py` | `python manage.py test trade_hub.tests.test_models` | `Backend CI` |
| RFQ Lifecycle & Concurrency | `apps/api/trade_hub/tests/test_lifecycle.py` | `python manage.py test trade_hub.tests.test_lifecycle` | `Backend CI` |
| RFQ Visibility & Scoping | `apps/api/trade_hub/tests/test_visibility.py` | `python manage.py test trade_hub.tests.test_visibility` | `Backend CI` |
| RFQ Invitations & Access | `apps/api/trade_hub/tests/test_invitations.py` | `python manage.py test trade_hub.tests.test_invitations` | `Backend CI` |
| RFQ Builder API & Validation | `apps/api/trade_hub/tests/test_builder_api.py` | `python manage.py test trade_hub.tests.test_builder_api` | `Backend CI` |
| Supply Listing Domain & API | `apps/api/trade_hub/tests/test_supply_listing.py` | `python manage.py test trade_hub.tests.test_supply_listing` | `Backend CI` |
| Trade Hub & Integration Flow | `apps/api/trade_hub/tests/test_epic_integration.py` | `python manage.py test trade_hub.tests.test_epic_integration` | `Backend CI` |
| OpenAPI Contract Validation | `apps/api/schema.yaml` | `npm run api:generate && git diff --exit-code` | `OpenAPI Contract Validation` |
| Frontend RFQ Builder Tests | `apps/web/tests/components/rfq-builder.test.tsx` | `npm run test:components` | `Frontend CI` |
| Frontend Workspace Tests | `apps/web/tests/components/rfq-workspace.test.tsx` | `npm run test:components` | `Frontend CI` |
| Frontend Trade Hub Tests | `apps/web/tests/components/trade-hub.test.tsx` | `npm run test:components` | `Frontend CI` |
| Frontend Lint, Types & Build | `apps/web/` | `npm run lint && npm run typecheck && npm run build` | `Frontend CI` |

### 16.2 Required Invariant Checks for Every Task
1. **Happy Path**: Expected creation, lifecycle advance, query filtering, and presentation.
2. **Permission Denial**: Verify 403 Forbidden for unauthorized capabilities, wrong memberships, or unauthenticated requests.
3. **Foreign / Cross-Org IDOR**: Member of Org A cannot edit Org B's RFQ or view Org B's Private RFQ.
4. **Lifecycle Violation**: Cannot publish non-draft RFQ; cannot edit frozen fields on published RFQ.
5. **Stale Writes & Concurrency**: Stale `expected_version` returns HTTP 409 Conflict.
6. **Dynamic Specification Validity**: Unknown fields, type errors, or numeric bound violations raise structured ValidationError.
7. **PostgreSQL Invariants**: Direct invalid inserts trigger PostgreSQL check/unique constraint errors.

---

## 17. Integration Task Strategy (T0510)

**T0510 (Trade Hub)** is the natural integration task for Epic 5. Rather than inventing an artificial integration task ID:
1. T0510 builds the unified Trade Hub frontend page (`/fa/trade-hub`) providing tabbed access to Demand (RFQs) and Supply (Supply Listings) with search and filtering.
2. T0510 implements the full **Hero Slice Acceptance Test** (`test_epic_integration.py`):
   - Buyer logs in, selects active Buyer organization.
   - Buyer creates RFQ draft with dynamic Bitumen specifications (e.g. penetration grade 60/70, softening point 49).
   - Dynamic specifications are validated by `validate_commodity_payload`.
   - Buyer sets Private visibility and selects verified Supplier and Broker organizations from Directory to invite.
   - Buyer publishes RFQ (advancing version 1 → 2).
   - Invited Supplier logs in: verifies RFQ is visible in their Trade Hub with complete specifications.
   - Uninvited Supplier logs in: verifies RFQ returns 404 / is excluded from their Trade Hub.
   - Invited Broker logs in: verifies RFQ is visible.
   - Operator logs in: verifies global visibility and ability to inspect participant list.
3. T0510 verifies zero regression across Epics 1–4.

---

## 18. Final Epic Review Gate Preview (Adversarial Probes)

When all 10 tasks are merged into `codex/epic-05-trade-hub-rfq`, the Codex Review Gate Auditor will execute an adversarial probe suite attacking:

1. **Cross-Organization IDOR**: Attempt to read/edit/publish another organization's RFQ or Supply Listing.
2. **Private Visibility Leakage**: Attempt to discover Private RFQs through search filters, aggregate counts, or direct ID enumeration without an invitation.
3. **Capability Confusion**: Attempt to create an RFQ from an organization that holds only `Supplier` capability. Attempt to create a Supply Listing from an organization that holds only `Buyer` capability.
4. **Lifecycle Bypass & Stale Concurrency**: Execute concurrent threads attempting double-publication or publishing with mismatched `expected_version`.
5. **Dynamic Specification Bypass**: Attempt to store unvalidated JSONB payloads, unknown fields, or attributes from another commodity.
6. **Schema Version Mismatch**: Attempt to attach a draft or retired schema version to a new RFQ. Attempt to revalidate an existing RFQ against a newly published schema version.
7. **Post-Publication Tampering**: Attempt to alter `quantity`, `payment_terms`, or `specifications` on a Published RFQ.
8. **Participant Privacy Leakage**: Verify that invited Supplier A cannot see Supplier B in the participant list.
9. **PostgreSQL Constraint Probes**: Execute raw SQL probes attempting to insert negative quantities, invalid statuses, or duplicate invitations.
10. **Packaging Integrity**: Build `sdist` and `wheel` (`python -m build apps/api`) and confirm `trade_hub`, all models, migrations, and submodules are bundled cleanly.
11. **OpenAPI Drift**: Verify `npm run api:generate` produces 0 git diff.
12. **Frontend Cache & Session Isolation**: Verify switching personas or organizations clears React Query caches and does not display cached private RFQs.
13. **Full Regression**: Execute complete test suites across `identity`, `organizations`, `commodities`, `documents`, and `trade_hub`.

---

## 19. Packaging & Build Pipeline Safeguards

To prevent package discovery omissions discovered in previous review gates:
1. In **T0501**, update `apps/api/pyproject.toml`:
   ```toml
   [tool.setuptools.packages.find]
   include = ["config*", "identity*", "organizations*", "commodities*", "documents*", "trade_hub*"]
   ```
2. In **T0501**, verify build artifacts:
   ```bash
   python -m build apps/api
   tar -tf apps/api/dist/commodity_platform_api-0.1.0.tar.gz | grep trade_hub
   ```
3. Update `.github/workflows/ci.yml`:
   Ensure `branches` includes `codex/epic-05-*` so CI runs on task PRs targeting the Epic integration branch.

---

## 20. Scope Exclusions (Strict Non-Goals)

The following later-roadmap entities must **NOT** be introduced in Epic 5:
- **No Offers or Offer Versions** (Epic 8, T0801–T0804).
- **No Offer Normalisation or Landed Cost Engine** (Epic 8, T0805–T0807).
- **No Award or Deal Entities** (Epic 8/9, T0813, T0901–T0905).
- **No Execution Monitor or Milestones** (Epic 10, T1001–T1009).
- **No Matching Engine or Automated Scoring** (Epic 7, T0701–T0708).
- **No Market Discovery or Opportunity Desk** (Epic 6, T0601–T0612).
- **No External Counterparty Entities** (Epic 6, T0604).
- **No Real Settlement, Escrow, Payment, Financing, or Logistics Execution** (Specification §56).
- **No Infrastructure Additions**: No Kafka, RabbitMQ, Redis, Elasticsearch, Temporal, or Microservices.

---

## 21. Documentation Inconsistencies & Alignment Log

1. **`AGENTS.md` Scope**: Contains stale references to Epic 4 execution on `codex/epic-04-organizations-network-verification`. In accordance with prompt instructions, the owner's request establishes that Epic 4 is approved and merged, and authorizes Epic 5 planning.
2. **Roadmap T0504 vs. T0505/T0506 Order**: Roadmap §9 orders T0504 (Builder UI) before T0505 (Visibility) and T0506 (Invitations). As detailed in §7, sequential implementation requires ordering T0505 and T0506 before T0504 to prevent UI contract churn and mocking.
3. **CI Branch Filter**: `.github/workflows/ci.yml` currently lists `codex/epic-04-*`. When `codex/epic-05-trade-hub-rfq` is created, CI configuration must be updated to include `codex/epic-05-*`.
