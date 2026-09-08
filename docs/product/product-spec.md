# Final Product Specification

## B2B Commodity Procurement & Trade Platform — Demo / Pilot-Ready v1

---

# 1. Product Vision

هدف محصول ساخت یک **B2B Commodity Procurement & Trade Platform** است که بتواند:

* Demand و Supply را از Network و Market Discovery جمع‌آوری کند.
* RFQ و Supply Opportunity را به داده ساختاریافته تبدیل کند.
* Buyer را به Supplier و Broker مناسب متصل کند.
* Offerها را Normalize، Compare و Evaluate کند.
* Negotiation و Award را مدیریت کند.
* Deal Attribution را حفظ کند.
* اجرای معامله را از طریق یک **Execution Monitor** قابل مشاهده و قابل پیگیری کند.
* از RFQ، Offer، Deal و Execution Data یک لایه Trust و Intelligence بسازد.

Commodity اولیه در Demo:

> **Bitumen**

اما Data Architecture باید از ابتدا برای Commodityهای دیگر قابل توسعه باشد.

محصول نباید از ابتدا یک Generic Commodity Platform کامل باشد.

---

# 2. Product Positioning

محصول یک Marketplace ساده نیست.

Positioning:

> **Procurement + Market Discovery + Deal Orchestration + Execution Visibility + Transaction Intelligence**

معماری مفهومی:

```text
                    TRADE HUB
               Supply ↔ Demand
                      │
                      ▼
               PROCUREMENT ENGINE
                      │
              Matching / Comparison
                      │
            ┌─────────┴──────────┐
            │                    │
      Existing Network      MARKET DISCOVERY
                            Opportunity Desk
            │                    │
            └─────────┬──────────┘
                      ▼
                 QUALIFIED DEAL
                      │
                      ▼
               EXECUTION MONITOR
                      │
                      ▼
                 COMPLETED DEAL
                      │
                      ▼
          DATA / TRUST / INTELLIGENCE
```

---

# 3. Core Business Principles

## 3.1. Marketplace is not the final product

Trade Hub فقط نقطه ورود Supply و Demand است.

ارزش اصلی از:

* Procurement Workflow
* Market Discovery
* Decision Support
* Deal Execution Visibility
* Structured Data

ایجاد می‌شود.

---

## 3.2. Brokers are participants, not enemies

Business Actor رسمی:

* Buyer
* Supplier
* Broker

مفهوم Trader در محصول استفاده نمی‌شود.

Broker می‌تواند:

* Demand معرفی کند.
* Supply معرفی کند.
* به RFQ پاسخ دهد.
* Opportunity ایجاد کند.
* Source یک Deal باشد.

Platform نباید Broker را مجبور کند Network خصوصی خود را تحویل دهد.

---

## 3.3. Human-in-the-loop is intentional

Market Discovery در Pilot عمداً Human-Assisted است.

Operator بخشی از Product است.

هدف اولیه:

> Support operators, not replace them.

---

## 3.4. Transaction Layer is monitoring-first

نسخه Demo و Pilot نباید ادعا کند Transaction را Execute می‌کند.

فعلاً:

> **Execution Monitor**

داریم.

یعنی:

* Visibility
* Status Tracking
* Logistics Monitoring
* Quality Monitoring
* Document Tracking
* Issue Tracking

ولی:

* Payment execution
* Escrow
* Financing
* Insurance
* Real logistics execution

نداریم.

---

# 4. Users and Actors

## 4.1. Buyer

می‌تواند:

* RFQ ایجاد کند.
* Supplier/Broker دعوت کند.
* Offers را مشاهده کند.
* Offers را Compare کند.
* Revision درخواست کند.
* Offer را Award کند.
* Deal و Execution را مشاهده کند.
* Documents و Issues مرتبط را ببیند.

---

## 4.2. Supplier

می‌تواند:

* Supply Listing ایجاد کند.
* RFQهای دعوت‌شده را مشاهده کند.
* Offer ثبت کند.
* Offer Revision ارسال کند.
* Dealهای خود را مشاهده کند.
* Execution statusهای مربوط به خود را مشاهده کند.

---

## 4.3. Broker

می‌تواند:

* RFQهای مرتبط را ببیند.
* Supply یا Demand Opportunity معرفی کند.
* Offer ارائه کند.
* Supply source معرفی کند.
* Dealهای attributed به خود را مشاهده کند.

Broker مالک دائمی Customer نیست.

Attribution باید Deal/Opportunity-specific باشد.

---

## 4.4. Operator

یکی از مهم‌ترین Actorهای محصول.

می‌تواند:

* RFQ را Qualify کند.
* Supplier/Broker Match کند.
* Participant دعوت کند.
* Opportunity ایجاد کند.
* External Counterparty ثبت کند.
* Contact Attempt ثبت کند.
* Opportunity را Qualify کند.
* Offer را به نمایندگی Counterparty ثبت کند.
* Verification را بررسی کند.
* Deal را مدیریت کند.
* Execution Monitor را Update کند.
* Documents و Issues را مدیریت کند.
* Internal Note ثبت کند.

---

## 4.5. Admin

مسئول:

* User Management
* Organization Management
* Commodity Definitions
* Verification Rules
* Permissions
* System Settings
* Audit access

است.

---

# 5. Organization Model

Organization نباید فقط یک Role داشته باشد.

مثلاً یک Company می‌تواند:

```text
Buyer
Supplier
```

باشد.

مدل:

```text
Organization

OrganizationCapability
- Buyer
- Supplier
- Broker
```

Operator و Admin:

> System Roles

هستند.

Buyer / Supplier / Broker:

> Business Capabilities

هستند.

---

# 6. Dynamic Commodity Architecture

این یکی از Architectural Invariantهای اصلی پروژه است.

## Rule

هیچ Commodity-specific field نباید مستقیماً در RFQ، Offer یا Deal Table Hard-code شود.

مثلاً این اشتباه است:

```text
RFQ.grade
RFQ.softening_point
RFQ.penetration
```

---

# 7. Hybrid Data Model

## Static Relational Fields

فیلدهایی که بین Commodityها تقریباً مشترک‌اند:

* Commodity
* Quantity
* Unit
* Currency
* Origin
* Destination
* Delivery Window
* Incoterm
* Payment Terms
* Organization
* Price
* Status

Relational ذخیره می‌شوند.

---

## Dynamic Specifications

Commodity-specific fields در JSONB ذخیره می‌شوند.

مثلاً Bitumen:

```json
{
  "penetration_grade": "60/70",
  "softening_point": 49,
  "penetration": 65
}
```

Base Oil:

```json
{
  "base_oil_group": "Group I",
  "viscosity_grade": "SN500",
  "viscosity_40c": 96
}
```

---

# 8. Commodity Definition Model

```text
CommodityDefinition
- id
- code
- name
- active_schema_version_id

CommoditySchemaVersion
- id
- commodity_id
- version
- status

CommodityAttributeDefinition
- id
- schema_version_id
- key
- label
- data_type
- unit_family
- allowed_units
- required
- enum_options
- validation_rules
- display_group
- sort_order
```

---

# 9. Schema Versioning

هر RFQ / Supply / Offer باید Schema Version مورد استفاده را ذخیره کند.

مثلاً:

```text
Commodity:
Bitumen

Schema Version:
1
```

اگر بعداً Specification تغییر کرد:

```text
Schema Version:
2
```

ایجاد می‌شود.

Historical Data نباید با تغییر Schema جدید معنی‌اش تغییر کند.

---

# 10. Dynamic Form Rendering

Frontend باید Form را از Commodity Definition تولید کند.

مثلاً Bitumen Form:

```text
Penetration Grade
Softening Point
Penetration
Flash Point
...
```

اما Fieldها در Component Hard-code نشوند.

Backend نیز همان Specification Schema را Validate می‌کند.

Validation Layer:

> JSON Schema

---

# 11. Trade Hub

Trade Hub شامل دو سمت است:

## Demand

RFQها.

## Supply

Supply Listings.

Visibility:

* Private
* Network
* Public

---

# 12. RFQ

RFQ شامل:

## Product

* Commodity
* Dynamic Specifications
* Quantity
* Unit

## Commercial

* Currency
* Target Price optional
* Payment Terms
* Incoterm

## Delivery

* Origin
* Destination
* Delivery Window

## Quality

* Dynamic Specification
* Inspection Requirement

## Participation

* Private
* Network
* Public

## Invitations

Buyer یا Operator می‌تواند Counterpartyها را Invite کند.

---

# 13. RFQ Workspace

هر RFQ یک Workspace مستقل دارد.

Tabs:

* Overview
* Participants
* Offers
* Comparison
* Negotiation
* Activity
* Documents

Participant status:

```text
Invited
Viewed
Responded
Offer Submitted
Declined
Expired
```

---

# 14. Supply Listing

Supplier یا Operator می‌تواند Supply ثبت کند.

شامل:

* Commodity
* Dynamic Specifications
* Quantity
* Origin
* Availability Window
* Indicative Price
* Commercial Terms
* Visibility

Supply Listing رسمی با Opportunity متفاوت است.

---

# 15. Matching Engine v1

نسخه اول Rule-Based است.

Matching criteria:

* Commodity
* Dynamic Specifications
* Geography
* Organization Capability
* Historical Participation
* Verification Level
* Previous Relationship
* Availability
* Past Performance

نتیجه:

```text
Supplier A — 92%
Broker B — 84%
Supplier C — 79%
```

هر Score باید Explainable باشد.

مثلاً:

```text
Commodity Match
Geography Match
Verified
Previous Successful Deal
```

AI Fake Scoring ممنوع است.

---

# 16. Market Discovery

نام Capability:

> **Market Discovery**

Workspace عملیاتی:

> **Opportunity Desk**

---

# 17. Opportunity Desk

Opportunity Desk یک Human-Assisted Market Discovery Workspace است.

Opportunity Direction:

* Supply
* Demand

Opportunity ID:

```text
OPP-2026-000124
```

---

# 18. Opportunity Sources

Possible Sources:

* Broker Referral
* Buyer Referral
* Supplier Referral
* Operator Sourcing
* Existing Relationship
* Inbound Lead
* Other

اگر Source = Broker:

```text
OriginatingBrokerId
```

ذخیره می‌شود.

---

# 19. Opportunity Data

حداقل:

* Opportunity ID
* Direction
* Commodity
* Dynamic Specifications
* Quantity
* Geography
* Indicative Price
* Delivery Window
* Payment Terms
* Source
* Originating Broker
* External Counterparty
* Confidentiality
* Urgency
* Confidence
* Assigned Operator
* Notes
* Contact Attempts
* Verification Status
* Expiration
* Related RFQ
* Related Supply Listing
* Related Deal

---

# 20. Opportunity Lifecycle

```text
Captured
   ↓
Contacted
   ↓
Qualified
   ↓
Matching
   ↓
Converted
```

Alternative statuses:

```text
On Hold
Rejected
Lost
Expired
```

---

# 21. External Counterparty

Operator باید بتواند Party خارج از Platform ایجاد کند.

مثلاً:

```text
ExternalCounterparty
- Name
- Company Name
- Phone
- Email
- Geography
- Notes
- Source
```

External Counterparty الزاماً Account ندارد.

بعداً:

> Convert to Organization

امکان‌پذیر است.

---

# 22. Opportunity Actions

Operator بتواند:

* Opportunity ایجاد کند.
* Contact Attempt ثبت کند.
* Follow-up Task ایجاد کند.
* Broker attribution ثبت کند.
* External Counterparty اضافه کند.
* Documents اضافه کند.
* Opportunity را Qualify کند.
* به RFQ متصل کند.
* به Supply Listing تبدیل کند.
* Offer به نمایندگی Party ثبت کند.
* Lost / Rejected / Expired کند.

---

# 23. Matching + Opportunity

Matching Engine فقط Registered Organizations را نمی‌بیند.

Sources:

```text
Registered Suppliers
Brokers
Supply Listings
Qualified Opportunities
```

مثلاً:

```text
6 Network Matches
2 Broker Matches
1 Qualified Market Opportunity
```

---

# 24. Offer

Offer شامل:

* Price
* Currency
* Quantity Offered
* Incoterm
* Origin
* Delivery
* Payment Terms
* Logistics Cost
* Inspection Terms
* Dynamic Specifications
* Valid Until
* Notes

Supplier یا Broker می‌تواند Submit کند.

Operator نیز می‌تواند:

> Submit on behalf of Counterparty

---

# 25. Offer Versioning

Negotiation نباید Offer قبلی را Overwrite کند.

```text
Offer
 ├── V1
 ├── V2
 └── V3
```

Historical versions باید قابل مشاهده باشند.

---

# 26. Offer Normalisation

نسخه اولیه:

```text
Product Price
+
Logistics Cost
+
Known Additional Costs
=
Landed Cost
```

Comparison باید:

* Headline Price
* Landed Cost
* Payment
* Delivery
* Trust
* Quality
* Verification

را کنار هم نشان دهد.

---

# 27. Decision Support

سیستم می‌تواند Score محاسبه کند.

مثلاً:

```text
Price        40%
Delivery     20%
Payment      15%
Reliability  15%
Quality      10%
```

Weights بعداً configurable می‌شوند.

سیستم فقط Recommendation می‌دهد.

نه Decision قطعی.

---

# 28. Negotiation

Actions:

* Request Revision
* Submit Revised Offer
* View Offer History

Chat کامل در v1 لازم نیست.

---

# 29. Award

Buyer یا Operator می‌تواند Offer را Award کند.

قبل از Award:

* Supplier
* Final Price
* Quantity
* Total Value
* Delivery
* Payment Terms
* Attribution
* Conditions

Review می‌شوند.

پس از Award:

> Deal

ساخته می‌شود.

---

# 30. Deal Attribution

Deal باید Origin را ثبت کند.

Possible Sources:

* Platform Network
* Direct Supplier
* Broker
* Opportunity Desk
* Buyer Existing Supplier
* Other

اگر Broker دخیل است:

```text
Demand Originator
Supply Originator
Broker
Opportunity Source
```

ثبت می‌شود.

Attribution:

> Deal-specific

است.

---

# 31. Deal Workspace

Tabs:

* Overview
* Terms
* Parties
* Attribution
* Execution
* Logistics
* Quality
* Documents
* Issues
* Activity

---

# 32. Execution Monitor

نسخه فعلی Monitoring Layer است.

Streams:

## Commercial

* Contract Status
* Final Terms

## Payment Monitoring

فقط:

```text
Payment Expected
Payment Reported
Payment Confirmed
```

Platform Payment را Execute نمی‌کند.

## Logistics

* Transport Mode
* Carrier
* Pickup
* Destination
* Scheduled Loading
* Actual Loading
* ETA
* Actual Delivery
* Tracking Reference
* Logistics Cost

## Quality

* Inspection Required
* Agency
* Inspection Date
* Status
* Result

## Documents

* Contract
* Invoice
* COA
* Inspection Report
* Weight Certificate
* Shipping Documents

## Issues

* Quality
* Delay
* Quantity
* Document
* Other

---

# 33. Execution Workflow

Workflow نباید کاملاً Hard-coded باشد.

Data Model:

```text
ExecutionWorkflowTemplate

ExecutionMilestoneDefinition

ExecutionMilestone
```

Bitumen initial workflow:

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

در Demo Workflow Builder UI لازم نیست.

---

# 34. Verification / KYB

Statuses:

```text
Unverified
Documents Submitted
Under Review
Basic Verified
Verified
Suspended
```

Documents:

* Company Registration
* Tax ID
* Trade License
* Bank Details
* Authorized Representative
* Certifications

Verification فعلاً Manual است.

Real KYC Provider Integration نداریم.

---

# 35. Documents

Actual files:

> Object Storage

Database فقط Metadata را ذخیره می‌کند.

```text
Document
- id
- file_name
- object_key
- mime_type
- type
- uploaded_by
- verification_status
- created_at
```

---

# 36. Issues

Issue Types:

* Quality
* Quantity
* Logistics
* Payment
* Document
* Contract
* Other

Statuses:

```text
Open
Investigating
Resolved
Rejected
```

---

# 37. Supplier Performance

Metrics:

* Response Rate
* Win Rate
* Average Response Time
* On-Time Delivery
* Quality Pass Rate
* Deals Completed
* Average Price Position

این اطلاعات بعداً Trust Layer را تقویت می‌کند.

---

# 38. Broker Performance

Metrics قابل ثبت:

* Opportunities Introduced
* Qualified Opportunity Rate
* RFQ Response Rate
* Deals Attributed
* Deal Conversion
* Total Deal Value
* Network Contribution

---

# 39. Intelligence Dashboard

Demo Dashboard شامل:

* Active RFQs
* Offers Received
* Deals in Negotiation
* Active Deals
* Completed Deal Value
* Average Time to First Offer
* Average Offers per RFQ
* Quote Spread
* Award Rate
* Opportunity Conversion Rate
* Execution Delays
* Recent Activity

---

# 40. Market Intelligence

Demo می‌تواند:

* Average Quote
* Min Quote
* Max Quote
* Quote Spread
* Requested Volume
* Awarded Volume
* Executed Price

را نمایش دهد.

ولی اگر Data کافی نیست:

> Insufficient data for reliable benchmark

نمایش داده شود.

Price Index Fake ممنوع است.

---

# 41. Tasks and Notifications

Notifications:

* New RFQ
* New Offer
* Offer Expiring
* Supplier Has Not Responded
* Revision Received
* Deal Awarded
* Missing Document
* Delivery Delay
* Issue Opened

Operator Task Management نیز وجود داشته باشد.

---

# 42. Internal Notes

Operator بتواند روی:

* Organization
* Opportunity
* RFQ
* Deal

Internal Note ثبت کند.

Internal Notes برای Customer قابل مشاهده نیست.

---

# 43. Audit Trail

Events مهم باید ثبت شوند.

```text
Who
What
When
Old Value
New Value
```

Audit برای:

* Verification
* RFQ
* Offer
* Award
* Deal
* Execution

ضروری است.

---

# 44. Search and Filters

Global Search:

* Organizations
* Opportunities
* RFQs
* Deals

Filters:

* Commodity
* Organization
* Status
* Geography
* Verification
* Date
* Buyer
* Supplier
* Broker

---

# 45. Internationalization

Architecture از روز اول Locale-aware است.

Target languages:

* Persian
* English

Demo:

> Persian only

Routing:

```text
/fa/...
/en/...
```

Demo فقط `/fa` فعال خواهد بود.

Direction:

```text
fa → RTL
en → LTR
```

هیچ User-facing Text نباید داخل reusable component hard-coded باشد.

---

# 46. Frontend UX Direction

Frontend:

> Enterprise Operations Product

نه Consumer Marketplace.

Design priorities:

* Dense Tables
* Workspaces
* Filters
* Status Badges
* Comparison Screens
* Side Panels
* Timeline
* Activity Feed
* Operator Efficiency

Desktop-first.

Responsive باشد، ولی Mobile-first نیست.

---

# 47. Demo Personas

Demo accounts:

```text
Buyer
Supplier
Broker
Operator
Admin
```

Development / Demo Mode می‌تواند:

> Switch Persona

داشته باشد.

فقط در Demo/Development.

---

# 48. Demo Seed Data

حداقل:

* 4 Buyers
* 8 Suppliers
* 5 Brokers
* 20 RFQs
* 40+ Offers
* 10 Deals
* Multiple Opportunities
* Verification cases
* Execution histories

Data باید coherent و realistic باشد.

---

# 49. Hero Demo Scenario

## Step 1

Buyer:

> 500 MT Bitumen 60/70

RFQ ایجاد می‌کند.

---

## Step 2

Dynamic Commodity Form براساس Bitumen Schema Render می‌شود.

---

## Step 3

Matching:

```text
7 Suppliers
3 Brokers
```

---

## Step 4

دو Supplier Offer ارسال می‌کنند.

Broker یک Supply خارج Network معرفی می‌کند.

---

## Step 5

Operator:

```text
OPP-2026-00124
```

ایجاد می‌کند.

Source:

> Broker Referral

---

## Step 6

External Supplier ثبت می‌شود.

Opportunity:

> Qualified

می‌شود.

---

## Step 7

Operator Offer را به نمایندگی External Supplier ثبت می‌کند.

---

## Step 8

سه Offer Normalize می‌شوند.

Comparison:

* Price
* Logistics
* Landed Cost
* Payment
* Delivery
* Trust

---

## Step 9

Buyer Revision درخواست می‌کند.

Supplier V2 Offer ثبت می‌کند.

---

## Step 10

Buyer Offer مناسب را Award می‌کند.

---

## Step 11

Deal ساخته می‌شود.

Attribution:

```text
Supply Origin:
Broker X

Opportunity:
OPP-2026-00124
```

---

## Step 12

Execution Monitor:

```text
Contract Signed
Payment Reported
Loading Completed
Inspection Completed
In Transit
Delivered
Closed
```

---

## Step 13

Dashboard Update می‌شود:

* Executed Price
* Supplier Performance
* Broker Contribution
* Opportunity Conversion
* Deal Value
* Execution Metrics

---

# 50. Backend Stack

## Framework

> **Django 6**

## API

> Django REST Framework

## Database

> PostgreSQL

## Dynamic Specifications

> PostgreSQL JSONB + Versioned JSON Schema

## Validation

> JSON Schema validation

## Object Storage

> S3-compatible

Demo:

> MinIO

## API Style

> REST + OpenAPI

---

# 51. Backend Architecture

Architecture:

> **Modular Monolith**

Suggested modules:

```text
identity
organizations
commodities
trade_hub
procurement
opportunities
matching
offers
deals
execution
verification
documents
analytics
notifications
audit
```

Domain boundaries باید واضح باشند.

Microservices در v1 ممنوع است.

---

# 52. Frontend Stack

> Next.js + TypeScript

UI:

* Tailwind CSS
* shadcn/ui

Frontend باید مستقل از Backend implementation باشد.

API Contract:

> OpenAPI

---

# 53. Repository Structure

Monorepo:

```text
commodity-platform/

apps/
  web/
  api/

docs/
  product/
  domain/
  architecture/
  adr/

infra/
  docker/

scripts/

README.md
docker-compose.yml
```

---

# 54. Persistence Principles

PostgreSQL Source of Truth اصلی است.

Do not introduce:

* MongoDB
* Graph DB
* Elasticsearch

در v1.

Search اولیه با PostgreSQL انجام می‌شود.

---

# 55. Event Architecture

فعلاً:

> In-process Domain Events

Examples:

```text
RFQPublished
OfferSubmitted
OpportunityQualified
DealAwarded
ExecutionMilestoneCompleted
```

Message Broker در v1 نداریم.

---

# 56. Explicit Non-Goals

Demo / Pilot v1 نباید شامل موارد زیر باشد:

* AI Agent
* AI Matching
* Price Prediction
* Blockchain
* Escrow
* Real Payment Processing
* Trade Finance
* Insurance
* Full Logistics Marketplace
* ERP Integration
* GPS Integration
* IoT
* Complex Accounting
* Mobile App
* Multi-language UI beyond Persian Demo
* Generic Commodity Builder UI
* Microservices
* Kafka
* RabbitMQ
* Redis unless justified later
* Elasticsearch
* Kubernetes
* Temporal
* Event Sourcing

---

# 57. Architectural Invariants

## Invariant 1

> Commodity-specific fields must never be hard-coded into core domain tables.

---

## Invariant 2

> Dynamic commodity specifications must use versioned schema definitions.

---

## Invariant 3

> The initial UI may be Bitumen-focused, but underlying data structures must remain commodity-extensible.

---

## Invariant 4

> Market Discovery remains human-assisted during Pilot.

---

## Invariant 5

> Execution Monitor provides visibility and orchestration only; the platform does not execute settlement, financing, insurance or logistics.

---

## Invariant 6

> Broker attribution must be preserved at Opportunity and Deal level.

---

## Invariant 7

> User-facing frontend text must be localization-ready from day one.

---

## Invariant 8

> Authorization must be enforced server-side.

---

## Invariant 9

> PostgreSQL is the source of truth.

---

## Invariant 10

> Do not introduce infrastructure or architectural complexity without a demonstrated requirement.

---

# 58. Demo Definition of Done

Hero Flow باید end-to-end قابل اجرا باشد:

```text
Buyer RFQ
→ Dynamic Commodity Form
→ Matching
→ Broker / Supplier Participation
→ Opportunity Desk
→ Offer Submission
→ Normalisation
→ Negotiation
→ Award
→ Deal
→ Execution Monitor
→ Intelligence Update
```

بدون Manual Database Editing.

---

# 59. Quality Requirements

هر Feature باید:

* Authorization داشته باشد.
* Validation داشته باشد.
* Error State داشته باشد.
* Empty State داشته باشد.
* Loading State داشته باشد.
* Auditability در صورت نیاز داشته باشد.
* Tests مناسب داشته باشد.

---

# 60. Testing Strategy

## Backend

* Business Rule Unit Tests
* API Tests
* PostgreSQL Integration Tests

## Frontend

* Critical Component Tests

## E2E

Playwright برای Hero Flow.

Critical E2E:

```text
Create RFQ
→ Match
→ Create Opportunity
→ Submit Offers
→ Compare
→ Revise
→ Award
→ Execution
```

---

# 61. Product Development Method

Implementation با Feature Dump انجام نمی‌شود.

Hierarchy:

```text
Epic
  ↓
Capability Slice
  ↓
Task
  ↓
Acceptance Criteria
  ↓
Codex Prompt
  ↓
Implementation
  ↓
Automated Tests
  ↓
Manual Review
  ↓
Commit / Push
```

هر Task باید کوچک و قابل Review باشد.

---

# 62. Task Design Rules

هر Task باید:

* یک هدف مشخص داشته باشد.
* Scope محدود داشته باشد.
* Dependencies مشخص داشته باشد.
* Files/Modules احتمالی مشخص داشته باشد.
* Acceptance Criteria مشخص داشته باشد.
* Non-goals داشته باشد.
* Test Expectations داشته باشد.
* UX Acceptance در صورت Frontend بودن داشته باشد.

Taskهای بزرگ باید شکسته شوند.

---

# 63. Codex Working Model

Codex باید Repository-aware باشد.

قبل از هر Task:

1. Scope Task را بخواند.
2. فقط Files/Modules مرتبط را Inspect کند.
3. Architecture Invariants را رعایت کند.
4. Minimal necessary changes انجام دهد.
5. Tests مرتبط را اجرا کند.
6. Summary ارائه دهد.

Broad repository exploration بدون نیاز انجام نشود.

---

# 64. GitHub Workflow

Codex قرار است در محیطی کار کند که به GitHub Account / Repository پروژه متصل است.

وقتی Authentication و دسترسی Repository موجود باشد، Codex باید Task-by-Task کار کند.

Recommended workflow:

```text
Task
↓
Implement
↓
Run Tests
↓
Review Diff
↓
Commit
↓
Push
```

Commit باید فقط شامل همان Task باشد.

از Commitهایی مثل:

```text
update stuff
fix things
misc
```

استفاده نشود.

Commit Message باید Scope را مشخص کند.

مثلاً:

```text
feat(rfq): add dynamic commodity specification support
```

یا:

```text
feat(opportunities): add operator opportunity lifecycle
```

---

# 65. Git Safety Rules

Codex نباید بدون دستور:

* Force Push کند.
* History Rewrite کند.
* Remote Branch حذف کند.
* Large unrelated refactor انجام دهد.
* Generated secrets commit کند.
* `.env` واقعی commit کند.

---

# 66. Review Model

بعد از هر Task:

Codex باید گزارش دهد:

### Changed

چه چیزی تغییر کرده.

### Why

چرا.

### Tests

چه تست‌هایی اجرا شده.

### Risks

ریسک احتمالی چیست.

### Follow-up

چه چیزی عمداً انجام نشده.

این خروجی برای Review انسانی استفاده می‌شود.

---

# 67. Suggested High-Level Delivery Phases

## Phase 0

Foundation / Architecture / Repository

## Phase 1

Identity / Organizations / Roles / i18n

## Phase 2

Dynamic Commodity Model

## Phase 3

Trade Hub / RFQ / Supply

## Phase 4

Opportunity Desk / Market Discovery

## Phase 5

Matching / Offers / Normalisation / Negotiation

## Phase 6

Award / Deal / Attribution

## Phase 7

Execution Monitor

## Phase 8

Verification / Documents / Issues

## Phase 9

Analytics / Intelligence

## Phase 10

Demo Data / UX Polish / E2E

---

# 68. Final Product Statement

> این محصول یک B2B Commodity Procurement & Trade Platform است که Buyer از طریق آن Demand ایجاد می‌کند، Supplier و Broker در Network یا Market Discovery شناسایی می‌شوند، Opportunityها به Dealهای ساختاریافته تبدیل می‌شوند، Procurement Engine Offerها را Compare و Evaluate می‌کند، Deal مذاکره و Award می‌شود و سپس Platform اجرای معامله را از طریق Execution Monitor قابل مشاهده می‌کند؛ تمام این فعالیت‌ها در نهایت یک Data / Trust / Intelligence Layer اختصاصی ایجاد می‌کنند.

---

# 69. Product Success Principle

هدف Demo صرفاً نمایش UI نیست.

Demo باید این Concept را واضح منتقل کند:

> **We do not only connect buyers and sellers. We structure, discover, evaluate and monitor commodity deals.**

---

# 70. Status

این سند:

> **Source of Truth for Product Scope v1**

است.

هر تغییر Business یا Architecture که با این سند تعارض دارد باید ابتدا در این Specification اصلاح شود و سپس وارد Taskهای Development شود.
