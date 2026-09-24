# Epic 11 — Operational Tooling

## Design Contract, Domain Invariants & Delivery Requirements

**Status:** Proposed owner design contract for Epic 11 implementation  
**Target path:** `docs/product/epic-11-operational-tooling-design-contract.md`  
**Epic:** Epic 11 — Operational Tooling  
**Priority:** P1

---

# 1. Objective

Epic 11 adds cross-cutting operational tools needed to run the platform day to day without weakening the domain boundaries established in Epics 1–10.

The Epic covers:

```text
Internal Notes
Audit Trail
Notifications
Notification Center
Operator Tasks
Operator Task UI
Global Search
Advanced Filters
```

These capabilities sit around existing domain aggregates.

They must not become alternate sources of truth for Organization, RFQ, Opportunity, Offer, Award, Deal, or Execution.

---

# 2. Canonical Roadmap Scope

The roadmap defines exactly:

```text
T1101 — Internal Notes
  Organization
  RFQ
  Opportunity
  Deal

T1102 — Audit Trail
  Track important mutations

T1103 — Notifications Domain
  RFQ invitation
  Offer submitted
  Revision
  Award
  Expiration
  Execution delay
  Issue

T1104 — Notification Center UI

T1105 — Operator Task Model

T1106 — Operator Task UI

T1107 — Global Search
  Organizations
  Opportunities
  RFQs
  Deals

T1108 — Advanced Filters
  Reusable filter infrastructure
```

This contract refines those requirements without adding a new business Epic.

---

# 3. Existing Architectural Contracts

Epic 11 must preserve:

- PostgreSQL is authoritative.
- Django remains a modular monolith.
- REST → OpenAPI → generated TypeScript remains authoritative.
- Product roles remain distinct from Django staff/superuser.
- Organization capability is not authorization.
- Buyer/Supplier/Broker privacy rules remain backend-authoritative.
- Opportunities preserve internal/external provenance boundaries.
- Submitted OfferVersions remain immutable.
- Awards and Deal snapshots remain immutable.
- Execution state remains separate from Deal commercial truth.
- ExternalCounterparty does not require a fake User/Organization.
- Internal notes, sourcing data, audit metadata, and object-storage keys must not leak into customer projections.
- Persian/RTL remains the primary demo UI.
- `Trader` is forbidden vocabulary; use `Broker`.

---

# 4. Core Boundary

Correct direction:

```text
Domain Action
    ↓
Authoritative Domain Service
    ↓
Committed Domain State
    ├── Audit Event
    ├── Notification(s)
    └── optional Operator Task
```

Incorrect:

```text
Audit / Notification / Task
    ↓
silently mutates domain state
```

Operational tooling observes, records, surfaces, and coordinates. It does not replace domain services.

---

# 5. No Magic Signal Architecture

Important Epic 11 behavior must not primarily depend on implicit generic Django `post_save` / `m2m_changed` signals.

Preferred:

```text
explicit domain service action
→ explicit operational hook/event
```

Reasons:

- clear transaction semantics;
- reliable actor attribution;
- deterministic deduplication;
- easier tests;
- less accidental firing during migrations/admin/tests;
- lower coupling.

Framework-level hooks may be used only for truly infrastructure-level behavior.

---

# 6. No New Event Infrastructure

Epic 11 does not require:

```text
Kafka
RabbitMQ
Redis Streams
Celery
Temporal
microservices
```

Cross-cutting event publication remains in-process and transaction-aware.

---

# 7. Internal Notes — Meaning

Internal Notes are private operational annotations for the platform team.

They are not:

- customer comments;
- Offer negotiation messages;
- Execution Issue comments;
- CRM contact history;
- Audit Events.

Roadmap-supported targets are exactly:

```text
Organization
RFQ
Opportunity
Deal
```

---

# 8. Internal Notes — Visibility

v1 policy:

```text
Operator / Product Admin
→ read/write

Buyer/Supplier/Broker organization users
→ no access

Django staff/superuser without Product role
→ no access
```

No count, snippet, author, timestamp, or existence hint may leak to customer projections.

---

# 9. Internal Note Model

Recommended:

```text
InternalNote
------------
id

organization_id?
rfq_id?
opportunity_id?
deal_id?

body
created_by
created_at
```

Use typed foreign keys instead of `GenericForeignKey`.

Exactly one target FK must be populated.

---

# 10. Internal Note Integrity

Database invariant:

```text
exactly one of:
organization_id
rfq_id
opportunity_id
deal_id
```

must be non-null.

Never zero; never multiple.

---

# 11. Internal Note Immutability

v1 policy:

```text
note body is append-only after creation
```

No normal edit/delete API.

Correction is a follow-up note.

This keeps operational history clear without introducing note-revision machinery.

---

# 12. Internal Note Content

- plain text / safely rendered text;
- reasonable length limit;
- arbitrary HTML forbidden;
- note content never drives business state automatically.

Example:

```text
"Supplier should be suspended"
```

does not suspend the Supplier.

---

# 13. Existing Verification-local Notes

Epic 4 may already contain verification-local notes.

Do not silently migrate or reinterpret them as generic Epic 11 notes unless semantics are proven equivalent.

Verification notes may remain verification-domain evidence/history.

---

# 14. Internal Note API

Conceptually:

```text
GET  /internal-notes/?organization_id=...
GET  /internal-notes/?rfq_id=...
GET  /internal-notes/?opportunity_id=...
GET  /internal-notes/?deal_id=...
POST /internal-notes/
```

Do not accept arbitrary model names.

---

# 15. Audit Trail — Meaning

Audit Trail records important mutations and answers:

```text
Who acted?
What business action occurred?
Which resource was affected?
When?
Which important safe fields changed?
Which request/action caused it?
```

Audit is evidence, not the source of domain state.

---

# 16. AuditEvent Model

Recommended:

```text
AuditEvent
----------
id
event_type
occurred_at

actor_type
actor_user_id?
actor_label_snapshot?

resource_type
resource_id
resource_label_snapshot?

organization_scope_id?

request_id?
correlation_id?

changes JSONB?
metadata JSONB?
```

Audit is append-only.

---

# 17. Audit Resource Pointer

Audit spans many current/future resource types and must survive source retirement/deletion.

Use intentionally detached identifiers:

```text
resource_type
resource_id
resource_label_snapshot
```

Do not use a cascading historical FK or `GenericForeignKey` as the sole identity.

`resource_type` comes from an allowlisted registry.

---

# 18. Audit Actor

Support:

```text
USER
SYSTEM
```

For USER:

```text
actor_user_id
actor_label_snapshot
```

For SYSTEM:

```text
actor_user_id = null
```

No fake User for system/scanner actions.

---

# 19. Audit Actor Is Server-derived

Client must never provide authoritative:

```text
actor_user_id
actor_label
occurred_at
request_id
```

for normal product mutations.

---

# 20. Append-only Audit

No normal product API may:

```text
UPDATE AuditEvent
DELETE AuditEvent
```

Retention/archival policy is outside Epic 11.

---

# 21. Audit Transaction Semantics

For synchronous domain mutations:

```text
domain mutation + AuditEvent
```

should commit in the same DB transaction where practical.

If domain mutation rolls back:

```text
AuditEvent rolls back
```

No false success evidence.

---

# 22. Audit Payload Safety

Audit is not a full before/after dump.

Good:

```text
status: Published → Closed
verification_status: Basic → Verified
payment_status: Reported → Confirmed
```

Forbidden payloads include:

- full model `__dict__`;
- raw request bodies;
- passwords;
- API keys;
- auth/session headers;
- CSRF secrets;
- document bytes;
- raw storage object keys;
- unbounded private notes.

Use event-specific safe serializers/builders.

---

# 23. Stable Audit Event Codes

Examples:

```text
organization.profile_updated
organization.verification_decided

rfq.published
rfq.closed
rfq.cancelled
rfq.invitation_created

opportunity.created
opportunity.qualified
opportunity.converted

offer.version_submitted
offer.revision_requested

award.finalized

deal.materialized
deal.attribution_resolved

execution.milestone_completed
execution.logistics_updated
execution.inspection_updated
execution.payment_reported
execution.payment_confirmed
execution.issue_opened
execution.issue_resolved

internal_note.created
operator_task.created
operator_task.assigned
operator_task.status_changed
```

Localized text is not event identity.

---

# 24. Minimum Audit Coverage

At minimum instrument important mutations from implemented business areas:

### Organization / Verification
- safe profile update;
- verification decision/status changes;
- membership/capability/system-role changes where authoritative services exist.

### RFQ
- publish;
- close;
- cancel;
- invitation creation.

### Opportunity
- create;
- qualification/lifecycle changes;
- conversion to RFQ/Supply Listing/Offer.

### Offer / Procurement
- OfferVersion submission;
- Revision Request created/resolved;
- Award finalized.

### Deal
- materialized;
- attribution manually resolved.

### Execution
- important milestone transitions;
- important logistics changes;
- inspection result/completion;
- payment reported/confirmed;
- issue opened/resolved/cancelled;
- execution document upload metadata if useful.

### Epic 11
- Internal Note created;
- Operator Task created/reassigned/status changed.

Do not audit every GET/read in v1.

---

# 25. Audit Query Access

Audit querying is internal-only:

```text
Operator
Product Admin
```

No ordinary customer audit API in v1.

---

# 26. Audit Filters

Support validated filters:

```text
resource_type
resource_id
event_type
actor_user
occurred_from
occurred_to
organization_scope
```

Ordering:

```text
occurred_at DESC
id DESC
```

---

# 27. Operational Event Contract

Notification and future operational consumers receive typed service events.

Conceptually:

```text
OperationalEvent
----------------
event_type
occurred_at
actor_user_id?
resource identifiers
audience context
safe payload
deduplication_key
```

This does not need to be a persisted generic event table.

---

# 28. Audit vs Notification

One domain action may produce both:

```text
AuditEvent
Notification(s)
```

but they remain separate concerns.

Audit:
- internal evidence;
- append-only;
- broad mutation coverage.

Notification:
- per-recipient UX;
- read/unread state;
- narrow roadmap event catalog.

---

# 29. Notification Event Catalog

v1 supports exactly:

```text
RFQ_INVITATION
OFFER_SUBMITTED
REVISION
AWARD
EXPIRATION
EXECUTION_DELAY
ISSUE
```

---

# 30. Notification Model

Recommended:

```text
Notification
------------
id
recipient_user
event_type

resource_type
resource_id
organization_context_id?

title_key
message_key
payload JSONB

deduplication_key
created_at
read_at?
```

One row per recipient.

---

# 31. Localizable Notification Content

Persist:

```text
title_key
message_key
payload
```

rather than Persian prose as the only truth.

Payload contains only safe display parameters.

---

# 32. Notification Deep Links

Generate routes from allowlisted resource mappings.

Do not persist arbitrary client-provided URLs.

Authorization is rechecked when opening the destination.

Notification existence never grants resource access.

---

# 33. Read State

v1 lifecycle:

```text
UNREAD
READ
```

represented by nullable:

```text
read_at
```

Actions:

```text
mark one read
mark all read
```

No business-domain side effects.

---

# 34. Notification Immutability

Business event content is immutable.

Only recipient state such as `read_at` changes.

No normal edit/delete needed in v1.

---

# 35. Notification Idempotency

Every notification has a deterministic deduplication key.

Unique conceptually:

```text
(recipient_user, deduplication_key)
```

Examples:

```text
rfq-invitation:{invitation_id}
offer-submitted:{offer_version_id}
revision:{revision_request_id}:{phase}
award:{award_id}:{recipient_role}
issue:{issue_id}:{event_kind}
```

Retries must not duplicate rows.

---

# 36. Notification Audience Resolver

Recipient selection is explicit by event type.

Do not broadcast based on capability alone.

Notification audience does not redefine domain authorization.

---

# 37. RFQ Invitation Recipients

Recommended default:

```text
active Owner
active Manager
active Member
```

of invited Organization.

Viewer is read-only and does not receive action-oriented invitation notifications by default.

If existing RFQ policy says otherwise, preserve authoritative policy.

---

# 38. Offer Submitted Recipients

Notify authorized procurement actors of RFQ-owning Buyer Organization.

Recommended:

```text
Owner
Manager
Member
```

Do not notify every Operator globally.

---

# 39. Revision Recipients

Revision request:

```text
Offer party's eligible internal users
```

ExternalCounterparty:

```text
no fake recipient
Operator handles external party
```

Revised Offer submission may notify Buyer procurement actors using the same category with structured subtype.

---

# 40. Award Recipients

Notify selected internal Seller/Broker users and relevant Buyer procurement actors.

Do not expose competitor identities or pricing.

ExternalCounterparty has no direct recipient.

---

# 41. Expiration Notification

Initial supported time-derived sources should be explicit, e.g.:

```text
RFQ submission deadline
OfferVersion valid_until
```

Do not build a generic arbitrary-date scanner.

---

# 42. Execution Delay Notification

A delay exists when:

```text
milestone.expected_at < now
AND milestone not completed/skipped
AND execution OPEN
```

It is advisory and must not mutate milestone state.

---

# 43. Delay Deduplication

Recommended:

```text
one notification per milestone + expected_at version
```

If expected date later changes and becomes delayed again, a new stable key may be generated.

---

# 44. Issue Notification

At minimum support useful events such as:

```text
issue opened
blocking issue opened
issue resolved
```

Only safe customer-visible metadata is included.

---

# 45. Time-based Scanner

Expiration and delay need time evaluation.

Do not introduce Celery/Redis.

Implement an idempotent service plus management command:

```text
python manage.py emit_due_notifications
```

It can later be scheduled by cron/Kubernetes CronJob.

Repeated execution must be safe.

---

# 46. Notification Channel

Epic 11 v1 is:

```text
IN-APP ONLY
```

No email, SMS, push, WhatsApp, Slack.

---

# 47. Notification Center UI

Provide:

```text
unread badge/count
paginated list
read/unread state
mark read
mark all read
safe deep links
empty/loading/error
```

Persian/RTL.

---

# 48. Notification Query Isolation

Every query is:

```text
recipient_user = request.user
```

Operator/Admin status does not grant access to another user's personal notification center.

---

# 49. Operator Tasks — Meaning

Operator Tasks are a lightweight internal work queue.

They are not:

- Jira;
- generic PM;
- customer tasks;
- Execution Issues;
- workflow milestones.

---

# 50. OperatorTask Model

Recommended:

```text
OperatorTask
------------
id
title
description?

status
priority

assigned_to?
created_by
due_at?

resource_type?
resource_id?
resource_label_snapshot?

version
created_at
updated_at
completed_at?
```

---

# 51. Task Status

```text
TODO
IN_PROGRESS
DONE
CANCELLED
```

---

# 52. Task Priority

```text
LOW
MEDIUM
HIGH
URGENT
```

Priority is internal ordering only.

---

# 53. Task Assignee

Assignee must be an active:

```text
Operator
or
Product Admin
```

Unassigned tasks are allowed.

Ordinary customer users cannot be assignees.

---

# 54. Task Creation Policy

v1 supports manual task creation.

Do not automatically create a Task for every Audit/Notification event.

Automation rules require separate business policy.

---

# 55. Task Resource Link

Optional allowlisted targets:

```text
ORGANIZATION
RFQ
OPPORTUNITY
DEAL
EXECUTION
EXECUTION_ISSUE
```

Use controlled type registry.

No arbitrary class names.

---

# 56. Task Mutations

Explicit actions/services:

```text
assign
unassign
start
complete
cancel
change due date
change priority
```

Avoid broad mass-assignment serializer.

---

# 57. Task Concurrency

Require:

```text
expected_version
transaction.atomic
select_for_update
```

No last-write-wins for assignment/status.

---

# 58. Task Completion

On DONE:

```text
completed_at = server time
```

Task completion never automatically changes linked domain state.

---

# 59. Task Audit

Create Audit Events for:

```text
task created
assigned/reassigned
status changed
priority/due date changed
```

Avoid recursive Audit-of-Audit behavior.

---

# 60. Task UI

Provide internal surfaces such as:

```text
My Tasks
Unassigned
All Open
Completed
```

with filters:

```text
status
priority
assignee
due date
resource type
```

Overdue is derived, not persisted.

---

# 61. Task Access

```text
Operator / Product Admin
→ read/write

ordinary customer users
→ none

Django flags-only
→ none
```

---

# 62. Global Search — Meaning

Search navigates authorized existing resources.

Roadmap-supported resource types are exactly:

```text
Organizations
Opportunities
RFQs
Deals
```

No arbitrary model search.

---

# 63. Authorization-before-search

Critical invariant:

```text
Authorized QuerySet
    ↓
Search
    ↓
Rank / Serialize
```

Never:

```text
Search all rows
→ hide unauthorized results afterward
```

Counts, ranking, and existence must not leak hidden objects.

---

# 64. Search Scope per Resource

### Organizations
Use existing Company Directory rules.

### Opportunities
Use existing Opportunity access rules. Internal external-supply opportunities remain hidden from unauthorized customers.

### RFQs
Use authoritative RFQ visibility/participation rules.

### Deals
Use Deal party/Product-role rules. Attributed-only Broker gains no search access.

---

# 65. Search Result Contract

Normalized result:

```text
resource_type
resource_id
title
subtitle?
status?
safe_context?
route
rank
```

Each resource uses a safe projection.

---

# 66. Search Fields

Allowlist human navigation fields.

Examples:

```text
Organization:
name
safe registration identifier if already searchable

Opportunity:
identifier
safe authorized display fields

RFQ:
identifier/title
commodity display name

Deal:
identifier
principal party display names
commodity display name
```

Do not search notes, audit payloads, secrets, or arbitrary JSON.

---

# 67. PostgreSQL Search Only

Epic 11 v1 uses PostgreSQL.

Allowed techniques:

```text
normalized ILIKE
pg_trgm
PostgreSQL full-text
```

where evidence justifies them.

No Elasticsearch/OpenSearch.

---

# 68. Search Ranking

Recommended understandable ranking:

```text
exact identifier
prefix match
strong text match
weaker text match
```

Then deterministic tie-break.

No ML/vector ranking.

---

# 69. Persian Search Normalization

Where existing utilities permit, normalize:

- Arabic/Persian Yeh;
- Arabic/Persian Kaf;
- whitespace.

Do not build a linguistic search engine.

---

# 70. Search Guardrails

- minimum normalized query length;
- bounded results;
- paginated/full-list handoff;
- allowlisted `types`;
- empty query does not dump all records.

---

# 71. Search Privacy Regression

An unauthorized exact ID/name must reveal no:

```text
existence
title
status
count
```

---

# 72. Advanced Filters — Meaning

T1108 creates reusable filtering infrastructure.

It is not a generic query language.

---

# 73. Filter Pipeline

Correct:

```text
authorized base QuerySet
→ validated resource FilterSet
→ ordering
→ pagination
```

Incorrect:

```text
client field/operator/value
→ arbitrary ORM lookup
```

---

# 74. Resource-specific FilterSets

Examples:

```text
OrganizationFilterSet
OpportunityFilterSet
RFQFilterSet
DealFilterSet
OperatorTaskFilterSet
AuditFilterSet
```

Infrastructure is reusable; business filters remain explicit.

---

# 75. Filter Operator Allowlist

Support only needed operations:

```text
exact
in
gte/lte
boolean
safe contains/search
```

Forbidden client-controlled forms include:

```text
__regex
__raw
arbitrary relation traversal
arbitrary Django lookup names
```

---

# 76. Canonical Filter Encoding

Filters are represented in URL query params:

```text
?status=TODO&priority=HIGH&due_before=...
```

This gives refresh-safe/shareable state where authorization permits.

---

# 77. Filter Validation

Invalid:

```text
unknown enum
bad UUID
invalid date
invalid combination
oversized list
```

returns a controlled 400 according to project conventions.

Do not silently broaden results.

---

# 78. Authorization Subset Invariant

Always:

```text
filtered_result ⊆ authorized_base_queryset
```

Filters can only narrow.

---

# 79. Frontend Filter Components

Reusable typed components may include:

```text
select
multi-select
date range
boolean
search
```

Business options come from real domain enums/contracts.

---

# 80. Request/Action Context

Introduce or reuse a trusted small context:

```text
actor_user
request_id
correlation_id?
```

Pass this to Audit/Notification integration without passing raw HTTP requests deep into domain services.

---

# 81. Request ID

Reuse existing correlation middleware if present.

Otherwise a lightweight request ID is acceptable.

Distributed tracing is not required.

---

# 82. Failure Semantics

Audit evidence for important synchronous mutation should be strongly consistent with the DB transaction.

Notifications should normally be created transactionally when cheap.

A frontend Notification Center failure never means the committed business action failed.

---

# 83. `transaction.on_commit`

Use only for post-commit effects that are safe to retry.

Do not use it as the only persistence path for critical Audit evidence if it creates a crash window.

---

# 84. No Recursive Operational Events

AuditEvent/Notification creation does not recursively emit itself.

Task changes may be audited.

Notification read-state changes do not need AuditEvents in v1.

---

# 85. Retention Boundary

Epic 11 defines no regulatory retention duration.

Application behavior:

- no ordinary AuditEvent hard delete;
- no Note delete;
- Notification delete not needed in v1;
- completed/cancelled Tasks remain queryable.

---

# 86. Indexing — Audit

Target real queries:

```text
resource_type + resource_id + occurred_at
event_type + occurred_at
actor_user + occurred_at
organization_scope + occurred_at
```

Avoid speculative JSONB indexes.

---

# 87. Indexing — Notifications

Target:

```text
recipient_user + read_at + created_at
recipient_user + created_at
unique recipient + deduplication key
```

---

# 88. Indexing — Tasks

Target:

```text
assigned_to + status
status + priority
status + due_at
```

---

# 89. Search Indexing

Measure before adding heavy indexes.

If `pg_trgm` is used, enable via migration and exercise it in PostgreSQL CI.

---

# 90. Security Targets

Attack all of:

```text
Internal Note target substitution
customer note access
Audit actor spoofing
Audit secret leakage
Notification recipient substitution
notification IDOR
unsafe deep links
Task assignee escalation
Task resource substitution
Global Search hidden exact IDs
Filter lookup injection
persona/session cache leakage
CSRF on mutations
Django staff/superuser confusion
```

---


# 91. T1101 — Internal Notes

Implementation scope:

- generic InternalNote model;
- exactly four roadmap target types;
- Operator/Admin-only API;
- append-only body;
- safe internal UI integration where appropriate.

Required tests:

- each target type;
- exactly-one target DB constraint;
- customer denied;
- Django flags-only denied;
- foreign target handling;
- immutable/no-delete behavior;
- deterministic ordering;
- XSS-safe rendering.

---

# 92. T1102 — Audit Trail

Implementation scope:

- append-only AuditEvent;
- trusted actor/action context;
- explicit event recorder;
- instrumentation of important existing mutations.

Required tests:

- actor derived server-side;
- SYSTEM actor;
- mutation + audit atomicity;
- rollback leaves no false event;
- safe changes payload;
- sensitive redaction;
- internal-only access;
- no update/delete;
- representative events from Organization/RFQ/Opportunity/Offer/Award/Deal/Execution;
- stable ordering/filtering.

---

# 93. T1103 — Notifications Domain

Implementation scope:

- Notification model;
- exact seven roadmap categories;
- recipient resolver;
- deduplication;
- in-app only;
- time-derived expiration/delay scanner.

Required tests:

- RFQ invitation recipients;
- Offer submitted recipients;
- Revision recipients;
- Award recipients;
- ExternalCounterparty has no fake user notification;
- expiration;
- execution delay;
- issue notification;
- retry deduplication;
- safe payload;
- destination authorization re-check;
- idempotent scanner.

---

# 94. T1104 — Notification Center UI

Required:

```text
badge / unread count
notification list
mark one read
mark all read
safe navigation
loading
empty
error
```

Also prove:

- current-user isolation;
- stale-session cache invalidation;
- Persian/RTL;
- generated TypeScript only.

---

# 95. T1105 — Operator Task Model

Implementation scope:

- OperatorTask;
- status;
- priority;
- assignee;
- due date;
- optional allowlisted resource pointer;
- optimistic concurrency;
- Audit integration.

Required tests:

- unassigned Task;
- valid Operator/Admin assignee;
- customer assignee rejected;
- valid transitions;
- completion/cancellation;
- overdue derived;
- stale expected_version;
- assignment race;
- resource validation;
- customer access denied;
- Audit Events emitted.

---

# 96. T1106 — Operator Task UI

Required:

```text
My Tasks
Unassigned
Open
Completed
```

with:

```text
status filter
priority filter
assignee filter
due-date filter
resource-type filter
assign/start/complete/cancel
linked-resource navigation
```

Also:

- 409 handling;
- Persian/RTL;
- Operator/Admin only.

---

# 97. T1107 — Global Search

Implementation scope:

Search exactly:

```text
Organizations
Opportunities
RFQs
Deals
```

Requirements:

- authorization-before-search;
- normalized result contract;
- PostgreSQL-native search;
- safe ranking;
- safe result projection.

Required tests:

- exact identifier match;
- prefix/text match;
- deterministic rank;
- Persian normalization;
- minimum query guard;
- resource type filter;
- per-resource authorization;
- hidden exact-ID attack;
- no Notes/Audit search;
- bounded result size/pagination.

---

# 98. T1108 — Advanced Filters

Implementation scope:

- reusable backend filtering infrastructure;
- explicit resource FilterSets;
- reusable frontend filter components;
- canonical URL query representation.

Required tests:

- exact/in/range/boolean behavior;
- invalid enum/date handling;
- invalid lookup rejected;
- unknown filter follows explicit repository policy;
- authorization cannot broaden;
- large `in` list bounded;
- deterministic URL encoding;
- integration with selected list/search/task surfaces.

---

# 99. Recommended Execution Order

Recommended order:

```text
1. T1102 — Audit Trail
2. T1101 — Internal Notes
3. T1103 — Notifications Domain
4. T1104 — Notification Center UI
5. T1105 — Operator Task Model
6. T1106 — Operator Task UI
7. T1107 — Global Search
8. T1108 — Advanced Filters
9. Epic 11 Adversarial Review Gate
```

Reason:

- Audit exists before new Notes/Tasks mutations.
- Notification domain precedes its UI.
- Task model precedes its UI.
- Search behavior is known before generic filter reuse is finalized.

Task IDs and canonical roadmap scope are unchanged.

---

# 100. Hero Flow — Operator Day

Required representative flow:

```text
Operator signs in
→ sees Task queue
→ opens Opportunity
→ adds Internal Note
→ performs important domain action
→ Audit records action
→ completes Task
→ Task transition is audited
→ searches related RFQ/Deal globally
→ narrows list using Advanced Filters
```

At no point does customer-visible data reveal Notes, Audit, or internal Task context.

---

# 101. Hero Flow — Procurement Notifications

```text
Buyer invites Supplier to RFQ
→ eligible Supplier user gets RFQ Invitation

Supplier submits Offer
→ eligible Buyer users get Offer Submitted

Buyer requests Revision
→ eligible Supplier users get Revision

Supplier submits revised Offer
→ Buyer gets Revision update

Award finalizes
→ selected internal Seller/Broker users get Award
```

Every deep link re-checks domain permission.

---

# 102. Hero Flow — External Counterparty

```text
Operator-managed ExternalCounterparty
→ external Offer revised/awarded
→ no fake User
→ no direct Notification row for external party
→ Operator continues operational handling
```

Do not weaken identity boundaries just to satisfy notification mechanics.

---

# 103. Hero Flow — Time-derived Notification

```text
Execution milestone expected_at passes
→ milestone still incomplete
→ due-notification scanner runs
→ one EXECUTION_DELAY Notification is emitted
→ scanner runs again
→ no duplicate
```

The milestone remains unchanged.

---

# 104. Search Privacy Hero Flow

```text
Operator searches exact internal Opportunity identifier
→ sees result

Buyer searches same identifier
→ no result

Buyer searches own RFQ
→ sees result

Unrelated Supplier searches private Deal identifier
→ no result
→ no count/existence leak
```

---

# 105. Filter Hero Flow

```text
GET /operator/tasks/
?status=TODO
&priority=HIGH
&due_before=...

authorized Operator QuerySet
→ validated filters
→ ordered result
→ pagination
```

No dynamic ORM injection.

---

# 106. Audit Integration Strategy

When retrofitting old domain services, prefer explicit calls at the business-action boundary.

Example:

```text
publish_rfq(...)
    mutate
    validate
    save
    audit.record("rfq.published", ...)
```

Avoid placing Audit calls in:

- serializer `to_representation`;
- generic model `save()`;
- implicit signal chains;
- frontend code.

---

# 107. Notification Integration Strategy

Notifications should be created from semantic domain events.

Example:

```text
submit_offer_version(...)
    save immutable version
    resolve buyer recipients
    create deduplicated notifications
```

Do not infer an Offer submission from arbitrary row updates.

---

# 108. Scanner Locking / Concurrency

Time-based scanner must tolerate concurrent runs.

Use a deterministic unique deduplication constraint as the final guard.

Optional row locking or batching may reduce duplicate work, but correctness must not depend solely on one scanner instance.

Concurrent scanners should converge on one Notification per recipient/event key.

---

# 109. Scanner Batching

Scanner should process bounded batches.

Do not load every expirable RFQ/Offer/milestone into memory.

Use indexed date/status queries.

No new queue required.

---

# 110. Expiration Semantics

Expiration notification does not itself change domain lifecycle.

Example:

```text
OfferVersion.valid_until < now
```

may make Offer ineligible by existing procurement rules, but Notification code does not mutate that rule/state.

Same for RFQ deadline.

---

# 111. Audit Organization Scope

`organization_scope_id` is optional denormalized context useful for internal filtering.

It does not replace resource authorization.

Examples:

- Buyer-owned RFQ → Buyer org scope;
- Supplier Offer submission → RFQ Buyer scope and/or safe metadata;
- Organization mutation → that Organization.

Do not attach misleading scope where event spans multiple organizations.

---

# 112. Audit Labels

Snapshot labels are convenience/audit context only.

Do not use:

```text
resource_label_snapshot
```

to perform authorization or domain identity checks.

---

# 113. Audit Changes Structure

Recommended simple shape:

```json
{
  "status": {
    "from": "PUBLISHED",
    "to": "CLOSED"
  }
}
```

For list/set changes, store bounded safe semantic values rather than entire rows.

---

# 114. Audit Metadata Versioning

If Audit metadata schemas evolve, include:

```text
event_schema_version
```

or make event builders backward-compatible.

Do not force old AuditEvents through today's serializer assumptions.

---

# 115. Notification Payload Versioning

Notification payload should include a small schema/version if structure may evolve.

UI must tolerate old notifications after frontend deployment.

Do not require backfilling every historical row for a wording change.

---

# 116. Notification Localization

Store canonical values.

Render Persian labels/messages in frontend localization.

Do not persist only localized strings that become impossible to re-render in another locale.

---

# 117. Notification Recipient Lifecycle

If recipient user later becomes inactive:

- historical notifications remain;
- inactive user cannot authenticate/read them;
- new recipient resolver excludes inactive users.

---

# 118. Membership Changes

Recipient resolution uses current authoritative membership at event creation time.

A later membership change does not rewrite historical Notification recipients.

Resource access is still re-evaluated at click time.

---

# 119. Task Resource Pointer Safety

Task resource pointer is navigation context, not a source FK for business truth.

The Task may remain historically meaningful even if linked operational object becomes unavailable under future retention rules.

Store safe label snapshot where useful.

---

# 120. Task Description Privacy

Operator Task title/description is internal.

Never expose Task snippets/counts through customer-facing endpoints or global customer search.

---

# 121. Global Search and Advanced Filters

Global Search is navigation.

Advanced Filters narrow list surfaces.

Do not force every search behavior into a generic FilterSet or every filter into Global Search.

Keep responsibilities separate.

---

# 122. Search Resource Adapters

Recommended internal architecture:

```text
GlobalSearchService
    ├── OrganizationSearchProvider
    ├── OpportunitySearchProvider
    ├── RFQSearchProvider
    └── DealSearchProvider
```

Each provider owns:

- authorized base QuerySet;
- searchable fields;
- safe projection;
- rank inputs;
- route.

This avoids one giant cross-domain query with authorization shortcuts.

---

# 123. Search Result Rank Comparability

Cross-type ranking only needs to be useful and deterministic.

Do not claim a mathematically universal relevance score across resource types.

A simple bounded provider score plus stable type ordering is acceptable for v1.

---

# 124. Search Failure Isolation

If one provider fails unexpectedly, recommended default is fail the request rather than silently return a partial result set that looks complete.

Do not mask backend failures as "no results".

---

# 125. Advanced Filter Reuse

Reusable infrastructure should provide:

- parsing;
- validation;
- error contract;
- URL encoding;
- common components.

It should not erase domain-specific semantics.

Example:

```text
RFQ status
```

and:

```text
Deal commodity
```

still belong to their own resource filter definitions.

---

# 126. Filtering and Ordering

Ordering fields must also be allowlisted.

Do not expose arbitrary:

```text
?ordering=some__deep__relation__secret
```

Supported ordering is explicit per endpoint.

---

# 127. Pagination

Search, Audit, Notifications, Tasks, and advanced filtered lists must be paginated or hard-limited.

No unbounded collection endpoints.

---

# 128. OpenAPI Contract

Document accurately:

- Internal Note target union;
- Audit filters/projection;
- Notification categories/read actions;
- Task actions and 409 stale errors;
- Global Search normalized result union;
- filter query parameters and 400 validation.

Do not hide query-contract gaps behind frontend casts.

---

# 129. Generated TypeScript

Frontend consumes generated API types.

No parallel handwritten:

```text
NotificationDTO
TaskDTO
SearchResultDTO
Filter enum
```

when generated contracts are available.

---

# 130. PostgreSQL Constraints

At minimum investigate/enforce:

### Internal Notes
- exactly one target FK.

### Notifications
- recipient FK;
- valid category;
- unique `(recipient, deduplication_key)`.

### Operator Tasks
- valid status/priority;
- nonnegative/valid version;
- valid assignee at service layer;
- timestamps consistent where practical.

### Audit
- valid actor/resource type values;
- append-only enforced at application boundary.

---

# 131. PostgreSQL Concurrency Tests

Use real separate connections for at least:

```text
concurrent notification creation for same dedup key
concurrent Task assignment/status transition
```

Assert:

- one notification;
- one authoritative Task state;
- no leaking IntegrityError as 500.

---

# 132. Fresh and Upgrade Migrations

Require:

```text
fresh PostgreSQL migrate
upgrade from post-Epic-10 schema
makemigrations --check --dry-run
```

Do not fabricate historical AuditEvents/Notifications/Tasks for actions that occurred before Epic 11.

---

# 133. No Historical Audit Backfill

Old domain history remains in existing domain records.

Do not invent:

```text
"RFQ published by user X"
```

if actor/time evidence was not already stored reliably.

Audit begins prospectively from Epic 11 instrumentation.

---

# 134. Packaging

Built wheel/sdist must include:

- operational tooling models;
- migrations;
- audit service;
- notification scanner/management command;
- task services/APIs;
- search providers;
- filter infrastructure.

Editable checkout success is insufficient.

---

# 135. Performance Baseline

At pilot scale:

```text
PostgreSQL + correct indexes + bounded queries
```

is sufficient.

Do not add infrastructure preemptively.

Measure actual Global Search and Audit/Notification list queries.

---

# 136. Logging Boundary

Application logs and Audit Trail are different.

Logs are operational diagnostics.

Audit records business-significant mutations.

Do not write secrets to either.

Do not use Elasticsearch logs as the canonical Audit Trail.

---

# 137. Notification vs Task Boundary

Notification says:

```text
"Something happened that this user should know."
```

Task says:

```text
"An internal Operator has work to do."
```

Do not automatically create both for every event.

---

# 138. Task vs Issue Boundary

Execution Issue is domain operational exception tied to a Deal execution.

Operator Task is internal work coordination.

An Issue may motivate a Task later, but they remain separate aggregates.

---

# 139. Note vs Audit Boundary

Internal Note:

```text
human-authored operational context
```

Audit Event:

```text
system-recorded evidence that a mutation occurred
```

Creating a Note may itself produce:

```text
internal_note.created
```

Audit Event, but Note text need not be copied into Audit payload.

---

# 140. Search vs Directory Boundary

Global Search does not redefine Organization Directory visibility.

Organization search provider must reuse/compose the directory's authorized scope.

---

# 141. Review Gate — Internal Notes

Verify:

- exactly four roadmap target types;
- typed integrity;
- Operator/Admin only;
- no customer count/snippet leak;
- append-only semantics;
- safe rendering;
- no accidental verification-note conflation.

---

# 142. Review Gate — Audit

Verify:

- append-only;
- actor server-derived;
- request/correlation context;
- rollback correctness;
- sensitive redaction;
- representative mutation coverage;
- internal-only read;
- no recursive Audit loop;
- stable query/index behavior.

---

# 143. Review Gate — Notifications

Verify all seven roadmap categories.

Attack:

- duplicate emission;
- wrong recipient;
- inactive membership;
- Viewer policy;
- external party path;
- permission revoked after notification;
- concurrent scanner runs;
- delay/expiration dedup;
- payload leakage;
- arbitrary deep-link injection.

---

# 144. Review Gate — Notification Center

Verify:

- unread count;
- current-user isolation;
- mark read/all;
- safe navigation;
- stale-session protection;
- Persian/RTL;
- no authorization implication from Notification.

---

# 145. Review Gate — Operator Tasks

Verify:

- internal-only;
- valid assignee;
- lifecycle;
- optimistic concurrency;
- due/priority behavior;
- safe resource links;
- Audit integration;
- no automatic domain mutation.

---

# 146. Review Gate — Global Search

Verify:

- exactly four roadmap resource categories;
- authorization-before-search;
- exact hidden identifier attack;
- Persian normalization;
- deterministic rank;
- bounded result set;
- no Notes/Audit search;
- PostgreSQL-native architecture.

---

# 147. Review Gate — Advanced Filters

Verify:

- explicit FilterSets;
- no arbitrary lookup injection;
- invalid input contracts;
- authorization subset invariant;
- bounded list inputs;
- URL canonicalization;
- reusable frontend components.

---

# 148. Review Gate — Roles

Exercise:

```text
Buyer Owner/Manager/Member/Viewer
Supplier Owner/Manager/Member/Viewer
Broker Owner/Manager/Member/Viewer
Operator
Product Admin
Django staff/superuser without Product role
anonymous
inactive actors/memberships where relevant
```

Capabilities never substitute for authorization.

---

# 149. Review Gate — CI / Contract

Verify:

- PostgreSQL migrations;
- concurrency;
- OpenAPI/runtime agreement;
- deterministic generated TypeScript;
- canonical test discovery;
- packaging;
- no SQLite fallback;
- no orphan DoD tests.

---

# 150. Review Gate — Scope

Verify no premature:

```text
Epic 12 intelligence metrics
supplier/broker performance
market benchmark
email/SMS/push
search cluster
AI/vector search
generic workflow automation
Jira-like project management
```

implementation.

---

# 151. Epic Definition of Done

Epic 11 is complete when:

```text
Operator can add private Internal Notes
important mutations produce immutable Audit Events
users receive correct in-app Notifications
Notification Center manages read state safely
Operators manage internal Tasks
authorized users globally search core resources
list surfaces use reusable validated Advanced Filters
```

while proving:

```text
customer privacy
server-derived actors
append-only audit history
notification idempotency
operator-only internal tooling
authorization-before-search
filter safety
PostgreSQL-native sufficiency
```

---

# 152. Long-term Contract

After Epic 11:

```text
InternalNote
= private human operational context

AuditEvent
= immutable evidence of important mutation

Notification
= per-user in-app awareness

OperatorTask
= internal work coordination

GlobalSearch
= authorization-aware navigation

FilterSet Infrastructure
= explicit reusable query narrowing
```

Epic 12 may aggregate domain facts for analytics but must not reinterpret Notification/Task/Note records as commercial truth.

---

# 153. Final Architectural Statement

> **Operational tooling must make the platform easier to operate without becoming a second domain model. Notes are private context, Audit is immutable evidence, Notifications create awareness, Tasks coordinate internal work, Search navigates only what the actor may already see, and Filters may only narrow authorized querysets.**

The resulting Epic 11 foundation must be:

```text
Private
Explicit
Append-oriented
Authorization-aware
Idempotent
Search-safe
Filter-safe
PostgreSQL-native
Low-coupling
Operationally useful
```
