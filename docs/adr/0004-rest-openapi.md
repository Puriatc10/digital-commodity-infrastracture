# ADR 0004: REST + OpenAPI

Status: Accepted — explicit source decision; documentation foundation approved by the project owner; not implemented.

## Context and decision

Use Django REST Framework REST APIs with generated OpenAPI contracts. Keep the frontend independent of backend implementation through the API contract. Provide generated frontend API client infrastructure; do not manually duplicate that contract.

Always enforce authorization server-side. Frontend visibility and demo persona switching are not authorization mechanisms.

## Consequences and open detail

T0102 plans a GET /api/health endpoint, and T0105 plans contract generation. No endpoint is implemented in this foundation. OpenAPI version, generation/client libraries, API versioning policy, and exact session/token mechanism remain unspecified. The complete permission matrix requires review under Epic 2.

Sources: [Product Specification](../product/product-spec.md) §§50, 52, 57; [Delivery Roadmap](../delivery/roadmap.md) T0102, T0105, T0201–T0206.
