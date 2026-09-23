# Epic 9 — Deal & Attribution

## Design Contract, Domain Invariants & Delivery Requirements

**Status:** Owner-approved design contract for Epic 9 implementation  
**Target path:** `docs/product/epic-09-deal-attribution-design-contract.md`  
**Epic:** Epic 9 — Deal & Attribution  
**Priority:** P0

---

# 1. Objective

Epic 9 converts a finalized procurement Award into immutable commercial Deal records with durable source attribution.

The core flow is:

```text
Finalized Award
    ↓
Award Allocation(s)
    ↓
Deal Materialization
    ↓
Immutable Deal Terms Snapshot
    ↓
Immutable Party Snapshot
    ↓
Attribution Resolution
    ↓
Broker / Opportunity Provenance
    ↓
Deal Workspace
```

Epic 9 creates the commercial truth that later execution monitoring operates on.

It does not execute logistics, payment, inspection, or settlement.

---

# 2. Roadmap Scope

Epic 9 covers:

```text
T0901 — Deal Creation
T0902 — Deal Terms Snapshot
T0903 — Deal Attribution
T0904 — Broker Attribution
T0905 — Deal Workspace UI
```

The required roadmap behavior is:

- Award creates the initial immutable commercial snapshot.
- Deal terms include quantity, price, specifications, payment, delivery, and counterparties.
- Later RFQ changes must not change the Deal.
- Attribution tracks:
  - Platform Network
  - Direct Supplier
  - Broker
  - Opportunity Desk
  - Buyer Existing Supplier
- Broker attribution supports:
  - Supply Originator
  - Demand Originator
  - Related Opportunity
- Deal Workspace exposes:
  - Overview
  - Terms
  - Parties
  - Attribution
  - Execution
  - Logistics
  - Quality
  - Documents
  - Issues
  - Activity

This contract defines the detailed implementation semantics for those requirements.

---

# 3. Existing Architectural Contracts

Epic 9 must preserve all earlier invariants:

- PostgreSQL is the source of truth.
- Django remains a modular monolith.
- REST → OpenAPI → generated TypeScript is authoritative.
- Organization capabilities are Buyer / Supplier / Broker.
- System roles are Operator / Admin.
- Django staff/superuser grant no Product authorization.
- ExternalCounterparty never requires a fake User or Organization.
- Commodity-specific technical data remains schema-bound JSONB.
- Historical records retain their original CommoditySchemaVersion.
- Submitted OfferVersions are immutable.
- Finalized Awards and AwardAllocations are immutable.
- An AwardAllocation references the exact selected OfferVersion.
- Multi-Award is supported manually.
- `Trader` is forbidden vocabulary; use `Broker`.

---

# 4. Core Boundary

Epic 8 ended with:

```text
Human Procurement Decision
→ Finalized Award
→ exact AwardAllocation(s)
```

Epic 9 begins with:

```text
Finalized AwardAllocation
→ immutable Deal
```

Epic 10 begins with:

```text
Deal
→ execution milestones
→ logistics
→ quality
→ payment monitoring
→ issues
```

This boundary must remain explicit.

---

# 5. Frozen v1 Policy — One AwardAllocation Creates One Deal

This is the most important Deal cardinality rule.

```text
1 AwardAllocation
→ exactly 1 Deal
```

Therefore:

```text
Award:
A V2 → 400 MT
B V1 → 350 MT
C V3 → 250 MT
```

materializes into:

```text
Deal A → 400 MT with Counterparty A
Deal B → 350 MT with Counterparty B
Deal C → 250 MT with Counterparty C
```

Do NOT create one multi-party Deal containing all three suppliers.

Reason:

- each allocation may have a different counterparty;
- different price/payment/delivery terms may apply;
- logistics and quality execution will diverge;
- payment monitoring will diverge;
- issues/disputes may diverge;
- Epic 10 needs an execution unit with one commercial counterparty.

---

# 6. Deal Identity

`Deal` is the stable identity of one awarded commercial relationship.

Conceptually:

```text
Deal
├── source Award
├── source AwardAllocation
├── source Offer
├── exact source OfferVersion
├── Buyer
├── commercial counterparty
├── DealTermsSnapshot
├── DealPartySnapshot(s)
├── DealAttribution
└── DealBrokerAttribution(s)
```

The Deal is not a mutable mirror of RFQ/Offer data.

---

# 7. Deal Materialization Source

A Deal may only be created from:

```text
FINALIZED Award
+
valid immutable AwardAllocation
```

No direct arbitrary Deal creation API for ordinary product actors.

Do not allow:

```text
POST /deals/
```

with arbitrary commercial fields.

Creation is a controlled domain action against a finalized Award.

---

# 8. Idempotent Materialization

Deal materialization must be safe to repeat.

Structural rule:

```text
AwardAllocation
→ OneToOne Deal
```

or equivalent unique constraint.

Calling materialization twice must return the same Deal(s), not duplicate them.

Never rely only on a service-level "does it exist?" check.

---

# 9. Multi-Award Materialization Is Atomic

When one Award has multiple allocations:

```text
lock Award
lock AwardAllocations
validate finalized state
validate exact OfferVersions
create all missing Deals + snapshots
commit
```

If snapshot creation fails for any allocation:

```text
no partial set of new Deals
```

is persisted for that materialization attempt.

Existing already-materialized Deals from a prior successful invocation remain intact.

---

# 10. Explicit Materialization Boundary

Recommended v1 API/action:

```text
POST /awards/{award_id}/materialize-deals/
```

The action requires a finalized Award.

This preserves module direction:

```text
Deals depend on Awards
```

rather than forcing the Award module to import Deal implementation.

The UI may call this immediately after Award finalization, but Deal creation remains an explicit, idempotent domain action.

---

# 11. Deal Is Not an Execution Lifecycle

Epic 9 does not invent execution statuses such as:

```text
Loaded
In Transit
Delivered
Accepted
```

Those belong to Epic 10.

A Deal existing means:

> a finalized awarded commercial relationship has been materialized.

Execution state is introduced later.

---

# 12. Deal Deletion Policy

Normal product APIs must not hard-delete Deals.

Deal history is commercial history.

Source commercial records that a Deal relies on must not cascade-delete the Deal.

Use `PROTECT` or equivalent historical-safe relationships where appropriate.

---

# 13. Deal Terms Snapshot

Each Deal has exactly one immutable DealTermsSnapshot.

The snapshot records the accepted commercial terms at Deal creation time.

It must remain meaningful even if source entities later change.

---

# 14. Snapshot Source

Snapshot values come from:

```text
AwardAllocation
+
exact selected OfferVersion
+
target RFQ context
+
source Offer provenance
```

AwardAllocation determines the awarded quantity.

OfferVersion determines accepted commercial terms.

RFQ provides stable demand/context facts where they are part of the Deal contract.

---

# 15. Awarded Quantity Is Authoritative

Deal quantity:

```text
deal.quantity = award_allocation.awarded_quantity
```

not:

```text
offer_version.offered_quantity
```

because an Offer may be partially awarded.

Example:

```text
Offer V2 = 700 MT
AwardAllocation = 400 MT
Deal quantity = 400 MT
```

---

# 16. Unit Price

Deal unit price is copied from the exact selected OfferVersion.

It is immutable after snapshot creation.

Use Decimal-backed storage.

Never floating point.

---

# 17. Currency

Deal currency is copied from the exact selected OfferVersion.

No automatic FX conversion.

No later DecisionRun/market rate may reinterpret Deal currency.

---

# 18. Product Cost Snapshot

Deal may deterministically snapshot:

```text
product_cost
=
unit_price × awarded_quantity
```

using Decimal arithmetic.

If stored, this is a derived immutable snapshot created at materialization time.

It must not conflict with unit price × awarded quantity.

---

# 19. Cost Components

Commercial cost components accepted in the selected OfferVersion should be snapshotted.

At minimum preserve:

- logistics cost status;
- known separate logistics amount where applicable;
- other accepted known cost components;
- currency;
- descriptions/semantic kind.

Do not point only to mutable/foreign cost rows.

---

# 20. Landed Cost Semantics

If the selected OfferVersion had a complete accepted landed-cost representation, Deal may snapshot it.

If logistics was `UNKNOWN`, the Deal must preserve that uncertainty.

Do not turn unknown cost into zero during Deal creation.

Deal materialization is not a new normalisation pass that invents information.

---

# 21. Payment Terms

Accepted payment terms are copied into DealTermsSnapshot.

Later RFQ/Offer changes must not mutate them.

If payment terms are structured, preserve their canonical structure.

Do not store only localized rendered text as the source of truth.

---

# 22. Delivery Terms

Snapshot accepted delivery semantics including applicable:

- delivery window;
- delivery terms;
- Incoterm;
- origin;
- destination;
- other structured delivery facts already present in Offer/RFQ domain.

Do not infer route, distance, freight, or customs.

---

# 23. Commodity Identity

Deal snapshot must preserve:

```text
commodity
schema_version
specifications
```

The schema version is the exact historical version attached to the selected OfferVersion/RFQ.

Never replace it with today's active schema.

---

# 24. Dynamic Specifications

Accepted Deal specifications are copied from the selected OfferVersion.

```text
DealTermsSnapshot.specifications JSONB
```

Validation during Deal creation verifies the source version was valid and schema-bound.

No Bitumen-specific columns.

No commodity-specific snapshot model.

---

# 25. Requested vs Accepted Specifications

The accepted Deal terms are the selected OfferVersion specifications.

If useful for audit/UI, the Deal may also snapshot the RFQ requested specification context separately.

Do not conflate:

```text
requested specifications
```

with:

```text
accepted specifications
```

The accepted terms are authoritative for Deal execution.

---

# 26. Commercial Notes

Only notes that are part of the accepted commercial OfferVersion may be snapshotted as Deal terms.

Do not copy:

- Operator internal notes;
- Opportunity contact notes;
- private verification notes;
- negotiation-internal comments not part of accepted terms.

---

# 27. Deal Party Model

Separate actual Deal parties from attribution.

A Deal has exactly two principal commercial roles in v1:

```text
BUYER
SELLER / COMMERCIAL_COUNTERPARTY
```

The Seller may be:

```text
Supplier Organization
Broker Organization
ExternalCounterparty
```

depending on the selected Offer's economic party.

---

# 28. Buyer Party

Buyer is derived from the RFQ owner Organization.

The Deal stores:

- source Organization reference;
- immutable identity snapshot needed for commercial history.

Do not derive Buyer from current session/context.

---

# 29. Seller / Commercial Counterparty

The Deal seller is the selected Offer's economic party.

If selected Offer came from:

```text
Supplier Organization
```

the Supplier is the commercial counterparty.

If selected Offer came from:

```text
Broker Organization
```

the Broker is the commercial counterparty.

If selected Offer was Operator-entered for:

```text
ExternalCounterparty
```

that ExternalCounterparty is the commercial counterparty.

Do not silently substitute another Organization.

---

# 30. Party Snapshot

Recommended model:

```text
DealPartySnapshot
```

Conceptual fields:

```text
deal
role
party_type
organization_id?
external_counterparty_id?
name_snapshot
country_snapshot?
registration_identifier_snapshot?
other minimal legal/commercial identity fields
created_at
```

Exactly one backing source reference according to `party_type`.

---

# 31. Minimal Snapshot Principle

Snapshot only identity information needed to preserve the commercial record.

Do not indiscriminately duplicate:

- private contacts;
- passwords/auth fields;
- memberships;
- capabilities;
- verification documents;
- internal notes.

Party snapshot is commercial identity, not a CRM export.

---

# 32. Party Snapshot Immutability

After Deal creation:

```text
DealPartySnapshot
```

is immutable.

If an Organization later changes display name or verification status, historical Deal identity remains reconstructable.

Current Organization state may be displayed separately where useful.

---

# 33. Source References and Snapshots Coexist

A Deal keeps both:

```text
source references
+
immutable snapshots
```

References provide traceability/navigation.

Snapshots preserve historical truth.

Never rely on only one of the two.

---

# 34. Deal Snapshot Must Survive Source Change

Tests must prove:

```text
create Deal
→ later update allowed RFQ administrative field
→ later Organization display metadata changes
→ later verification changes
```

does not rewrite:

```text
DealTermsSnapshot
DealPartySnapshot
```

---

# 35. Source Deletion Safety

Do not allow normal source deletion to erase Deal history.

At minimum protect:

- AwardAllocation;
- selected OfferVersion;
- source Offer;
- relevant CommoditySchemaVersion.

Optional provenance references may use protected or history-safe semantics.

---

# 36. Deal Attribution Is Not Deal Party

Attribution answers:

> How did this Deal originate?

Party answers:

> Who is commercially participating in this Deal?

These concepts must remain separate.

A Broker may be attributed without being the commercial seller.

A Broker attribution never grants Deal access by itself.

---

# 37. Primary Deal Attribution Categories

Use exactly the roadmap business categories:

```text
PLATFORM_NETWORK
DIRECT_SUPPLIER
BROKER
OPPORTUNITY_DESK
BUYER_EXISTING_SUPPLIER
```

No `Trader`.

These categories are canonical machine values with localized labels.

---

# 38. DealAttribution Aggregate

Recommended:

```text
DealAttribution
---------------
deal
status
primary_channel?
resolution_method?
resolved_by?
resolved_at?
evidence_snapshot
created_at
```

`primary_channel` uses the five roadmap categories only.

---

# 39. Attribution Status

Avoid guessing when provenance is insufficient.

Use workflow state:

```text
PENDING
RESOLVED
```

This is not an additional attribution category.

If the system can deterministically classify from explicit provenance, resolve automatically.

If evidence is insufficient/ambiguous, keep Attribution `PENDING`.

---

# 40. Attribution Resolution Must Use Explicit Evidence

Do not infer source from weak signals such as:

- "this Supplier has previous Deals";
- Organization country;
- current verification status;
- current matching score;
- user memory;
- repeated Buyer interaction.

Use explicit persisted provenance.

---

# 41. Primary Attribution Precedence

When explicit evidence overlaps, use deterministic business precedence:

```text
1. BUYER_EXISTING_SUPPLIER
2. BROKER
3. OPPORTUNITY_DESK
4. PLATFORM_NETWORK
5. DIRECT_SUPPLIER
```

This is a classification priority, not a value judgment.

The resolver must also preserve all underlying evidence so the primary label does not erase provenance.

---

# 42. BUYER_EXISTING_SUPPLIER

Use only when explicit persisted evidence states that the supply relationship was an existing Buyer supplier relationship.

Do not infer this category merely because:

- Buyer and Supplier transacted before;
- Supplier appears in Buyer history;
- Supplier was manually invited.

If no explicit evidence exists, do not assign this category.

---

# 43. BROKER Attribution

Primary channel becomes `BROKER` when explicit provenance establishes a Broker-originated commercial path.

Examples:

- selected Offer economic party is a Broker;
- supply Opportunity source is Broker Referral;
- demand Opportunity/RFQ provenance is Broker Referral;
- explicit Broker originator attribution is preserved from earlier domains.

Broker evidence must remain separately queryable.

---

# 44. OPPORTUNITY_DESK Attribution

Use when a relevant Opportunity is the explicit sourcing/demand origin and no higher-priority existing-supplier/Broker origin is established.

Examples:

- Operator Sourcing;
- Inbound Lead;
- Supplier Referral;
- Buyer Referral;
- other explicit Opportunity Desk sources supported by current product semantics.

Do not use merely because an Operator touched the Deal.

---

# 45. PLATFORM_NETWORK Attribution

Use when explicit platform-network discovery created the commercial path.

Examples may include:

- a persisted Matching selection/result leading to participation;
- network/directory discovery explicitly recorded;
- a platform-network invitation with durable provenance.

Do not infer from the fact that both parties happen to have platform accounts.

---

# 46. DIRECT_SUPPLIER Attribution

Use when the Supplier/Broker directly participated in the RFQ and no stronger explicit source provenance exists.

This is the fallback among resolved business categories, not a fallback for missing data.

If Deal origin is genuinely unknown, Attribution remains `PENDING` rather than silently labeling Direct Supplier.

---

# 47. Manual Attribution Resolution

If automatic resolution is impossible, Operator/Product Admin may resolve a `PENDING` attribution.

Required:

```text
selected primary_channel
reason
actor
timestamp
evidence/reference where available
```

Normal Buyer/Supplier/Broker actors cannot arbitrarily rewrite attribution.

---

# 48. Resolved Attribution Is Immutable in v1

Once `RESOLVED`, primary attribution cannot be silently overwritten.

If future correction workflow is needed, it must be explicit and auditable.

Epic 9 v1 does not add a generic correction engine.

---

# 49. Attribution Evidence Snapshot

Persist enough structured evidence to explain why a category was assigned.

Examples:

```text
source_offer_id
source_offer_version_id
source_supply_opportunity_id
source_demand_opportunity_id
source_matching_candidate_id
source_rfq_invitation_id
broker_referral facts
existing_relationship fact
```

Only include references that actually exist in the implemented product.

Do not fabricate unavailable evidence fields.

---

# 50. Opportunity Attribution

A Deal may be related to more than one Opportunity.

For example:

```text
Demand Opportunity
→ RFQ

Supply Opportunity
→ Operator-entered Offer

Award
→ Deal
```

Both are relevant.

Do not force the Deal to retain only one Opportunity if both are explicit sources.

---

# 51. DealOpportunityAttribution

Recommended model:

```text
DealOpportunityAttribution
```

Conceptual fields:

```text
deal
opportunity
role
created_at
```

Roles:

```text
DEMAND_ORIGIN
SUPPLY_ORIGIN
```

Unique:

```text
(deal, opportunity, role)
```

This provides durable bidirectional traceability.

---

# 52. Broker Attribution

Broker attribution is a dedicated structure, not a free-text field.

Recommended:

```text
DealBrokerAttribution
```

Conceptual fields:

```text
deal
broker_organization
role
related_opportunity?
created_at
```

---

# 53. Broker Roles

Support exactly the roadmap semantics:

```text
SUPPLY_ORIGINATOR
DEMAND_ORIGINATOR
```

A Broker may appear in either role.

A Deal may have both roles represented.

---

# 54. Multiple Brokers Are Structurally Allowed

Do not impose one Broker total per Deal.

Multiple broker rows may exist when explicit provenance supports them.

Use uniqueness such as:

```text
(deal, broker_organization, role, related_opportunity)
```

or an equivalent non-duplicating key.

This accommodates multi-layer broker networks without changing the core Deal model.

---

# 55. Supply Originator Broker

Typical sources:

- Broker was selected Offer economic party;
- supply Opportunity was Broker Referral;
- explicit supply-side Broker attribution flowed into the Offer.

Do not infer supply-originator role merely because Organization has Broker capability.

---

# 56. Demand Originator Broker

Typical source:

```text
Broker-originated Demand Opportunity
→ converted to RFQ
→ Award
→ Deal
```

The Broker who introduced demand may be attributed as:

```text
DEMAND_ORIGINATOR
```

even if a different party supplies the Deal.

---

# 57. Related Opportunity

Broker attribution should retain the related Opportunity when available.

This must use actual persisted Opportunity linkage, not free-text IDs.

---

# 58. Broker Attribution Does Not Grant Access

Being:

```text
SUPPLY_ORIGINATOR
DEMAND_ORIGINATOR
```

does not automatically grant the Broker permission to read the Deal.

Authorization is based on Deal party/product role policy.

Attribution is provenance, not ACL.

---

# 59. Attribution Snapshot vs Live Source

Deal attribution preserves the source decision at Deal creation/resolution time.

If an Opportunity is later edited within allowed semantics, Deal attribution does not silently change.

If a Broker capability is later removed, historical broker attribution remains.

---

# 60. Deal Creation Service

Recommended domain service:

```text
materialize_deals_from_award(award, actor)
```

Responsibilities:

1. authorize actor;
2. lock Award;
3. require FINALIZED;
4. load all AwardAllocations deterministically;
5. validate exact selected OfferVersions;
6. return existing Deal for already-materialized allocations;
7. create missing Deal identities;
8. create immutable Terms snapshots;
9. create Party snapshots;
10. capture explicit Opportunity/Broker provenance;
11. auto-resolve primary attribution when deterministic;
12. leave Attribution PENDING when not deterministic;
13. commit atomically.

---

# 61. Materialization Actor

Recommended allowed actors:

```text
Buyer Owner/Manager on the RFQ-owning Organization
Operator
Product Admin
```

If existing RFQ/Award conventions allow Member-level procurement actions, align with them deliberately.

Viewer is read-only.

Seller-side actors cannot materialize Buyer Deals.

---

# 62. No Commercial Editing During Materialization

Materialization accepts no client-supplied:

- quantity;
- price;
- currency;
- specification;
- payment;
- delivery;
- counterparty identity.

All commercial values are derived from authoritative Award/Offer/RFQ records.

Client may supply only action/concurrency metadata where required.

---

# 63. Optimistic Concurrency

Materialization should use the finalized Award's authoritative version or immutable-finalized state.

If an `expected_version` convention exists for Award actions, preserve it.

Never allow materialization against a stale/unfinalized Award.

---

# 64. Concurrent Materialization

Mandatory PostgreSQL race:

```text
two requests materialize same finalized Award
```

Expected result:

- one Deal per allocation;
- no duplicates;
- no IntegrityError leaking as 500;
- both callers receive coherent final state.

---

# 65. Snapshot Creation Failure

Inject failure during:

- Terms snapshot creation;
- Party snapshot creation;
- Attribution creation.

Transaction must not leave a partially-created Deal graph for a newly materialized allocation.

---

# 66. Deal Source Integrity

Each Deal must structurally satisfy:

```text
deal.award_allocation.award == deal.award
deal.offer_version == award_allocation.offer_version
deal.offer == offer_version.offer
deal.rfq == award.rfq == offer.rfq
```

Where these are stored as convenience references, verify consistency.

Do not accept mismatched client IDs.

---

# 67. Counterparty Integrity

Deal commercial counterparty must equal selected Offer economic party.

For internal Offer:

```text
Deal seller Organization == Offer offering_organization
```

For external Offer:

```text
Deal seller ExternalCounterparty == Offer external_counterparty
```

No substitution.

---

# 68. Buyer Integrity

Deal Buyer Organization must equal RFQ owner Organization.

No client override.

---

# 69. DealTermsSnapshot Model

Recommended explicit relational core:

```text
DealTermsSnapshot
-----------------
deal
commodity
schema_version
specifications JSONB

quantity
quantity_unit

unit_price
currency
product_cost_snapshot?

payment_terms
delivery_terms
incoterm
delivery_start
delivery_end
origin snapshot/reference
destination snapshot/reference

logistics_cost_status
logistics_cost_amount?

created_at
```

Other accepted known costs may use child snapshot rows.

---

# 70. DealCostSnapshot

If Epic 8 has structured OfferCostComponents, copy them into:

```text
DealCostSnapshot
```

Conceptual:

```text
deal_terms_snapshot
kind
amount
currency
description_snapshot?
```

Do not retain only live references to OfferVersion cost rows.

---

# 71. Schema-Version Historical Integrity

The Deal's schema version is immutable.

Later:

```text
Commodity.active_schema_version = newer version
```

must not alter Deal validation/rendering semantics.

Deal specification view always uses Deal's stored schema version.

---

# 72. Terms Snapshot Immutability

Normal application APIs must expose no PATCH/DELETE of commercial Deal terms.

Django Admin/internal tooling must not casually mutate immutable terms.

If Admin is registered, make commercial snapshots appropriately read-only.

---

# 73. Deal Party Snapshot Constraints

For each Deal:

```text
exactly one BUYER
exactly one SELLER
```

Use uniqueness constraints.

Each PartySnapshot:

```text
exactly one backing source reference appropriate to party_type
```

where applicable.

---

# 74. External Counterparty Deal

A Deal with ExternalCounterparty Seller is valid.

It remains Operator-managed because ExternalCounterparty has no platform account.

Do not create an account merely because the Deal now exists.

---

# 75. Internal Seller Deal

If seller is an Organization:

- Supplier capability or Broker capability is historical provenance from Offer validation;
- Deal does not reclassify the party;
- later capability changes do not rewrite historical snapshot.

---

# 76. Deal Authorization

Baseline:

### Buyer side
Authorized users of the Buyer Organization may access their Deal according to role policy.

### Seller Organization side
Authorized users of the actual seller Organization may access their Deal.

### External Seller
No direct user access unless a future identity relationship is explicitly built.

### Operator / Product Admin
Internal global operational access.

### Other Organizations
No access.

### Attributed Broker that is not a Deal party
No access merely due to attribution.

---

# 77. Deal Role Matrix

Recommended baseline:

```text
Buyer Owner/Manager/Member → read Deal
Buyer Viewer               → read safe Deal view
Seller Owner/Manager/Member → read Deal
Seller Viewer               → read safe Deal view
Operator                    → internal Deal access
Product Admin               → internal Deal access
Django staff/superuser only → no Product access
```

Epic 9 v1 adds little/no customer mutation after Deal creation, so read permissions are the dominant customer boundary.

---

# 78. Internal vs Customer Projection

Use explicit projections.

Customer Deal view may show:

- accepted terms;
- principal parties;
- safe attribution label where product policy allows;
- execution placeholders.

Internal view may additionally show:

- source Opportunities;
- external source references;
- Broker attribution detail;
- attribution resolution evidence;
- operational metadata.

Do not leak private Opportunity notes/contact attempts.

---

# 79. Attribution Visibility

Primary attribution may be safe to show to Buyer depending on product UX.

Detailed internal provenance must remain internal by default.

Especially hide:

- ExternalCounterparty contact details not part of Deal terms;
- Operator sourcing notes;
- Opportunity contact history;
- private Broker sourcing metadata.

---

# 80. Attribution Is Not Commission Logic

Epic 9 attribution tracks provenance.

It does NOT calculate:

- broker commission;
- revenue share;
- referral fee;
- payment obligation;
- ownership percentage.

Those require separate business policy.

Do not infer economics from attribution.

---

# 81. Attribution Is Not Authorization

Repeat invariant:

```text
Attribution ≠ permission
```

No ACL is created from provenance records.

---

# 82. Attribution Is Not Trust Scoring

Do not turn Deal attribution into:

- broker quality score;
- supplier performance score;
- recommendation score.

Metrics belong to later Intelligence Epic.

---

# 83. Deal Workspace

Route should follow repository conventions, conceptually:

```text
/[locale]/deals/[id]
```

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

# 84. Overview Tab

Shows:

- Deal identity;
- source Award;
- awarded quantity;
- commodity;
- Buyer;
- commercial counterparty;
- accepted unit price/currency;
- delivery summary;
- creation time;
- attribution summary.

No fake execution status.

---

# 85. Terms Tab

Uses immutable DealTermsSnapshot.

Displays:

- quantity;
- price;
- currency;
- dynamic commodity specifications;
- payment;
- delivery;
- Incoterm;
- accepted known costs.

Historical CommoditySchemaVersion is used for rendering.

---

# 86. Parties Tab

Shows principal parties:

```text
Buyer
Commercial Counterparty
```

Uses DealPartySnapshot for historical identity.

May link to current Organization profile when authorized, but must distinguish:

```text
snapshot identity
```

from:

```text
current profile state
```

---

# 87. Attribution Tab

Customer-safe mode may show primary channel only if approved.

Internal mode shows:

- primary attribution category;
- resolution method;
- Demand/Supply Opportunities;
- Broker originator rows;
- related source facts.

Do not expose internal notes.

---

# 88. Execution Tab

Epic 9 does not implement execution.

Show an honest staged empty state such as:

```text
Execution monitoring will appear here once execution tracking is available.
```

Do not fabricate milestones.

Epic 10 will own this tab's real data.

---

# 89. Logistics Tab

No logistics tracking model is introduced in Epic 9.

Show honest staged/empty state.

Epic 10 owns logistics tracking.

Do not derive logistics tracking from Deal delivery terms.

---

# 90. Quality Tab

No inspection workflow is introduced in Epic 9.

Show staged empty state.

Epic 10 owns Quality & Inspection.

---

# 91. Documents Tab

Epic 9 does not invent a Deal document system merely to populate the tab.

If no existing safe Deal-associated document contract exists:

```text
honest empty/staged state
```

Epic 10 T1007 owns Execution Documents.

Do not copy private RFQ/verification evidence automatically.

---

# 92. Issues Tab

No issue-management model in Epic 9.

Show staged empty state.

Epic 10 T1008 owns Issues.

---

# 93. Activity Tab

Epic 9 may show domain-derived events already present:

- Award finalized;
- Deal materialized;
- attribution auto-resolved/manual-resolved;
- source OfferVersion selected.

Do not create the generic Audit Trail from Epic 11.

Activity can be derived from immutable timestamps/domain records.

---

# 94. No Fake Future Data

Future tabs must not show:

- fake milestones;
- fake shipment progress;
- fake inspection status;
- fake payment status;
- fake issues;
- fake documents.

Empty state is correct.

---

# 95. Persian / RTL

Demo remains Persian and RTL.

Machine values remain canonical.

Dynamic specifications use the existing historical schema renderer.

Do not hard-code commodity-specific Persian fields.

---

# 96. Session / Persona Isolation

Deal data is commercially sensitive.

On actor/persona/organization switch:

- Deal list/detail cache invalidates;
- Attribution internal data invalidates;
- in-flight prior-actor requests cannot repopulate new session cache.

Backend remains authoritative.

---

# 97. Deal List / Discovery

If Epic 9 adds a Deal list, server-side scope by actor.

Do not fetch all Deals and filter in React.

At minimum:

```text
Buyer → own Buyer Deals
Seller Organization → own Seller Deals
Operator/Admin → internal global
```

Attributed Broker-only relation does not grant list visibility.

---

# 98. Deal API — Conceptual

Suggested:

```text
POST /awards/{award_id}/materialize-deals/

GET /deals/
GET /deals/{deal_id}/
GET /deals/{deal_id}/terms/
GET /deals/{deal_id}/parties/
GET /deals/{deal_id}/attribution/
```

Internal attribution resolution if necessary:

```text
POST /deals/{deal_id}/attribution/resolve/
```

Exact routes follow repository conventions.

---

# 99. No Generic Deal PATCH

Do not expose:

```text
PATCH /deals/{id}/
```

for commercial terms.

Deal commercial truth is immutable.

Later execution state lives in separate Epic 10 aggregates.

---

# 100. Mass-assignment Protection

Clients cannot set:

- source Award;
- source Allocation;
- source OfferVersion;
- Buyer;
- Seller;
- quantity;
- price;
- currency;
- specifications;
- party snapshots;
- primary attribution through Deal create;
- Broker attribution rows arbitrarily.

All derive from authoritative sources or tightly controlled attribution resolution.

---

# 101. Attribution Manual Resolution API

If used, request may contain only:

```text
primary_channel
reason
expected attribution version if applicable
```

Server derives:

- actor;
- timestamp;
- Deal;
- existing evidence.

Do not allow client to forge broker/opportunity evidence.

---

# 102. OpenAPI

Document accurate customer/internal projections.

Document:

- 400 validation;
- 403/404 authorization;
- 409 stale/already-resolved conflicts where applicable;
- idempotent materialization response semantics;
- pending vs resolved attribution.

Generated TypeScript must reflect real wire behavior.

---

# 103. PostgreSQL Constraints

At minimum investigate/enforce:

- one Deal per AwardAllocation;
- one TermsSnapshot per Deal;
- one Buyer PartySnapshot per Deal;
- one Seller PartySnapshot per Deal;
- valid party type/role;
- exactly-one party backing reference;
- valid attribution categories/status;
- unique DealOpportunityAttribution tuple;
- unique DealBrokerAttribution tuple;
- valid Broker attribution roles.

---

# 104. Real PostgreSQL Concurrency

Mandatory:

```text
materialize vs materialize same Award
```

Use separate DB connections/barriers.

Prove one Deal per allocation.

Do not claim concurrency safety from sequential duplicate calls alone.

---

# 105. Historical Source Mutation Tests

After Deal creation:

1. change allowed Organization metadata;
2. change verification status;
3. activate a new Commodity schema;
4. change permitted RFQ administrative metadata;
5. create newer unrelated Offer state where possible.

Assert Deal snapshots remain unchanged.

---

# 106. Deletion Integrity Tests

Attempt supported deletion paths for:

- AwardAllocation;
- selected OfferVersion;
- CommoditySchemaVersion;
- source Offer;
- relevant source Opportunity/Broker where protected by policy.

Deal history must not silently disappear.

Document which provenance references may become unavailable and why.

---

# 107. T0901 — Deal Creation Tests

Required:

- single Award allocation → one Deal;
- multi-Award → N allocations → N Deals;
- idempotent repeat;
- concurrent materialization;
- unfinalized Award rejected;
- foreign Award rejected;
- Buyer identity derived correctly;
- internal Supplier seller;
- Broker seller;
- ExternalCounterparty seller;
- no fake identities;
- atomic all-or-nothing materialization;
- no client commercial override.

---

# 108. T0902 — Deal Terms Snapshot Tests

Required:

- awarded quantity not offered quantity;
- exact unit price/currency;
- accepted specifications copied;
- exact schema version copied;
- payment copied;
- delivery copied;
- cost semantics copied;
- logistics UNKNOWN preserved;
- Party snapshots created;
- later source mutations do not rewrite Deal;
- snapshot mutation API absent/rejected;
- historical schema rendering still works.

---

# 109. T0903 — Deal Attribution Tests

Required primary-channel scenarios:

```text
PLATFORM_NETWORK
DIRECT_SUPPLIER
BROKER
OPPORTUNITY_DESK
BUYER_EXISTING_SUPPLIER
```

Also:

- no weak inference;
- ambiguous evidence → PENDING;
- deterministic precedence;
- manual resolution Operator/Admin-only;
- ordinary actor denied;
- resolved attribution immutable;
- evidence snapshot preserved.

---

# 110. T0904 — Broker Attribution Tests

Required:

- Supply Originator;
- Demand Originator;
- both on one Deal;
- multiple Broker rows if explicit provenance supports;
- related Opportunity linkage;
- no capability-only false attribution;
- no access gained through attribution;
- broker provenance preserved after later capability change;
- duplicate tuple rejected.

---

# 111. T0905 — Deal Workspace Tests

Required:

- Buyer sees own Deal;
- actual internal Seller sees own Deal;
- unrelated Organization denied;
- attributed-only Broker denied;
- Operator/Admin internal view;
- customer projection excludes internal Opportunity contact/private data;
- historical terms/specs render;
- Attribution tab accurate;
- future Execution/Logistics/Quality/Documents/Issues tabs show honest empty states;
- Activity uses real domain events;
- Persian/RTL;
- persona/session cache isolation.

---

# 112. CI Reachability

Every Task DoD automated test must be reachable from canonical CI.

Backend:

```text
python manage.py test
→ PostgreSQL CI
```

Frontend:

```text
canonical npm test/component commands
→ frontend CI
```

Contract:

```text
OpenAPI validation
→ generated TypeScript
→ drift check
```

No orphaned tests.

---

# 113. Packaging

Built wheel/sdist must contain:

- Deal models;
- migrations;
- materialization service;
- snapshot logic;
- attribution logic;
- Broker attribution;
- APIs.

Source checkout success is insufficient.

---

# 114. Migration Validation

Require:

- fresh PostgreSQL migrate;
- `makemigrations --check --dry-run`;
- upgrade from pre-Epic-9 state containing finalized Award examples;
- no invented historical Deal backfill.

If old finalized Awards exist in a real upgrade fixture, materialization remains explicit/idempotent rather than a migration fabricating commercial Deals.

---

# 115. Performance

Avoid obvious N+1 on:

```text
Deal
→ Terms
→ Parties
→ Attribution
→ Broker attributions
→ Opportunity attributions
```

Use select/prefetch appropriately.

No Redis/Elasticsearch/caching infrastructure for Epic 9.

---

# 116. Security Review Targets

Attack:

- foreign Deal UUID;
- foreign Award ID materialization;
- competitor Deal;
- attributed Broker access;
- forged seller;
- forged Buyer;
- forged OfferVersion;
- forged Opportunity/Broker attribution;
- Django superuser without Product role;
- mass assignment;
- stale persona/cache;
- CSRF on attribution resolution/materialization.

---

# 117. Recommended Sequential Execution Order

```text
1. T0901 — Deal Creation
2. T0902 — Deal Terms Snapshot
3. T0903 — Deal Attribution
4. T0904 — Broker Attribution
5. T0905 — Deal Workspace UI
6. Epic 9 Adversarial Review Gate
```

The roadmap order is already dependency-safe.

---

# 118. T0901 Scope Boundary

T0901 establishes:

- Deal identity;
- One Deal per AwardAllocation;
- controlled materialization;
- idempotency;
- source references;
- authorization;
- concurrency safety.

It should not prematurely implement full terms/attribution UI.

---

# 119. T0902 Scope Boundary

T0902 adds:

- immutable Terms snapshot;
- Party snapshots;
- cost snapshots;
- historical rendering integrity.

It does not add execution workflow.

---

# 120. T0903 Scope Boundary

T0903 adds:

- primary attribution aggregate;
- deterministic resolver;
- PENDING/RESOLVED;
- explicit evidence;
- manual internal resolution where required.

It does not implement analytics.

---

# 121. T0904 Scope Boundary

T0904 adds:

- Broker attribution rows;
- Supply/Demand Originator semantics;
- Opportunity linkage;
- multi-broker provenance support.

It does not calculate broker economics/commission.

---

# 122. T0905 Scope Boundary

T0905 assembles the Deal workspace from real Epic 9 data.

Future Epic 10 tabs are staged honestly.

No fake future backend entities are created merely for UI completeness.

---

# 123. Epic 9 Hero Flow — Single Supplier

```text
RFQ
→ Offer V2 selected
→ Finalized Award
→ AwardAllocation 500 MT
→ Materialize
→ Deal
→ immutable terms
→ Buyer + Seller snapshots
→ attribution resolved
→ Deal Workspace
```

---

# 124. Epic 9 Hero Flow — Multi-Award

```text
RFQ 1000 MT

Award:
Supplier A V2 → 400 MT
Supplier B V1 → 350 MT
External Supplier C V3 → 250 MT

Materialize
→ Deal A
→ Deal B
→ Deal C
```

Each Deal independently preserves:

- party;
- quantity;
- terms;
- provenance;
- future execution boundary.

---

# 125. Epic 9 Hero Flow — Broker / Opportunity Provenance

Example:

```text
Broker Referral
→ Qualified Supply Opportunity
→ Operator-entered Offer
→ Offer V2
→ AwardAllocation
→ Deal
```

Deal should preserve:

```text
Commercial Seller = ExternalCounterparty
Primary Attribution = BROKER
Supply Originator Broker = Broker Organization
Supply Opportunity = related provenance
```

The Broker is not automatically a Deal party.

---

# 126. Demand-origin Broker Example

```text
Broker introduces Buyer demand
→ Demand Opportunity
→ RFQ
→ Supplier Offer
→ Award
→ Deal
```

Deal should preserve:

```text
Commercial Seller = Supplier Organization
Demand Originator Broker = Broker Organization
Demand Opportunity = related provenance
```

---

# 127. Platform Network Example

```text
RFQ
→ Matching
→ Supplier discovered via platform network
→ participation/Offer
→ Award
→ Deal
```

When the network discovery link is explicitly persisted:

```text
Primary Attribution = PLATFORM_NETWORK
```

Do not infer merely because Matching exists somewhere in the system.

---

# 128. Direct Supplier Example

```text
RFQ
→ Supplier directly participates
→ no Broker provenance
→ no Opportunity source
→ no explicit existing-supplier relation
→ no persisted platform-network discovery path
→ Award
→ Deal
```

Then:

```text
Primary Attribution = DIRECT_SUPPLIER
```

---

# 129. Buyer Existing Supplier Example

Use only when explicit persisted relationship provenance exists.

Then:

```text
Primary Attribution = BUYER_EXISTING_SUPPLIER
```

Do not derive it from historical Deal count.

---

# 130. Explicit Non-goals

Epic 9 does not implement:

```text
Execution milestones
Logistics tracking
Inspection workflow
Payment monitoring
Issue management
Execution documents
Settlement
Escrow
Contract signing engine
Broker commissions
Referral payouts
Deal cancellation/amendment workflow
Generic audit trail
Notifications
Analytics
Supplier performance
Broker performance
Market intelligence
AI
New infrastructure
```

---

# 131. Architecture Failure Conditions

Epic 9 is architecturally failed if:

```text
Deal points only to mutable sources without immutable snapshots
```

or:

```text
one multi-award creates one multi-seller Deal
```

or:

```text
Deal quantity uses offered quantity instead of awarded quantity
```

or:

```text
Deal specifications use today's active schema
```

or:

```text
external seller requires fake Organization/User
```

or:

```text
Broker attribution automatically grants Deal access
```

or:

```text
attribution is guessed from weak historical signals
```

or:

```text
primary attribution overwrites/erases source provenance
```

or:

```text
Deal terms can be PATCHed after creation
```

or:

```text
future Execution/Logistics/Quality data is fabricated
```

or:

```text
if commodity == "bitumen"
```

exists in generic Deal snapshot/rendering.

---

# 132. Epic 9 Review Gate — Materialization

Verify:

- exact reviewed Award source;
- finalized-only creation;
- one Deal/allocation;
- multi-award creates multiple Deals;
- idempotency;
- real concurrency;
- all-or-nothing new materialization;
- correct Buyer/Seller;
- external seller support.

---

# 133. Epic 9 Review Gate — Snapshot Integrity

Verify:

- awarded quantity;
- exact OfferVersion;
- exact schema version;
- dynamic specifications;
- price/currency;
- cost semantics;
- payment/delivery;
- party snapshots;
- no future source mutation rewrites history;
- deletion safety.

---

# 134. Epic 9 Review Gate — Attribution

Verify all five categories.

Attack ambiguous scenarios.

Verify:

- explicit evidence;
- precedence;
- PENDING behavior;
- manual internal resolution;
- immutable resolved result;
- underlying evidence retained.

---

# 135. Epic 9 Review Gate — Broker Provenance

Verify:

- Supply Originator;
- Demand Originator;
- related Opportunities;
- multiple Broker support;
- no false capability-based attribution;
- no ACL implication.

---

# 136. Epic 9 Review Gate — Authorization

Verify:

- Buyer party;
- Seller party;
- unrelated Buyer/Supplier/Broker;
- attributed-only Broker;
- ExternalCounterparty has no fake direct session;
- Operator;
- Product Admin;
- Django staff/superuser only;
- anonymous.

---

# 137. Epic 9 Review Gate — Workspace

Verify:

- Overview;
- Terms;
- Parties;
- Attribution;
- historical schema rendering;
- Persian/RTL;
- customer/internal projection separation;
- honest staged future tabs;
- no fake operational data;
- session/persona isolation.

---

# 138. Epic 9 Review Gate — PostgreSQL / Contract / CI

Verify:

- fresh migrations;
- upgrade;
- DB constraints;
- concurrent materialization;
- OpenAPI runtime accuracy;
- generated TypeScript deterministic;
- canonical tests CI-reachable;
- package contents;
- no SQLite.

---

# 139. Epic Definition of Done

Epic 9 is complete when the system can demonstrate:

```text
Finalized Award
→ Materialize Deals
→ exactly one Deal per allocation
→ immutable accepted commercial snapshot
→ immutable principal party snapshots
→ explicit primary attribution
→ Broker/Opportunity provenance
→ authorized Deal Workspace
```

and prove:

```text
source changes do not rewrite Deal
attribution does not grant access
multi-award remains separate Deals
external counterparties require no fake identity
future execution data is not fabricated
```

---

# 140. Long-term Contract Created by Epic 9

After Epic 9:

```text
AwardAllocation
= exact procurement allocation decision

Deal
= stable commercial relationship identity

DealTermsSnapshot
= immutable accepted commercial truth

DealPartySnapshot
= immutable principal-party identity at creation

DealAttribution
= explainable origin classification

DealBrokerAttribution
= explicit broker provenance

DealOpportunityAttribution
= demand/supply opportunity provenance
```

Epic 10 builds execution on top of `Deal`.

Epic 12 may aggregate Deal/Attribution data but must not rewrite it.

---

# 141. Final Architectural Statement

Epic 9 must create a durable boundary between procurement decision and execution.

The core invariant is:

> **An Award decides what was purchased; each AwardAllocation materializes into one immutable Deal; the Deal snapshots the exact accepted commercial terms and parties; attribution explains how the Deal originated without changing who the Deal parties are or who may access it.**

The resulting Deal foundation must be:

```text
Immutable
Auditable
Multi-award safe
External-counterparty compatible
Broker-aware
Opportunity-aware
Commodity-agnostic
Historically reproducible
Execution-ready
Privacy-preserving
```
