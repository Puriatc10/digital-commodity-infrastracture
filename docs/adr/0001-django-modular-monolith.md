# ADR 0001: Django Modular Monolith

Status: Accepted — explicit source decision; documentation foundation approved by the project owner; not implemented.

## Context and decision

Use Django 6 with Django REST Framework in a modular monolith. Domain boundaries must be clear; microservices are forbidden in v1. Use in-process domain events, not a message broker.

The specification suggests identity, organizations, commodities, trade_hub, procurement, opportunities, matching, offers, deals, execution, verification, documents, analytics, notifications, and audit modules. These are suggested boundaries, not a finalized interface/ownership design.

The planned monorepo separates apps/api and apps/web. Docker Compose with PostgreSQL and MinIO is explicitly planned local infrastructure; this ADR does not bootstrap it or permit additional infrastructure.

## Consequences and open detail

Keep feature work scoped to its domain/task. Exact module interfaces, dependency versions beyond Django 6, and production topology remain to be defined within authorized tasks. Do not introduce additional infrastructure without explicit approval.

Sources: [Product Specification](../product/product-spec.md) §§50–56; [Delivery Roadmap](../delivery/roadmap.md) T0003, T0101–T0104.
