# ADR 0004: REST + OpenAPI

Status: Accepted — REST/OpenAPI contract foundation implemented in Epic 1.

## Context and decision

Use Django REST Framework REST APIs with generated OpenAPI contracts. Keep the frontend independent of backend implementation through the API contract. Provide generated frontend API client infrastructure; do not manually duplicate that contract.

Always enforce authorization server-side. Frontend visibility and demo persona switching are not authorization mechanisms.

## Consequences and open detail

T0102 implements GET /api/health. T0105 uses drf-spectacular to generate OpenAPI 3.0.3, exposes /api/schema/ and /api/docs/, and uses openapi-typescript plus openapi-fetch for the frontend contract/client. CI validates the schema and rejects generated TypeScript drift. API versioning policy and the exact session/token mechanism remain unspecified. The complete permission matrix requires review under Epic 2.

Sources: [Product Specification](../product/product-spec.md) §§50, 52, 57; [Delivery Roadmap](../delivery/roadmap.md) T0102, T0105, T0201–T0206.
