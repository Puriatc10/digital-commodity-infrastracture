# Architecture Decision Records

These records derive from the authoritative [Product Specification](../product/product-spec.md) and [Delivery Roadmap](../delivery/roadmap.md). “Accepted” means explicitly specified by the user; the project owner has approved the documentation foundation. Epic 1 implements the backend/frontend scaffolds, PostgreSQL/MinIO services, and OpenAPI generation/client foundation. Domain-specific decisions remain pending their delivery tasks. Open implementation details and recorded source ambiguities are not resolved by foundation implementation.

| ADR | Status |
| --- | --- |
| [0001 — Django Modular Monolith](0001-django-modular-monolith.md) | Accepted |
| [0002 — PostgreSQL as Source of Truth](0002-postgresql-source-of-truth.md) | Accepted |
| [0003 — Dynamic Commodity Specifications](0003-dynamic-commodity-specifications.md) | Accepted |
| [0004 — REST + OpenAPI](0004-rest-openapi.md) | Accepted |
| [0005 — Monitoring-first Execution Layer](0005-monitoring-first-execution-layer.md) | Accepted |
| [0006 — Human-assisted Market Discovery](0006-human-assisted-market-discovery.md) | Accepted |
| [0007 — S3-compatible Object Storage](0007-s3-compatible-object-storage.md) | Accepted |
| [0008 — Locale-aware Frontend](0008-locale-aware-frontend.md) | Accepted |

Numbering follows roadmap T0003: Execution is 005 and Market Discovery is 006. The initial pre-roadmap foundation had these two reversed; filenames and titles are now aligned with the roadmap. Four-digit filename prefixes are retained consistently; 0005 corresponds to ADR-005.

ADR 0007 is no longer a placeholder: specification §§35, 50 and roadmap T0104/T0405 explicitly specify S3-compatible storage, demo MinIO, and database metadata.

See [source review](../architecture/source-review.md) for unresolved differences. Do not silently choose new product behavior or rewrite the authoritative documents to settle them.
