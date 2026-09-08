# ADR 0003: Dynamic Commodity Specifications

Status: Accepted — explicit source decision; documentation foundation approved by the project owner; not implemented.

## Context and decision

The demo focuses on Bitumen while the data model must support other commodities. Never hard-code commodity-specific attributes into core domain tables, reusable forms, or Bitumen-specific matching rules.

Use relational fields for shared commercial data and PostgreSQL JSONB for commodity-specific values. Use versioned JSON Schema for validation, with CommodityDefinition, CommoditySchemaVersion, and CommodityAttributeDefinition metadata. Each schema version has a runtime validation schema; backend validation rejects invalid specifications.

RFQ/Supply/Offer records store the schema version used. New definitions must not change the meaning of historical data. Forms and reusable specification displays derive from the definitions rather than hard-coded commodity fields.

## Consequences and open detail

T0302 requires initial string, number, boolean, enum, and unit-aware numeric support. Bitumen seed attributes are dynamic data; the small Base Oil schema in T0305 is an architecture test proving extension without migration. Do not build a generic commodity-builder UI.

Exact schema status/lifecycle policy, JSON Schema dialect, unit conversion rules, complete seed validation limits, and cross-version compatibility rules remain unspecified. Deal snapshots preserve specifications, but additional schema-reference design must not be invented in this documentation task.

Sources: [Product Specification](../product/product-spec.md) §§6–10, 50, 57; [Delivery Roadmap](../delivery/roadmap.md) T0301–T0308, T0703, T0902.
