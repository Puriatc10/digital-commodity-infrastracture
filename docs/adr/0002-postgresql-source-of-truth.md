# ADR 0002: PostgreSQL as Source of Truth

Status: Accepted — explicit source decision; documentation foundation approved by the project owner; not implemented.

## Context and decision

PostgreSQL is the source of truth and the initial search backend. Shared commercial fields are relational; commodity-specific values use JSONB with versioned schemas. Do not introduce MongoDB, Graph DB, or Elasticsearch in v1.

Document bytes live in S3-compatible object storage, with metadata in PostgreSQL; this explicitly supplied file-storage split does not replace PostgreSQL as the source of truth.

## Consequences and open detail

Preserve historical commodity meaning, Offer revisions, and the initial immutable Deal snapshot. Business persistence must support PostgreSQL integration tests. JSONB query/index work is planned in T0308 without over-indexing. Transaction boundaries and exact indexes are not selected here.

Sources: [Product Specification](../product/product-spec.md) §§7–9, 25, 35, 50, 54; [Delivery Roadmap](../delivery/roadmap.md) T0308, T0901–T0902. Related: [ADR 0003](0003-dynamic-commodity-specifications.md), [ADR 0007](0007-s3-compatible-object-storage.md).
