# Implementation Roadmap & Codex Delivery Plan

## B2B Commodity Procurement & Trade Platform

این سند روش اجرای Product Specification را مشخص می‌کند.

---

# 1. Delivery Model

ساختار کار:

```text
Product Specification
        ↓
      Epic
        ↓
Capability Slice
        ↓
      Task
        ↓
Acceptance Criteria
        ↓
   Codex Execution
        ↓
 Automated Tests
        ↓
 Human Review
        ↓
 Commit / Push
        ↓
      Next Task
```

هر Task باید به‌اندازه‌ای محدود باشد که بتوان تغییرات آن را مستقلاً Review کرد.

Codex نباید با یک Prompt بزرگ چند Epic را هم‌زمان پیاده‌سازی کند.

---

# 2. Sources of Truth

سه فایل/سیستم منبع حقیقت خواهند بود:

### Product Scope

```text
docs/product/product-spec.md
```

همان Final Product Specification.

### Architecture Decisions

```text
docs/architecture/
docs/adr/
```

### Work Backlog

GitHub Issues.

بنابراین:

> GitHub Issue = واحد رسمی کار

و Codex هر بار یک Issue مشخص را اجرا می‌کند.

---

# 3. Priority Levels

## P0 — Core Product

بدون آن Hero Demo ناقص است.

## P1 — Important Product Depth

برای Demo جدی و Pilot-readiness مهم است.

## P2 — Polish / Operational Improvement

ارزشمند است ولی dependency هسته محصول نیست.

---

# 4. Epic 0 — Product & Architecture Foundation

**Priority:** P0

هدف:

قبل از نوشتن Feature Code، Codex باید Context پایدار پروژه را داشته باشد.

---

## T0001 — Add Product Specification

**Scope**

ایجاد:

```text
docs/product/product-spec.md
```

از Final Product Specification.

### Acceptance

* Product Vision ثبت شده باشد.
* Actors ثبت شده باشند.
* Modules ثبت شده باشند.
* Non-goals ثبت شده باشند.
* Architectural Invariants ثبت شده باشند.

---

## T0002 — Add Domain Glossary

ایجاد:

```text
docs/domain/glossary.md
```

تعریف دقیق:

* Buyer
* Supplier
* Broker
* Operator
* Organization
* RFQ
* Supply Listing
* Opportunity
* Offer
* Offer Version
* Award
* Deal
* Attribution
* Execution Monitor
* Commodity Definition
* Commodity Schema
* External Counterparty

### Important

کلمه `Trader` نباید در Domain Vocabulary استفاده شود.

---

## T0003 — Record Architecture Decisions

ایجاد ADR برای:

```text
ADR-001 Django Modular Monolith
ADR-002 PostgreSQL as Source of Truth
ADR-003 Dynamic Commodity Specifications
ADR-004 REST + OpenAPI
ADR-005 Execution Monitoring First
ADR-006 Human-assisted Market Discovery
ADR-007 S3-compatible Document Storage
ADR-008 Locale-aware Frontend
```

---

## T0004 — Add AGENTS.md

فایل:

```text
AGENTS.md
```

باید شامل:

* Project purpose
* Architecture rules
* Business vocabulary
* Testing rules
* Git rules
* Scope rules
* Non-goals
* Codex behavior

باشد.

این فایل Context دائمی Codex است.

---

## Epic 0 Review Gate

قبل از ادامه:

* هیچ code feature نباید پیاده شده باشد.
* Product Spec و ADRها باید Human Reviewed شوند.
* AGENTS.md باید با Product Spec هم‌راستا باشد.

---

# 5. Epic 1 — Repository & Platform Foundation

**Priority:** P0

---

## T0101 — Bootstrap Monorepo

Structure:

```text
apps/
  web/
  api/

docs/
  product/
  architecture/
  domain/
  adr/

infra/
  docker/

scripts/
```

### Acceptance

* local setup documented
* root commands documented
* `.env.example` موجود
* secrets commit نشده باشند

---

## T0102 — Bootstrap Django API

Components:

* Django 6
* Django REST Framework
* PostgreSQL config
* environment config
* structured settings
* health endpoint

Endpoint:

```text
GET /api/health
```

---

## T0103 — Bootstrap Next.js Frontend

Components:

* Next.js
* TypeScript
* Tailwind
* shadcn/ui
* Persian locale foundation
* RTL root layout

Demo locale:

```text
/fa
```

---

## T0104 — Local Infrastructure

Docker Compose:

* PostgreSQL
* MinIO

### Acceptance

یک command بتواند infrastructure را بالا بیاورد.

---

## T0105 — OpenAPI Contract Foundation

Backend:

OpenAPI generation.

Frontend:

generated API client infrastructure.

### Rule

Frontend نباید API Contract را دستی duplicate کند.

---

## T0106 — CI Foundation

حداقل pipeline:

```text
Backend lint/test
Frontend lint/typecheck
Build
```

---

# Epic 1 Review Gate

از fresh clone:

```text
setup
run
test
```

باید بدون تغییر دستی کار کند.

---

# 6. Epic 2 — Identity, Organizations & Authorization

**Priority:** P0

---

## T0201 — User Authentication

Implement:

* User
* login
* logout
* authenticated session/token mechanism

Demo implementation باید Production-compatible باشد.

---

## T0202 — Organization Model

Entities:

```text
Organization
OrganizationMembership
OrganizationCapability
```

Capabilities:

```text
Buyer
Supplier
Broker
```

---

## T0203 — System Roles

System roles:

```text
Operator
Admin
```

Organization roles نمونه:

```text
Owner
Manager
Member
Viewer
```

---

## T0204 — Server-side Authorization

Permission checks برای APIها.

### Critical Rule

Frontend hiding ≠ authorization.

---

## T0205 — Frontend Session & Organization Context

Frontend باید:

* current user
* current organization
* capabilities
* permissions

را بشناسد.

---

## T0206 — Demo Persona Switcher

فقط در Demo/Development:

```text
Buyer
Supplier
Broker
Operator
Admin
```

قابل Switch باشد.

Production code path نباید امنیتش به این feature وابسته باشد.

---

# Epic 2 Review Gate

Permission matrix review شود.

حداقل تست:

* Buyer نمی‌تواند Organization دیگر را edit کند.
* Supplier نمی‌تواند Offer دیگری را edit کند.
* Broker access محدود باشد.
* Operator access مشخص باشد.
* Admin access مشخص باشد.

---

# 7. Epic 3 — Dynamic Commodity Platform

**Priority:** P0

این Epic یکی از مهم‌ترین بخش‌های کل معماری است.

---

## T0301 — Commodity Definition Models

Implement:

```text
CommodityDefinition
CommoditySchemaVersion
CommodityAttributeDefinition
```

---

## T0302 — JSON Schema Representation

هر Schema Version باید runtime validation schema داشته باشد.

Support اولیه:

* string
* number
* boolean
* enum
* unit-aware numeric field

---

## T0303 — Dynamic Specification Validation

Backend service:

```text
validate_specification(
    commodity,
    schema_version,
    specifications
)
```

Invalid specification باید rejected شود.

---

## T0304 — Bitumen Commodity Seed

Bitumen schema realistic ایجاد شود.

نمونه attributes:

* penetration grade
* penetration
* softening point
* flash point
* ductility

این‌ها DB columns نیستند.

---

## T0305 — Secondary Commodity Architecture Test

یک Base Oil schema کوچک فقط برای تست architecture.

هدف:

اثبات اینکه بدون migration می‌توان Commodity دیگری تعریف کرد.

UI اصلی همچنان Bitumen-focused است.

---

## T0306 — Dynamic Form Renderer

Frontend component:

```text
CommoditySpecificationForm
```

Form را از Schema دریافت کند.

Fieldهای Bitumen داخل component hard-coded نباشند.

---

## T0307 — Dynamic Specification Display

Reusable component:

```text
CommoditySpecificationView
```

برای:

* RFQ
* Offer
* Supply
* Opportunity
* Deal

---

## T0308 — JSONB Query & Index Foundation

Query capability و indexهای لازم برای dynamic specifications.

Over-indexing انجام نشود.

---

# Epic 3 Review Gate

یک تست معماری مهم:

بدون migration:

```text
Bitumen
→ Base Oil
```

قابل تعریف و validate باشد.

---

# 8. Epic 4 — Organizations, Network & Verification

**Priority:** P1

---

## T0401 — Company Directory

List + search + filters.

Filters:

* capability
* geography
* commodity
* verification

---

## T0402 — Organization Profile

نمایش:

* company information
* capabilities
* commodities
* geography
* verification
* activity summary

---

## T0403 — Verification Domain

Implement statuses:

```text
Unverified
Documents Submitted
Under Review
Basic Verified
Verified
Suspended
```

---

## T0404 — Verification Checklist

Operator بتواند verification items را review کند.

---

## T0405 — Verification Documents

Document metadata + MinIO upload.

---

## T0406 — Verification Operator UI

Operator workspace برای:

* pending cases
* documents
* notes
* approve/reject/suspend

---

# 9. Epic 5 — Trade Hub & RFQ

**Priority:** P0

---

## T0501 — RFQ Domain Model

Core:

* organization
* commodity
* schema version
* specifications
* quantity
* unit
* commercial terms
* delivery
* visibility
* lifecycle

---

## T0502 — RFQ Lifecycle

Suggested statuses:

```text
Draft
Published
Collecting Offers
Negotiating
Awarded
Closed
Cancelled
```

---

## T0503 — RFQ Builder API

Create/update/publish.

Validation کامل.

---

## T0504 — RFQ Builder UI

Multi-section UI:

* Product
* Commercial
* Delivery
* Quality
* Participation
* Preview

Dynamic commodity fields باید از Schema بیایند.

---

## T0505 — RFQ Visibility

Implement:

```text
Private
Network
Public
```

Permission tests ضروری.

---

## T0506 — RFQ Invitations

Buyer/Operator بتواند:

* Suppliers
* Brokers

را invite کند.

---

## T0507 — RFQ Workspace

Tabs:

```text
Overview
Participants
Offers
Comparison
Negotiation
Activity
Documents
```

---

## T0508 — Supply Listing Domain

Supply-side counterpart RFQ.

Fields:

* commodity
* specifications
* quantity
* geography
* availability
* indicative terms
* visibility

---

## T0509 — Supply Listing UI

Supplier/Operator create/edit/list.

---

## T0510 — Trade Hub

Unified view:

```text
Demand
Supply
```

با search/filter.

---

# Epic 5 Review Gate

Hero slice:

```text
Buyer
→ Create RFQ
→ Publish
→ Invite Supplier/Broker
```

باید کامل کار کند.

---

# 10. Epic 6 — Market Discovery / Opportunity Desk

**Priority:** P0

یکی از differentiatorهای اصلی محصول.

---

## T0601 — Opportunity Domain Model

Fields مطابق Product Specification.

Direction:

```text
Supply
Demand
```

---

## T0602 — Opportunity Identifier

Human-readable ID:

```text
OPP-2026-000124
```

---

## T0603 — Opportunity Lifecycle

Implement:

```text
Captured
Contacted
Qualified
Matching
Converted
On Hold
Rejected
Lost
Expired
```

Transition rules تعریف شوند.

---

## T0604 — External Counterparty

Implement:

```text
ExternalCounterparty
```

بدون User Account.

---

## T0605 — Opportunity Source & Broker Attribution

Sources:

* Broker Referral
* Operator Sourcing
* Buyer Referral
* Supplier Referral
* Existing Relationship
* Inbound Lead

Broker source باید traceable باشد.

---

## T0606 — Contact Attempts

Operator بتواند:

* call
* message
* email
* meeting
* note

ثبت کند.

---

## T0607 — Opportunity Tasks / Follow-ups

Operator follow-up date/task بسازد.

---

## T0608 — Opportunity Qualification

Operator بتواند:

```text
Captured
→ Qualified
```

با required fields مشخص.

---

## T0609 — Opportunity → RFQ Conversion

Demand Opportunity بتواند RFQ بسازد.

Source link حفظ شود.

---

## T0610 — Opportunity → Supply Listing Conversion

Supply Opportunity بتواند Supply Listing شود.

Traceability حفظ شود.

---

## T0611 — Submit Offer from Opportunity

Operator بتواند از Qualified Supply Opportunity:

Offer

روی RFQ ثبت کند.

---

## T0612 — Opportunity Desk UI

Views:

* Inbox
* Assigned to me
* Qualified
* Follow-up required
* Converted
* Lost

---

# Epic 6 Review Gate

Demo Flow:

```text
Broker Referral
→ Opportunity
→ External Supplier
→ Qualification
→ RFQ Offer
```

باید end-to-end کار کند.

---

# 11. Epic 7 — Matching Engine

**Priority:** P0

---

## T0701 — Matching Candidate Model

Matching result persisted یا reproducible باشد.

---

## T0702 — Core Matching Rules

Rules:

* commodity
* organization capability
* geography
* availability

---

## T0703 — Dynamic Specification Matching

Commodity specification compatibility.

Hard-coded Bitumen matching ممنوع.

---

## T0704 — Trust / Verification Signals

Match score بتواند verification را لحاظ کند.

---

## T0705 — Historical Signals

در صورت وجود data:

* previous response
* previous deal
* historical performance

---

## T0706 — Opportunity Sources

Matching باید:

```text
Organizations
Supply Listings
Qualified Opportunities
Brokers
```

را ببیند.

---

## T0707 — Explainable Scoring

Result نمونه:

```text
92%

Commodity Match
Specification Match
Verified
Previous Successful Deal
```

---

## T0708 — Matching UI

Operator/Buyer suggestions را ببیند و انتخاب کند.

---

# 12. Epic 8 — Offers, Procurement & Negotiation

**Priority:** P0

---

## T0801 — Offer Domain Model

Offer باید parent identity مستقل داشته باشد.

---

## T0802 — Offer Version Model

```text
Offer
  V1
  V2
  V3
```

Overwrite ممنوع.

---

## T0803 — Supplier/Broker Offer Submission

Validation + permissions.

---

## T0804 — Operator Submission on Behalf

Operator بتواند Offer خارجی را ثبت کند.

`entered_by_operator` traceable باشد.

---

## T0805 — Offer Normalisation Engine

Initial calculation:

```text
Product Cost
+ Logistics
+ Other Known Costs
= Landed Cost
```

---

## T0806 — Comparison API

Normalized comparison model.

---

## T0807 — Comparison UI

Table با:

* headline price
* landed price
* payment
* delivery
* quality
* verification
* trust

---

## T0808 — Decision Support Model

Configurable weighted scoring.

---

## T0809 — Explainable Recommendation

Recommendation بدون explainability نمایش داده نشود.

---

## T0810 — Request Revision

Buyer/Operator Revision Request.

---

## T0811 — Revised Offer

Supplier/Broker version جدید ارائه دهد.

---

## T0812 — Negotiation History UI

V1 → V2 → V3 قابل مشاهده باشد.

---

## T0813 — Award Offer

Award flow + confirmation.

---

# Epic 8 Review Gate

Flow:

```text
Offer V1
→ Compare
→ Revision Request
→ Offer V2
→ Compare
→ Award
```

بدون DB manipulation.

---

# 13. Epic 9 — Deal & Attribution

**Priority:** P0

---

## T0901 — Deal Creation

Award باید immutable commercial snapshot اولیه بسازد.

---

## T0902 — Deal Terms Snapshot

Snapshot:

* quantity
* price
* specifications
* payment
* delivery
* counterparties

بعداً تغییر RFQ نباید Deal را تغییر دهد.

---

## T0903 — Deal Attribution

Track:

```text
Platform Network
Direct Supplier
Broker
Opportunity Desk
Buyer Existing Supplier
```

---

## T0904 — Broker Attribution

Support:

* Supply Originator
* Demand Originator
* Related Opportunity

---

## T0905 — Deal Workspace UI

Tabs:

```text
Overview
Terms
Parties
Attribution
Execution
Logistics
Quality
Documents
Issues
Activity
```

---

# 14. Epic 10 — Execution Monitor

**Priority:** P0

Execution نه Payment Platform.

---

## T1001 — Workflow Template Model

```text
ExecutionWorkflowTemplate
ExecutionMilestoneDefinition
ExecutionMilestone
```

---

## T1002 — Bitumen Execution Workflow Seed

Initial:

```text
Awarded
Contract Signed
Payment Reported
Loading Scheduled
Loaded
Inspection Completed
In Transit
Delivered
Accepted
Closed
```

---

## T1003 — Execution Timeline

Deal instance milestones.

---

## T1004 — Logistics Tracking

Fields:

* carrier
* transport mode
* pickup
* destination
* loading
* ETA
* actual delivery
* reference
* logistics cost

---

## T1005 — Quality & Inspection

Fields:

* required
* agency
* date
* status
* result
* notes

---

## T1006 — Payment Monitoring

فقط statuses:

```text
Expected
Reported
Confirmed
```

No money movement.

---

## T1007 — Execution Documents

Associate documents with milestones.

---

## T1008 — Issue Management

Types:

* Quality
* Quantity
* Logistics
* Payment
* Document
* Contract
* Other

---

## T1009 — Execution Monitor UI

Timeline + panels.

---

# Epic 10 Review Gate

Deal باید از Award تا Closed به‌طور کامل قابل مشاهده باشد.

Platform نباید Payment/Settlement واقعی اجرا کند.

---

# 15. Epic 11 — Operational Tooling

**Priority:** P1

---

## T1101 — Internal Notes

Entities:

* Organization
* RFQ
* Opportunity
* Deal

---

## T1102 — Audit Trail

Track important mutations.

---

## T1103 — Notifications Domain

Events:

* RFQ invitation
* Offer submitted
* Revision
* Award
* Expiration
* Execution delay
* Issue

---

## T1104 — Notification Center UI

---

## T1105 — Operator Task Model

---

## T1106 — Operator Task UI

---

## T1107 — Global Search

Search:

* Organizations
* Opportunities
* RFQs
* Deals

---

## T1108 — Advanced Filters

Reusable filter infrastructure.

---

# 16. Epic 12 — Intelligence

**Priority:** P1

---

## T1201 — Procurement Metrics Query Layer

Metrics:

* RFQ count
* offer count
* award rate
* time to first offer
* offers per RFQ
* quote spread

---

## T1202 — Deal Metrics

* deal count
* awarded volume
* completed value
* execution delays

---

## T1203 — Supplier Performance

* response rate
* win rate
* delivery
* quality
* completed deals

---

## T1204 — Broker Performance

* opportunities introduced
* qualification rate
* deals attributed
* conversion
* attributed value

---

## T1205 — Opportunity Metrics

* captured
* qualified
* converted
* lost
* conversion rate

---

## T1206 — Market Activity

Commodity-level:

* min quote
* max quote
* average quote
* quote spread
* executed values

---

## T1207 — Insufficient Data Guard

اگر data کافی نیست:

```text
Insufficient data for reliable benchmark
```

نمایش داده شود.

Fake price index ممنوع.

---

## T1208 — Dashboard UI

Operator dashboard.

---

# 17. Epic 13 — Demo Quality & Release

**Priority:** P0/P1

---

## T1301 — Realistic Seed Dataset

حداقل:

* 4 Buyers
* 8 Suppliers
* 5 Brokers
* 20 RFQs
* 40+ Offers
* 10 Deals
* Opportunities
* Execution histories

---

## T1302 — Hero Scenario Seed

Dedicated scenario:

```text
500 MT Bitumen 60/70
```

با Broker-originated external supply.

---

## T1303 — Persian Localization Pass

تمام Demo:

Persian.

هیچ placeholder انگلیسی ناخواسته وجود نداشته باشد.

---

## T1304 — RTL UX Review

Review:

* tables
* forms
* filters
* sidebars
* dropdowns
* charts
* timeline
* dialogs

---

## T1305 — Empty / Loading / Error States

برای critical pages.

---

## T1306 — Permission E2E Tests

Buyer / Supplier / Broker / Operator.

---

## T1307 — Hero Playwright E2E

```text
Create RFQ
→ Matching
→ Offers
→ Opportunity
→ Comparison
→ Revision
→ Award
→ Deal
→ Execution
```

---

## T1308 — Demo Reset Script

یک command:

Demo database را به seed state برگرداند.

---

## T1309 — Demo Navigation Polish

Navigation role-aware.

---

## T1310 — Final Demo QA

Review کامل:

* backend
* UI
* data
* permissions
* Hero Flow
* audit
* performance basics

---

# 18. Dependency Graph

High-level:

```text
Epic 0
  ↓
Epic 1
  ↓
Epic 2
  ↓
Epic 3
  ↓
Epic 4 ──────────────┐
  ↓                  │
Epic 5               │
  ↓                  │
Epic 6               │
  ↓                  │
Epic 7 ◄─────────────┘
  ↓
Epic 8
  ↓
Epic 9
  ↓
Epic 10
  ↓
Epic 11
  ↓
Epic 12
  ↓
Epic 13
```

بعضی Taskهای Epic 11/12 می‌توانند بعد از stable شدن Epicهای قبلی parallel شوند.

اما در شروع پروژه Parallel Agentها را زیاد نمی‌کنیم.

---

# 19. Development Gates

بعد از هر Epic:

## Gate A — Automated

* tests pass
* lint passes
* typecheck passes
* migrations valid

## Gate B — Functional

Acceptance Criteria اجرا شود.

## Gate C — Architecture

هیچ invariant شکسته نشده باشد.

## Gate D — Human Review

Diff توسط Owner review شود.

سپس Epic بعدی.

---

# 20. Task Status Model

GitHub Issue labels:

```text
status:ready
status:in-progress
status:review
status:blocked
status:done
```

Priority:

```text
priority:P0
priority:P1
priority:P2
```

Area:

```text
area:backend
area:frontend
area:domain
area:infra
area:docs
area:e2e
```

Epic:

```text
epic:foundation
epic:commodities
epic:rfq
epic:opportunities
...
```

---

# 21. Recommended Git Strategy

هر Task:

```text
main
  │
  └── codex/T0805-offer-normalisation
```

Codex فقط همان Task را روی branch خودش انجام دهد.

بعد:

```text
implement
→ test
→ commit
→ push
→ review
→ merge
```

Codex نباید خودش branchهای unrelated را merge کند.

---

# 22. Commit Policy

یک Task ممکن است ۱ تا چند commit کوچک داشته باشد، ولی ترجیحاً history ساده بماند.

نمونه:

```text
feat(commodities): add versioned commodity schemas
```

```text
feat(opportunities): add opportunity qualification flow
```

```text
test(rfq): cover private visibility permissions
```

---

# 23. Pull Request Policy

اگر GitHub CLI / integration در environment قابل استفاده باشد:

Codex بعد از Task:

* branch را Push کند.
* PR بسازد.
* Issue ID را reference کند.
* Summary و tests را در PR توضیح دهد.

Codex نباید PR را خودش Merge کند مگر صریحاً دستور داده شود.

---

# 24. Standard GitHub Issue Template

هر Task دقیقاً با قالب زیر تعریف شود:

```markdown
# T0805 — Implement Offer Normalisation

## Epic
Epic 8 — Offers & Procurement

## Priority
P0

## Goal
Normalize received offers into a comparable economic representation.

## Context
See:
- docs/product/product-spec.md
- docs/architecture/...
- AGENTS.md

## Scope
- Calculate product cost
- Include logistics cost
- Include known additional costs
- Produce landed cost

## Out of Scope
- AI recommendations
- Currency market feeds
- Dynamic logistics pricing
- Payment-risk modelling

## Dependencies
- T0801
- T0802

## Acceptance Criteria
- [ ] Landed cost calculated deterministically
- [ ] Missing optional costs handled explicitly
- [ ] Calculation unit tested
- [ ] API returns normalised values
- [ ] Existing Offer data remains unchanged

## Tests
- unit tests for calculation
- integration/API test

## Review Notes
Do not modify unrelated modules.

## Git
Branch:
codex/T0805-offer-normalisation
```

---

# 25. Standard Codex Prompt

برای اجرای Issue:

```text
Implement GitHub task T0805 — Offer Normalisation.

Read first:
- AGENTS.md
- docs/product/product-spec.md
- the GitHub issue for T0805
- only the architecture/domain docs relevant to this task

Before changing code:
1. Inspect only the modules/files necessary for this task.
2. Confirm the implementation approach against the existing architecture.
3. Do not broaden the scope.

Implementation requirements:
- Implement every acceptance criterion in T0805.
- Preserve all architectural invariants.
- Do not implement anything listed under Out of Scope.
- Add/update the minimum necessary tests.
- Do not perform unrelated refactors.

Validation:
- Run the relevant tests.
- Run lint/type checks relevant to changed code.
- Review the final diff for unintended changes.

Git:
- Work on branch codex/T0805-offer-normalisation.
- Commit only this task.
- Use a meaningful Conventional Commit message.
- If GitHub authentication is available, push the branch.
- If GitHub CLI/PR creation is available, open a PR referencing T0805.
- Never merge the PR yourself.

At the end report:
1. Changed
2. Architecture decisions
3. Tests run/results
4. Risks or assumptions
5. Deliberately not implemented
6. Commit hash / branch / PR if available
```

---

# 26. Codex Review Prompt

بعد از Implementation می‌توان یک Codex Thread جدا برای Review داشت:

```text
Review the implementation of T0805 against its GitHub issue,
AGENTS.md, Product Specification, and architecture invariants.

Do not modify code.

Check:
- Acceptance criteria coverage
- Domain correctness
- Data-model correctness
- Authorization implications
- Error handling
- Test quality
- Scope creep
- Unrelated changes
- Maintainability
- Migration risks
- Breaking API changes

Report findings by severity:
Blocker / Major / Minor / Nit

Conclude with:
APPROVE
or
CHANGES REQUIRED
```

این Review Agent از Implementation Agent جدا باشد.

---

# 27. Project-wide Codex Rules

در `AGENTS.md`:

```text
1. Product Spec is the source of truth.
2. Do not invent product requirements.
3. Do not use Trader as a business role; use Broker.
4. Never hard-code commodity-specific attributes into core tables.
5. Do not build a generic commodity platform UI.
6. Market Discovery is intentionally human-assisted.
7. Execution is monitoring/orchestration only.
8. No real payment, escrow, financing, insurance or logistics execution.
9. Backend architecture is Django modular monolith.
10. PostgreSQL is the source of truth.
11. Do not introduce new infrastructure without explicit approval.
12. Do not perform unrelated refactors.
13. Always preserve server-side authorization.
14. User-facing frontend code must remain localization-ready.
15. Demo UI is Persian/RTL.
16. Add tests for business rules.
17. Prefer small changes over broad repository exploration.
18. Never force-push.
19. Never merge a PR without explicit approval.
20. Never commit secrets.
```

---

# 28. GitHub Repository Setup

Repository باید شامل:

```text
README.md
AGENTS.md

docs/
  product/
    product-spec.md

  domain/
    glossary.md

  architecture/
    overview.md

  adr/

  delivery/
    roadmap.md
```

GitHub:

* Issues enabled
* Pull Requests enabled

Suggested labels از بخش Task Status ایجاد شوند.

---

# 29. Milestones

GitHub Milestones را می‌توان این‌طور ساخت:

```text
M0 — Foundation
M1 — Core Domain
M2 — Procurement
M3 — Market Discovery
M4 — Deal & Execution
M5 — Intelligence
M6 — Demo Release
```

Epicها زیر این Milestoneها قرار می‌گیرند.

---

# 30. What to Review Personally

همه Taskها به اندازه یکسان نیاز به Review ندارند.

### Deep Review Required

* Data Model
* Authorization
* Dynamic Commodity Architecture
* Opportunity Attribution
* Matching
* Normalisation
* Deal Snapshot
* Execution Model
* migrations

### Functional/UI Review

* forms
* tables
* dashboards
* filters
* notifications

### Mostly Automated

* small plumbing
* generated API client
* minor presentation work

---

# 31. Recommended Implementation Sequence

ترتیب شروع:

```text
T0001
T0002
T0003
T0004

T0101
T0102
T0103
T0104
T0105
T0106

T0201 → T0206

T0301 → T0308

T0401 → T0406

T0501 → T0510

T0601 → T0612

T0701 → T0708

T0801 → T0813

T0901 → T0905

T1001 → T1009

T1101 → T1108

T1201 → T1208

T1301 → T1310
```

در اولین pass بهتر است Taskها sequential اجرا شوند تا معماری تثبیت شود.

بعداً بعضی UI/analytics Taskها قابل parallelisation هستند.

---

# 32. First Release Gate

اولین نقطه‌ای که Product واقعاً باید Demo شود:

```text
Buyer
→ RFQ
→ Matching
→ Supplier/Broker
→ Opportunity Desk
→ Offer
→ Comparison
→ Revision
→ Award
→ Deal
→ Execution Monitor
```

قبل از رسیدن به این flow، Polish نباید اولویت اصلی شود.

---

# 33. Final Demo Gate

Demo final وقتی Ready است که:

### Business

* Hero Scenario واقعی به‌نظر برسد.
* Broker value واضح باشد.
* Market Discovery قابل نمایش باشد.
* تفاوت Marketplace و Platform واضح باشد.

### Product

* Personaها درست کار کنند.
* Dynamic Commodity Model واقعی باشد.
* Opportunity Attribution از بین نرود.
* Execution قابل مشاهده باشد.

### Engineering

* Hero E2E pass شود.
* permission tests pass شوند.
* migrations clean باشند.
* seed/reset reliable باشد.
* repo clean باشد.

### UX

* فارسی/RTL consistent باشد.
* UI populated باشد.
* empty/error/loading states وجود داشته باشند.
* هیچ صفحه واضحاً prototype خام به‌نظر نرسد.

---

# 34. Definition of Done — Every Codex Task

یک Task Done نیست مگر اینکه:

* Acceptance Criteria کامل باشد.
* Tests مرتبط پاس شده باشند.
* Diff scope محدود داشته باشد.
* Documentation در صورت نیاز update شده باشد.
* No unrelated refactor وجود داشته باشد.
* Branch push شده باشد، در صورتی که GitHub access موجود باشد.
* Human review انجام شده باشد.

---

# 35. Final Delivery Philosophy

قاعده اصلی:

> **One business capability at a time.**

نه:

> Build the whole platform.

هدف این Task Architecture این است که هر بار بتوان مشخصاً گفت:

> «این تغییر چه Business Capabilityای اضافه کرد؟»

و آن را مستقل Review کرد.
