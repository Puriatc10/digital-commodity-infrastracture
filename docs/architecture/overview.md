# Architecture Overview

Derived from the authoritative [Product Specification](../product/product-spec.md) and [Delivery Roadmap](../delivery/roadmap.md). This is a navigation/reference document; the complete sources remain unchanged. Epic 1 implements the platform foundation; Epic 2 adds Identity, Organizations, authorization, and frontend session context. Later domain work still requires its own authorization.

## Required stack

| Area | Decision |
| --- | --- |
| Backend | Django 6 + Django REST Framework |
| Application structure | Modular monolith |
| Source of truth | PostgreSQL |
| Dynamic specifications | PostgreSQL JSONB + versioned JSON Schema; server-side JSON Schema validation |
| API | REST + OpenAPI generation and generated frontend API client |
| Frontend | Next.js + TypeScript, Tailwind CSS, shadcn/ui |
| Object storage | S3-compatible; MinIO for demo; files in object storage, metadata in PostgreSQL |
| Local infrastructure | Docker Compose with PostgreSQL 17 and MinIO, implemented in T0104 |
| Initial search | PostgreSQL |
| Domain events | In-process; no message broker in v1 |
| Demo presentation | Persian, RTL, /fa only |
| Future localization | English, LTR, /en architectural support; inactive in demo |

Sources: specification §§35, 45, 50–55; roadmap T0101–T0106. Dependency versions beyond Django 6, production deployment details, and library/provider configuration remain unspecified.

## Business architecture

```text
Trade Hub
→ Procurement Engine
↔ Market Discovery / Opportunity Desk
→ Qualified Deal
→ Execution Monitor
→ Completed Deal
→ Data / Trust / Intelligence
```

The Procurement Engine uses both the existing network and Market Discovery / Opportunity Desk for matching/comparison before a Qualified Deal (specification §2). These concepts do not imply independently deployed services.

## Repository and domain boundaries

Specification §53 and roadmap T0101 prescribe a monorepo with apps/api, apps/web, docs, infra/docker, and scripts. Epic 1 implements that layout, API/frontend bootstraps, local infrastructure, contract generation, and CI; Epic 2 adds only Identity and Organizations domain modules.

Specification §51 suggests these backend modules (not a finalized ownership/interface design):

```text
identity, organizations, commodities, trade_hub, procurement,
opportunities, matching, offers, deals, execution, verification,
documents, analytics, notifications, audit
```

Domain boundaries must be clear. REST/OpenAPI provides the frontend contract; roadmap T0105 requires generated client infrastructure and prohibits manually duplicating that contract. In-process event examples include RFQPublished, OfferSubmitted, OpportunityQualified, DealAwarded, and ExecutionMilestoneCompleted (specification §55).

## Data and workflow rules

- Shared commercial fields remain relational; commodity attributes use JSONB with versioned JSON Schema. CommodityDefinition, CommoditySchemaVersion, and CommodityAttributeDefinition define the metadata. RFQ/Supply/Offer records retain their schema version and historical meaning. Forms and displays are schema-driven; backend validation rejects invalid specifications (specification §§6–10; T0301–T0308).
- Bitumen is the demo focus. A small Base Oil schema is an architecture test proving extension without migration (T0305), not a generic commodity-builder product.
- Opportunities preserve sources and Broker attribution through conversions. External counterparties need no account. Operator-entered Offers must remain traceable. Broker attribution is Opportunity/Deal-specific, not permanent customer ownership (specification §§18–24, 30; T0605–T0611, T0804).
- Offer versions never overwrite history. Award creates an immutable initial Deal snapshot; subsequent RFQ changes must not change it (specification §§25, 29; T0901–T0902).
- Matching is rule-based and explainable, including Qualified Opportunities; recommendations inform decisions. Analytics must disclose insufficient data rather than fabricate benchmarks (specification §§15, 23, 27, 40).
- Execution uses workflow templates, milestone definitions, and Deal-instance milestones. It tracks commercial, payment, logistics, quality, document, and issue status only; no workflow-builder UI is needed in the demo (specification §§32–33).
- Document bytes use object storage; PostgreSQL stores metadata. Verification is manual. Internal Notes are not customer-visible, and important mutations require audit records (specification §§34–35, 42–43).

## Architectural invariants

1. Commodity-specific attributes must never be hard-coded into core database tables.
2. Dynamic commodity specifications must use versioned schema definitions.
3. The initial product is Bitumen-focused, but the data model must be extensible to other commodities.
4. Do not build a generic commodity-builder product yet.
5. Market Discovery / Opportunity Desk is intentionally human-assisted during the pilot.
6. Broker attribution must be preserved at Opportunity and Deal level.
7. Execution Monitor provides visibility and orchestration only.
8. Do not implement real settlement, escrow, financing, insurance, payment processing, or logistics execution.
9. PostgreSQL is the source of truth.
10. Do not introduce microservices, Redis, Kafka, RabbitMQ, Elasticsearch, Kubernetes, Temporal, or additional infrastructure without explicit approval. PostgreSQL and demo MinIO/Docker Compose are the implemented Epic 1 infrastructure; all specification §56 non-goals still apply.
11. Authorization must always be enforced server-side.
12. Avoid unrelated refactors and unnecessary repository exploration.
13. User-facing frontend architecture must remain localization-ready.
14. Demo UI is Persian and RTL.

## Actors and authorization

The business actors are Buyer, Supplier, Broker, Operator, and Admin. Buyer/Supplier/Broker are Organization capabilities; organizations can have multiple capabilities. Operator/Admin are system roles. OrganizationMembership and example organization roles are given in T0202–T0203. Do not introduce Trader as a business role.

Specification §4 defines actor actions; roadmap T0204 and the Epic 2 gate require server-side authorization and permission-matrix review. UI hiding or a demo persona switcher cannot replace authorization. Demo persona switching is limited to development/demo paths. The Epic 2 Organization permission matrix and inactive-state semantics are recorded in the [backend guide](../../apps/api/README.md) and reviewed in the [Epic 2 gate](../delivery/epic-02-review-gate.md). Future business-module permissions remain outside this foundation.

## Frontend and quality

Use locale-aware architecture from day one: /fa RTL is active in demo; /en LTR is a future target. Reusable components must not hard-code user-facing text. The UX is a desktop-first, responsive enterprise operations product with tables, workspaces, filters, comparison, panels, and timelines (specification §§45–47).

Features require authorization, validation, appropriate auditability, and error/empty/loading states. Testing covers business rules, APIs, PostgreSQL integration, critical frontend components, and Playwright Hero Flow/permission scenarios as those features are introduced. Epic 1 checks endpoint/schema/docs behavior, PostgreSQL connectivity through migrations, frontend lint/typecheck/build, and generated-contract drift (specification §§58–60; roadmap §19).

## Decision records and unresolved detail

All eight requested decisions are recorded in the [ADR index](../adr/README.md), including S3-compatible storage and demo MinIO, now explicit in specification §50 and T0104/T0405. The project owner has approved the documentation foundation; the ADRs record decisions, not implementation.

See [source review](source-review.md) for disagreements and ambiguities. Exact permission/transition matrices, schema lifecycle policy, calculation conventions, production storage settings, and detailed module interfaces remain unresolved. Epic 1 uses drf-spectacular, openapi-typescript, and openapi-fetch for the contract boundary; Identity and Organization models/migrations are implemented; subsequent business models remain future work. [ADR 0009](../adr/0009-authentication-architecture.md) records server-side sessions, CSRF, and the first-party browser transport. See the [setup guide](../../README.md) for executable commands.
