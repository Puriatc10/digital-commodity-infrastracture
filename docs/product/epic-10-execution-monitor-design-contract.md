# Epic 10 — Execution Monitor

## Design Contract, Domain Invariants & Delivery Requirements

**Status:** Owner-approved design contract for Epic 10 implementation  
**Target path:** `docs/product/epic-10-execution-monitor-design-contract.md`  
**Epic:** Epic 10 — Execution Monitor  
**Priority:** P0

---

# 1. Objective

Epic 10 introduces a structured execution-monitoring layer on top of immutable Deals.

The core flow is:

```text
Deal
  ↓
Execution Instance
  ↓
Workflow Template Snapshot
  ↓
Milestones
  ↓
Logistics / Quality / Payment Monitoring
  ↓
Documents / Issues
  ↓
Execution Timeline
  ↓
Closed
```

The platform observes and coordinates execution.

It does **not** move money, settle transactions, book transport, perform inspection, or replace an ERP/TMS/payment provider.

---

# 2. Roadmap Scope

Epic 10 covers:

```text
T1001 — Workflow Template Model
T1002 — Bitumen Execution Workflow Seed
T1003 — Execution Timeline
T1004 — Logistics Tracking
T1005 — Quality & Inspection
T1006 — Payment Monitoring
T1007 — Execution Documents
T1008 — Issue Management
T1009 — Execution Monitor UI
```

The roadmap explicitly defines Execution as monitoring rather than a Payment Platform.

Initial Bitumen workflow:

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

# 3. Existing Architectural Contracts

Epic 10 must preserve:

- Deal is immutable commercial truth.
- DealTermsSnapshot and DealPartySnapshot are historical snapshots.
- One AwardAllocation creates one Deal.
- ExternalCounterparty may be a Deal seller without a platform User/Organization.
- Deal Attribution is provenance, not authorization.
- PostgreSQL is authoritative.
- Django remains a modular monolith.
- REST → OpenAPI → generated TypeScript remains authoritative.
- Commodity-specific execution behavior must not be hard-coded into generic engine code.
- Persian/RTL remains the demo UI.
- `Trader` is forbidden vocabulary; use `Broker`.

---

# 4. Core Boundary

Epic 9 ended with:

```text
Deal
= immutable accepted commercial truth
```

Epic 10 begins with:

```text
Execution
= mutable operational progress around that Deal
```

The Deal itself must not be edited to represent operational progress.

Do not add fields such as:

```text
deal.loaded_at
deal.delivered_at
deal.payment_status
```

to the immutable Deal model.

Operational state lives in Execution aggregates.

---

# 5. Frozen v1 Policy — One Deal Has One Execution Instance

For Epic 10 v1:

```text
1 Deal
→ exactly 1 Execution
```

Recommended structure:

```text
Deal
 └── Execution
      ├── Milestones
      ├── Logistics Record
      ├── Quality/Inspection Records
      ├── Payment Monitoring
      ├── Documents
      └── Issues
```

No multiple independent execution instances per Deal in v1.

---

# 6. Execution Identity

Recommended model:

```text
Execution
---------
id
deal_id
workflow_template_version_id
status
version
started_at
closed_at?
created_at
updated_at
```

`Execution` is mutable operational state.

It is not a commercial snapshot.

---

# 7. Execution Creation

Execution should be created from an existing Deal using an explicit idempotent domain action.

Suggested conceptual API:

```text
POST /deals/{deal_id}/execution/
```

Recommended v1 policy:

```text
explicit idempotent creation
```

Calling the action twice must return the same Execution.

Structural uniqueness:

```text
unique(deal)
```

---

# 8. Execution Lifecycle

Keep Execution lifecycle minimal:

```text
OPEN
CLOSED
```

Do not duplicate milestone names into `Execution.status`.

Operational detail belongs to milestones.

`CLOSED` is reached only when the closing milestone is completed and blocking rules are satisfied.

---

# 9. Workflow Template Model

Epic 10 requires reusable execution workflows.

Recommended models:

```text
ExecutionWorkflowTemplate
ExecutionWorkflowTemplateVersion
ExecutionMilestoneDefinition
```

A Template represents business workflow identity.

A Version represents immutable workflow semantics.

Milestone Definitions belong to a Template Version.

---

# 10. Workflow Template Versioning

Published workflow versions are immutable.

Flow:

```text
Template
├── v1 Published
└── v2 Draft/Published
```

An existing Execution remains bound to the workflow version active at its creation.

Later workflow changes must not reinterpret old Deal execution history.

---

# 11. Workflow Version States

Use:

```text
DRAFT
PUBLISHED
RETIRED
```

Rules:

- Draft editable.
- Published immutable.
- Retired remains readable historically.
- New Execution uses active Published version.
- Retired version cannot be used for new Execution.

---

# 12. Generic Workflow Engine

Workflow definitions are data.

Do not implement:

```python
if commodity.code == "bitumen":
    ...
```

inside generic execution services.

Bitumen v1 is seeded as workflow data.

Later commodities may use different workflow definitions without changing the core engine.

---

# 13. Milestone Definition

Recommended fields:

```text
id
workflow_template_version
code
name_fa
name_en
sort_order

required
blocking
terminal

expected_offset_days?
category?
```

`code` is stable machine identity.

Labels are localized.

---

# 14. Milestone Dependencies

Recommended v1 support:

```text
previous milestone / prerequisite set
```

Do not build a generic BPMN/workflow engine.

A milestone definition may depend on one or more earlier milestone definitions.

For simple Bitumen v1, execution may primarily be sequential.

---

# 15. Milestone Instance

Each Execution materializes milestone instances from its workflow version.

Recommended model:

```text
ExecutionMilestone
------------------
execution
definition
status
expected_at?
actual_at?
completed_by?
notes?
version
created_at
updated_at
```

---

# 16. Milestone Statuses

Use a small explicit set:

```text
PENDING
IN_PROGRESS
COMPLETED
BLOCKED
SKIPPED
```

Rules:

- `COMPLETED` is historical fact.
- `SKIPPED` requires explicit reason and only if definition/policy allows.
- `BLOCKED` must have reason/reference where appropriate.
- No silent reverse from COMPLETED to PENDING.

---

# 17. Completed Milestone Immutability

Once completed, the core completion fact must not be overwritten.

Do not silently mutate:

```text
completed_by
actual_at
completion evidence
```

If correction is needed later, use an explicit correction/audit mechanism rather than editing history in place.

For v1, ordinary APIs should not allow reopening COMPLETED milestones unless explicitly required.

---

# 18. Milestone Completion Rules

A milestone may be completed only when:

- Execution is OPEN.
- Required prerequisites are satisfied.
- actor is authorized.
- expected_version is current.
- milestone-specific guards are satisfied.

---

# 19. Milestone Side Effects

Milestone completion may update derived Execution state/timestamps but must not mutate Deal commercial truth.

Example allowed:

```text
Closed milestone → Execution.status = CLOSED
```

Example forbidden:

```text
Loaded milestone → Deal quantity changed
```

---

# 20. Workflow Snapshot Semantics

Execution must never resolve milestone semantics from the currently active workflow.

It must use:

```text
execution.workflow_template_version
```

forever.

Historical rendering is version-bound.

---

# 21. Bitumen v1 Workflow Seed

Seed deterministic Bitumen workflow:

```text
1. AWARDED
2. CONTRACT_SIGNED
3. PAYMENT_REPORTED
4. LOADING_SCHEDULED
5. LOADED
6. INSPECTION_COMPLETED
7. IN_TRANSIT
8. DELIVERED
9. ACCEPTED
10. CLOSED
```

Labels localized for `fa` and `en`.

Seed must be idempotent.

Re-running seed must not mutate Published workflow history.

---

# 22. AWARDED Initial Milestone

Because Execution starts after Deal materialization from Award, the first milestone:

```text
AWARDED
```

may be auto-completed at Execution creation.

Completion timestamp should derive from authoritative Award/Deal source.

---

# 23. CONTRACT_SIGNED

This milestone records reported/confirmed contract-signing completion.

Epic 10 does not implement e-signature or contract generation.

Optional supporting document may be attached.

---

# 24. PAYMENT_REPORTED

This milestone indicates reported payment progress.

It does not mean the platform transferred funds.

Payment monitoring details are defined separately.

---

# 25. LOADING_SCHEDULED

Represents an operational loading schedule.

It may require logistics pickup/loading date data.

Do not build a carrier booking engine.

---

# 26. LOADED

Represents reported actual loading completion.

May capture:

```text
actual_loading_at
```

through Logistics Tracking.

---

# 27. INSPECTION_COMPLETED

Represents quality/inspection completion.

It should be driven by Quality/Inspection records.

Do not hard-code inspection details into milestone itself.

---

# 28. IN_TRANSIT

Represents reported shipment movement after loading.

No GPS or telematics integration in v1.

---

# 29. DELIVERED

Represents reported actual delivery.

May require:

```text
actual_delivery_at
```

from Logistics Tracking.

---

# 30. ACCEPTED

Represents Buyer-side acceptance of delivered goods.

No automatic assumption that Delivered means Accepted.

Acceptance remains explicit.

---

# 31. CLOSED

Final execution milestone.

Completing CLOSED:

```text
Execution.status = CLOSED
closed_at = milestone.actual_at
```

Only after required milestones/issue policy permit.

---

# 32. Execution Timeline

The timeline is derived from actual domain records.

It must combine:

- milestone state changes;
- logistics-relevant facts;
- inspection events;
- payment-monitoring events;
- issue events;
- document attachments where appropriate.

Do not invent a generic audit platform.

---

# 33. Timeline Event Model

Recommended approach:

Use existing domain records as source and produce a deterministic timeline projection.

Avoid duplicating every domain mutation into a second generic timeline table unless necessary.

---

# 34. Timeline Ordering

Ordering must be deterministic:

```text
event_at ASC
stable_type_priority
stable_id ASC
```

Do not rely only on timestamp when ties are possible.

---

# 35. Logistics Tracking

Recommended model:

```text
ExecutionLogistics
------------------
execution
carrier_name?
transport_mode
pickup_area/reference?
destination_area/reference?
scheduled_loading_at?
actual_loading_at?
eta?
actual_delivery_at?
transport_reference?
logistics_cost?
currency?
version
```

One v1 logistics record per Execution.

---

# 36. Logistics Fields

Roadmap-required fields:

```text
carrier
transport mode
pickup
destination
loading
ETA
actual delivery
reference
logistics cost
```

---

# 37. Transport Mode

Use stable enum values such as:

```text
ROAD
SEA
RAIL
AIR
MULTIMODAL
OTHER
```

Do not infer transport mode from geography.

---

# 38. Pickup and Destination

Reuse platform GeographicArea/reference concepts where available.

Support hierarchical geography.

Do not reduce locations to arbitrary free text if structured geography exists.

---

# 39. Logistics Snapshot vs Deal Terms

DealTermsSnapshot contains accepted commercial delivery terms.

ExecutionLogistics contains actual operational execution data.

Do not overwrite Deal terms when actual logistics changes.

---

# 40. Logistics Cost

Execution logistics cost may represent actual/reported operational cost.

It does not rewrite Offer/Deal landed-cost snapshot.

If actual cost differs from Deal commercial assumption, both remain historically meaningful.

---

# 41. Logistics Cost Currency

Store explicit currency.

No FX conversion in Epic 10.

---

# 42. Logistics Concurrency

Mutations use:

```text
expected_version
transaction.atomic
select_for_update
```

No last-write-wins.

---

# 43. Quality & Inspection

Recommended model:

```text
ExecutionInspection
-------------------
id
execution
required
agency?
scheduled_at?
inspection_at?
status
result
notes?
version
created_at
updated_at
```

---

# 44. Inspection Status

Use:

```text
NOT_REQUIRED
PENDING
SCHEDULED
COMPLETED
CANCELLED
```

---

# 45. Inspection Result

Use:

```text
PASS
FAIL
CONDITIONAL
UNKNOWN
```

Do not infer result from free-text notes.

---

# 46. Required Inspection

If Deal/RFQ commercial terms required inspection, Execution inspection should reflect:

```text
required = true
```

derived during initialization where reliable.

---

# 47. Inspection Agency

Agency may be free text in v1.

Do not invent a new InspectionCompany domain.

---

# 48. Inspection Documents

Inspection certificates/reports attach through Execution Documents.

Do not store document bytes on inspection model.

---

# 49. INSPECTION_COMPLETED Guard

Recommended:

`INSPECTION_COMPLETED` may complete when:

- inspection is `NOT_REQUIRED`; or
- required inspection has status `COMPLETED`.

A FAIL result means inspection completed, but downstream closure/acceptance may be blocked by issue policy.

---

# 50. Payment Monitoring

Epic 10 monitors payment status only.

Roadmap statuses:

```text
EXPECTED
REPORTED
CONFIRMED
```

No money movement.

---

# 51. Payment Monitoring Model

Recommended:

```text
ExecutionPayment
----------------
execution
status
expected_amount?
currency?
expected_at?
reported_at?
confirmed_at?
reported_by?
confirmed_by?
reference?
notes?
version
```

One v1 payment-monitoring record per Execution.

---

# 52. v1 Payment Policy

Model one aggregate payment-monitoring status.

Do not prematurely implement:

- installments;
- payment schedules;
- escrow;
- partial settlement;
- reconciliation ledger.

---

# 53. EXPECTED

Represents commercial expectation.

May be initialized from DealTermsSnapshot when reliable.

---

# 54. REPORTED

Represents reported payment.

Required:

```text
reported_by
reported_at
```

It is not confirmation.

---

# 55. CONFIRMED

Represents authorized operational confirmation.

Required:

```text
confirmed_by
confirmed_at
```

No bank integration implied.

---

# 56. Payment Transition Rules

Allowed:

```text
EXPECTED → REPORTED → CONFIRMED
```

No normal reverse transition.

---

# 57. Payment Authorization

Recommended v1:

- Buyer/Seller authorized operational members may report where semantically appropriate.
- Operator/Admin may report and confirm.
- If confirmation ownership is ambiguous, keep confirmation Operator/Admin-only in v1.
- Viewer cannot mutate.

---

# 58. PAYMENT_REPORTED Milestone

Completion requires payment status at least:

```text
REPORTED
```

Milestone must not independently claim payment.

---

# 59. Payment and Deal Terms

ExecutionPayment must not alter Deal payment terms.

---

# 60. Execution Documents

Recommended model:

```text
ExecutionDocument
-----------------
id
execution
milestone?
inspection?
issue?
category
storage metadata/reference
uploaded_by
uploaded_at
```

Reuse existing S3-compatible document infrastructure.

---

# 61. Execution Document Categories

Initial categories:

```text
CONTRACT
PAYMENT_PROOF
LOADING_DOCUMENT
INSPECTION_REPORT
TRANSPORT_DOCUMENT
DELIVERY_PROOF
ACCEPTANCE_DOCUMENT
OTHER
```

Keep generic.

---

# 62. Document Association

A document belongs to one Execution.

Optional association to:

```text
milestone
inspection
issue
```

must reference the same Execution.

---

# 63. Document Bytes

Bytes remain in S3-compatible storage.

PostgreSQL stores metadata.

No public URLs.

No raw object-key leakage.

---

# 64. Document Immutability

Evidence is append-oriented.

Do not silently overwrite prior evidence bytes.

---

# 65. Issue Management

Recommended model:

```text
ExecutionIssue
--------------
id
execution
type
status
severity?
title
description
opened_by
opened_at
resolved_by?
resolved_at?
resolution_notes?
blocks_execution
version
```

---

# 66. Issue Types

Use exactly roadmap types:

```text
QUALITY
QUANTITY
LOGISTICS
PAYMENT
DOCUMENT
CONTRACT
OTHER
```

---

# 67. Issue Status

Use:

```text
OPEN
IN_PROGRESS
RESOLVED
CANCELLED
```

---

# 68. Issue Severity

Optional:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

No automatic Deal mutation.

---

# 69. Issue Lifecycle

Example:

```text
OPEN → IN_PROGRESS → RESOLVED
OPEN → CANCELLED
```

No silent deletion.

---

# 70. Issue Blocking

Recommended:

```text
blocks_execution = true/false
```

Only explicit blocking issues prevent close.

Do not infer blocking from type alone.

---

# 71. Closing Execution

Execution may close only when:

- terminal CLOSED milestone prerequisites are complete;
- no explicit blocking Issue remains open;
- required guards are satisfied.

---

# 72. Quantity Issue

Quantity discrepancy must not mutate Deal quantity.

Operational actuals belong to execution data.

---

# 73. Quality Issue

Quality issue may reference inspection failure/conditional result.

Do not rewrite accepted specifications.

---

# 74. Payment Issue

Payment issue does not automatically change Payment status.

No magical coupling.

---

# 75. Execution Activity vs Epic 11 Audit Trail

Epic 10 stores enough domain history to explain execution.

It does not build the generic Audit Trail from Epic 11.

---

# 76. Internal Notes

Do not implement generic internal notes in Epic 10 unless directly required by one of the explicit entities above.

---

# 77. Authorization Model

Execution rights derive from Deal party + Product role.

Principal actors:

```text
Buyer Organization
Seller Organization
Operator
Product Admin
```

ExternalCounterparty has no direct session.

Attributed-only Broker gains no access.

---

# 78. Customer Read Access

Buyer and actual Seller organization users may read their Execution.

Unrelated Organizations denied.

Attributed-only Broker denied.

---

# 79. Customer Mutation Access

Recommended v1:

```text
Owner / Manager / Member → permitted operational actions by side
Viewer → read only
```

Exact side-specific rules are server-side.

---

# 80. Side-specific Operational Authority

Recommended baseline:

### Seller side
May report/update:

- loading schedule / actual loading;
- transport reference;
- ETA;
- seller-provided documents;
- inspection coordination where appropriate;
- payment evidence where appropriate.

### Buyer side
May report/update:

- delivery receipt;
- acceptance;
- buyer-provided documents;
- inspection confirmation where appropriate;
- payment reporting where appropriate.

### Operator/Admin
May perform global operational actions according to product policy.

---

# 81. Milestone Authority

Examples:

```text
LOADED
→ Seller or Operator

DELIVERED
→ authorized Buyer/Seller/Operator depending evidence policy

ACCEPTED
→ Buyer or Operator

CLOSED
→ Buyer/Operator/Admin
```

Exact policy must be encoded server-side.

---

# 82. External Seller Execution

If Seller is ExternalCounterparty:

- no fake account;
- Operator manages external-side updates;
- Buyer sees safe execution state.

---

# 83. Internal vs Customer Projection

Internal projection may expose more operational metadata.

Customer projection must not leak private Opportunity/source data.

---

# 84. Session / Persona Isolation

On actor/org switch:

- execution cache invalidates;
- milestone/logistics/quality/payment/documents/issues invalidate;
- old in-flight responses cannot repopulate the new actor state.

---

# 85. Optimistic Concurrency

Mutable execution aggregates use:

```text
expected_version
transaction.atomic
select_for_update
```

Apply to:

- Milestones
- Logistics
- Inspection
- Payment
- Issues
- Closing Execution

---

# 86. Concurrency — Milestone

Real PostgreSQL race:

```text
complete same milestone vs complete same milestone
```

Exactly one authoritative completion.

---

# 87. Concurrency — Logistics

Race:

```text
update ETA
vs
record actual delivery
```

must not lose writes silently.

---

# 88. Concurrency — Payment

Race:

```text
report payment
vs
confirm payment
```

must preserve legal ordering.

---

# 89. Concurrency — Issues

Race:

```text
resolve
vs
cancel
```

one authoritative transition.

---

# 90. Concurrency — Close

Race:

```text
close Execution
vs
open blocking Issue
```

must not create an invalid CLOSED state.

---

# 91. Time Semantics

Authoritative action timestamps are server-generated.

Reported historical occurrence may use separate:

```text
actual_at / occurred_at
```

from:

```text
recorded_at
```

---

# 92. Derived Delay State

Do not persist `is_delayed`.

Derive from expected date/current state/current time.

---

# 93. Expected Dates

Expected dates may derive from:

- Deal delivery terms;
- workflow offset defaults;
- explicit scheduling.

Do not fabricate dates without source.

---

# 94. Historical Integrity

Later workflow changes, Deal-party profile changes, or other source changes must not rewrite historical Execution semantics.

---

# 95. No Deal Mutation

Epic 10 must never PATCH:

```text
DealTermsSnapshot
DealPartySnapshot
DealAttribution
Award
OfferVersion
```

---

# 96. Execution Monitor UI

Use Epic 9 Deal Workspace.

Activate:

```text
Execution
Logistics
Quality
Documents
Issues
```

and include Payment Monitoring within the Execution area/panel.

---

# 97. Execution Tab

Show:

- workflow progress;
- current milestone;
- timeline;
- expected vs actual;
- allowed actions;
- blocking conditions.

---

# 98. Timeline UX

Distinguish:

```text
Completed
Current
Pending
Blocked
Skipped
```

with actor/time/evidence where relevant.

---

# 99. Logistics Tab

Show required roadmap fields and keep actual execution separate from commercial terms.

---

# 100. Quality Tab

Show:

- required;
- agency;
- date;
- status;
- result;
- notes;
- documents.

---

# 101. Payment Panel

Show:

```text
Expected
Reported
Confirmed
```

with actor/time/reference.

No money-movement language.

---

# 102. Documents Tab

Authorized list/upload/download.

Show contextual association.

No raw object key.

---

# 103. Issues Tab

Show issue type/status/severity/blocking/resolution.

---

# 104. Error States

Distinguish:

```text
loading
empty
unauthorized
not found
validation
409 conflict
server error
```

---

# 105. 409 Conflict UX

No automatic mutation retry.

Refetch and inform user.

Preserve unsaved input where practical.

---

# 106. Persian / RTL

All `/fa` UI localized and RTL.

Canonical enum values never leak directly.

---

# 107. OpenAPI

Accurately document:

- milestone actions;
- logistics;
- inspection;
- payment;
- document multipart;
- issue actions;
- 409s;
- authorization responses.

---

# 108. Generated Types

No handwritten duplicate DTOs.

Generated TypeScript remains authoritative.

---

# 109. PostgreSQL Constraints

Enforce/investigate:

- unique Execution per Deal;
- unique milestone per `(execution, definition)`;
- valid enums;
- positive cost/amount where applicable;
- child associations scoped to same Execution through service validation.

---

# 110. Migration Validation

Require:

- fresh migration;
- post-Epic-9 upgrade;
- no fabricated historical operational events.

Existing Deals may remain without Execution until explicitly initialized.

---

# 111. Seed Validation

Bitumen workflow seed must be deterministic, idempotent and history-safe.

---

# 112. PostgreSQL Authority

No SQLite fallback.

---

# 113. Storage

Reuse MinIO/S3.

Real storage tests.

Isolated cleanup.

Compensation on DB failure where practical.

---

# 114. Packaging

Built distributions must include all execution modules, migrations, services, APIs, and seed logic.

---

# 115. Performance

Avoid obvious N+1 across Execution graph.

No new cache infrastructure.

---

# 116. Security Review Targets

Attack:

- foreign Execution IDs;
- cross-Execution child IDs;
- document substitution;
- issue IDOR;
- payment actor spoofing;
- attributed Broker access;
- Django superuser confusion;
- mass assignment;
- raw object-key leakage;
- CSRF;
- persona cache leakage.

---

# 117. T1001 — Workflow Template Model

Implement generic template/version/milestone definitions and lifecycle.

Key tests:

- unique codes;
- immutable Published versions;
- Retired readable;
- active version valid;
- generic multi-workflow behavior;
- no commodity hard-code.

---

# 118. T1002 — Bitumen Workflow Seed

Implement exact ten milestones.

Tests:

- exact codes/order;
- localized labels;
- idempotency;
- Published history preserved.

---

# 119. T1003 — Execution Timeline

Implement Execution, milestone instances, timeline and milestone actions.

Tests:

- one Execution per Deal;
- idempotent creation;
- AWARDED initialized correctly;
- prerequisite guards;
- expected_version;
- real completion race;
- historical workflow binding;
- close behavior.

---

# 120. T1004 — Logistics Tracking

Implement all roadmap logistics fields and concurrency-safe update semantics.

---

# 121. T1005 — Quality & Inspection

Implement inspection requirement/status/result/agency/date/notes and milestone integration.

---

# 122. T1006 — Payment Monitoring

Implement:

```text
EXPECTED → REPORTED → CONFIRMED
```

only.

No money movement.

---

# 123. T1007 — Execution Documents

Implement secure MinIO-backed evidence with contextual association.

---

# 124. T1008 — Issue Management

Implement exact roadmap types, issue lifecycle, blocking semantics, and close integration.

---

# 125. T1009 — Execution Monitor UI

Activate Deal Workspace execution surfaces using real generated API contracts.

---

# 126. Recommended Sequential Order

```text
T1001
→ T1002
→ T1003
→ T1004
→ T1005
→ T1006
→ T1007
→ T1008
→ T1009
→ Epic 10 Adversarial Review Gate
```

---

# 127. Hero Flow

```text
Deal
→ Execution
→ Awarded
→ Contract Signed
→ Payment Reported
→ Loading Scheduled
→ Loaded
→ Inspection Completed
→ In Transit
→ Delivered
→ Accepted
→ Closed
```

with real logistics, inspection, payment monitoring, documents and issues.

---

# 128. Failure Hero Flow

```text
Loaded
→ Inspection FAIL
→ blocking Quality Issue
→ Delivered
→ close rejected
→ resolve Issue
→ Accepted
→ close succeeds
```

---

# 129. External Seller Flow

```text
ExternalCounterparty Seller
→ Operator-managed execution
→ Buyer sees safe state
→ no fake external account
```

---

# 130. Explicit Non-goals

Do not implement:

```text
Payment execution
Settlement
Escrow
Financing
Bank integration
Carrier marketplace
Carrier booking
GPS/telematics
Route optimization
Freight pricing engine
Customs brokerage
Inventory/WMS
ERP
E-signature
Contract generation
Inspection marketplace
Generic BPMN builder
Generic ticketing platform
Generic audit platform
Notifications
Analytics
AI
Kafka
Redis
Elasticsearch
Temporal
Microservices
```

---

# 131. Failure Conditions

Epic 10 fails architecturally if:

- execution mutates Deal commercial snapshots;
- payment monitoring moves money;
- generic engine hard-codes Bitumen;
- historical Execution uses today's workflow;
- external seller requires fake account;
- attributed Broker gains access;
- completed milestones are casually overwritten;
- frontend hiding replaces backend authorization.

---

# 132. Review Gate — Workflow

Verify generic versioned workflow, Bitumen seed, history, no hard-code.

---

# 133. Review Gate — Timeline

Verify one Execution/Deal, milestones, guards, concurrency, completed history, closure.

---

# 134. Review Gate — Logistics

Verify roadmap fields, operational/commercial separation, geography, actual timestamps, concurrency, no freight inference.

---

# 135. Review Gate — Quality

Verify requirement/status/result, failed inspection semantics, document linkage and no Deal-spec mutation.

---

# 136. Review Gate — Payment

Verify state transitions, actors/timestamps, concurrency and no money movement.

---

# 137. Review Gate — Documents

Verify real private object storage, no raw keys, cross-Execution protection, compensation and isolated cleanup.

---

# 138. Review Gate — Issues

Verify all issue types, lifecycle, blocking, concurrency and close behavior.

---

# 139. Review Gate — Authorization

Verify Buyer, Seller, external-seller Operator path, unrelated actors, attributed-only Broker, Operator/Admin, Django flags-only and anonymous.

---

# 140. Review Gate — UI

Verify all execution surfaces, Persian/RTL, 409 handling, cache isolation and no fake operational data.

---

# 141. Review Gate — PostgreSQL / OpenAPI / CI

Verify fresh/upgrade migrations, constraints, real concurrency, accurate contracts, generated TS drift, CI reachability, packaging and no SQLite.

---

# 142. Definition of Done

Epic 10 is complete when a Deal can be monitored end-to-end from Awarded to Closed without database manipulation and while proving:

```text
Deal truth remains immutable
Execution history remains version-bound
operational facts are explicit
unknown data is not fabricated
external counterparties need no fake identity
authorization is server-side
no money movement occurs
```

---

# 143. Long-term Contract

After Epic 10:

```text
Deal
= immutable commercial truth

Execution
= operational lifecycle

WorkflowTemplateVersion
= immutable execution semantics

ExecutionMilestone
= execution progress

ExecutionLogistics
= actual logistics monitoring

ExecutionInspection
= quality monitoring

ExecutionPayment
= payment-status monitoring only

ExecutionDocument
= operational evidence

ExecutionIssue
= execution exception/history
```

---

# 144. Final Architectural Statement

> **The Deal says what was agreed; Execution records what happened afterward. Operational updates must never rewrite the accepted commercial truth, and monitoring must never pretend to execute payment, logistics, inspection, or settlement services that the platform does not actually provide.**
