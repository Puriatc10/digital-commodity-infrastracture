# ADR 0009: Authentication Architecture

Status: Accepted — Identity module foundation implemented in Epic 2.

## Context and decision

Use Django server-side sessions combined with CSRF protection for first-party browser application authentication.

We will explicitly avoid introducing JSON Web Tokens (JWT), refresh tokens, localStorage authentication, or custom token infrastructure. Using Django’s built-in session framework provides out-of-the-box robustness, straightforward CSRF defenses without managing expiration timelines manually, and aligns with the principle of maintaining minimal infrastructure without speculative complexity.

## Consequences and open detail

This implements `/api/auth/login`, `/api/auth/logout`, and `/api/auth/me`. The frontend must send credentials to `/api/auth/login` to establish the session, and include CSRF tokens on subsequent unsafe requests. Later tasks will determine any required frontend configuration (e.g., cross-origin requests, `withCredentials`) should the API and Web applications run on different domains.

Sources: [Product Specification](../product/product-spec.md); [Delivery Roadmap](../delivery/roadmap.md) T0201.
