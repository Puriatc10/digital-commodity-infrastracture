# ADR 0003: Dynamic Commodity Specifications

Status: Accepted — product-owner-approved Epic 3 design; implementation is not authorized by this documentation synchronization.

## Context and decision

Bitumen is the beachhead, while materially different commodities must be supported through definition data. The [Epic 3 Design Contract](../product/epic-03-dynamic-commodity-design-contract.md) is the authoritative detailed contract; this ADR records the decision and consequences rather than duplicating it.

Adopt Hybrid Relational + Dynamic JSONB architecture. CommodityDefinition → CommoditySchemaVersion → CommodityAttributeDefinition are relational, versioned, platform-level definitions. Attribute Definitions are authoritative; deterministic JSON Schema is derived for reusable schema-version-aware runtime validation. Never maintain an independent JSON Schema as a second source of truth.

Future specification-bearing records use commodity_id, schema_version_id, and specifications JSONB. Definitions describe valid values; they do not store business instance values. Shared commercial fields remain relational; commodity-specific fields never become generic domain columns. Every future record retains its creation-time schema version. Historical validation/rendering uses that version rather than today's active schema; future RFQ responses must remain comparable in the RFQ schema context.

Draft definitions are editable. Published semantics are immutable, including attributes, constraints, enum and unit meaning. Changes require a new version. Retired versions remain retrievable for historical interpretation and are not used for new instances. Published/historically referenced schemas must not be hard-deleted. An active schema belongs to the same Commodity and must be Published; setup may have no active schema, but a usable active Commodity requires one. Internal admin operations must respect these invariants beyond UI-only checks.

## Consequences

- The application engine remains commodity-agnostic: no commodity-specific validators, components, or commodity-code branches. Base Oil is an architecture proof, not product expansion.
- Backend validation is authoritative. Support string, number, integer, boolean, and enum with structured field errors, required/optional and explicit null semantics, unknown-field rejection, numeric bounds, and basic string constraints. Optional is not automatically nullable.
- v1 values remain flat. Store canonical enum values rather than localized labels; units are definition metadata, not value/unit payload wrappers. No unit conversion engine.
- Generic forms and read-only views consume localized labels, ordering/grouping, units, enum options, and validation metadata. The demo remains Persian/RTL; English remains an inactive architectural target.
- T0306 provides discovery, active schema, and historical schema reads through Django → OpenAPI → generated TypeScript → typed client. No public schema-management write API or generic Schema Builder UI.
- Epic 3 creates definition/validation/rendering foundations only, with deterministic/idempotent Bitumen and Base Oil seeds. It creates no fake JSONB specification entity or future business modules.
- JSONB indexing is deferred until the first real specification-bearing entity, such as RFQ or Supply Listing, has real query patterns. Do not add artificial tables/indexes in Epic 3. Relational integrity constraints still belong in T0301.

## Implementation details left to scoped tasks

The contract governs lifecycle and historical semantics. Exact JSON Schema dialect/library, route names, field storage choices, practical enforcement mechanisms, and representative seed bounds may be selected within the assigned task and existing conventions. These choices must not weaken the contract, introduce a second schema source, or expand into cross-version migration/conversion machinery or later procurement behavior.

Sources: [Product Specification](../product/product-spec.md) §§6–10, 50, 57; [Delivery Roadmap](../delivery/roadmap.md) T0301–T0308; [Epic 3 Design Contract](../product/epic-03-dynamic-commodity-design-contract.md).
