# Epic 12 — Intelligence

## Design Contract, Metric Definitions, Reliability Policy & Delivery Requirements

**Status:** Proposed owner design contract for Epic 12 implementation  
**Target path:** `docs/product/epic-12-intelligence-design-contract.md`  
**Epic:** Epic 12 — Intelligence  
**Priority:** P1

---

# 1. Objective

Epic 12 turns authoritative procurement, Deal, attribution, Opportunity, and Execution facts into explainable operational intelligence.

The core architecture is:

```text
Authoritative Domain Records
        ↓
Metric Query Services
        ↓
Explicit Metric Definitions
        ↓
Reliability / Comparability Guard
        ↓
Operator Intelligence APIs
        ↓
Operator Dashboard
```

Epic 12 is a read/query layer.

It must not mutate business history in order to produce analytics.

---

# 2. Canonical Roadmap Scope

Epic 12 contains exactly:

```text
T1201 — Procurement Metrics Query Layer
    RFQ count
    offer count
    award rate
    time to first offer
    offers per RFQ
    quote spread

T1202 — Deal Metrics
    deal count
    awarded volume
    completed value
    execution delays

T1203 — Supplier Performance
    response rate
    win rate
    delivery
    quality
    completed deals

T1204 — Broker Performance
    opportunities introduced
    qualification rate
    deals attributed
    conversion
    attributed value

T1205 — Opportunity Metrics
    captured
    qualified
    converted
    lost
    conversion rate

T1206 — Market Activity
    commodity-level:
        min quote
        max quote
        average quote
        quote spread
        executed values

T1207 — Insufficient Data Guard

T1208 — Dashboard UI
    Operator dashboard
```

Roadmap requirement:

```text
Insufficient data for reliable benchmark
```

must be shown when data is not sufficient.

Fake price indexes are forbidden.

---

# 3. Existing Architectural Contracts

Epic 12 must preserve:

- PostgreSQL is the source of truth.
- Domain records, not AuditEvent rows, are authoritative for metrics.
- Submitted OfferVersions are immutable historical commercial facts.
- AwardAllocations reference exact OfferVersions.
- DealTermsSnapshot is immutable commercial truth.
- DealAttribution and DealBrokerAttribution preserve provenance.
- Execution records actual operational facts after Deal creation.
- Unknown data is not zero.
- No implicit FX conversion.
- No silent quantity-unit conversion.
- Historical CommoditySchemaVersions are preserved.
- Semantic fingerprints may be used for cross-schema attribute identity where already supported.
- Customer authorization and competitor privacy remain backend-authoritative.
- Epic 12 dashboard is Operator-facing.
- Persian/RTL remains the primary demo UI.

---

# 4. Intelligence Is Derived, Not Authoritative State

Never persist a business fact merely because a dashboard needs it.

Correct:

```text
OfferVersion submitted_at
→ derive quote metrics
```

Incorrect:

```text
dashboard_offer_count field on RFQ
```

Correct:

```text
Execution actual_delivery_at
+ Deal promised delivery_end
→ derive on-time delivery
```

Incorrect:

```text
supplier.performance_score manually updated
```

---

# 5. Domain Tables, Not Audit Trail

AuditEvent is evidence of important mutations.

It is not the metric source of truth.

Reasons:

- Epic 11 Audit is prospective, not historically backfilled.
- Audit payloads are intentionally bounded and redacted.
- Some metrics require precise relationships and immutable domain snapshots.

Epic 12 queries authoritative domain models directly.

Audit may help diagnose a discrepancy, but metrics do not depend on Audit completeness.

---

# 6. No Data Warehouse in v1

Epic 12 v1 uses PostgreSQL query services.

Do not introduce:

```text
ClickHouse
BigQuery
Snowflake
Redshift
Elasticsearch
OLAP cube
Kafka
CDC pipeline
```

At pilot scale:

```text
PostgreSQL
+ correct indexes
+ explicit query services
```

is sufficient.

---

# 7. No Materialized Aggregate Tables by Default

Do not create mutable summary tables such as:

```text
supplier_monthly_stats
market_daily_average
broker_score_cache
```

unless profiling proves live queries cannot meet requirements.

v1 metrics should be reproducible from authoritative records.

Materialized views/caches are future optimizations, not the semantic foundation.

---

# 8. Intelligence Access Policy

Epic 12 v1 APIs/UI are internal:

```text
Operator
Product Admin
→ allowed

Buyer/Supplier/Broker customer users
→ denied

Django staff/superuser without Product role
→ denied
```

Supplier/Broker performance metrics are not customer-facing scorecards in v1.

---

# 9. No Composite Supplier/Broker Score

Epic 12 exposes named metrics.

Do not create:

```text
Supplier Score = 87
Broker Score = 92
```

unless a later product policy explicitly defines such a score.

Performance metrics remain separate:

```text
response rate
win rate
delivery
quality
completed deals
```

This preserves explainability and avoids arbitrary weighting.

---

# 10. Time Window Contract

Every metric query that depends on time accepts an explicit bounded window:

```text
from
to
```

using offset-aware timestamps.

Backend normalizes to UTC.

Use half-open interval:

```text
[from, to)
```

unless an existing project-wide convention differs.

---

# 11. `as_of` Semantics

Analytics responses expose:

```text
as_of
```

Normally:

```text
as_of = to
```

for historical window queries, or current server time for current-state queries.

No metric may include events after `as_of`.

This prevents a historical January report from changing because an Offer was submitted in February.

---

# 12. Cohort vs Event Metrics

Metric definitions must explicitly state whether they are:

```text
COHORT
EVENT
CURRENT_STATE
```

Examples:

```text
RFQ procurement metrics
→ cohort by first published_at

completed value
→ event by Execution.closed_at

currently delayed executions
→ current state as_of
```

Do not mix these semantics silently.

---

# 13. Metric Response Envelope

Every nontrivial metric should expose enough metadata to interpret it:

```text
metric_code
definition_version
value
unit?
currency?
sample_size
numerator?
denominator?
reliability_status
reason_code?
as_of
filters
```

Exact API shape may group related metrics, but these semantics remain available.

---

# 14. Metric Definition Version

Epic 12 v1 definitions are:

```text
definition_version = "v1"
```

If formulas later change materially:

```text
v2
```

must be explicit.

Do not silently redefine historical dashboard semantics.

A database model for definition versions is not required in v1.

---

# 15. Reliability Status

Use a small explicit set:

```text
AVAILABLE
INSUFFICIENT_DATA
NOT_COMPARABLE
NOT_APPLICABLE
```

Do not encode missing reliability as numeric zero.

---

# 16. Counts vs Rates/Averages

Raw factual counts may be displayed even for small samples.

Example:

```text
2 Deals
1 qualified Opportunity
```

Rates, averages, quote benchmarks, and performance percentages require sample metadata and reliability guards.

---

# 17. Initial Performance Reliability Threshold

For v1 rate/average performance metrics:

```text
minimum denominator/sample = 3
```

Examples:

- Supplier response rate
- Supplier win rate
- Supplier delivery rate
- Supplier quality rate
- Broker qualification rate
- Broker conversion rate
- Opportunity conversion rate
- average time to first offer

If sample < 3:

```text
value = null
reliability_status = INSUFFICIENT_DATA
```

while numerator/denominator/sample counts remain available.

This threshold is a policy constant with a single central definition.

---

# 18. Initial Market Reliability Threshold

For market quote statistics to be displayed as a reliable observed-market benchmark, require at least:

```text
5 comparable quote observations
3 distinct RFQs
3 distinct economic counterparties
```

within the selected cohort.

Otherwise:

```text
value = null
reliability_status = INSUFFICIENT_DATA
message = "Insufficient data for reliable benchmark"
```

Raw sample counts remain visible.

---

# 19. No Fake Price Index

Epic 12 must never label any output:

```text
Price Index
Market Index
Reference Price
Fair Value
```

unless a later dedicated methodology exists.

T1206 outputs descriptive:

```text
Observed Market Activity
```

only.

---

# 20. Currency Comparability

Never aggregate monetary values across currencies.

Incorrect:

```text
100 USD + 100 EUR = 200
```

Correct:

```text
USD group
EUR group
```

No live FX feed.

No implicit conversion.

---

# 21. Quantity Comparability

Never sum quantities across incompatible units.

Incorrect:

```text
500 MT + 500 barrels
```

Correct:

```text
group by commodity + quantity_unit
```

No silent unit conversion in Epic 12.

---

# 22. Monetary Precision

All monetary calculations use Decimal semantics.

Never binary floating-point arithmetic for currency metrics.

---

# 23. Percentage Precision

Rates are computed from integer numerator/denominator and returned with documented precision.

Do not store rounded percentages as source data.

---

# 24. Commodity Filtering

Metrics that involve commodity activity must be filterable by Commodity where applicable.

Use stable Commodity identity.

Do not identify commodity by localized display text.

---

# 25. Dynamic Specification Filtering

Market Activity may optionally narrow a commodity cohort by dynamic specification attributes.

Where cross-schema comparison is needed, use established semantic identities/fingerprints.

Never assume:

```text
same JSON key = same meaning
```

No Bitumen-specific filter branch in generic intelligence code.

---

# 26. Geography Filtering

Where relevant, reuse hierarchical GeographicArea semantics.

Do not infer logistics economics from geography.

Potential filters may include:

```text
origin area
destination area
supplier area
```

only when source data has the corresponding meaning.

---

# 27. Procurement Cohort

For T1201, RFQ cohort is:

```text
RFQs whose first published_at ∈ [from, to)
```

Draft RFQs that were never published are excluded.

All related events are cut off at:

```text
as_of = to
```

by default.

---

# 28. RFQ Count

Definition:

```text
RFQ count
=
count(distinct RFQ in procurement cohort)
```

Cancelled-after-publication RFQs still count as published procurement attempts.

---

# 29. Offer Count

Definition:

```text
Offer count
=
count(distinct Offer parent)
```

where:

- Offer targets an RFQ in cohort;
- at least one OfferVersion was submitted by `as_of`.

Revisions do not increase Offer count.

Example:

```text
Supplier A
V1 → V2 → V3

Offer count = 1
```

---

# 30. Procurement Outcome Cohort

For Award Rate, unresolved/open RFQs should not dilute decision quality.

Resolved procurement outcome:

```text
AWARDED
or
CLOSED without Award
```

Exclude:

```text
still open/in progress
CANCELLED without procurement decision
```

from Award Rate denominator.

Report excluded/open/cancelled counts separately.

---

# 31. Award Rate

Definition:

```text
awarded_rfq_count
/
decided_rfq_count
```

where:

```text
decided_rfq_count
=
awarded RFQs
+
closed-without-award RFQs
```

If denominator < reliability threshold:

```text
INSUFFICIENT_DATA
```

---

# 32. Time to First Offer

For each RFQ in procurement cohort with at least one submitted OfferVersion by `as_of`:

```text
first_offer_at
=
minimum submitted_at across all OfferVersions/Offer parents

time_to_first_offer
=
first_offer_at - rfq.published_at
```

Primary aggregate:

```text
average_time_to_first_offer
```

Return sample count.

Median may be returned as supplemental descriptive data if implementation does so consistently, but roadmap-required primary metric is the average.

---

# 33. Offers per RFQ

Definition:

```text
distinct submitted Offer parents
/
RFQ count
```

Revisions do not increase numerator.

Open RFQs in the cohort remain valid for this descriptive metric as of cutoff.

---

# 34. RFQ-level Quote Observation

For quote comparison on one RFQ:

- take each Offer thread's latest submitted OfferVersion as of cutoff;
- use original submitted unit price;
- require same currency;
- require same quantity unit / pricing unit semantics.

No FX.

No headline-price fallback to landed-cost or vice versa.

---

# 35. RFQ Quote Spread

For a comparable RFQ with at least two current quote observations:

```text
absolute_spread
=
max(unit_price) - min(unit_price)
```

Relative spread:

```text
relative_spread_pct
=
(max(unit_price) - min(unit_price))
/
min(unit_price)
× 100
```

If prices/currencies/units are not comparable:

```text
NOT_COMPARABLE
```

---

# 36. Aggregate Procurement Quote Spread

Across the RFQ cohort:

- relative spreads may be averaged across eligible RFQs;
- absolute spread must remain grouped by currency/unit.

Return:

```text
eligible_rfq_count
excluded_not_comparable_count
sample counts
```

Never collapse mixed currencies into one absolute number.

---

# 37. T1201 Query Output

Procurement Metrics should expose at minimum:

```text
rfq_count
offer_count
award_rate
time_to_first_offer
offers_per_rfq
quote_spread
```

with reliability and sample metadata.

---

# 38. Deal Metric Time Semantics

Different Deal metrics use different event dates intentionally.

The response must make this explicit.

Do not force every metric to use `Deal.created_at`.

---

# 39. Deal Count

Definition:

```text
count(Deal)
```

whose source Award was finalized in `[from, to)`.

Commercial transaction date is Award finalization, not delayed materialization time.

---

# 40. Awarded Volume

For Deals whose Award finalized in the window:

```text
sum(DealTermsSnapshot.quantity)
```

grouped by:

```text
commodity
quantity_unit
```

Never sum incompatible units.

---

# 41. Completed Deal

A Deal is operationally completed when:

```text
Execution.status = CLOSED
```

and:

```text
Execution.closed_at
```

is authoritative.

Deal existence alone does not mean completed.

---

# 42. Completed Value

Definition:

For Executions closed in `[from, to)`:

```text
completed_value
=
sum(Deal commercial product value)
```

where commercial product value is:

```text
Deal unit_price × Deal awarded quantity
```

or the equivalent immutable product-cost snapshot.

Group by currency.

Do not use actual logistics cost to rewrite commercial value.

---

# 43. Completed Value Is Not Settlement

`completed_value` means value of Deals whose operational Execution closed.

It does not mean:

- money settled;
- payment transferred;
- revenue recognized;
- cash collected.

Use honest dashboard labels.

---

# 44. Execution Delay — Promised Baseline

Supplier/Deal delivery performance should be judged against the accepted Deal commitment where available.

Preferred promised delivery baseline:

```text
DealTermsSnapshot.delivery_end
```

Actual:

```text
ExecutionLogistics.actual_delivery_at
```

Operational ETA updates do not rewrite the original promise.

---

# 45. Delayed Completed Execution

A completed Deal delivery is late when:

```text
actual_delivery_at > promised delivery_end
```

where both exist.

If promised date is absent:

```text
NOT_APPLICABLE / insufficient for delivery metric
```

---

# 46. Currently Delayed Execution

At `as_of`, an open Execution is delayed when at least one required milestone satisfies:

```text
expected_at < as_of
AND status not COMPLETED/SKIPPED
```

using Epic 10 milestone semantics.

---

# 47. Execution Delay Metrics

T1202 should expose at least:

```text
currently_delayed_execution_count
late_completed_execution_count
```

and sample/context counts.

Do not fabricate a historical "delay incident" count if prior expected-date history is not stored.

---

# 48. Supplier Performance Scope

Supplier Performance applies to:

```text
Organization with Supplier capability
```

and uses actual Supplier participation/Deal seller facts.

A Broker Organization's performance is not silently merged into Supplier metrics unless it also explicitly acted as Supplier in a domain path that permits that semantics.

---

# 49. Supplier Response Opportunity

For v1, response rate denominator is based on explicit RFQ invitations.

A response opportunity exists when:

```text
Supplier Organization was invited to an RFQ
```

and invitation was actionable under the RFQ policy.

Public RFQs that the Supplier could theoretically discover do not create denominator rows.

---

# 50. Supplier Response

Supplier responded when:

```text
the invited Supplier Organization submitted an Offer
```

for that RFQ by the applicable cutoff/deadline.

Count at most once per:

```text
Supplier + RFQ
```

---

# 51. Supplier Response Rate

Definition:

```text
responded_invited_rfqs
/
actionable_invited_rfqs
```

Return:

```text
numerator
denominator
rate
reliability
```

---

# 52. Supplier Win Opportunity

Win Rate considers procurement decisions where the Supplier had a submitted Offer and the RFQ reached a procurement outcome.

Exclude:

```text
open/unresolved RFQs
cancelled-without-decision RFQs
```

---

# 53. Supplier Win

Supplier wins an RFQ when any finalized AwardAllocation selects that Supplier's OfferVersion.

With Multi-Award:

```text
Supplier A + Supplier B
```

both count as winners for that RFQ.

Count one win per Supplier + RFQ.

---

# 54. Supplier Win Rate

Definition:

```text
won_decided_rfqs
/
supplier_decided_offer_rfqs
```

A Supplier with multiple OfferVersions on the same RFQ still contributes one denominator item.

---

# 55. Supplier Delivery Sample

Include Seller Deals where:

- seller is that Supplier Organization;
- promised delivery_end exists;
- actual_delivery_at exists.

External sellers are not included in an internal Supplier Organization's performance.

---

# 56. Supplier On-time Delivery Rate

Definition:

```text
deliveries where actual_delivery_at <= delivery_end
/
supplier delivery sample
```

Return late count separately.

Do not judge against mutable operational ETA.

---

# 57. Supplier Quality Sample

Use completed inspection records for Deals where the Supplier is the commercial Seller.

Include results with known completed outcome:

```text
PASS
FAIL
CONDITIONAL
```

`UNKNOWN` is excluded from quality-rate denominator and counted separately.

---

# 58. Supplier Quality Rate

Primary v1 quality metric:

```text
PASS count
/
known completed inspection result count
```

Also return:

```text
conditional_count
fail_count
unknown_count
```

Do not treat CONDITIONAL as PASS.

---

# 59. Supplier Completed Deals

Definition:

```text
count(distinct Deal)
```

where:

- Supplier Organization is commercial Seller;
- Execution is CLOSED;
- closure is within requested window when a window is applied.

---

# 60. Supplier Performance Is Not a Rating

Do not convert performance metrics into:

```text
4.8 stars
A+
Gold Supplier
87/100
```

unless later product policy explicitly defines such ratings.

---

# 61. Broker Performance Source

Broker metrics use explicit provenance from:

```text
Opportunity broker source/originator data
DealBrokerAttribution
DealOpportunityAttribution
```

Do not infer Broker involvement from Broker capability alone.

---

# 62. Broker Opportunities Introduced

Definition:

```text
count(distinct Opportunity)
```

where explicit Broker-origin provenance identifies the Broker.

May include:

```text
Supply origin
Demand origin
```

Return role breakdown where data supports it.

---

# 63. Broker Qualification Outcome Cohort

For qualification rate:

Resolved qualification outcomes are introduced Opportunities that by `as_of` are either:

```text
QUALIFIED
or
terminal LOST / rejected-equivalent outcome
```

Still-pending/unreviewed opportunities do not enter denominator.

Return pending count separately.

---

# 64. Broker Qualification Rate

Definition:

```text
qualified_introduced_opportunities
/
resolved_introduced_opportunities
```

with reliability guard.

---

# 65. Broker Deals Attributed

Definition:

```text
count(distinct Deal)
```

having explicit DealBrokerAttribution for the Broker.

If Broker appears in both demand and supply originator roles on one Deal:

```text
deal count = 1
```

for total deals attributed.

Role-specific counts may also be returned.

---

# 66. Broker Conversion Unit

Broker conversion is Opportunity-to-Deal, not number-of-Deals-per-Opportunity.

A Broker-introduced Opportunity is converted when it is explicitly related to at least one Deal through preserved provenance.

Multi-Award producing multiple Deals still counts that Opportunity once for conversion.

---

# 67. Broker Conversion Rate

Definition:

```text
distinct introduced qualified opportunities that produced >=1 Deal
/
distinct introduced qualified opportunities with resolved conversion outcome
```

Still-active qualified Opportunities are excluded from denominator and reported separately.

---

# 68. Broker Attributed Value

For each Broker:

```text
sum commercial product value of distinct attributed Deals
```

grouped by currency.

A Deal attributed to the same Broker in multiple roles is counted once.

---

# 69. Broker Attributed Value Is Non-additive Across Brokers

If one Deal has multiple attributed Brokers, the same Deal may contribute full value to each Broker's individual attribution view.

Therefore:

```text
sum(Broker A attributed value + Broker B attributed value + ...)
```

must not be presented as platform total transaction value.

API/UI must label Broker attributed value as non-additive across Brokers.

---

# 70. Broker Attribution Is Not Commission

Attributed value does not mean:

- broker fee;
- commission;
- revenue share;
- payable amount.

Epic 12 calculates none of these.

---


# 71. Opportunity Metrics Scope

Opportunity metrics operate on authoritative Opportunity records.

Support filters where already modeled and useful:

```text
direction
source
commodity
assigned operator
broker provenance
```

Do not invent dimensions not present in the Opportunity domain.

---

# 72. Opportunity Captured

Definition:

```text
count(Opportunity)
```

with:

```text
created_at ∈ [from, to)
```

This is the acquisition cohort.

---

# 73. Opportunity Qualified

Within the captured cohort:

```text
qualified
=
Opportunity reached the authoritative Qualified state by as_of
```

Do not infer qualification from notes, contact attempts, or score.

---

# 74. Opportunity Converted

Within the captured cohort, an Opportunity is converted when at least one canonical conversion artifact exists through authoritative conversion linkage:

```text
RFQ
Supply Listing
Offer
```

according to implemented Opportunity conversion semantics.

Count one converted Opportunity even if multiple artifacts later exist.

---

# 75. Opportunity Lost

Definition uses the authoritative terminal lost state or equivalent lifecycle fact.

Do not infer Lost because no activity happened recently.

---

# 76. Opportunity Conversion Outcome Cohort

For Conversion Rate, use qualified Opportunities with resolved conversion outcomes:

```text
CONVERTED
or
LOST
```

Qualified but still-active Opportunities are excluded from denominator and reported separately.

---

# 77. Opportunity Conversion Rate

Definition:

```text
converted_qualified_opportunities
/
resolved_qualified_opportunities
```

with reliability guard.

Return:

```text
qualified_active_count
lost_count
converted_count
```

so the rate is interpretable.

---

# 78. Opportunity Funnel

T1205 may expose a funnel:

```text
Captured
→ Qualified
→ Converted / Lost
```

Do not imply that every Opportunity must become Qualified.

Counts remain authoritative facts.

---

# 79. Market Activity — Meaning

T1206 is descriptive internal market activity.

It answers:

> What prices and executed commercial values have actually been observed on this platform within a comparable cohort?

It does **not** answer:

> What is the true market price?

---

# 80. Market Quote Observation

A quote observation is based on submitted commercial Offer data.

For each Offer thread in the selected window/cohort, use the latest submitted OfferVersion as of cutoff according to the selected query semantics.

Do not count every revision as an independent competing market participant.

---

# 81. Quote Event Window

For market-activity quote metrics, include an Offer thread when its relevant/latest submitted quote observation occurred in `[from, to)`.

If multiple versions were submitted in the period:

```text
latest submitted version in the period / as_of
```

is the observation.

This avoids revision inflation.

---

# 82. Quote Comparison Cohort

A monetary quote cohort must share:

```text
commodity
currency
price/quantity unit semantics
```

and any explicit user-selected specification/geography filters.

Never combine:

```text
USD with EUR
MT with barrel
Bitumen with Base Oil
```

---

# 83. Commodity-level Does Not Mean Specification-blind Benchmark

Roadmap calls T1206 commodity-level.

That permits high-level activity grouping by Commodity, but price benchmark claims still require comparable cohort metadata.

UI/API must surface selected cohort dimensions.

If multiple materially different grades/specifications are mixed, label output as broad commodity activity and never imply grade-specific reference pricing.

---

# 84. Optional Specification Cohort

Where operator selects dynamic specification filters:

```text
Commodity
+ semantic specification constraints
+ currency
+ unit
```

forms a narrower market cohort.

Cross-schema attribute identity must use stable semantic fingerprints where available.

---

# 85. Minimum Quote

For reliable comparable quote cohort:

```text
min_quote
=
minimum observed unit_price
```

No FX.

---

# 86. Maximum Quote

```text
max_quote
=
maximum observed unit_price
```

within the exact same cohort.

---

# 87. Average Quote

Use arithmetic mean of quote-level unit prices:

```text
sum(unit_price) / quote_count
```

Each Offer thread contributes at most one selected quote observation.

Do not quantity-weight by default.

If quantity-weighted average is later introduced, it must be a separately named metric.

---

# 88. Market Quote Spread

```text
absolute_spread
=
max_quote - min_quote
```

```text
relative_spread_pct
=
(max_quote - min_quote)
/
min_quote
× 100
```

only when:

```text
min_quote > 0
```

and cohort is comparable.

---

# 89. Market Executed Value

Executed value uses immutable Deal commercial product value.

Cohort date:

```text
source Award finalized_at ∈ [from, to)
```

Group by:

```text
commodity
currency
```

and quantity metrics separately by quantity unit.

This means commercial transaction value, not payment settlement and not Execution closed value.

---

# 90. Market Deal Count / Volume Metadata

Market activity response should accompany executed value with useful factual sample metadata:

```text
deal_count
awarded_volume by unit
distinct counterparties
```

without inventing a market index.

---

# 91. Market Counterparty Count

For quote reliability:

```text
distinct economic counterparties
```

means distinct Offer economic parties.

Multiple Offer threads from the same counterparty across RFQs count once for this diversity guard.

---

# 92. Market RFQ Count

Quote benchmark diversity guard uses:

```text
distinct RFQ count
```

not Offer count alone.

Five quotes on one RFQ do not satisfy the initial reliable-market threshold requiring three RFQs.

---

# 93. Insufficient Data Guard — Central Service

Implement one central reliability evaluator, not scattered UI heuristics.

Conceptually:

```text
MetricReliabilityPolicy
```

or stateless equivalent.

Responsibilities:

- sample thresholds;
- comparable currency/unit guard;
- distinct-RFQ/counterparty threshold;
- metric-specific applicability;
- standardized reason codes.

---

# 94. Reliability Reason Codes

Recommended stable codes:

```text
SAMPLE_TOO_SMALL
DENOMINATOR_TOO_SMALL
MIXED_CURRENCY
MIXED_UNIT
MISSING_REQUIRED_FIELD
NO_COMPARABLE_QUOTES
INSUFFICIENT_RFQ_DIVERSITY
INSUFFICIENT_COUNTERPARTY_DIVERSITY
NOT_APPLICABLE
```

UI localizes them.

---

# 95. Reliable Benchmark Message

When T1207 blocks a benchmark-like market metric, Persian UI should render the localized equivalent of:

```text
Insufficient data for reliable benchmark
```

Do not replace it with zero.

---

# 96. Raw Counts Survive the Guard

Example:

```text
quote_count = 2
average_quote = null
reliability = INSUFFICIENT_DATA
```

This gives operators honest context without pretending statistical reliability.

---

# 97. Missing Data Is Not Failure

Supplier delivery example:

```text
no promised delivery_end
```

means:

```text
not evaluable
```

not:

```text
late
```

Quality example:

```text
inspection result UNKNOWN
```

is excluded from PASS/FAIL denominator and reported separately.

---

# 98. Zero Is a Real Value

Do not confuse:

```text
0
```

with:

```text
unknown
```

Examples:

```text
0 awarded RFQs out of 5 decided RFQs
→ valid 0% if denominator sufficient

0 logistics cost explicitly NOT_APPLICABLE
→ valid known zero

missing logistics cost
→ unknown
```

---

# 99. Data Freshness

Analytics response includes:

```text
generated_at
as_of
```

No claim of real-time streaming.

Queries reflect PostgreSQL state at request time within normal transaction semantics.

---

# 100. Reproducibility

Given the same immutable historical records, filters, metric definition version, and as_of cutoff, the query should produce semantically identical output.

Mutable current-state metrics such as currently delayed executions are explicitly tied to `as_of`.

---

# 101. No Analytics Write-back

Epic 12 never writes:

```text
supplier rank
broker score
market price
opportunity probability
recommended supplier
```

back into domain aggregates.

Analytics is read-only.

---

# 102. No Predictive Analytics in v1

Do not implement:

```text
forecasting
win probability
supplier failure prediction
price prediction
demand prediction
AI recommendation
```

Epic 12 is descriptive/diagnostic intelligence only.

---

# 103. No Statistical Claims Beyond Methodology

Do not label a small descriptive average as:

```text
statistically significant
market benchmark
confidence interval
```

unless methodology actually supports it.

T1207 exists specifically to prevent overclaiming.

---

# 104. Procurement Metrics API

Conceptual:

```text
GET /intelligence/procurement/
```

Filters:

```text
from
to
commodity?
buyer_organization?
```

Internal Operator/Admin only.

Exact routes follow repository conventions.

---

# 105. Deal Metrics API

Conceptual:

```text
GET /intelligence/deals/
```

Returns grouped:

```text
deal_count
awarded_volume
completed_value
execution_delay metrics
```

with currency/unit grouping.

---

# 106. Supplier Performance API

Conceptual:

```text
GET /intelligence/suppliers/
GET /intelligence/suppliers/{organization_id}/
```

Filters may include:

```text
from
to
commodity?
geography?
```

Do not expose customer-facing supplier leaderboard in v1.

---

# 107. Broker Performance API

Conceptual:

```text
GET /intelligence/brokers/
GET /intelligence/brokers/{organization_id}/
```

Return explicit source samples and non-additivity metadata for attributed value.

---

# 108. Opportunity Metrics API

Conceptual:

```text
GET /intelligence/opportunities/
```

Filters:

```text
from
to
direction?
source?
commodity?
broker?
```

where supported by actual model fields.

---

# 109. Market Activity API

Conceptual:

```text
GET /intelligence/market-activity/
```

Required:

```text
from
to
commodity
```

Optional:

```text
currency
quantity_unit
geography
dynamic specification filters
```

Do not produce a single blended monetary metric when multiple currencies remain after filtering.

---

# 110. Query Service Architecture

Recommended:

```text
IntelligenceServiceFacade
    ├── ProcurementMetricsQuery
    ├── DealMetricsQuery
    ├── SupplierPerformanceQuery
    ├── BrokerPerformanceQuery
    ├── OpportunityMetricsQuery
    ├── MarketActivityQuery
    └── ReliabilityEvaluator
```

Avoid one giant dashboard query.

Each query object owns its metric semantics and efficient ORM/SQL.

---

# 111. DTO / Result Contracts

Use typed result structures.

Do not return ad-hoc dictionaries whose shape changes based on sample availability.

Unavailable numeric metrics should remain present with:

```text
value = null
reliability_status = ...
```

---

# 112. Query Filters Reuse

Reuse Epic 11 advanced-filter parsing/components where semantics align.

Do not allow generic filter infrastructure to redefine metric cohorts.

Metric-specific date/cohort rules remain inside Intelligence services.

---

# 113. Dashboard — Audience

T1208 is:

```text
Operator Dashboard
```

v1 access:

```text
Operator
Product Admin
```

No Buyer/Supplier/Broker analytics dashboard in this Epic.

---

# 114. Dashboard Global Controls

Recommended controls:

```text
date range
commodity
currency where relevant
quantity unit where relevant
```

Optional contextual filters may appear per section.

Do not force one currency selector onto non-monetary metrics.

---

# 115. Dashboard Sections

Recommended structure:

```text
Procurement
Deals
Supplier Performance
Broker Performance
Opportunity Funnel
Market Activity
```

Each panel uses the authoritative corresponding query API.

---

# 116. Procurement Dashboard Panel

Show:

```text
RFQ count
Offer count
Award rate
Average time to first offer
Offers per RFQ
Quote spread
```

Every rate/average shows:

```text
sample size
reliability state
```

---

# 117. Deal Dashboard Panel

Show:

```text
Deal count
Awarded volume
Completed value
Delayed executions
```

Never merge currencies/quantity units.

---

# 118. Supplier Performance UI

Table or detail view may show:

```text
Supplier
Response rate
Win rate
On-time delivery
Quality pass rate
Completed deals
Sample counts
```

No composite rank/score.

If sorting by a specific metric is supported, label the sorted metric explicitly.

---

# 119. Broker Performance UI

Show:

```text
Broker
Opportunities introduced
Qualification rate
Deals attributed
Conversion rate
Attributed value by currency
```

UI must state:

```text
Attributed values across Brokers are non-additive
```

where multiple attribution is possible.

---

# 120. Opportunity Funnel UI

Show factual counts:

```text
Captured
Qualified
Converted
Lost
Still active
```

Conversion rate only when denominator is reliable.

---

# 121. Market Activity UI

Show only comparable groups.

Example:

```text
Bitumen
USD / MT
Observed quotes: 12
RFQs: 5
Counterparties: 6

Min
Max
Average
Spread
Executed value
```

Do not label this a price index.

---

# 122. Market Activity Mixed Currency UX

If cohort contains:

```text
USD
EUR
```

either:

- show separate currency groups; or
- require operator to narrow currency.

Never show one blended average.

---

# 123. Market Activity Mixed Unit UX

Same rule:

```text
MT
barrel
```

remain separate.

---

# 124. Insufficient Data UI

Distinct from:

```text
No data
```

Use at least three states:

```text
No data
Insufficient data for reliable benchmark
Available
```

A server error is a fourth separate state and must not appear as "No data".

---

# 125. Charts

Charts must not:

- connect missing values as zeros;
- combine currencies;
- combine incompatible units;
- imply continuous price history if only sparse quotes exist;
- use fake extrapolation.

Show sample size/tooltips where useful.

---

# 126. Dashboard Empty / Loading / Error

Every panel distinguishes:

```text
loading
no data
insufficient data
available
error
unauthorized
```

---

# 127. Persian / RTL

Dashboard is Persian/RTL under `/fa`.

Numbers/currencies/units must render without bidi corruption.

Canonical metric codes/enums remain English machine values.

---

# 128. Historical Trend Buckets

If v1 dashboard includes time series, use explicit buckets:

```text
day
week
month
```

based only on authoritative event timestamps.

No interpolation for missing buckets.

A missing bucket may be rendered as zero only for true count metrics where zero is semantically valid.

---

# 129. Metric Privacy

Although v1 dashboard is internal, query services still use safe domain joins and avoid returning:

- private note bodies;
- Audit payloads;
- ExternalCounterparty contact details;
- raw document metadata;
- secrets.

Only fields required for metrics or internal drill-down identifiers are exposed.

---

# 130. Drill-down

A metric may link to an authorized filtered list of underlying domain records.

Examples:

```text
Offer count
→ filtered Offer list

Delayed executions
→ filtered Execution list
```

Drill-down is optional per task but must reuse normal authorization.

Do not create a separate privileged bypass query.

---

# 131. Indexing Strategy

Add indexes only for actual Intelligence query predicates/grouping, such as:

```text
RFQ published_at
OfferVersion submitted_at
Award finalized_at
Execution closed_at
ExecutionMilestone expected_at/status
Opportunity created_at/status
Deal seller identity
DealBrokerAttribution broker
```

Inspect existing indexes first.

No speculative duplicate indexes.

---

# 132. Query Performance Budget

At pilot/demo scale, dashboard requests should remain interactive on realistic Epic 13 seed data.

Do not optimize for millions of rows before profiling.

Avoid:

- per-row Python loops over large QuerySets;
- N+1;
- loading full JSON documents when only counts are needed.

Prefer database aggregation.

---

# 133. JSONB Specification Filtering

If dynamic specification filters are implemented for T1206:

- use targeted query patterns;
- validate semantic attribute identity;
- add JSONB index only if profiling justifies it.

Do not add a broad GIN index solely because specifications are JSONB.

---

# 134. No Cached Stale Truth in v1

Without an explicit cache invalidation contract, do not cache metric results in Redis/local process.

A live query that is slightly more expensive is preferable to silently stale analytics.

---

# 135. Concurrency Semantics

Intelligence queries are read-only.

A dashboard request may observe the committed database state at query time.

It does not require a global serializable snapshot across all panels unless one combined endpoint promises it.

For one multi-metric response, use a consistent transaction snapshot where practical.

---

# 136. Deterministic Tests

Metric tests must construct exact source records and assert exact numerators/denominators.

Avoid mocks that simply return the expected metric.

---

# 137. T1201 Required Tests

Procurement metrics:

- draft RFQ excluded;
- published RFQ included;
- offer revisions count once;
- Offer submitted after `as_of` excluded;
- open RFQ excluded from Award Rate denominator;
- cancelled RFQ excluded from decided denominator;
- closed-no-award counted as decided loss;
- multi-award RFQ counts as one awarded RFQ;
- time-to-first-offer exact duration;
- offers-per-RFQ exact;
- same-currency quote spread;
- mixed currency NOT_COMPARABLE;
- reliability threshold.

---

# 138. T1202 Required Tests

Deal metrics:

- deal count uses Award finalized date;
- multi-award produces multiple Deals/counts;
- awarded volume grouped by commodity/unit;
- incompatible units not summed;
- completed value only when Execution CLOSED in window;
- currencies separated;
- late completed delivery;
- currently overdue milestone;
- missing promised delivery does not become late.

---

# 139. T1203 Required Tests

Supplier performance:

- invitation denominator;
- public RFQ without invitation not denominator;
- one response per Supplier/RFQ;
- Offer revisions do not inflate response;
- unresolved RFQ excluded from Win Rate;
- cancelled-without-decision excluded;
- Multi-Award Supplier win;
- promised delivery baseline vs mutable ETA;
- on-time/late;
- PASS/FAIL/CONDITIONAL/UNKNOWN quality handling;
- completed Deal count;
- sample threshold;
- no composite score.

---

# 140. T1204 Required Tests

Broker performance:

- explicit Broker-introduced Opportunity;
- capability-only Broker does not count;
- supply/demand origin roles;
- qualification outcome denominator;
- pending excluded/reported;
- DealBrokerAttribution distinct Deal count;
- Broker in two roles on same Deal counts once;
- one Opportunity producing multiple Deals converts once;
- attributed value currency grouping;
- multiple Brokers may each see same Deal value;
- non-additivity metadata.

---

# 141. T1205 Required Tests

Opportunity metrics:

- captured by created_at window;
- qualification by authoritative lifecycle;
- conversion via canonical conversion linkage;
- multiple conversion artifacts count once;
- Lost authoritative only;
- active Qualified excluded from resolved conversion denominator;
- conversion rate threshold;
- direction/source filters.

---

# 142. T1206 Required Tests

Market activity:

- latest submitted quote per Offer thread;
- revision inflation prevented;
- commodity separation;
- currency separation;
- unit separation;
- min/max/average exact Decimal;
- quote spread;
- distinct RFQ count;
- distinct counterparty count;
- executed value from immutable Deal product value;
- no settlement semantics;
- optional semantic spec filter if implemented;
- no `price_index` output.

---

# 143. T1207 Required Tests

Insufficient Data Guard:

- count metrics work at n=0/1;
- performance rate suppressed below denominator 3;
- rate available at threshold;
- market quote benchmark suppressed below 5 quotes;
- RFQ diversity guard;
- counterparty diversity guard;
- mixed currency NOT_COMPARABLE;
- mixed unit NOT_COMPARABLE;
- message/reason code;
- zero preserved when it is a real value;
- UNKNOWN never converted to zero.

---

# 144. T1208 Required Tests

Dashboard:

- Operator allowed;
- Product Admin allowed;
- Buyer/Supplier/Broker denied;
- Django staff/superuser-only denied;
- global date/commodity filtering;
- currency groups separated;
- unit groups separated;
- no composite supplier/broker score;
- insufficient/no-data/error states distinct;
- Persian/RTL;
- generated API types;
- no stale persona/session leakage.

---

# 145. OpenAPI Contract

Document:

- date/filter inputs;
- grouped monetary/quantity outputs;
- reliability enum;
- nullable unavailable values;
- sample sizes;
- reason codes;
- metric definition version;
- access errors.

Frontend must not infer meaning from undocumented dictionaries.

---

# 146. Generated TypeScript

Dashboard uses generated types.

Do not create parallel handwritten metric DTOs that drift from backend.

---

# 147. PostgreSQL Migration Policy

Epic 12 should require few schema changes.

Likely changes are indexes/extensions only.

Require:

```text
fresh migrate
upgrade from post-Epic-11
makemigrations --check --dry-run
```

No analytics backfill tables.

---

# 148. CI Reachability

All metric/query tests must run in canonical PostgreSQL CI.

Backend:

```text
python manage.py test
```

Frontend dashboard tests use canonical npm commands.

No SQLite fallback.

---

# 149. Realistic Data Validation

Before Epic Review Gate, run queries against realistic multi-entity data, ideally approaching Epic 13 target shape:

```text
multiple Buyers
multiple Suppliers
multiple Brokers
20+ RFQs
40+ Offers
10+ Deals
Opportunities
Execution histories
```

Do not rely only on one-row unit fixtures.

---

# 150. Security Review Targets

Attack:

- customer direct Intelligence endpoints;
- Organization capability used as authorization;
- ExternalCounterparty contact leakage;
- hidden Offer price leakage through drill-down;
- arbitrary metric/filter name injection;
- unbounded date range/query cost;
- raw SQL injection;
- dynamic JSONB filter injection;
- mixed-currency accidental aggregate;
- competitor data appearing in future customer projection.

---

# 151. Query Range Guard

To avoid accidental pathological queries, validate time windows.

Recommended v1:

- require explicit bounded dates on expensive trend/market queries;
- enforce a reasonable maximum window or controlled internal override based on actual data volume.

Do not accept unbounded all-history joins by default if query cost becomes unsafe.

---

# 152. Auditability of Metric Definitions

Metric code/formula should be documented beside query service/tests.

Do not bury definitions only inside SQL annotations.

A reviewer should be able to answer:

```text
What is the denominator?
What records are excluded?
Which timestamp defines the cohort?
What happens when data is missing?
```

---

# 153. Recommended Execution Order

Roadmap order is dependency-safe:

```text
1. T1201 — Procurement Metrics Query Layer
2. T1202 — Deal Metrics
3. T1203 — Supplier Performance
4. T1204 — Broker Performance
5. T1205 — Opportunity Metrics
6. T1206 — Market Activity
7. T1207 — Insufficient Data Guard
8. T1208 — Dashboard UI
9. Epic 12 Adversarial Review Gate
```

Implementation recommendation:

Reliability primitives may be introduced minimally during T1201 and finalized/generalized in T1207, but T1201–T1206 must not ship misleading values while waiting for T1207.

---

# 154. Hero Flow — Procurement Intelligence

```text
Operator selects last 90 days
→ Procurement panel shows RFQ count
→ Offer count excludes revisions
→ Award rate uses only decided procurement outcomes
→ Time to first Offer shows sample size
→ Quote spread separates currencies
```

---

# 155. Hero Flow — Supplier Performance

```text
Supplier A

10 actionable RFQ invitations
7 responses
5 procurement outcomes
2 wins
4 deliveries with promised date
3 on time
3 completed known inspections
2 PASS / 1 FAIL
6 completed Deals

Dashboard shows each metric independently
with denominator/sample size
and no overall Supplier score
```

---

# 156. Hero Flow — Broker Performance

```text
Broker B
→ introduced 8 Opportunities
→ 5 resolved qualification outcomes
→ 3 qualified
→ 2 qualified resolved Opportunities produced Deals
→ 3 distinct Deals attributed
→ USD attributed value shown

No commission is inferred.
No global platform value is calculated by summing Brokers.
```

---

# 157. Hero Flow — Insufficient Market Data

```text
Bitumen / USD / MT
2 quotes
1 RFQ
2 counterparties
```

Response:

```text
quote_count = 2
min_quote = null
max_quote = null
average_quote = null
spread = null
reliability = INSUFFICIENT_DATA
```

UI:

```text
Insufficient data for reliable benchmark
```

No fake index.

---

# 158. Hero Flow — Reliable Observed Market Activity

```text
Bitumen / USD / MT
8 selected quote observations
4 RFQs
5 counterparties
```

Dashboard may show:

```text
Observed Min
Observed Max
Observed Average
Observed Spread
Executed Deal Value
```

with sample counts and selected filters.

Still do not call it a Price Index.

---

# 159. Explicit Non-goals

Epic 12 does not implement:

```text
Price Index
Fair Value model
Market forecast
Demand forecast
AI recommendations
ML ranking
Supplier composite rating
Broker composite rating
credit scoring
risk scoring
fraud scoring
automatic procurement decisions
automatic sourcing recommendations
currency conversion
FX feed
unit-conversion engine
external commodity-price feed
web scraping
benchmark ingestion
data warehouse
ClickHouse
Elasticsearch
Kafka analytics pipeline
customer analytics portal
billing/revenue recognition
commission calculation
```

---

# 160. Architecture Failure Conditions

Epic 12 is architecturally failed if:

```text
AuditEvent becomes the main analytics source
```

or:

```text
Offer revisions inflate Offer count as separate suppliers
```

or:

```text
USD and EUR are averaged together
```

or:

```text
incompatible quantity units are summed
```

or:

```text
missing delivery date becomes a late delivery
```

or:

```text
small sample produces a "reliable benchmark"
```

or:

```text
Market Activity is labeled Price Index
```

or:

```text
Broker attributed values are summed as unique platform GMV
```

or:

```text
mutable ETA replaces promised Deal delivery baseline for Supplier performance
```

or:

```text
one opaque Supplier/Broker performance score is introduced
```

or:

```text
analytics writes derived rankings back into domain state
```

or:

```text
if commodity == "bitumen"
```

exists in generic intelligence queries.

---

# 161. Epic 12 Review Gate — Metric Semantics

For every metric, reviewer must identify:

```text
source records
cohort timestamp
numerator
denominator
exclusions
unit/currency
missing-data behavior
reliability threshold
```

Any ambiguous metric is a finding.

---

# 162. Review Gate — Procurement

Verify:

- published cohort;
- revisions not counted as Offers;
- award denominator;
- as_of cutoff;
- time-to-first Offer;
- offer/RFQ ratio;
- quote comparability.

---

# 163. Review Gate — Deals

Verify:

- finalized Award date for Deal count/volume;
- Execution close date for completed value;
- commercial product value semantics;
- currency/unit grouping;
- delay semantics.

---

# 164. Review Gate — Supplier Performance

Verify:

- invitation-based response denominator;
- decided-outcome Win Rate;
- Multi-Award;
- promised delivery baseline;
- quality denominator;
- sample guards;
- no composite score.

---

# 165. Review Gate — Broker Performance

Verify:

- explicit provenance only;
- qualification denominator;
- Opportunity-to-Deal conversion;
- distinct Deal attribution;
- multi-role dedup;
- currency grouping;
- non-additivity warning.

---

# 166. Review Gate — Opportunities

Verify:

- captured cohort;
- qualified lifecycle;
- conversion linkage;
- Lost lifecycle;
- active Qualified handling;
- conversion-rate denominator.

---

# 167. Review Gate — Market Activity

Attack:

- mixed currencies;
- mixed units;
- revisions;
- one RFQ with many quotes;
- one counterparty with many quotes;
- different specifications;
- insufficient sample;
- executed value definition;
- fake benchmark/index naming.

---

# 168. Review Gate — Reliability

Verify centralized, consistent handling of:

```text
AVAILABLE
INSUFFICIENT_DATA
NOT_COMPARABLE
NOT_APPLICABLE
```

No UI-only reliability rules that disagree with backend.

---

# 169. Review Gate — Authorization

Verify:

```text
Operator
Product Admin
Buyer
Supplier
Broker
Django staff/superuser only
anonymous
```

Only intended internal actors access Intelligence.

---

# 170. Review Gate — Performance

Review real PostgreSQL query plans for the heaviest dashboard queries on realistic seed data.

Check:

- N+1;
- full-table scans where avoidable;
- duplicate joins inflating counts;
- `distinct` masking semantic join bugs;
- unnecessary JSONB scans.

---

# 171. Review Gate — Contract / UI

Verify:

- OpenAPI accuracy;
- generated TS drift-free;
- correct nullable metrics;
- sample/reliability metadata;
- Persian/RTL;
- chart unit/currency integrity;
- no-data vs insufficient vs error distinction.

---

# 172. Epic Definition of Done

Epic 12 is complete when an Operator can open one dashboard and inspect:

```text
Procurement activity
Deal activity
Supplier performance
Broker performance
Opportunity funnel
Observed market activity
```

and every value is:

```text
derived from authoritative facts
defined by an explicit formula
bounded by time/filter semantics
currency/unit safe
sample-aware
honest when insufficient
```

---

# 173. Long-term Contract Created by Epic 12

After Epic 12:

```text
Intelligence Query Layer
= reproducible read-only metrics over domain truth

Reliability Guard
= centralized protection against misleading small/incomparable samples

Supplier Performance
= separate explainable operational metrics

Broker Performance
= provenance-based conversion/value metrics

Market Activity
= descriptive observed activity, not a price index

Operator Dashboard
= internal view over these explicit metrics
```

---

# 174. Final Architectural Statement

> **Intelligence must summarize what the platform actually knows without pretending to know more. Counts come from authoritative records; rates expose their denominators; money is never mixed across currencies; quantities are never mixed across incompatible units; performance remains decomposed into explainable metrics; and market statistics disappear behind an insufficient-data guard before they become fake benchmarks.**

The Epic 12 foundation must be:

```text
Deterministic
Read-only
Explainable
Sample-aware
Currency-safe
Unit-safe
Provenance-aware
Historically grounded
PostgreSQL-native
Honest about uncertainty
```
