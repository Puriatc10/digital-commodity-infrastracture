# Repository Context

This repository is a B2B Commodity Procurement & Trade Platform, initially focused on Bitumen and designed to support other commodities.

## Read before working

- [Product specification](docs/product/product-spec.md): authoritative product context and scope.
- [Epic 3 Design Contract](docs/product/epic-03-dynamic-commodity-design-contract.md): authoritative detailed Epic 3 implementation contract; read in full before Epic 3 work.
- [Delivery roadmap](docs/delivery/roadmap.md): authorized phase and delivery scope.
- [Epic 4 execution plan](docs/delivery/epic-04-execution-plan.md): read in full before Epic 4 work; owner-approved policies, task boundaries, common-base waves, tests and integration barriers.
- [Domain glossary](docs/domain/glossary.md): actors and business terminology.
- [Architecture overview](docs/architecture/overview.md): stack, business flow, and architectural invariants.
- [Architecture decision records](docs/adr/README.md): supplied decisions and open implementation details.

The supplied Product Specification is authoritative for product scope; the supplied Delivery Roadmap defines delivery tasks and gates. Architecture docs and ADRs record those decisions; GitHub Issues are the formal work backlog. Read the assigned issue and only relevant deeper docs. Do not invent requirements or silently resolve source conflicts; see [source review](docs/architecture/source-review.md). Changes that conflict with the specification must first be reflected in the specification with owner direction.

## Current scope

Epic 4 is authorized on `codex/epic-04-organizations-network-verification` under `docs/delivery/epic-04-execution-plan.md`, including its owner-approved policies. Preserve approved Epic 1–3 foundations and unrelated unresolved source ambiguities. The current documentation synchronization task is documentation-only: do not implement T0401–T0406, create branches, commit, push or merge in this task. Future implementation sessions work only their assigned Issue and wave; Wave 1 is T0403 alone. The Epic 3 review record remains historical evidence, not current execution authorization.

## Required guardrails

- Backend: Django 6, Django REST Framework, PostgreSQL, modular monolith, REST + OpenAPI. Frontend: Next.js + TypeScript, Tailwind CSS, shadcn/ui; generate the API client from OpenAPI rather than duplicating contracts.
- Business actors: Buyer, Supplier, Broker, Operator, Admin. Buyer/Supplier/Broker are Organization capabilities (multiple allowed); Operator/Admin are system roles. Never introduce Trader as a business role. Preserve Opportunity- and Deal-specific Broker attribution, not permanent customer ownership.
- Never hard-code commodity-specific attributes into core database tables or reusable forms. Relational Attribute Definitions are the schema source of truth; JSON Schema is derived. Published schema semantics are immutable; future specification-bearing records retain their creation-time schema version with JSONB values. Generic validation/rendering must not branch on commodity code. Active schemas must belong to the same Commodity and be Published. Do not build fake specification instance tables, premature JSONB indexes, or a generic low-code Schema Builder. See the Epic 3 Design Contract for the complete invariants.
- Market Discovery / Opportunity Desk is human-assisted during the pilot. Execution Monitor provides visibility and orchestration only; no real settlement, escrow, financing, insurance, payment processing, or logistics execution.
- PostgreSQL is the source of truth and initial search backend. Files use S3-compatible storage (MinIO for demo); the database holds metadata. Use in-process domain events. Do not introduce additional infrastructure without explicit approval; respect specification section 56 non-goals.
- Always enforce authorization server-side. Demo UI is Persian/RTL at `/fa`; keep architecture ready for English/LTR at `/en`, inactive in demo. Do not hard-code user-facing text in reusable components.
- Matching is rule-based and explainable; no AI matching or fabricated scoring/price indices. Offer revisions must not overwrite history; awarded Deals preserve an immutable initial commercial snapshot.
- Keep changes within the authorized task. Avoid unrelated refactors and unnecessary repository exploration. Consult the linked documents for deeper context.

## Delivery, testing, and Git

- Each agent works one scoped issue/capability at a time; Epic 4 concurrency follows the execution plan's waves, dependencies, file ownership and review gates. Parallel siblings start from the exact same recorded Wave Base SHA on isolated temporary `jules/t04xx-...` branches. PRs target `codex/epic-04-organizations-network-verification`, never `master`. After the first sibling merge, remaining siblings must sync with the latest Epic state, resolve conflicts, regenerate combined contracts and rerun canonical CI before merge. Wave N+1 cannot start before Wave N's full integration/CI barrier completes. Do not implement multiple epics from one broad prompt.
- Add tests for business rules. Run relevant unit/API/PostgreSQL integration tests, critical frontend tests, and Playwright Hero Flow/permission checks as applicable; run relevant lint/type/build/migration checks. See specification sections 59–60 and roadmap section 19.
- Review the diff for scope and unintended changes. Report changes, reasons, validation results, risks, and follow-up; human review remains required.
- The owner has superseded the roadmap's generic branch examples: use the Epic integration branch and isolated task branches under the execution plan, with task-scoped Conventional Commits when authorized. Preserve reviewed remote/PR history. Never force-push, merge a PR without explicit approval, or commit secrets/real `.env` files. Do not rewrite history or delete remote branches without explicit direction. Leave this documentation synchronization uncommitted for owner review; it authorizes no commit, push or merge.
