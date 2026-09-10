# Repository Context

This repository is a B2B Commodity Procurement & Trade Platform, initially focused on Bitumen and designed to support other commodities.

## Read before working

- [Product specification](docs/product/product-spec.md): authoritative product context and scope.
- [Delivery roadmap](docs/delivery/roadmap.md): authorized phase and delivery scope.
- [Domain glossary](docs/domain/glossary.md): actors and business terminology.
- [Architecture overview](docs/architecture/overview.md): stack, business flow, and architectural invariants.
- [Architecture decision records](docs/adr/README.md): supplied decisions and open implementation details.

The supplied Product Specification is authoritative for product scope; the supplied Delivery Roadmap defines delivery tasks and gates. Architecture docs and ADRs record those decisions; GitHub Issues are the formal work backlog. Read the assigned issue and only relevant deeper docs. Do not invent requirements or silently resolve source conflicts; see [source review](docs/architecture/source-review.md). Changes that conflict with the specification must first be reflected in the specification with owner direction.

## Current scope

The current authorized task is the Epic 2 Review Gate for T0201–T0206 on `codex/epic-02-identity-organizations`, against `master`: review, validate, and fix concrete Identity, Organization, authorization, session, and demo persona defects. Epic 1 is the approved foundation. Do not begin Epic 3 or implement future business modules or application-level storage integration. Do not commit, push, or merge until the owner reviews the work and authorizes those actions. Recorded source ambiguities remain unresolved.

## Required guardrails

- Backend: Django 6, Django REST Framework, PostgreSQL, modular monolith, REST + OpenAPI. Frontend: Next.js + TypeScript, Tailwind CSS, shadcn/ui; generate the API client from OpenAPI rather than duplicating contracts.
- Business actors: Buyer, Supplier, Broker, Operator, Admin. Buyer/Supplier/Broker are Organization capabilities (multiple allowed); Operator/Admin are system roles. Never introduce Trader as a business role. Preserve Opportunity- and Deal-specific Broker attribution, not permanent customer ownership.
- Never hard-code commodity-specific attributes into core database tables or reusable forms. Use JSONB with versioned JSON Schema, backend validation, and schema-driven UI; preserve historical meaning. Retain multi-commodity extensibility without building a generic commodity-builder product.
- Market Discovery / Opportunity Desk is human-assisted during the pilot. Execution Monitor provides visibility and orchestration only; no real settlement, escrow, financing, insurance, payment processing, or logistics execution.
- PostgreSQL is the source of truth and initial search backend. Files use S3-compatible storage (MinIO for demo); the database holds metadata. Use in-process domain events. Do not introduce additional infrastructure without explicit approval; respect specification section 56 non-goals.
- Always enforce authorization server-side. Demo UI is Persian/RTL at `/fa`; keep architecture ready for English/LTR at `/en`, inactive in demo. Do not hard-code user-facing text in reusable components.
- Matching is rule-based and explainable; no AI matching or fabricated scoring/price indices. Offer revisions must not overwrite history; awarded Deals preserve an immutable initial commercial snapshot.
- Keep changes within the authorized task. Avoid unrelated refactors and unnecessary repository exploration. Consult the linked documents for deeper context.

## Delivery, testing, and Git

- Work one scoped issue/capability at a time, sequentially while architecture stabilizes; follow dependencies, acceptance criteria, non-goals, and review gates. Do not implement multiple epics from one broad prompt.
- Add tests for business rules. Run relevant unit/API/PostgreSQL integration tests, critical frontend tests, and Playwright Hero Flow/permission checks as applicable; run relevant lint/type/build/migration checks. See specification sections 59–60 and roadmap section 19.
- Review the diff for scope and unintended changes. Report changes, reasons, validation results, risks, and follow-up; human review remains required.
- The owner has superseded the roadmap's per-task branch convention: use one branch per Epic, with separate task-scoped Conventional Commits. This review stays on `codex/epic-02-identity-organizations`; do not create another branch. Preserve reviewed remote/PR history when transitioning existing branches. Never force-push, merge a PR without explicit approval, or commit secrets/real `.env` files. Do not rewrite history or delete remote branches without explicit direction. Commits and pushes remain prohibited until review for this task.
