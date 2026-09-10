# Authoritative Source Review

Reviewed against the supplied [Product Specification](../product/product-spec.md) and [Delivery Roadmap](../delivery/roadmap.md). The Product Specification remains unchanged. The roadmap Epic 3 section is now synchronized under explicit owner direction to the [approved Epic 3 Design Contract](../product/epic-03-dynamic-commodity-design-contract.md). This review records the resolution and remaining unrelated differences; it does not independently decide product behavior.

## Confirmed foundation decisions

The sources agree on Django 6/DRF, a modular monolith, PostgreSQL, REST/OpenAPI, JSONB with versioned JSON Schema, human-assisted discovery, preserved Broker attribution, monitoring-only Execution, and a locale-aware Persian/RTL demo. They explicitly specify S3-compatible document storage with MinIO for demo and PostgreSQL metadata, resolving the earlier storage placeholder.

Buyer/Supplier/Broker are Organization capabilities, while Operator/Admin are system roles. The five named actors are unchanged. Market Discovery is the capability; Opportunity Desk is its operational workspace. These are clarifications from the finalized sources, not additional roles or products.

## Unresolved source differences and delivery ambiguities

| Topic | Evidence | Detail to resolve before dependent implementation |
| --- | --- | --- |
| Scoring configurability timing | Specification §27 says weights become configurable later and gives example weights; roadmap T0808 requests configurable weighted scoring in Epic 8. | Establish whether v1 requires configurability and at what level. Example weights are not silently promoted to fixed product requirements. |
| Opportunity identifiers | Specification §17 and roadmap T0602 show OPP-2026-000124; specification §49 uses OPP-2026-00124. | Confirm canonical identifier formatting/padding. These examples differ by one digit. |
| Execution milestone labels and coverage | Specification §33 and roadmap T1002 use Loaded and include Loading Scheduled and Accepted. Specification §49's Hero flow uses Loading Completed and omits several template steps. | Confirm whether Hero steps are illustrative shorthand and whether Loaded/Loading Completed are the same milestone. Do not define aliases or skip rules here. |
| Issue classifications | Specification §32's Execution list includes Delay and a smaller type set. Specification §36 and roadmap T1008 instead list Quality, Quantity, Logistics, Payment, Document, Contract, Other. | Confirm whether Delay maps to Logistics or is separate, and whether the shorter list is merely illustrative. No new enum or mapping is chosen. |
| Source category coverage | Specification §18 includes Other for Opportunity sources, omitted from T0605. Specification §30 includes Other for Deal origin, omitted from T0903. | Ensure task acceptance criteria account for the full specification; roadmap omissions do not authorize removing specification categories. |
| Opportunity qualification transitions | Specification §20 shows Captured → Contacted → Qualified; roadmap T0608 shows Captured → Qualified and T0603 requires transition rules. | Define whether Contacted can be skipped and which required fields/guards establish qualification. |
| Cross-epic Offer dependency | Roadmap T0611 and the Epic 6 review gate require a Qualified Opportunity to yield an RFQ Offer; Offer parent/version/submission models are scheduled in Epic 8 (T0801–T0804), after Epic 6 in §§18, 31. | Clarify the prerequisite implementation/staging before attempting the Epic 6 gate. No reordering or early feature implementation is authorized here. |
| Human review versus commit/push order | Specification §61 and roadmap §1 place human review before commit/push; specification §64 and roadmap §§21, 23 describe commit/push before the PR review flow. | Clarify which review occurs before commits versus after pushing during later implementation. For this foundation, the owner has explicitly approved the documentation and authorized its local commit; pushing remains prohibited. |

## Documentation alignment completed

- Removed obsolete statements that the authoritative documents had not been supplied.
- Expanded the glossary with definitions from the sources, including every term requested by T0002 and Admin.
- Recorded JSONB/JSON Schema, generated API clients, MinIO, locale routing, in-process events, and other explicit architecture details without implementing them.
- Updated ADR 0007 from placeholder to accepted source decision.
- Aligned ADR numbering to roadmap T0003: 0005 is Execution, 0006 is Market Discovery. This corrects the pre-roadmap document numbering only.
- Recorded the owner's foundation approval and local commit authorization in AGENTS.md. The documentation-only scope and no-push restriction remain; the roadmap does not authorize starting Epic 1 during this task.

## Remaining design detail, not invented requirements

The full permission matrix, lifecycle transition guards, future cross-version conversion/compatibility beyond the Epic 3 historical-version and RFQ-context invariants, qualification criteria, precise unit/currency/rounding rules for normalisation, library versions/configuration, and production storage/retention policy still require definition within authorized work. The supplied actors, lifecycle labels, example schemas, and suggested modules are not a substitute for those details.

The Product Specification's suggested phases (§67) and the roadmap's Epics are different planning levels; this review does not invent a one-to-one mapping. Roadmap Epic 4 is P1 but appears before core P0 work in its dependency sequence; priority labels do not automatically remove dependencies.

The project owner has approved the documentation foundation and requested a final consistency check and local commit. This approval does not mark application tasks or later review gates complete, resolve the differences above, or authorize implementation or a push. The final check preserves both authoritative documents and all recorded product-scope constraints.

## Epic 3 documentation synchronization — 2026-09-10

The full owner-supplied Design Contract was already present as an untracked repository file and is preserved in full, with an authority notice and explicit owner synchronization clarification. It is the detailed Epic 3 implementation contract alongside the Product Specification's product scope. This synchronization authorizes documentation only, not T0301 implementation or any commit/push/merge.

| Conflict or stale statement | Resolution under owner direction |
| --- | --- |
| Roadmap T0302 described JSON Schema representation rather than lifecycle. | T0302 now covers Draft/Published/Retired, immutability, active-schema ownership/state integrity, and safe evolution; deterministic derivation is in T0303. |
| Roadmap T0306/T0307 were form/display; T0308 required JSONB query/index work. ADR 0002 repeated that index requirement. | T0306 is read API/OpenAPI, T0307 form, T0308 view/integration coverage. Indexing waits for a real specification-bearing entity and real query patterns; no fake tables or indexes. |
| ADR 0003 listed lifecycle as unspecified and a unit-aware numeric type; overview/source review left commodity lifecycle unresolved. | The approved lifecycle and integrity requirements now govern. Five supported types include integer; units are definition metadata, values stay flat, and no conversion engine is added. Unrelated lifecycle ambiguities remain unresolved. |
| Prior metadata/JSON Schema wording did not establish one authoritative source. | Relational Attribute Definitions are authoritative; deterministic JSON Schema is derived. No independently maintained second schema is permitted. |
| Contract §9 used “preferably Published”; §73 called the mapping suggested. | The owner's synchronization request fixes active schemas to usable Published versions and makes the exact T0301–T0308 mapping authoritative. An explicit notice preserves the original contract wording while recording this clarification. |
| Product Specification §7 uses illustrative enum strings such as 60/70; contract §15 illustrates canonical 60_70 with localized 60/70 labels. | These are examples, not conflicting fixed enum requirements. Actual definitions must use canonical stored values distinct from localized display labels; examples are not promoted into exhaustive seed requirements. Product Specification remains unchanged. |
| AGENTS.md still authorized the Epic 2 Review Gate and named the Epic 2 branch. | Updated minimally to this docs-only task and the existing Epic 3 branch; no branch was created/switched and no Epic 2 gate approval is inferred. Existing no-commit/push/merge restrictions remain. |
| Source review claimed both source files were unchanged verbatim attachments. | Corrected provenance to acknowledge the owner-authorized Epic 3 roadmap synchronization. Earlier foundation approval/commit notes above are historical, not authorization for this task. |

No genuine product-level conflict requiring a Product Specification amendment was found. The contract elaborates §§6–10 and preserves Bitumen focus, multi-commodity extensibility, locale readiness, and platform non-goals. ADR 0004's generated API boundary and ADR 0008's Persian/RTL policy are compatible and need no Epic 3 amendment. Exact routes, schema dialect/library, representation/enforcement choices, and representative seed bounds remain scoped implementation details rather than new product requirements.

A fresh Jules session can read AGENTS.md, the full contract, the synchronized roadmap, and the assigned GitHub Issue without chat history. GitHub Issues remain the formal backlog; no issue was changed by this repository-only synchronization. T0301 must be explicitly authorized before implementation. All unrelated source differences above remain open.
