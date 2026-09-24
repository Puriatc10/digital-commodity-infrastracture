# Epic 13 — Demo Quality & Release

## Status

**Authoritative Design Contract**

## Priority

**P0 / P1**

## Epic Branch

```text
codex/epic-13-demo-quality-release
```

## Recommended Document Path

```text
docs/product/epic-13-demo-quality-release-design-contract.md
```

---

# 1. Purpose

Epic 13 is the final product-readiness Epic of the current roadmap.

Its purpose is NOT to introduce a new business domain.

Its purpose is to transform the completed Epics 1–12 into a:

```text
coherent
realistic
repeatable
Persian/RTL
permission-safe
E2E-verifiable
demo-ready
release-ready
```

product experience.

The final product must no longer look or behave like an accumulation of completed Epics.

It must behave like one coherent procurement platform.

---

# 2. Authoritative Inputs

Implementation must be based on:

```text
AGENTS.md
Product Specification
domain glossary
architecture overview
relevant ADRs
delivery roadmap
completed Epic 1–12 implementation
completed Epic Review Gates
current OpenAPI/generated TypeScript contract
current frontend architecture
```

Epic 13 roadmap scope is authoritative for:

```text
T1301 → T1310
```

No business capability outside this Epic's approved scope may be invented merely to improve the Demo.

---

# 3. Source-derived vs Engineering-derived Requirements

The roadmap explicitly requires:

* realistic demo data;
* dedicated 500 MT Bitumen 60/70 Hero Scenario;
* Persian Demo;
* RTL review;
* critical loading/empty/error states;
* permission E2E;
* Hero Playwright flow;
* Demo reset;
* role-aware navigation;
* final Demo QA.

This Design Contract additionally defines engineering constraints necessary to make those roadmap requirements reliable.

These additional constraints are:

> **Derived engineering requirements, not new product business requirements.**

They must not alter earlier product semantics.

---

# 4. Epic 13 Success Definition

Epic 13 is successful when a clean Demo environment can support this coherent product journey:

```text
Buyer
  ↓
RFQ
  ↓
Dynamic Commodity Specification
  ↓
Matching
  ↓
Supplier / Broker Discovery
  ↓
Offers
  ↓
External Opportunity
  ↓
Comparison
  ↓
Revision
  ↓
Award
  ↓
Deal
  ↓
Execution Monitor
  ↓
Intelligence
```

and the same system can demonstrate:

```text
Buyer
Supplier
Broker
Operator
```

using their real existing permissions and domain relationships.

The final state must be believable enough to communicate the actual product architecture without requiring an engineer to explain missing pieces manually.

---

# 5. Core Release Principles

## 5.1 No New Core Business Domain

Epic 13 must not introduce:

```text
new procurement domain
new matching algorithm
new Offer semantics
new Deal semantics
new Execution semantics
new verification model
new analytics model
```

unless required to fix a concrete defect blocking release readiness.

---

## 5.2 No Fake Demo Logic

The Demo must use:

```text
real models
real services
real APIs
real authorization
real UI
real lifecycle transitions
```

Do not create Demo-only shortcuts that bypass domain behavior.

Forbidden examples:

```text
set RFQ status directly
insert Award directly
fake recommendation response
hard-code dashboard numbers
fake Deal object
fake execution timeline
frontend-only permission
```

---

## 5.3 Demo Data Is Domain Data

Seeded Demo data must pass through the same domain model and validation rules as normal application data.

No parallel "presentation database".

---

## 5.4 Demo Must Remain Resettable

Any state introduced by Demo execution must be recoverable through the canonical reset mechanism.

---

## 5.5 Demo Must Be Repeatable

Running:

```text
reset
→ seed
→ Demo
```

multiple times must not progressively corrupt or duplicate the environment.

---

# 6. Demo Environment Boundary

Demo/Development mode must remain distinct from production.

The existing Demo Persona architecture already requires real seeded Users, Organizations, capabilities and SystemRoleAssignments rather than fake roles or Django-superuser equivalence.

Epic 13 must preserve that model.

Demo functionality must never silently activate in normal production configuration.

---

# 7. Demo Personas

The established Demo personas are:

```text
Buyer
Supplier
Broker
Operator
Admin
```

The mandatory permission E2E matrix is:

```text
Buyer
Supplier
Broker
Operator
```

Admin remains available for operational/admin validation where needed.

The Demo accounts must represent real domain state:

```text
User
Organization where appropriate
OrganizationMembership
OrganizationCapability
SystemRoleAssignment where applicable
```

No:

```text
pretendRole
fake permission flag
frontend-only identity
```

---

# 8. Localization Baseline

The application architecture supports:

```text
/fa/...
/en/...
```

but the Demo is explicitly:

```text
/fa
Persian
RTL
```

and user-facing Demo text must be Persian.

English may remain only where it is semantically an intentional technical/proper token, such as:

```text
USD
MT
V1
API identifiers
URLs
machine identifiers
recognized brand/product names
```

There must be no accidental UI English such as:

```text
Loading...
Something went wrong
Submit
Cancel
No data
TODO
Lorem ipsum
```

in the Demo.

---

# 9. UX Baseline

The product is:

> **Enterprise Operations Product**

not Consumer Marketplace.

Therefore the Demo should preserve:

```text
Dense Tables
Workspaces
Filters
Status Badges
Comparison Screens
Side Panels
Timeline
Activity Feed
Operator Efficiency
```

The design is:

```text
Desktop-first
Responsive
not mobile-first
```

This is an existing product direction and Epic 13 must polish rather than replace it.

---

# 10. T1301 — Realistic Seed Dataset

## Objective

Create a realistic, coherent dataset large enough to make:

```text
Trade Hub
RFQ
Matching
Opportunity Desk
Offers
Deals
Execution
Intelligence
```

look populated and internally consistent.

Roadmap minimum:

```text
4 Buyers
8 Suppliers
5 Brokers
20 RFQs
40+ Offers
10 Deals
Opportunities
Execution histories
```

This minimum is mandatory.

---

## 10.1 Dataset Coherence

The seed must not simply create the required number of rows.

Relationships must make business sense.

At minimum:

```text
Buyer
→ owns RFQs

Supplier
→ owns Supplier-capability Organization
→ submits Offers

Broker
→ owns Broker-capability Organization
→ introduces Opportunities

Opportunity
→ has source
→ has ExternalCounterparty where applicable
→ retains Broker attribution

Offer
→ belongs to RFQ
→ has valid economic party

Award
→ references exact OfferVersion

Deal
→ derives from Award

Execution
→ belongs to Deal

Analytics
→ derives from actual underlying records
```

---

## 10.2 Lifecycle Distribution

The dataset should contain records across the currently supported lifecycle states of:

```text
RFQ
Opportunity
Offer
Deal
Execution
```

Do not invent lifecycle values.

Use the existing domain enums/states.

The purpose is to ensure the UI demonstrates:

```text
active
pending
completed
failed/problematic
historical
```

rather than a dataset where everything is in one happy state.

---

## 10.3 Verification Distribution

Seed multiple realistic verification cases using the already-existing verification states.

At least one Demo organization should exercise each meaningful state that affects UI/security behavior.

Do not create a second verification model for Demo.

---

## 10.4 Offer Diversity

Offers should vary across:

```text
price
quantity
currency where supported
delivery
payment completeness
logistics completeness
verification
technical compliance
revision history
```

so that:

```text
Comparison
Decision Support
Unknown
Incomplete cost
Revision
Award eligibility
```

are actually visible.

No hard-coded dashboard statistics.

---

## 10.5 Intelligence Consistency

The seed must cause Epic 12 metrics to derive from real records.

For example:

```text
RFQ count
Offer count
Award rate
Opportunity conversion
Deal value
Execution delay
Supplier performance
Broker contribution
```

must reconcile with the seeded records.

Do not insert metric snapshots merely to make the dashboard look populated.

---

## 10.6 Market Intelligence Guard

The Demo must preserve the existing:

```text
Insufficient data for reliable benchmark
```

behavior.

Never add a fake market-price index solely for visual richness.

---

# 11. T1302 — Hero Scenario Seed

## Objective

Create a deterministic supporting data context for the canonical Hero Demo Scenario:

```text
500 MT Bitumen 60/70
```

The scenario explicitly includes:

```text
Broker-originated external supply
```

as specified by the roadmap and earlier product flow.

---

# 12. Hero Scenario Canonical Story

The Hero Scenario is:

### Step 1 — Buyer

Buyer creates an RFQ:

```text
Commodity:
Bitumen

Specification:
60/70

Quantity:
500 MT
```

The commodity form is rendered from the existing dynamic schema.

No Bitumen-specific RFQ field implementation is permitted.

---

### Step 2 — Matching

The Demo environment provides the intended discovery universe.

Canonical Demo expectation:

```text
7 Supplier candidates
3 Broker candidates
```

The exact numbers are a **Demo-data consistency requirement**, not a production matching guarantee.

---

### Step 3 — Initial Offers

Two internal Suppliers submit Offers.

At least one Offer should have an interesting weakness suitable for Comparison/Decision Support.

---

### Step 4 — Broker Discovery

A Broker introduces an off-network Supply Opportunity.

The Opportunity source is:

```text
Broker Referral
```

Broker attribution must remain traceable.

---

### Step 5 — Opportunity Desk

Operator views the Opportunity and records the external supplier relationship through the existing Opportunity model.

Opportunity example:

```text
OPP-2026-00124
```

The identifier is a Demo narrative reference, not a hard-coded application constant.

---

### Step 6 — Qualification

Operator:

```text
contacts external supplier
records relevant information
performs required verification activity
qualifies Opportunity
```

No direct DB mutation.

---

### Step 7 — External Offer

Operator enters the external commercial quote through the existing Operator-on-behalf Offer flow.

Economic party:

```text
ExternalCounterparty
```

Entering actor:

```text
Operator
```

Broker:

```text
provenance
```

No fake User/Organization is created.

---

### Step 8 — Comparison

At least three competing Offers become visible to the authorized Buyer:

```text
Price
Logistics
Landed Cost
Payment
Delivery
Trust
```

Comparison must remain based on actual Offers.

---

### Step 9 — Revision

Buyer explicitly requests revision.

Supplier provides a new OfferVersion.

The earlier submitted version remains immutable.

History visibly becomes:

```text
V1
→ Revision Request
→ V2
```

---

### Step 10 — Award

Buyer makes an explicit Award.

The system must not silently replace the human decision with a recommendation.

---

### Step 11 — Deal

Award produces the existing Deal flow.

Attribution remains:

```text
Supply Origin:
Broker X

Opportunity:
OPP-2026-00124
```

as supported by the existing Deal/Attribution implementation.

---

### Step 12 — Execution

The Deal reaches representative execution milestones:

```text
Contract Signed
Payment Reported
Loading Completed
Inspection Completed
In Transit
Delivered
Closed
```

These states are monitoring/execution records, not actual payment movement or logistics execution.

---

### Step 13 — Intelligence

After relevant Deal/Execution state:

```text
Executed Price
Supplier Performance
Broker Contribution
Opportunity Conversion
Deal Value
Execution Metrics
```

must update from actual domain data.

The earlier product Hero flow explicitly connects the Deal/Execution outcome to these intelligence views.

---

# 13. Hero Seed vs Hero E2E

The Hero seed must provide the supporting Demo ecosystem.

The Hero Playwright flow should still exercise real UI actions such as:

```text
Create RFQ
Submit Offer
Operate Opportunity
Submit External Offer
Compare
Request Revision
Award
Create/observe Deal
Advance Execution
```

Do not make Playwright pass by pre-inserting the final state into the database.

---

# 14. T1303 — Persian Localization Pass

## Objective

Ensure the Demo surface is consistently Persian.

---

## 14.1 Scope

Review at minimum:

```text
navigation
headers
forms
buttons
tables
filters
dialogs
drawers
notifications
status labels
empty states
loading states
error states
comparison
decision support
negotiation
award
deal
execution
dashboard
```

---

## 14.2 No Unintended English

Search source/localization resources for:

```text
English user-facing literals
TODO
placeholder
Lorem ipsum
demo filler
debug labels
```

Classify intentional English tokens separately.

Do not translate:

```text
machine identifiers
API codes
currency/unit standards
```

where Persian translation would damage semantics.

---

## 14.3 Localization Architecture

Do not solve localization by:

```text
conditional `if locale == fa`
```

throughout components.

Use the existing locale/i18n architecture.

No business logic may depend on translated strings.

---

# 15. T1304 — RTL UX Review

## Objective

Perform a systematic RTL review of the entire Demo.

Required:

```text
tables
forms
filters
sidebars
dropdowns
charts
timeline
dialogs
comparison
activity feeds
cards
pagination
```

These exact areas are called out by the roadmap.

---

## 15.1 RTL Requirements

Verify:

```text
direction
text alignment
logical margins/padding
icon placement
chevrons
breadcrumbs
drawer placement
table columns
pagination
filters
chart labels
timeline progression
```

Use logical layout primitives where appropriate.

Avoid unnecessary hard-coded:

```text
left
right
```

when the component is semantically directional.

---

## 15.2 Data-heavy UI

Mixed content must remain readable:

```text
V1
V2
USD
EUR
MT
500
OPP-2026-00124
dates
```

Do not allow bidirectional text rendering to become ambiguous.

---

# 16. T1305 — Empty / Loading / Error States

## Objective

All critical pages must have explicit state handling.

---

## 16.1 Loading

Every critical asynchronous surface must distinguish:

```text
initial loading
refreshing
action pending
```

No blank-screen loading.

No frozen buttons without feedback.

---

## 16.2 Empty

Differentiate:

```text
legitimately no records
no records for current filter
no historical data
no current DecisionRun
```

Do not show a generic empty table for all cases.

---

## 16.3 Error

At minimum handle:

```text
401
403
404
409 / stale conflict
422 validation
5xx
network failure
timeout
```

where those statuses are applicable to the current API.

---

## 16.4 Security Boundary

Do not convert:

```text
403
```

into:

```text
No data
```

when that would hide a meaningful authorization problem from the user or tester.

Do not leak hidden resource existence.

---

## 16.5 Critical Pages

Minimum QA coverage:

```text
RFQ Workspace
Matching
Opportunity Desk
Offer Comparison
Negotiation History
Deal Workspace
Execution Monitor
Intelligence Dashboard
```

---

# 17. T1306 — Permission E2E Tests

## Objective

Prove that the Demo works using actual permissions rather than UI assumptions.

Mandatory personas:

```text
Buyer
Supplier
Broker
Operator
```

---

# 18. Permission E2E Matrix

At minimum prove:

### Buyer

Can:

```text
access owned RFQs
create/manage permitted RFQs
view permitted Offers
compare Offers
request revision
Award
view owned Deals
```

Cannot:

```text
manage another Buyer RFQ
edit Supplier-owned data
see Operator-private Opportunity information
```

Use the exact already-authorized Product semantics.

---

### Supplier

Can:

```text
view permitted RFQs
manage own Offers
submit Offer
respond to permitted RevisionRequest
view own negotiation history
view own Deal/execution information where permitted
```

Cannot:

```text
see competitor Offers
see competitor negotiation history
use Buyer Decision intelligence
Award
```

---

### Broker

Can:

```text
operate permitted Broker workflows
create/refer Opportunities
see own relevant Opportunity context
participate in permitted Offer flows
```

Cannot:

```text
see competitor commercial intelligence
Award
```

---

### Operator

Can:

```text
Opportunity Desk
qualification
external Offer entry
Operator tools
Deal monitoring
Execution monitoring
operational Intelligence
```

subject to current Product System Role permissions.

---

# 19. Direct URL / API Attack

Permission E2E must not rely only on navigation visibility.

For every critical resource:

```text
visible route
direct route
direct API
```

must produce consistent authorization behavior.

Do not accept:

```text
hidden menu
+
working endpoint
```

as secure.

---

# 20. Cross-Organization Isolation

Test:

```text
Buyer A
Buyer B
Supplier A
Supplier B
Broker A
Broker B
```

and attempt cross-organization access using real IDs.

No horizontal privilege escalation.

---

# 21. T1307 — Hero Playwright E2E

## Objective

Exercise the complete platform journey through the browser.

The roadmap defines:

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

as the Hero E2E.

The earlier product definition extends the final observable outcome into Intelligence.

---

# 22. Browser Environment

The Hero test must start from a clean browser context.

No reliance on:

```text
previous localStorage
previous cookies
previous selected Organization
previous persisted UI state
```

unless that state is intentionally created by the current test.

---

# 23. Hero Persona Sequence

The canonical sequence is:

```text
Buyer
→ Supplier
→ Broker
→ Operator
→ Buyer
```

or the minimum required switching sequence necessary to complete the flow.

Persona transitions must use the established Demo Persona mechanism and real sessions.

No arbitrary impersonation.

---

# 24. Hero Browser Flow

## Buyer

```text
open /fa
→ enter Buyer Demo persona
→ open RFQ Workspace
→ create RFQ
→ select Bitumen
→ enter 60/70 specification
→ enter 500 MT
→ submit/publish
```

Verify UI uses dynamic commodity schema.

---

## Buyer / Matching

```text
open Matching
→ inspect candidates
→ see expected Demo discovery universe
→ no internal opportunity leakage
```

---

## Supplier A

```text
switch to Supplier
→ locate eligible RFQ
→ create Offer
→ submit
```

---

## Supplier B

Repeat with second Supplier.

---

## Broker

```text
switch to Broker
→ introduce Supply Opportunity
→ source = Broker Referral
```

Use existing Opportunity Desk workflow.

---

## Operator

```text
switch to Operator
→ inspect Opportunity
→ contact/qualification
→ verify required fields
→ Qualified
→ enter external Offer
```

Verify:

```text
ExternalCounterparty
≠ Operator
```

---

## Buyer

```text
switch to Buyer
→ Comparison
→ inspect all three Offers
→ inspect normalization
→ inspect technical/trust context
```

No private Opportunity data.

---

## Revision

```text
Request Revision
→ Supplier responds with V2
→ inspect Negotiation History
```

Verify:

```text
V1 unchanged
V2 current
```

---

## Award

```text
Buyer
→ select eligible current OfferVersion
→ finalize Award
```

No automatic recommendation selection.

---

## Deal

Observe/create the existing Deal flow.

Verify:

```text
Award
→ Deal
```

using normal domain behavior.

---

## Execution

Advance representative execution milestones using existing Operator workflows.

No direct DB writes.

---

## Intelligence

Navigate to existing Intelligence surfaces.

Verify metrics reflect the newly created real transaction.

No hard-coded Hero numbers.

---

# 25. Hero Assertions

Playwright must assert business outcomes, not only page presence.

Examples:

```text RFQ exists
Offer submitted
Opportunity Qualified
External Offer submitted
Comparison contains current versions
RevisionRequest exists
V2 submitted
Award finalized
Deal exists
Execution milestones present
Broker attribution preserved
```

---

# 26. T1308 — Demo Reset Script

## Objective

Provide one canonical command to restore the Demo environment.

Preferred conceptual interface:

```text
python manage.py reset_demo
```

or repository-equivalent naming.

Exact command name may be finalized during implementation, but there must be one documented canonical command.

---

# 27. Reset Semantics

Reset must:

```text
remove Demo-owned transactional state
restore canonical Demo seed
restore Persona state
restore Hero supporting state
```

The resulting environment must be equivalent to a fresh Demo seed.

---

# 28. Reset Safety

The command must NOT:

```text
drop production database
delete arbitrary customer data
delete unrelated non-demo data
truncate all tables blindly
```

The command must explicitly detect/require a Demo/Development context.

If production configuration is detected:

```text
refuse
```

before destructive operations.

---

# 29. Reset Atomicity

Prefer:

```text
transaction
→ reset
→ seed
→ validate
→ commit
```

or a safe equivalent.

A failed reset must not leave an obviously broken half-seeded Demo.

---

# 30. Seed/Reset Idempotency

Run:

```text
reset
reset
reset
```

and verify:

```text
same logical dataset
no duplicates
no orphan relationships
same Demo personas
same Hero scenario
```

---

# 31. Seed Version

The Demo fixture must have an explicit version identity.

Conceptually:

```text
DEMO_SEED_VERSION = "..."
```

Changing fixture semantics must produce a new version.

Do not silently mix old and new fixture structures.

---

# 32. E2E Compatibility

Playwright must be able to begin from:

```text
reset_demo
```

without manual database repair.

This is a release-level invariant.

---

# 33. T1309 — Demo Navigation Polish

## Objective

Ensure the application navigation communicates the product structure clearly and respects actual authorization.

---

# 34. Operator Navigation

The established Operator navigation hierarchy is:

```text
Overview

Trade Hub
  Demands
  Supply

Procurement
  RFQs

Market Discovery
  Opportunity Desk

Network
  Companies
  Brokers
  Verification

Deals
  Active Deals
  Execution Monitor

Intelligence
  Market Activity
  Performance

Operations
  Tasks
  Documents
  Issues

Admin
  Commodities
  Users
  Settings
```

This is the existing proposed Operator navigation architecture and should be treated as the baseline rather than replaced with an arbitrary new IA.

---

# 35. Other Personas

Buyer/Supplier/Broker navigation must be role-aware.

Do not invent a separate permission system.

Navigation visibility must follow the already-established backend authorization/capability model.

A hidden link is UX behavior, not security.

---

# 36. Navigation Rules

No user should see a primary navigation item that consistently leads to:

```text
403
404
empty unsupported surface
```

unless that behavior is intentionally part of the Product design.

---

# 37. Demo Navigation Coherence

The navigation should communicate the actual platform structure:

```text
Trade Hub
Procurement
Market Discovery
Deals
Execution
Intelligence
Operations
```

without making the Demo feel like unrelated applications glued together.

---

# 38. T1310 — Final Demo QA

## Objective

Perform a complete release-readiness review after T1301–T1309.

This is NOT another feature task.

It is a release-quality verification pass.

---

# 39. Backend QA

Verify:

```text
Django system check
migration consistency
full backend test suite
OpenAPI validation
generated TypeScript drift
seed/reset
```

against PostgreSQL.

---

# 40. UI QA

Review:

```text
RFQ
Matching
Opportunity Desk
Offers
Comparison
Negotiation
Award
Deal
Execution
Intelligence
```

for:

```text
visual consistency
Persian localization
RTL
loading
empty
error
permission state
responsive behavior
console errors
broken navigation
```

---

# 41. Data QA

Verify:

```text
Demo counts
relationships
attribution
Offer history
Award references
Deal references
Execution references
analytics reconciliation
```

No orphaned or obviously synthetic inconsistencies.

---

# 42. Permission QA

Run the full Demo persona matrix.

Check:

```text
Buyer
Supplier
Broker
Operator
Admin where relevant
```

and cross-organization access.

---

# 43. Hero Flow QA

Run the complete Hero Scenario from reset.

Do not use direct DB manipulation.

Record exact result.

---

# 44. Audit QA

Verify important actions preserve the existing audit model.

At minimum:

```text
RFQ
Offer
Revision
Award
Deal
Execution
Opportunity
```

where audit is already required by the completed Epics.

---

# 45. Performance Basics

This is not a performance-engineering Epic.

The goal is to detect obvious release blockers:

```text
N+1 queries
repeated API storms
obviously excessive dashboard queries
slow page caused by accidental recursion
large uncontrolled payloads
browser console/runtime errors
```

Do not introduce Redis, Elasticsearch, Kafka, Celery or other infrastructure merely to improve Demo performance.

---

# 46. Market Intelligence Integrity

Review:

```text
Average Quote
Min Quote
Max Quote
Quote Spread
Requested Volume
Awarded Volume
Executed Price
```

and related metrics.

If the available data does not support a benchmark:

```text
Insufficient data for reliable benchmark
```

must remain the behavior.

No fake price index.

---

# 47. Final Repository Hygiene

Before release:

```text
git status
git diff --check
```

No:

```text
debug files
SQLite artifacts
temporary scripts
screenshots
local database files
credentials
secrets
generated junk
```

---

# 48. CI / Contract QA

Mandatory:

```text
backend tests
frontend tests
lint
typecheck
production build
OpenAPI generation/validation
TypeScript generation
TypeScript drift check
Playwright Hero E2E
```

Every test counted toward Epic 13 Definition of Done must be reachable from canonical CI.

A manually-run test outside CI does not count as release evidence.

---

# 49. Browser Release Environment

The final Demo must be tested from:

```text
clean browser
fresh session
Demo seed
/fa
```

and not merely from the developer's already-populated browser.

---

# 50. No Fake Success

The following do NOT qualify as release evidence:

```text
screenshots of intended UI
manual DB inserts
mock API responses
hard-coded fixture responses
passing unit test with fake permission
```

Release evidence must represent actual integrated behavior.

---

# 51. Release Candidate Invariants

The final release candidate must preserve all major invariants from previous Epics, especially:

```text
server-side authorization
cross-organization isolation
dynamic commodity schemas
historical schema integrity
ExternalCounterparty semantics
Broker attribution
OfferVersion immutability
UNKNOWN ≠ zero
no implicit FX
DecisionRun reproducibility
Revision base-version integrity
Award exact-version integrity
Deal snapshot integrity
Execution monitoring boundary
Insufficient-data benchmark guard
```

Epic 13 must not weaken any of these merely to improve the Demo.

---

# 52. Critical Release Failure Conditions

Epic 13 is NOT Ready when any of the following is true:

```text
Hero Flow cannot complete from reset
Hero Flow requires direct DB manipulation
permission bypass exists
competitor data leaks between personas
Demo seed produces inconsistent relationships
reset duplicates or corrupts data
English placeholder text remains on core Demo surfaces
major RTL layout failure exists
critical pages have missing error handling
analytics values are hard-coded
market benchmark is fabricated
OpenAPI/TypeScript drift exists
canonical tests are red
Playwright Hero is red
production build fails
migration drift exists
secret/debug artifact exists
```

---

# 53. Cosmetic vs Release-blocking Defects

Minor visual polish must not be confused with business/release blockers.

### Release-blocking

```text
security
permissions
data integrity
Hero Flow failure
broken reset
broken migration
broken build
broken canonical CI
historical corruption
hard-coded business result
```

### Non-blocking unless widespread

```text
minor spacing
small visual inconsistencies
non-critical copy refinement
```

This distinction prevents Epic 13 from becoming an endless redesign.

---

# 54. Scope Boundary

Epic 13 must NOT become:

```text
new feature development
architecture rewrite
new domain modeling
new analytics engine
new matching algorithm
new authorization system
design-system rewrite
mobile-first redesign
performance infrastructure project
deployment platform rewrite
```

Only concrete release-blocking defects may justify touching previously completed domains.

---

# 55. Recommended Sequential Execution Order

The roadmap numbers the Tasks sequentially:

```text
T1301 → T1310
```

The recommended implementation order for integration safety is:

```text
T1301
↓
T1302
↓
T1308
↓
T1303
↓
T1304
↓
T1305
↓
T1309
↓
T1306
↓
T1307
↓
T1310
```

Rationale:

```text
T1301
→ establishes realistic dataset

T1302
→ establishes Hero-specific data

T1308
→ makes Demo state reproducible before E2E work

T1303/T1304/T1305
→ stabilize the actual UX surface

T1309
→ stabilizes role-aware navigation

T1306
→ proves permission behavior

T1307
→ proves the complete integrated Hero flow

T1310
→ final QA after everything else is stable
```

This is an engineering ordering recommendation, not a change to roadmap Task IDs.

---

# 56. Git Workflow

Epic 13 uses the established sequential workflow:

```text
one Task
→ implementation
→ validation
→ commit
→ push
→ PR
→ human review
→ merge into Epic branch
→ next Task
```

No parallel Epic 13 implementation lanes.

---

# 57. Task Branch Pattern

Use:

```text
antigravity/t1301-realistic-demo-seed
antigravity/t1302-hero-scenario-seed
antigravity/t1308-demo-reset
...
```

with target:

```text
codex/epic-13-demo-quality-release
```

Do not target `master`.

---

# 58. Definition of Done — Every Epic 13 Task

A Task is Done only when:

* roadmap scope is implemented;
* acceptance behavior is tested;
* changes remain task-scoped;
* no unrelated refactor is introduced;
* generated contracts are synchronized where relevant;
* canonical CI discovers new automated tests;
* Demo behavior is reproducible;
* documentation is updated where required.

---

# 59. Epic-level Definition of Done

Epic 13 is Done only when:

## Data

```text
4 Buyers
8 Suppliers
5 Brokers
20 RFQs
40+ Offers
10 Deals
multiple Opportunities
verification coverage
execution histories
```

exist coherently.

## Hero

```text
500 MT Bitumen 60/70
```

can complete the full Demo journey with Broker-originated external supply.

## UX

```text
Persian
RTL
role-aware navigation
critical states
```

are complete.

## Security

```text
Buyer
Supplier
Broker
Operator
```

permission E2E passes.

## Automation

Hero Playwright E2E passes from a clean reset state.

## Reproducibility

Reset → seed → Hero works repeatedly.

## Engineering

```text
migrations clean
backend tests green
frontend tests green
lint green
typecheck green
production build green
OpenAPI clean
TypeScript generation deterministic
```

## Data integrity

Dashboard and market intelligence reflect real underlying Demo data.

## Hygiene

Repository clean.

---

# 60. Final Release Gate

After T1310, run a dedicated:

```text
Epic 13 Final Release Gate
```

This is a Gate, not another roadmap Task.

It must verify:

```text
clean checkout
fresh PostgreSQL
reset_demo
seed
clean browser
/fa
Hero Playwright
permission matrix
full regression
OpenAPI
TypeScript
build
repository hygiene
```

---

# 61. Final Release Verdict

Exactly one:

```text
EPIC 13 — READY FOR DEMO / RELEASE
```

or:

```text
EPIC 13 — NOT READY
```

No conditional release.

---

# 62. Final Demo Narrative

The final Demo should communicate the platform in this order:

```text
1. Buyer need
2. Dynamic RFQ
3. Matching / Network
4. Broker as sourcing path
5. Opportunity Desk
6. External supplier
7. Offer comparison
8. Negotiation
9. Award
10. Deal
11. Execution
12. Intelligence
```

This follows the project's original Hero Flow and makes the Broker/Opportunity infrastructure visible rather than treating it as an internal implementation detail.

---

# 63. Product Story the Demo Must Communicate

The Demo must make these architectural ideas obvious without requiring explanation:

```text
Marketplace
≠
Platform
```

```text
Broker
≠
Supplier
```

```text
Opportunity
≠
Supply Listing
```

```text
Matching
≠
Decision
```

```text
Recommendation
≠
Award
```

```text
Award
≠
Deal
```

```text
Execution Monitor
≠
Payment Platform
```

These distinctions are central to the existing product direction.

---

# 64. Final Non-goals

Epic 13 does not introduce:

```text
real payment movement
settlement
escrow
financing
insurance
automated logistics execution
AI recommendation engine
new matching intelligence
real KYC provider
real market exchange feed
production impersonation
new marketplace model
new pricing engine
new Deal model
new execution domain
```

The Demo must showcase the completed platform rather than changing what the platform fundamentally is.

---

# 65. Design Contract Change Rule

Any proposed change to an Epic 13 invariant requires explicit owner approval.

Do not silently weaken an earlier Epic's security/domain behavior because:

```text
the Demo is easier
the E2E is flaky
the seed is inconvenient
the UI needs a shortcut
```

The correct response is to fix the Demo integration around the existing domain truth.

---

# 66. Release Philosophy

The target is not:

> "Every screen looks perfect."

The target is:

> **A coherent, believable, reproducible end-to-end procurement platform whose critical business and security behavior is real.**

The project reaches its first meaningful Demo milestone when:

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

works as one system.
