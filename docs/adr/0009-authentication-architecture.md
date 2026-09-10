# ADR 0009: Authentication Architecture

Status: Accepted — Identity module foundation implemented in Epic 2.

## Context and decision

Use Django server-side sessions combined with CSRF protection for first-party browser application authentication.

We will explicitly avoid introducing JSON Web Tokens (JWT), refresh tokens, localStorage authentication, or custom token infrastructure. Using Django’s built-in session framework provides out-of-the-box robustness, straightforward CSRF defenses without managing expiration timelines manually, and aligns with the principle of maintaining minimal infrastructure without speculative complexity.

## Consequences and open detail

This implements `/api/auth/login`, `/api/auth/logout`, and `/api/auth/me`. The frontend bootstraps `/api/auth/csrf`, sends cookies and the current CSRF header to login, and includes them on all subsequent unsafe requests. Anonymous login and demo switching also enforce CSRF. Browser requests use the frontend origin; Next.js forwards `/api` to an environment-configured backend during local development, preserving API trailing slashes. Production serves the API and frontend under one HTTPS origin and configures its actual hosts/trusted origins. DRF SessionAuthentication returns 403 for protected unauthenticated requests. Session cookies are HttpOnly/SameSite=Lax and Secure in production. Demo switching defaults off, is rejected by production settings, and accepts only fixed seeded identities. See the backend/frontend setup guides for configuration and reviewed permission semantics.

Sources: [Product Specification](../product/product-spec.md); [Delivery Roadmap](../delivery/roadmap.md) T0201.
