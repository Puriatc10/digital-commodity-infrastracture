# Epic 8 — Offers, Procurement & Negotiation

## Design Contract, Domain Invariants & Delivery Requirements

**Status:** Owner-approved design contract for Epic 8 implementation  
**Target path:** `docs/product/epic-08-offers-procurement-design-contract.md`  
**Priority:** P0

---

# 1. Objective

Epic 8 turns discovered/matched supply into a real procurement negotiation workflow:

```text
RFQ
→ Offer
→ Offer Versions
→ Normalisation
→ Comparison
→ Revision
→ Revised Offer
→ Explainable Decision Support
→ Human Award
```

The Epic must preserve commercial history, counterparty provenance, and exact versions of every submitted commercial proposal.

The output of Epic 8 is a finalized `Award`, not a `Deal`. Deal creation and immutable Deal terms belong to Epic 9.

---

# 2. Existing Architectural Contracts

Epic 8 must preserve these existing invariants:

- Organization capabilities are Buyer / Supplier / Broker.
- System roles are Operator / Admin.
- Product authorization is independent of Django staff/superuser.
- PostgreSQL is authoritative.
- REST → OpenAPI → generated TypeScript remains the API contract path.
- Commodity-specific properties remain dynamic and schema-bound.
- Historical records keep their original CommoditySchemaVersion.
- `Trader` is forbidden vocabulary; use `Broker`.
- ExternalCounterparty must not require a fake User or Organization.
- Matching remains separate from procurement decision support.

---

# 3. Product Boundary

Epic 8 answers:

> Given real commercial proposals submitted against one RFQ, how do we compare, revise, recommend, and award them?

Epic 8 does **not** perform supplier discovery. That is Epic 7 Matching.

Epic 8 does **not** create or execute Deals. That begins in Epic 9.

---

# 4. Frozen v1 Policies

## P1 — Offer Target

An Offer targets exactly one RFQ.

```text
Offer → RFQ
```

Supply Listings and Opportunities may be source/provenance context, but are not Offer targets.

---

## P2 — Economic Party and Entering Actor Are Different

Economic party may be:

```text
Supplier Organization
Broker Organization
ExternalCounterparty (Operator-entered only)
```

Entering actor may be:

```text
Supplier/Broker member
Operator
Product Admin
```

The system preserves both concepts independently.

---

## P3 — Offer Parent + Immutable OfferVersions

`Offer` is the stable negotiation identity.

`OfferVersion` is the immutable commercial snapshot.

```text
Offer
├── V1
├── V2
└── V3
```

A submitted version is never overwritten. Any commercial change produces a new version.

---

## P4 — One Offer Thread per Party / RFQ / Role

For v1:

```text
RFQ + economic party + offeror role
→ one Offer parent
```

Parallel alternative Offer trees are out of scope. Alternatives are represented through revisions in v1.

---

## P5 — Partial Quantity Is Allowed

A Supplier/Broker may offer less than the RFQ quantity.

```text
RFQ:   1000 MT
Offer:  400 MT
```

is valid.

An Offer may also exceed requested quantity. Surplus receives no score bonus.

Quantity coverage:

```text
min(offered_quantity / requested_quantity, 1.0)
```

---

## P6 — Manual Multi-Award Is Supported

A finalized Award may contain multiple allocations:

```text
RFQ: 1000 MT

A V2 → 400 MT
B V1 → 350 MT
C V3 → 250 MT
```

The Buyer selects these manually.

Epic 8 does **not** implement a portfolio/composite optimizer.

---

## P7 — Preserve Original Currency; No Automatic FX

Every OfferVersion keeps its submitted currency.

No automatic FX conversion, feed, inferred rate, or cross-currency landed-cost ranking exists in v1.

Cross-currency cost comparison is `UNKNOWN` unless a future explicit FX snapshot feature is introduced.

---

## P8 — Missing Cost Is Not Zero

Unknown logistics or other missing cost information must remain unknown.

The system must distinguish where relevant:

```text
KNOWN
INCLUDED_IN_PRICE
NOT_APPLICABLE
UNKNOWN
```

No missing monetary input may silently become zero.

---

## P9 — Offer Uses the Exact RFQ Schema Version

OfferVersion specifications use the same CommoditySchemaVersion as the RFQ.

Never use today's active schema.

No supplier-selected alternate schema is allowed in v1.

---

## P10 — Strict Offer Privacy

Buyer-side authorized actors may see competing Offers on their own RFQ.

Supplier/Broker participants may see only their own Offer thread, versions, and revision requests.

They must not see competitor:

- identity
- price
- quantity
- version history
- rank
- decision score
- recommendation
- award deliberation

Backend authorization/projections enforce this.

---

## P11 — Revision Request Produces a New Version

```text
V1
→ RevisionRequest
→ V2 Draft
→ V2 Submitted
```

The RevisionRequest never modifies V1.

---

## P12 — Explainable, Human-controlled Decision Support

Initial decision weights:

```text
Cost / Landed Cost              35%
Specification / Quality Fit     25%
Delivery                        15%
Payment Terms                   10%
Trust / Verification            10%
Commercial Completeness          5%
                                ----
                                100%
```

Recommendation never automatically awards.

Weights and thresholds are versioned policy data.

---

# 5. Domain Model

Recommended aggregate structure:

```text
RFQ
 │
 └── Offer
      ├── OfferVersion
      │    └── OfferCostComponent
      ├── RevisionRequest
      └── provenance

RFQ
 ├── DecisionRun
 │    ├── DecisionCandidate
 │    └── DecisionSignal
 └── Award
      └── AwardAllocation
```

---

# 6. Offer

Conceptual fields:

```text
id
rfq_id
offeror_role
offering_organization_id?
external_counterparty_id?
source_opportunity_id?
current_submitted_version_id?
aggregate_version
created_by
created_at
updated_at
```

`offeror_role`:

```text
SUPPLIER
BROKER
```

Internal Organization validation:

- Supplier role requires Supplier capability.
- Broker role requires Broker capability.
- Multi-capability Organization is valid.

ExternalCounterparty path is Operator/Admin-only.

---

# 7. Exactly-one Economic Party

Exactly one must exist:

```text
offering_organization
external_counterparty
```

Never both. Never neither.

Prefer a PostgreSQL CheckConstraint.

---

# 8. One Offer Parent per RFQ/Party/Role

Protect structurally:

```text
unique(rfq, offering_organization, offeror_role)
```

and conditional equivalent for ExternalCounterparty.

Do not rely only on unlocked service checks.

---

# 9. OfferVersion

Conceptual fields:

```text
id
offer_id
version_number
schema_version_id
specifications JSONB

offered_quantity
quantity_unit

unit_price
currency

payment_terms
delivery_terms
incoterm
delivery_start
delivery_end
valid_until

logistics_cost_status
logistics_cost_amount?

notes

submitted_by
submitted_at
created_at
```

Reuse existing RFQ commercial semantics where available instead of creating incompatible duplicate concepts.

---

# 10. OfferVersion Lifecycle

Only:

```text
DRAFT
SUBMITTED
```

Draft:
- editable by authorized actor;
- not commercial truth yet.

Submitted:
- immutable;
- historical;
- no normal PATCH/DELETE.

Do not add mutable `SUPERSEDED`; derive it from later submitted versions.

---

# 11. At Most One Draft per Offer

There may be at most one unsubmitted OfferVersion for an Offer.

Prefer a PostgreSQL conditional unique constraint.

---

# 12. Version Allocation

Server allocates:

```text
V1
V2
V3
...
```

Transaction:

```text
lock Offer
→ determine latest authoritative version
→ allocate next number
→ create version
```

Never use unsafe `COUNT()+1`.

DB unique:

```text
(offer, version_number)
```

Real PostgreSQL concurrency tests are mandatory.

---

# 13. Submitted Immutability

After submission, semantic mutation is forbidden for:

- quantity
- price
- currency
- specifications
- payment
- delivery
- incoterm
- validity
- cost components
- commercial notes

Correction means new OfferVersion.

Protection must exist beyond serializer conventions.

---

# 14. RFQ Lifecycle Integration

Expected operational path:

```text
Published
→ Collecting Offers
→ Negotiating
→ Awarded
```

Rules:

- Offer submission allowed in Published / Collecting Offers.
- First successful submitted Offer may move Published → Collecting Offers.
- Revision activity may move RFQ to Negotiating.
- Finalized Award moves RFQ → Awarded.
- Closed / Cancelled / Awarded reject new submissions/revisions.

Use authoritative RFQ lifecycle services.

---

# 15. Submission Deadline

If the RFQ submission deadline has passed, submission rejects by default.

No silent Operator override.

Any future late-submission override must be explicit and auditable.

---

# 16. Internal Supplier/Broker Submission

Submission requires:

1. authenticated user;
2. active membership in offeror Organization;
3. allowed membership role;
4. required Organization capability;
5. RFQ participation/visibility eligibility;
6. RFQ currently accepting Offers.

Recommended v1 operational role policy:

```text
Owner   → submit
Manager → submit
Member  → submit
Viewer  → read only
```

Capabilities never grant authorization by themselves.

---

# 17. Private RFQ Participation

For Private RFQs, only invited eligible Organizations may submit.

For Network/Public, reuse Epic 5 authoritative visibility/participation policy.

Offer submission must never broaden RFQ visibility.

---

# 18. Operator Submission on Behalf

Operator/Admin may enter an external supplier quote.

Required provenance:

```text
external_counterparty
source_opportunity
submitted_by / entered_by
entered_by_operator = true
```

For v1, external Offer submission must be tied to a Qualified Supply Opportunity.

Validate:

```text
Opportunity.direction = SUPPLY
Opportunity counterparty = external_counterparty
Opportunity state permits Offer conversion/submission
```

Never create fake User/Organization.

This becomes the correct foundation for deferred T0611.

---

# 19. Broker Offer

An internal Broker Organization may submit its own Offer when:

- it has Broker capability;
- actor has permitted membership;
- RFQ participation rules permit submission.

Do not rewrite Broker as Supplier.

---

# 20. Opportunity Provenance

If Opportunity sourced the Offer, the link must be durable and bidirectionally queryable.

Preserve:

- Opportunity identifier
- source
- Broker attribution
- external counterparty
- Operator actor

Buyer-facing projection must not leak private sourcing/contact details by default.

---

# 21. Dynamic Commodity Specifications

OfferVersion stores:

```text
schema_version_id
specifications JSONB
```

Schema version must equal RFQ schema version.

Use the generic commodity validator.

No commodity-specific fields or validators.

---

# 22. Schema Validity vs RFQ Compliance

Two separate concepts:

```text
Schema Valid?
RFQ Compliant?
```

Schema validity is required to submit.

RFQ compliance may be:

```text
PASS
FAIL
UNKNOWN
```

A valid but technically non-compliant Offer may remain visible for negotiation, but is not award-eligible by default.

A revised version may become compliant.

---

# 23. Quantity Semantics

Require positive quantity.

Allowed:

```text
partial
exact
surplus
```

Expose:

```text
quantity_coverage
surplus_quantity
```

Surplus gets no bonus.

---

# 24. Unit Compatibility

No unit conversion engine in Epic 8.

Offer quantity unit must match or be directly compatible under already-existing canonical trade-unit semantics.

Otherwise reject with controlled validation error.

---

# 25. Monetary Precision

All financial values use Decimal-backed database fields and Decimal arithmetic.

Never use binary floating point.

---

# 26. Original Currency Is Immutable Commercial Truth

Submitted price/currency remain exactly as submitted.

Normalised/derived values are separate.

---

# 27. OfferCostComponent

Recommended child entity:

```text
OfferCostComponent
```

Fields:

```text
offer_version
kind
amount
currency
description?
```

Kinds v1:

```text
LOGISTICS
OTHER
```

All components must use OfferVersion currency.

No mixed-currency cost basket.

---

# 28. Logistics Status

Allowed:

```text
KNOWN_SEPARATE
INCLUDED_IN_PRICE
NOT_APPLICABLE
UNKNOWN
```

Rules:

- KNOWN_SEPARATE requires amount.
- INCLUDED_IN_PRICE contributes zero extra but is known.
- NOT_APPLICABLE contributes zero extra but is known.
- UNKNOWN is never zero.

---

# 29. Product Cost

Derived:

```text
product_cost =
unit_price × offered_quantity
```

using Decimal arithmetic.

---

# 30. Known Cost Total

```text
known_cost_total =
product_cost
+ known separate logistics
+ sum(other known components)
```

This is not automatically a complete landed cost.

---

# 31. Landed Cost

Only when logistics is sufficiently known:

```text
landed_cost =
product_cost
+ logistics_addition
+ other_known_costs
```

The system must not imply every possible real-world incidental cost is known.

---

# 32. Landed Unit Cost

For comparison of partial Offers:

```text
landed_unit_cost =
landed_cost / offered_quantity
```

when landed cost is complete.

Use unit cost rather than total cost for ranking different quantities.

---

# 33. Normalisation Output

Structured output:

```text
product_cost
known_cost_total
landed_cost?
landed_unit_cost?
normalization_complete
missing_components[]
currency
policy_version
```

No external market data.

---

# 34. Normalisation Is Derived

Never mutate OfferVersion with "normalized truth".

If snapshots are persisted, record exact input OfferVersion and policy version.

---

# 35. Comparison Universe

Current comparison uses only each Offer's current submitted version.

Historical versions remain available in negotiation history.

They are not separate current competing rows.

---

# 36. Comparison API

Buyer/Operator comparison includes safe fields:

```text
offer id
offer version
safe offeror identity
offeror role
quantity / coverage
unit price / currency
product cost
known cost total
landed cost
landed unit cost
payment
delivery
quality/spec compliance
verification/trust
normalisation completeness
revision state
```

No private Opportunity notes/contact details.

---

# 37. Cross-currency Comparison

Different currencies may coexist.

Display original prices.

Cost signal becomes `UNKNOWN` when there is no common supported currency context.

Never invent FX.

---

# 38. Decision Support Pipeline

```text
Current submitted OfferVersions
→ normalised commercial facts
→ Decision Signal Providers
→ Decision Scoring
→ immutable DecisionRun
→ explainable recommendation
```

---

# 39. DecisionProfile

Use immutable/versioned decision policy.

Initial weights:

```text
COST           35
QUALITY        25
DELIVERY       15
PAYMENT        10
TRUST          10
COMPLETENESS    5
```

Published policy versions cannot be edited in place.

---

# 40. Decision Signal Statuses

Each signal returns:

```text
PASS
PARTIAL
FAIL
UNKNOWN
NOT_APPLICABLE
```

plus structured:

```text
score
weight
reason_code
expected_value?
actual_value?
snapshot_data
```

Do not store only Persian/English explanation strings.

---

# 41. Cost Signal

When same-currency landed unit costs are known:

```text
cost_score = best_cost / candidate_cost
```

bounded `[0,1]`.

Best cost = 1.0.

If landed unit cost unknown, cost signal = `UNKNOWN`.

Do not silently substitute headline price.

---

# 42. Quality Signal

Use generic RFQ-vs-Offer technical compatibility.

Hard RFQ requirement failure:

```text
FAIL
award_eligible = false
```

Unknown requirement:

```text
UNKNOWN
```

No Bitumen-specific scoring branch.

---

# 43. Delivery Signal

Use structured delivery windows/constraints.

Examples:

```text
full satisfaction → 1.0
partial overlap   → partial
hard incompatibility → FAIL
unknown           → UNKNOWN
```

No route/freight inference.

---

# 44. Payment Signal

Only score structured comparable payment fields.

If existing terms are free-text/insufficiently structured:

```text
PAYMENT = UNKNOWN
```

No heuristic NLP parsing in v1.

---

# 45. Trust Signal

Internal Organization mapping:

```text
Verified             1.00
Basic Verified       0.70
Under Review         0.30
Documents Submitted  0.15
Unverified           0.00
Suspended            NOT AWARD-ELIGIBLE
```

ExternalCounterparty:

```text
UNKNOWN
```

unless explicit evidence exists.

DecisionRun snapshots the trust state it used.

---

# 46. Completeness Signal

Commercial completeness reflects presence of decision-critical data, e.g.:

- cost completeness
- delivery data
- payment structure
- valid technical payload
- validity date where required

Do not reward verbosity.

---

# 47. Decision Score Math

Let:

```text
A = total applicable weight
K = total known weight
C = Σ(weight × score) for known signals
```

Then:

```text
DecisionScore = (C / K) × 100
```

Unknown never means 0.5 or 1.0.

---

# 48. Evidence Coverage

```text
EvidenceCoverage = (K / A) × 100
```

This expresses how much of the policy could actually be evaluated.

---

# 49. Effective Score

Ranking uses:

```text
EffectiveScore =
DecisionScore × EvidenceCoverage / 100
```

Store all three independently.

---

# 50. Recommendation Threshold

Default v1:

```text
minimum coverage = 70%
```

This belongs to DecisionProfile version.

No "Recommended" label when:

- coverage below threshold;
- hard quality failure;
- Suspended offeror;
- Offer otherwise not award-eligible.

Because cost weight is 35%, an otherwise fully-known cross-currency Offer with UNKNOWN cost can reach at most 65% coverage and therefore cannot receive a misleading recommendation.

---

# 51. Recommendation Semantics

Recommendation means:

> highest EffectiveScore among current award-eligible OfferVersions with sufficient coverage.

It is not probability, guarantee, or automatic decision.

UI must show:

```text
Decision Score
Evidence Coverage
Why
Missing evidence
Risks
Policy version
```

---

# 52. DecisionRun

Immutable snapshot:

```text
rfq
decision_profile_version
engine_version
created_by
created_at
input_fingerprint
```

It evaluates exact OfferVersion IDs, never vague mutable current state.

---

# 53. DecisionCandidate

Fields:

```text
decision_run
offer
offer_version
decision_score
evidence_coverage
effective_score
award_eligible
rank
```

Unique per `(decision_run, offer_version)`.

---

# 54. DecisionSignal

Fields:

```text
decision_candidate
code
status
weight
raw_score?
contribution?
expected_value?
actual_value?
reason_code
snapshot_data
```

Immutable.

---

# 55. Deterministic Ranking

Same:

```text
RFQ snapshot
OfferVersion snapshots
DecisionProfileVersion
EngineVersion
```

must produce same result.

Tie-break:

```text
effective_score DESC
evidence_coverage DESC
decision_score DESC
stable_offer_key ASC
```

---

# 56. RevisionRequest

Fields:

```text
id
offer
base_offer_version
requested_fields
message
requested_by
requested_at
status
resolved_by_version?
resolved_at?
```

Statuses:

```text
OPEN
RESOLVED
DECLINED
CANCELLED
```

---

# 57. Revision Permissions

Buyer-side authorized procurement actors, Operator, Product Admin may request revisions.

Supplier/Broker cannot issue Buyer revision requests to itself.

Use existing RFQ organization-action role conventions rather than inventing inconsistent permissions.

---

# 58. Revision Concurrency

Require `expected_version`.

Transaction:

```text
lock Offer
→ verify version
→ verify current submitted version
→ create request
→ increment aggregate version
```

No revision request against stale commercial state.

---

# 59. One Open Revision per Offer

v1 allows at most one `OPEN` RevisionRequest per Offer.

Prefer a conditional unique constraint.

---

# 60. Revised Offer Flow

```text
lock Offer
→ verify open RevisionRequest/base version
→ create next Draft copied from current version
→ edit
→ submit
→ resolve RevisionRequest with new version
→ commit atomically
```

V1 remains unchanged.

---

# 61. Negotiation History

Must reconstruct:

```text
V1 Submitted
→ RevisionRequest
→ V2 Submitted
→ RevisionRequest
→ V3 Submitted
```

with actors/timestamps and exact immutable snapshots.

---

# 62. Offer Withdrawal

Do not invent broad withdrawal workflows unless existing Product Specification requires them.

Keep v1 focused on submission, revision, comparison, and award.

---

# 63. Award

One procurement decision aggregate per RFQ.

Fields:

```text
id
rfq
status
version
created_by
created_at
finalized_by?
finalized_at?
```

Statuses:

```text
DRAFT
FINALIZED
```

---

# 64. AwardAllocation

Fields:

```text
award
offer
offer_version
awarded_quantity
quantity_unit
created_at
```

Allocation references exact selected submitted OfferVersion.

---

# 65. Award Quantity Rules

Per allocation:

```text
0 < awarded_quantity <= offer_version.offered_quantity
```

Across finalized Award:

```text
sum(awarded_quantity)
<= RFQ requested_quantity
```

No over-procurement in v1.

---

# 66. Allocation Uniqueness

Unique:

```text
(award, offer_version)
```

No duplicate row for the same commercial snapshot.

---

# 67. Award Eligibility

Selected OfferVersion must:

- belong to the Award RFQ;
- be submitted;
- be current submitted version at finalization;
- meet technical award eligibility;
- not be expired where validity applies;
- not come from Suspended Organization;
- have valid external provenance if external.

---

# 68. Finalize Award Atomically

```text
lock RFQ
lock Award
lock selected Offers
validate versions/current state
validate allocations
validate total quantity
re-check award eligibility
freeze Award
transition RFQ → Awarded
commit
```

Failure leaves no partial finalization.

---

# 69. Finalized Award Is Immutable

After `FINALIZED`:

- no allocation edit/delete;
- no selected-version change;
- no quantity change.

No post-award amendment workflow in Epic 8.

---

# 70. Award vs Deal

Epic 8 stops at Award.

Epic 9 consumes finalized Award/Allocations and creates Deal snapshot(s).

Do not create Deal rows in Epic 8.

---

# 71. Multi-Award Is Not Matching Optimization

Manual allocation across Offers is allowed.

Epic 8 does not generate the optimal combination of A+B+C.

That remains future matching/procurement optimization work.

---

# 72. Privacy Projections

Buyer comparison projection and Supplier/Broker own-thread projection must be separate.

Do not fetch all data then hide competitors in React.

---

# 73. Operator Visibility

Operator/Admin may see internal provenance required for operations.

Buyer must not automatically receive:

- external phone/email
- contact attempt history
- Operator notes
- unapproved internal broker attribution details

---

# 74. Session/Persona Isolation

On persona/org switch:

- Offers invalidate
- comparison invalidates
- DecisionRuns invalidate
- negotiation history invalidates
- Award UI invalidates
- old in-flight responses cannot restore previous actor's private data

---

# 75. API Action Style

Prefer explicit actions:

```text
create Offer
create/update draft
submit version
request revision
submit revised version
run decision
create/update draft Award
finalize Award
```

No generic status PATCH.

---

# 76. Optimistic Concurrency

Use `expected_version` for existing aggregate mutations.

Reject missing/null/stale according to repository conventions.

Use PostgreSQL row locking.

---

# 77. Mandatory Submission Race Test

Two simultaneous submit requests for one draft:

```text
exactly one succeeds
```

No duplicate submission/current-pointer corruption.

---

# 78. Mandatory Revision Race Tests

Test:

```text
revision request vs new version submission
revision request vs revision request
```

One authoritative outcome.

---

# 79. Mandatory Award Race Tests

Test:

```text
finalize vs finalize
finalize vs revised version
finalize vs RFQ cancellation
```

No mixed final state.

---

# 80. DecisionRun Staleness

DecisionRun remains historically valid even if V2 is submitted later.

UI must detect:

```text
run evaluated V1
current is V2
```

and not show old recommendation as current.

---

# 81. Conceptual API Surface

Exact routes follow repository conventions.

```text
POST /rfqs/{rfq}/offers/
GET  /rfqs/{rfq}/offers/

GET  /offers/{offer}/
POST /offers/{offer}/versions/
PATCH /offer-versions/{version}/          # draft only
POST /offer-versions/{version}/submit/

POST /offers/{offer}/revision-requests/
POST /revision-requests/{id}/decline/
POST /revision-requests/{id}/cancel/

GET  /rfqs/{rfq}/comparison/
POST /rfqs/{rfq}/decision-runs/
GET  /decision-runs/{id}/

POST /rfqs/{rfq}/awards/
POST /awards/{award}/allocations/
POST /awards/{award}/finalize/
```

---

# 82. Operator-on-Behalf Contract

Use an explicit request contract.

Server derives actor identity.

Client cannot spoof:

```text
entered_by
submitted_by
operator identity
```

---

# 83. Mass Assignment Protection

Client cannot set:

- current submitted version pointer
- aggregate version
- version number
- submitted actor/time
- Decision scores/rank/recommendation
- Award finalized actor/time
- unrelated source Opportunity

---

# 84. OpenAPI Accuracy

Document all mutations, stale conflicts, immutability failures, authorization, incomplete normalisation, and recommendation absence accurately.

Do not compensate for bad schema with frontend casts.

---

# 85. Generated Client

No handwritten duplicate Offer DTOs.

Repeated TypeScript generation must be deterministic and drift-free.

---

# 86. Comparison UI

At minimum:

```text
Offeror
Version
Headline Unit Price
Currency
Quantity
Coverage
Known/Landed Unit Cost
Payment
Delivery
Quality Fit
Trust
Evidence Coverage
```

---

# 87. Unknown UI Semantics

Render unknown explicitly.

Never use `0` for missing.

Distinguish:

```text
Unknown
Included
Not applicable
Known zero
```

---

# 88. Recommendation UI

Show:

```text
Recommended under current policy
Decision Score
Evidence Coverage
Positive factors
Risks
Missing evidence
Policy version
```

Never claim probability or guaranteed outcome.

---

# 89. Negotiation UI

Show immutable timeline and structured version differences.

Do not diff localized display strings; diff canonical structured fields.

---

# 90. Persian/RTL

All demo-facing Epic 8 UI is Persian/RTL and localization-ready.

Canonical enums remain machine values internally.

---

# 91. Domain Auditability

Without implementing generic Epic 11 Audit Trail, commercial history inherently stores:

- who submitted version
- submission time
- who requested revision
- base version
- resolving version
- who finalized Award
- exact selected versions/quantities

---

# 92. Historical Integrity

The system must reconstruct exactly:

```text
V1 → Revision → V2 → DecisionRun → Award
```

even after later Organization verification or other mutable platform state changes.

---

# 93. Verification Changes

Old DecisionRun keeps its captured trust state.

Award finalization re-checks current eligibility.

A currently Suspended organization cannot be awarded because an old DecisionRun was favorable.

---

# 94. Offer Validity

Expired OfferVersion remains historical but is not award-eligible.

No scheduler is required; expiry can be derived at action/read time.

---

# 95. Human May Ignore Recommendation

Buyer may Award a different eligible Offer than the recommendation.

System preserves recommendation vs actual Award.

Human agency is intentional.

---

# 96. No Automatic Revision

Decision Support may identify weaknesses but never sends RevisionRequest automatically.

---

# 97. No Automatic Award

No score or recommendation can trigger Award.

---

# 98. No AI Requirement

No LLM/ML is needed for core Epic 8 behavior.

No free-text parsing should become source of commercial truth.

---

# 99. No New Infrastructure

No Kafka, RabbitMQ, Redis, Elasticsearch, Temporal, vector DB, or new microservice.

Django modular monolith + PostgreSQL is enough.

---

# 100. Explicit Non-goals

Do not implement:

```text
Deal
Deal attribution
Execution
Payment movement
Settlement
Escrow
Financing
Insurance
Dynamic freight pricing
Carrier booking
FX feed
AI recommendation
Automatic negotiation
Automatic revision
Automatic award
Composite matching optimizer
Portfolio award optimizer
Generic chat
Generic contract editor
Generic workflow builder
```

---

# 101. PostgreSQL Integrity

Use DB constraints for structural invariants where practical:

- exactly one economic party
- one Offer thread per party/RFQ/role
- unique version number
- one draft per Offer
- valid enum values
- positive quantity/prices
- logistics-status consistency
- unique Award allocation

Cross-table semantic guards remain domain services where appropriate.

---

# 102. Required Task Test Themes

## T0801
- party exclusivity
- Supplier/Broker capability
- external provenance
- duplicate thread rejection
- authorization

## T0802
- V1/V2 allocation
- one draft
- submitted immutability
- concurrent numbering
- schema lock

## T0803
- membership/capability
- private invitation policy
- deadline
- stale submit
- submit race

## T0804
- Qualified Supply Opportunity → external Offer
- no fake identity
- source/Broker traceability
- spoof resistance

## T0805
- Decimal calculations
- logistics statuses
- unknown != zero
- landed unit cost
- deterministic normalisation

## T0806
- current versions only
- same-currency comparison
- cross-currency incomparability
- privacy projections

## T0808/T0809
- exact weights
- signal math
- score/coverage/effective score
- 70% threshold
- quality failure
- Suspended exclusion
- no misleading cross-currency recommendation
- deterministic ranking

## T0810/T0811
- stale base rejection
- one open request
- V2 resolution atomicity
- V1 unchanged
- concurrency

## T0812
- immutable history
- structured diff
- participant privacy
- cache/persona isolation

## T0813
- single/multi Award
- no over-allocation
- exact OfferVersion
- expiry/suspension/compliance checks
- finalization races
- finalized immutability
- no Deal creation

---

# 103. CI Rules

All backend tests must be discovered by:

```text
python manage.py test
```

against PostgreSQL.

Frontend tests must be reachable from existing canonical npm test commands.

Contract generation remains authoritative.

No Definition-of-Done automated test may be orphaned unless explicitly Review-Gate-only.

---

# 104. Migration & Packaging

Every relevant Task verifies:

- fresh PostgreSQL migrations
- migration drift
- upgrade from pre-Epic-8 state
- built wheel/sdist includes new modules/migrations
- no SQLite fallback

Do not invent historical commercial data during migrations.

---

# 105. Recommended Sequential Execution Order

```text
1. T0801 — Offer Domain Model
2. T0802 — Offer Version Model
3. T0803 — Supplier/Broker Offer Submission
4. T0804 — Operator Submission on Behalf
5. T0805 — Offer Normalisation Engine
6. T0806 — Comparison API
7. T0808 — Decision Support Model
8. T0809 — Explainable Recommendation
9. T0810 — Request Revision
10. T0811 — Revised Offer
11. T0807 — Comparison UI
12. T0812 — Negotiation History UI
13. T0813 — Award Offer
14. Epic 8 Adversarial Review Gate
```

Backend truth precedes UI; Award is last.

---

# 106. Required Hero Flow

```text
Buyer publishes RFQ
→ Supplier Offer V1
→ Broker Offer V1
→ Operator enters external Offer from Qualified Supply Opportunity
→ Normalise
→ Compare
→ DecisionRun
→ Explain recommendation
→ RevisionRequest
→ V2 submitted
→ old DecisionRun becomes historical/stale
→ re-run Decision
→ Buyer prepares multi-allocation Award
→ finalize Award
→ RFQ becomes Awarded
```

No direct DB manipulation.

---

# 107. Pilot-critical External Flow

```text
Broker Referral
→ External Supplier Opportunity
→ Qualified
→ Operator receives external quote
→ Offer on RFQ
→ entered_by_operator traceable
→ source Opportunity traceable
→ Buyer sees safe commercial Offer
→ private external contact/sourcing data remains hidden
→ comparison/revision/award
```

---

# 108. Architecture Failure Conditions

Epic 8 fails architecturally if any of these are required:

```text
mutate Submitted OfferVersion
missing cost → zero
implicit FX rate
participant reads competitor Offer
external quote requires fake Organization/User
Offer uses current active schema instead of RFQ schema
recommendation without structured explanation
Award references only mutable Offer parent
hidden magic Decision score
commodity-specific generic branch
```

---

# 109. Epic 8 Adversarial Review Gate

The final Gate must attack:

### Domain
- exactly-one party
- duplicate Offer thread
- version races
- immutability
- external provenance

### Commercial
- Decimal math
- cost UNKNOWN semantics
- same/cross currency
- partial quantity

### Privacy
- competitor IDOR
- participant projections
- Buyer/internal provenance leakage
- persona/cache race

### Decision
- exact policy version
- score/coverage math
- minimum coverage
- hard failures
- Suspended eligibility
- deterministic ranking
- stale run behavior

### Revision
- stale requests
- one open request
- atomic V2
- immutable V1

### Award
- multi-allocation
- no over-allocation
- exact current OfferVersion
- eligibility re-check
- concurrency
- finalized immutability
- no Deal creation

### Platform
- PostgreSQL migrations
- canonical CI reachability
- OpenAPI correctness
- generated TS drift
- packaging
- Persian/RTL
- no scope leakage

---

# 110. Definition of Done

Epic 8 is complete only when the supported product path can execute:

```text
RFQ
→ V1 Offers
→ external Operator-entered Offer
→ normalized comparison
→ explainable DecisionRun
→ RevisionRequest
→ V2
→ historical V1 retained
→ updated comparison
→ human multi-award
→ immutable finalized Award
```

while proving:

```text
commercial provenance
version immutability
competitor privacy
dynamic commodity correctness
missing-data honesty
currency honesty
concurrency safety
human-controlled decision making
```

---

# 111. Long-term Contract

After Epic 8:

```text
Offer
= stable negotiation identity

OfferVersion
= immutable commercial truth

DecisionRun
= immutable policy-based procurement analysis

Award
= explicit human procurement decision

Deal
= future immutable post-award commercial/execution entity
```

Later Epics must preserve these boundaries.

---

# 112. Final Architectural Statement

> Commercial proposals are immutable versioned facts. Comparison and scoring are derived, versioned and explainable. Missing information remains explicit. External supply can participate without fake platform identity. Buyers retain final decision authority. A finalized Award references the exact commercial versions selected.

The resulting architecture must be:

```text
Auditable
Deterministic
Privacy-preserving
Multi-party
External-counterparty compatible
Partial-quantity compatible
Multi-award ready
Commodity-agnostic
Historically reproducible
```
